mod shm;
mod polymarket;
mod strategy;
mod gas_oracle;
mod audit;
mod persistence;
mod config; 
mod journal; // Added journal module
mod tkg;

use shm::{ShmReader, L2BookStruct, CognitionStateStruct, AccountStateStruct, PositionInfoStruct, ShmWriter, GlobalRiskStruct, SpscRingBufferRust};
use polymarket::PolymarketClient;
use strategy::Strategy;
use gas_oracle::GasOracle;
use std::sync::atomic::{Ordering, AtomicU64};
use std::sync::Arc;
use std::path::Path; 
use crate::config::Config; 
use crate::journal::{JournalWriter, JournalEntry};

use polymarket_client_sdk_v2::gamma::{Client as GammaClient, types::request::MarketBySlugRequest};
use std::time::{SystemTime, UNIX_EPOCH};
use flume; // Import flume

// New function for Order Processor Task
async fn spawn_order_processor_task(
    client: Arc<polymarket::PolymarketClient>,
    db_conn: Arc<std::sync::Mutex<rusqlite::Connection>>,
    outcome_tx: std::sync::mpsc::Sender<strategy::StrategyUpdate>,
    order_rx: flume::Receiver<strategy::OrderRequest>,
    open_limit_orders: Arc<std::sync::Mutex<std::collections::HashMap<String, strategy::TrackedOrder>>>,
    processed_intents: Arc<std::sync::Mutex<std::collections::HashSet<String>>>,
    asset_name: String,
    is_shadow: bool,
) {
    println!("{} [ORDER_PROCESSOR] Background Order Processor Active (is_shadow: {}).", get_utc_ts(), is_shadow);
    while let Ok(order_req) = order_rx.recv_async().await {
        let client = client.clone();
        let db_conn = db_conn.clone();
        let outcome_tx = outcome_tx.clone();
        let open_limit_orders = open_limit_orders.clone();
        let processed_intents = processed_intents.clone();
        let asset_name = asset_name.clone();

        tokio::spawn(async move {
            let (order_id, is_ok, err_msg) = if is_shadow {
                // Shadow mode simulation: bypass the network call entirely and return Ok with intent_id as order_id
                (Some(order_req.intent_id.clone()), true, None)
            } else {
                let res = if let Some(lp) = order_req.limit_order_price { 
                    client.submit_limit_order(&order_req.token_id, order_req.size_param, lp, order_req.side, order_req.exchange_fee_bps, order_req.expiration, order_req.post_only).await 
                } else { 
                    client.submit_market_order(&order_req.token_id, order_req.size_param, order_req.side, order_req.exchange_fee_bps).await 
                };
                match res {
                    Ok(resp) => (Some(resp.order_id), true, None),
                    Err(e) => (None, false, Some(e)),
                }
            };

            if is_ok {
                if is_shadow {
                    tokio::time::sleep(std::time::Duration::from_millis(50)).await;
                }
                
                let price = if order_req.post_only { order_req.limit_order_price.unwrap_or(order_req.price) } else { order_req.limit_order_price.unwrap_or(order_req.price) };
                let rounded_price = (price * 100.0).round() / 100.0;
                let original_shares = if order_req.side == polymarket_client_sdk_v2::clob::types::Side::Buy {
                    let shares = order_req.size_param / rounded_price;
                    (shares * 100.0).round() / 100.0
                } else {
                    (order_req.size_param * 100.0).round() / 100.0
                };

                audit::log_event(&audit::new_order_event(
                    asset_name.clone(), 
                    audit::OrderDetail { 
                        token_id: order_req.token_id.clone(), 
                        order_type: if order_req.limit_order_price.is_some() { "LIMIT".to_string() } else { "MARKET".to_string() }, 
                        side: format!("{:?}", order_req.side), 
                        quantity_tokens: original_shares, 
                        price: rounded_price, 
                        exchange_order_id: order_id.clone(),
                    }, 
                    order_req.reason, 
                    audit::OutcomeDetail { status: "SUCCESS".to_string(), error_message: None, fill_price: None, fill_quantity: None, fees: None }), None);

                let final_order_id = order_id.clone().unwrap_or_else(|| order_req.intent_id.clone());

                let tracked_order = strategy::TrackedOrder {
                    order_id: final_order_id.clone(),
                    original_size_shares: original_shares,
                    filled_size_shares: 0.0,
                    side: order_req.side,
                    limit_price: price,
                    submission_timestamp: SystemTime::now(),
                    token_id: order_req.token_id.clone(),
                    post_only: order_req.post_only,
                    reserved_usd: order_req.reserved_usd,
                };

                {
                    let mut orders = open_limit_orders.lock().unwrap();
                    orders.insert(final_order_id.clone(), tracked_order.clone());
                }

                let conn = db_conn.lock().unwrap();

                // Try to update SQLite row from intent_id to final_order_id (if journal synced it first)
                let mut stmt = conn.prepare("UPDATE open_orders SET order_id = ?1 WHERE order_id = ?2").unwrap();
                let updated = stmt.execute(rusqlite::params![final_order_id, order_req.intent_id]).unwrap_or(0);

                if updated == 0 {
                    // If 0 rows updated, the journal thread hasn't processed the intent yet.
                    // Insert into processed_intents so the journal thread will skip it.
                    processed_intents.lock().unwrap().insert(order_req.intent_id.clone());

                    if let Err(e) = persistence::insert_order(&conn, &tracked_order) {
                        eprintln!("[ORDER_PROCESSOR_ERROR] Failed to persist order {}: {}", final_order_id, e);
                    }
                }
            } else {
                let error_detail = err_msg.unwrap_or_else(|| "Unknown execution error".to_string());
                
                // SQLite cleanup for failed orders to avoid dangling intent_ids
                {
                    let conn = db_conn.lock().unwrap();
                    let _ = persistence::delete_order(&conn, &order_req.intent_id);
                }
                processed_intents.lock().unwrap().insert(order_req.intent_id.clone());

                audit::log_event(&audit::new_order_event(
                    asset_name.clone(), 
                    audit::OrderDetail { 
                        token_id: order_req.token_id.clone(), 
                        order_type: if order_req.limit_order_price.is_some() { "LIMIT".to_string() } else { "MARKET".to_string() }, 
                        side: format!("{:?}", order_req.side), 
                        quantity_tokens: order_req.size_param, 
                        price: order_req.price, 
                        exchange_order_id: None,
                    }, 
                    order_req.reason, 
                    audit::OutcomeDetail { status: "FAILURE".to_string(), error_message: Some(error_detail), fill_price: None, fill_quantity: None, fees: None }), None);

                let _ = outcome_tx.send(strategy::StrategyUpdate::Failure(
                    order_req.token_id.clone(),
                    order_req.side.clone(),
                    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis() as u64,
                    order_req.reserved_usd,
                ));
            }
        });
    }
}

fn generate_market_slug(asset: &str, interval_minutes: u64, now_secs: u64) -> String {
    let interval_seconds = interval_minutes * 60;
    let rounded_timestamp = (now_secs / interval_seconds + 1) * interval_seconds;
    let timeframe_str = match interval_minutes {
        60 => "1h",
        15 => "15m",
        _ => "5m",
    };
    format!("{}-updown-{}-{}", asset.to_lowercase(), timeframe_str, rounded_timestamp)
}

fn get_utc_ts() -> String {
    chrono::Utc::now().format("%Y-%m-%d %H:%M:%S%.3f").to_string()
}

/// Pin the calling thread to a specific CPU core to eliminate scheduler jitter.
fn pin_to_cpu(cpu_id: usize) {
    unsafe {
        let mut cpuset: libc::cpu_set_t = std::mem::zeroed();
        libc::CPU_ZERO(&mut cpuset);
        libc::CPU_SET(cpu_id, &mut cpuset);
        let ret = libc::sched_setaffinity(0, std::mem::size_of::<libc::cpu_set_t>(), &cpuset);
        if ret == 0 {
            println!("{} [PERF] Pinned executor process to CPU {}", get_utc_ts(), cpu_id);
        } else {
            eprintln!("{} [WARN] Failed to pin to CPU {}: errno {}", get_utc_ts(), cpu_id, *libc::__errno_location());
        }
    }
}

#[tokio::main]
async fn main() {
    // Pin executor to CPU for deterministic low-latency scheduling
    let cpu_id = std::env::var("EXECUTOR_CORE")
        .ok()
        .and_then(|s| s.parse::<usize>().ok())
        .unwrap_or(5);
    pin_to_cpu(cpu_id);

    println!("{} Starting Research-Grounded HFT Execution Sidecar (v5)...", get_utc_ts());

    if let Err(e) = audit::initialize_audit_log(None) {
        eprintln!("[CRITICAL] Failed to initialize audit log: {}", e);
    }
    
    let db_conn = match persistence::initialize_db(None) {
        Ok(conn) => Arc::new(std::sync::Mutex::new(conn)),
        Err(e) => {
            eprintln!("[CRITICAL] Failed to initialize persistence database: {}. ABORTING.", e);
            std::process::exit(1);
        }
    };

    let journal = match JournalWriter::new() {
        Ok(j) => Arc::new(j),
        Err(e) => {
            eprintln!("{} [CRITICAL] Failed to initialize mmap journal: {}. ABORTING.", get_utc_ts(), e);
            std::process::exit(1);
        }
    };

    // --- Create Flume Channel for Order Requests ---
    let (order_tx, order_rx) = flume::unbounded::<strategy::OrderRequest>();

    let processed_intents = Arc::new(std::sync::Mutex::new(std::collections::HashSet::<String>::new()));

    // --- Background Journal Processor (The Async SQLite Sync) ---
    let db_conn_journal = Arc::clone(&db_conn);
    let journal_reader = Arc::clone(&journal);
    let processed_intents_journal = Arc::clone(&processed_intents);
    tokio::spawn(async move {
        println!("{} [JOURNAL] Background Sync Thread Active.", get_utc_ts());
        let header = journal_reader.get_header();
        loop {
            let head = header.head.load(Ordering::Acquire);
            let mut tail = header.tail.load(Ordering::Acquire);

            while tail < head {
                let entry = journal_reader.get_entry(tail as usize);
                
                // Convert JournalEntry to TrackedOrder or directly insert into SQLite
                let order_id = String::from_utf8_lossy(&entry.order_id).trim_matches(char::from(0)).to_string();
                
                if processed_intents_journal.lock().unwrap().remove(&order_id) {
                    // Already processed and mapped to the real order_id by the order processor task. Skip.
                    tail += 1;
                    header.tail.store(tail, Ordering::Release);
                    continue;
                }

                let token_id = String::from_utf8_lossy(&entry.token_id).trim_matches(char::from(0)).to_string();
                
                let tracked_order = strategy::TrackedOrder {
                    order_id: order_id.clone(),
                    original_size_shares: entry.size, // Size was USD for Buy, shares for sell? 
                    filled_size_shares: 0.0,
                    side: if entry.side == 0 { polymarket_client_sdk_v2::clob::types::Side::Buy } else { polymarket_client_sdk_v2::clob::types::Side::Sell },
                    limit_price: entry.price,
                    submission_timestamp: UNIX_EPOCH + std::time::Duration::from_nanos(entry.timestamp_ns),
                    token_id,
                    post_only: true, // Journal syncing is always for maker orders
                    reserved_usd: 0.0,
                };

                let conn = db_conn_journal.lock().unwrap();
                if let Err(e) = persistence::insert_order(&conn, &tracked_order) {
                    eprintln!("[JOURNAL_ERROR] Failed to sync entry {} to SQLite: {}", tail, e);
                } else {
                    // println!("[JOURNAL] Synced order {} to persistent ledger.", order_id);
                }

                tail += 1;
                header.tail.store(tail, Ordering::Release);
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    });

    let config = match Config::load(Path::new("config.toml")) {
        Ok(cfg) => {
            println!("{} Loaded configuration from config.toml", get_utc_ts());
            cfg
        },
        Err(e) => {
            eprintln!("{} [WARN] Failed to load config.toml: {}. Using default configuration.", get_utc_ts(), e);
            Config::default()
        }
    };

    let args: Vec<String> = std::env::args().collect();
    let is_shadow = args.contains(&"--shadow".to_string());
    
    let mut asset_name = "btc".to_string();
    if let Some(pos) = args.iter().position(|x| x == "--asset") {
        if pos + 1 < args.len() {
            asset_name = args[pos + 1].clone();
        }
    }

    let mut timeframe = config.strategy_params.timeframe_minutes;
    if let Some(pos) = args.iter().position(|x| x == "--timeframe") {
        if pos + 1 < args.len() {
            timeframe = args[pos + 1].parse::<u64>().unwrap_or(config.strategy_params.timeframe_minutes);
        }
    }
    
    if timeframe != 15 && timeframe != 60 {
        eprintln!("{} [CRITICAL] Timeframe {}m is NOT supported. Only 15m and 60m are allowed due to latency constraints. Exiting.", get_utc_ts(), timeframe);
        std::process::exit(1);
    }
    
    println!("{} Asset Scope: {} ({}m)", get_utc_ts(), asset_name.to_uppercase(), timeframe);

    let rpc_url = std::env::var("POLYGON_RPC_URL").unwrap_or_else(|_| "https://polygon-rpc.com".to_string());
    let rpc_url_parsed = match rpc_url.parse::<reqwest::Url>() {
        Ok(url) => url,
        Err(e) => {
            eprintln!("{} [CRITICAL] Invalid RPC URL {}: {}. ABORTING.", get_utc_ts(), rpc_url, e);
            std::process::exit(1);
        }
    };
    let provider = Arc::new(alloy::providers::RootProvider::new_http(rpc_url_parsed));
    let gas_oracle = Arc::new(GasOracle::new(provider));
    gas_oracle.start();

    let pkey = std::env::var("POLY_SECRET").unwrap_or_else(|_| "0000000000000000000000000000000000000000000000000000000000000001".to_string());
    
    let asset_crash = asset_name.clone();
    std::panic::set_hook(Box::new(move |info| {
        let msg = format!("[CRITICAL PANIC - {}] {:?}", asset_crash, info);
        eprintln!("{}", msg);
        let _ = std::fs::write(format!("/home/bdieu178/user/panic_{}.log", asset_crash), msg);
    }));

    let api_url = std::env::var("POLY_CLOB_API_URL").unwrap_or_else(|_| "https://clob.polymarket.com".to_string());
    let proxy_wallet = std::env::var("POLY_PROXY_WALLET")
        .or_else(|_| std::env::var("POLY_WALLET_ADDRESS")).ok();
    let sig_type_str = std::env::var("POLY_SIGNATURE_TYPE").unwrap_or_else(|_| "0".to_string());
    let sig_type = match sig_type_str.as_str() {
        "1" => polymarket_client_sdk_v2::clob::types::SignatureType::Proxy,
        "2" => polymarket_client_sdk_v2::clob::types::SignatureType::GnosisSafe,
        "3" => polymarket_client_sdk_v2::clob::types::SignatureType::Poly1271,
        _ => polymarket_client_sdk_v2::clob::types::SignatureType::Eoa,
    };
    
    let gamma_client = GammaClient::default();
    let now_secs = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
    let slug = generate_market_slug(&asset_name, timeframe, now_secs);
    
    let mut market_opt = None;
    for attempt in 1..=60 {
        match gamma_client.market_by_slug(&MarketBySlugRequest::builder().slug(slug.clone()).build()).await {
            Ok(m) => {
                market_opt = Some(m);
                break;
            }
            Err(e) => {
                if attempt % 5 == 0 {
                    println!("{} [WARN] Gamma API attempt {} failed: {:?}. Retrying...", get_utc_ts(), attempt, e);
                }
                tokio::time::sleep(std::time::Duration::from_secs(2)).await;
            }
        }
    }
    
    let market = match market_opt {
        Some(m) => m,
        None => {
            eprintln!("{} [CRITICAL] Failed to fetch market {} after 60 attempts. Exiting.", get_utc_ts(), slug);
            std::process::exit(1);
        }
    };
    let asset_ids = market.clob_token_ids.clone().unwrap_or_default();
    let outcomes = market.outcomes.clone().unwrap_or_default();
    let strike_price = market.line.clone().and_then(|l| l.to_string().parse::<f64>().ok()).unwrap_or(0.0);
    
    let mut token_id_up = "123".to_string();
    let mut token_id_down = "456".to_string();
    
    for (i, outcome) in outcomes.iter().enumerate() {
        if i >= asset_ids.len() { break; }
        if outcome.to_lowercase() == "up" {
            token_id_up = asset_ids[i].to_string();
        } else if outcome.to_lowercase() == "down" {
            token_id_down = asset_ids[i].to_string();
        }
    }
    
    println!("{} Resolved Tokens - UP: {}, DOWN: {}, Strike: {}", get_utc_ts(), token_id_up, token_id_down, strike_price);

    let client = Arc::new(PolymarketClient::new(&pkey, &api_url, proxy_wallet.as_deref(), 137, &rpc_url, sig_type).await);
    
    // --- Startup SQLite Reconciliation against CLOB API ---
    if !is_shadow {
        println!("{} [RECONCILE] Performing startup order reconciliation against Polymarket CLOB API...", get_utc_ts());
        match client.get_open_orders().await {
            Ok(live_orders) => {
                let live_ids: std::collections::HashSet<String> = live_orders.iter().map(|o| o.id.clone()).collect();
                println!("{} [RECONCILE] Found {} active open orders on Polymarket CLOB.", get_utc_ts(), live_ids.len());
                
                let db_orders = {
                    let conn = db_conn.lock().unwrap();
                    persistence::get_all_open_orders(&conn).unwrap_or_default()
                };
                
                let mut purged_count = 0;
                {
                    let conn = db_conn.lock().unwrap();
                    for order in db_orders {
                        // Purge orders from SQLite that are NOT in the active exchange order list, OR that are invalid local intent_ids
                        let is_valid_format = order.order_id.starts_with("0x") || order.order_id.len() > 10;
                        if !is_valid_format || !live_ids.contains(&order.order_id) {
                            if let Err(e) = persistence::delete_order(&conn, &order.order_id) {
                                eprintln!("{} [RECONCILE_ERROR] Failed to purge stale order {} from database: {}", get_utc_ts(), order.order_id, e);
                            } else {
                                purged_count += 1;
                            }
                        }
                    }
                }
                println!("{} [RECONCILE] Successfully purged {} stale/unmapped orders from SQLite database.", get_utc_ts(), purged_count);

                // FORCE CANCEL ALL GHOST ORDERS ON EXCHANGE
                println!("{} [RECONCILE] Forcing cancellation of all {} live orders on exchange to ensure clean state.", get_utc_ts(), live_orders.len());
                for order in live_orders {
                    if let Err(e) = client.cancel_order(&order.id).await {
                        eprintln!("{} [RECONCILE_ERROR] Failed to cancel ghost order {}: {}", get_utc_ts(), order.id, e);
                    }
                }
            }
            Err(e) => {
                eprintln!("{} [RECONCILE_ERROR] Failed to fetch live open orders for reconciliation: {}. Continuing with cached DB state.", get_utc_ts(), e);
            }
        }
    } else {
        println!("{} [RECONCILE] Running in shadow mode. Skipping CLOB API order reconciliation.", get_utc_ts());
    }
    
    // --- Create Flume Channel for Order Requests ---
    let (order_tx, order_rx) = flume::unbounded::<strategy::OrderRequest>();

    // --- Create Telemetry Channel & Redis Publisher Task ---
    let (telemetry_tx, telemetry_rx) = flume::unbounded::<serde_json::Value>();
    tokio::spawn(async move {
        match redis::Client::open("redis://127.0.0.1/") {
            Ok(redis_client) => {
                if let Ok(mut con) = redis_client.get_tokio_connection().await {
                    println!("{} [TELEMETRY] Connected to Redis for PnL/EV logging.", get_utc_ts());
                    while let Ok(msg) = telemetry_rx.recv_async().await {
                        let _ : redis::RedisResult<()> = redis::cmd("PUBLISH")
                            .arg("hft_telemetry")
                            .arg(msg.to_string())
                            .query_async(&mut con).await;
                    }
                } else {
                    eprintln!("{} [TELEMETRY_ERROR] Failed to establish Redis async connection.", get_utc_ts());
                }
            }
            Err(e) => {
                eprintln!("{} [TELEMETRY_ERROR] Failed to create Redis client: {}", get_utc_ts(), e);
            }
        }
    });

    // --- Create Strategy ---
    let mut strat = Strategy::new(Some(Arc::clone(&client)), Some(db_conn.clone()), is_shadow, asset_name.clone(), token_id_up.clone(), token_id_down.clone(), strike_price, config, journal.clone(), order_tx.clone(), Some(telemetry_tx));

    tokio::spawn(spawn_order_processor_task(
        Arc::clone(&client),
        Arc::clone(&db_conn),
        strat.outcome_tx.clone(),
        order_rx,
        strat.open_limit_orders.clone(),
        Arc::clone(&processed_intents),
        asset_name.clone(),
        is_shadow,
    ));

    if !is_shadow {
        let client_clone = Arc::clone(&client);
        let open_limit_orders_clone = strat.open_limit_orders.clone();
        let db_conn_clone = db_conn.clone();
        let asset_name_clone = asset_name.clone();
        let outcome_tx_clone = strat.outcome_tx.clone();
        let token_up_clone = token_id_up.clone();
        let token_down_clone = token_id_down.clone();
        tokio::spawn(async move {
            println!("{} [FILL_MONITOR] Active for {}.", get_utc_ts(), asset_name_clone);
            loop {
                tokio::time::sleep(std::time::Duration::from_millis(1000)).await;
                match client_clone.get_open_orders().await {
                    Ok(live_orders) => {
                        let live_ids: std::collections::HashSet<String> = live_orders.iter().map(|o| o.id.clone()).collect();
                        
                        // Reconcile: Cancel untracked open orders on the exchange
                        for live_order in live_orders.iter() {
                            let live_asset_str = live_order.asset_id.to_string();
                            if live_asset_str != token_up_clone && live_asset_str != token_down_clone {
                                continue; // Skip orders belonging to other executors (e.g. BTC vs ETH)
                            }
                            let local_exists = {
                                let orders = open_limit_orders_clone.lock().unwrap();
                                orders.contains_key(&live_order.id)
                            };
                            if !local_exists {
                                println!("{} [RECONCILE] Found untracked open order on exchange: ID={}. Cancelling it.",
                                    get_utc_ts(), live_order.id);
                                let client_c = client_clone.clone();
                                let oid = live_order.id.clone();
                                tokio::spawn(async move {
                                    let _ = client_c.cancel_order(&oid).await;
                                });
                            }
                        }

                        let mut missing_orders = Vec::new();
                        {
                            let orders = open_limit_orders_clone.lock().unwrap();
                            for (order_id, order) in orders.iter() {
                                let is_valid_format = order_id.starts_with("0x") || order_id.len() > 10;
                                if is_valid_format && !live_ids.contains(order_id) {
                                    if order.filled_size_shares < 0.01 {
                                        missing_orders.push((order_id.clone(), order.original_size_shares));
                                    }
                                }
                            }
                        }

                        for (order_id, original_shares) in missing_orders {
                            match client_clone.get_order(&order_id).await {
                                Ok(order_resp) => {
                                    let filled_shares = std::str::FromStr::from_str(&order_resp.size_matched.to_string()).unwrap_or(0.0);
                                    if filled_shares > 0.01 {
                                        println!("{} [FILL_MONITOR] Confirmed fill for order {}. Side: {:?}, Shares: {:.2}/{:.2}, Price: {:?}",
                                            get_utc_ts(), order_id, order_resp.side, filled_shares, original_shares, order_resp.price);
                                        
                                        let mut orders = open_limit_orders_clone.lock().unwrap();
                                        if let Some(order) = orders.get_mut(&order_id) {
                                            order.filled_size_shares = filled_shares;
                                            // For taker FAK/IOC orders or any order that is no longer on the exchange,
                                            // we must mark it as completed so it is processed and removed in strategy.rs
                                            order.original_size_shares = filled_shares;
                                        }
                                    } else {
                                        println!("{} [FILL_MONITOR] Order {} was canceled on-chain with 0 fills. Purging.", get_utc_ts(), order_id);
                                        let mut reserved_usd = 0.0;
                                        {
                                            let mut orders = open_limit_orders_clone.lock().unwrap();
                                            if let Some(order) = orders.remove(&order_id) {
                                                reserved_usd = order.reserved_usd;
                                            }
                                        }
                                        let conn = db_conn_clone.lock().unwrap();
                                        let _ = persistence::delete_order(&conn, &order_id);
                                        if reserved_usd > 0.01 {
                                            let _ = outcome_tx_clone.send(strategy::StrategyUpdate::CollateralReturn(reserved_usd));
                                        }
                                    }
                                }
                                Err(e) => {
                                    eprintln!("{} [FILL_MONITOR_ERROR] Failed to query order details for {}: {:?}", get_utc_ts(), order_id, e);
                                    let err_str = format!("{:?}", e);
                                    if err_str.contains("404") || err_str.contains("Not Found") {
                                        println!("{} [FILL_MONITOR] Order {} returned 404. Treating as canceled on-chain and purging.", get_utc_ts(), order_id);
                                        let mut reserved_usd = 0.0;
                                        {
                                            let mut orders = open_limit_orders_clone.lock().unwrap();
                                            if let Some(order) = orders.remove(&order_id) {
                                                reserved_usd = order.reserved_usd;
                                            }
                                        }
                                        let conn = db_conn_clone.lock().unwrap();
                                        let _ = persistence::delete_order(&conn, &order_id);
                                        if reserved_usd > 0.01 {
                                            let _ = outcome_tx_clone.send(strategy::StrategyUpdate::CollateralReturn(reserved_usd));
                                        }
                                    }
                                }
                            }
                        }
                    }
                    Err(e) => {
                        eprintln!("{} [FILL_MONITOR_ERROR] Failed to fetch open orders: {:?}", get_utc_ts(), e);
                    }
                }
            }
        });
    }

    let asset_name_clone = asset_name.clone();
    let _ = tokio::task::spawn_blocking(move || {
        let l2_shm_name = std::env::var("SHM_NAME").unwrap_or_else(|_| format!("/hl_l2_book_{}", asset_name_clone));
        let acc_shm_name = std::env::var("ACC_SHM_NAME").unwrap_or_else(|_| format!("/poly_account_{}", asset_name_clone));
        let cog_shm_name = std::env::var("COG_SHM_NAME").unwrap_or_else(|_| format!("/hl_cognition_{}", asset_name_clone));
        let pos_info_shm_name = format!("/poly_position_info_{}", asset_name_clone);
        let global_risk_shm_name = "/poly_global_risk".to_string();

        let l2_reader = match ShmReader::<SpscRingBufferRust<L2BookStruct>>::new(&l2_shm_name) {
            Ok(r) => r,
            Err(e) => {
                eprintln!("{} [CRITICAL] Failed to open L2 SHM {}: {}. C++ Ingestors must be running first!", get_utc_ts(), l2_shm_name, e);
                std::process::exit(1);
            }
        };
        let mut pos_info_writer = match ShmWriter::<PositionInfoStruct>::new(&pos_info_shm_name) {
            Ok(w) => w,
            Err(e) => {
                eprintln!("{} [CRITICAL] Failed to create PositionInfo SHM {}: {}", get_utc_ts(), pos_info_shm_name, e);
                std::process::exit(1);
            }
        };
        let mut global_risk_writer = match ShmWriter::<GlobalRiskStruct>::new(&global_risk_shm_name) {
            Ok(w) => w,
            Err(e) => {
                eprintln!("{} [CRITICAL] Failed to create GlobalRisk SHM {}: {}", get_utc_ts(), global_risk_shm_name, e);
                std::process::exit(1);
            }
        };
        
        let mut cog_reader = None;
        let mut acc_reader = None;

        let mut last_rotation_ts = 0;
        
        let mock_acc = AccountStateStruct::default();

        println!("{} Entering high-speed async fan-out loop (CPU Spin SPSC)...", get_utc_ts());
        unsafe {
            let current_write = (*l2_reader.ptr).write_index.load(Ordering::Acquire);
            (*l2_reader.ptr).read_index.store(current_write, Ordering::Release);
            println!("{} [INIT] Fast-forwarded SPSC Ring Buffer read_index to {} to skip backlog", get_utc_ts(), current_write);
        }
        loop {
            unsafe {
                if let Some(l2_snapshot_struct) = (*l2_reader.ptr).pop() {
                    if cog_reader.is_none() { cog_reader = ShmReader::<CognitionStateStruct>::new(&cog_shm_name).ok(); }
                    if acc_reader.is_none() { acc_reader = ShmReader::<AccountStateStruct>::new(&acc_shm_name).ok(); }
                    let l2_snapshot = l2_snapshot_struct.copy_to_snapshot();

                    if l2_snapshot.timeframe_minutes != timeframe as u32 {
                        eprintln!(
                            "{} [CRITICAL] Timeframe mismatch detected! Ingestor (SHM): {}m, Executor: {}m. Aborting process to prevent incorrect trading logic.",
                            get_utc_ts(),
                            l2_snapshot.timeframe_minutes,
                            timeframe
                        );
                        std::process::exit(1);
                    }

                    if l2_snapshot.rotation_ts != last_rotation_ts {
                        let new_up = String::from_utf8_lossy(&l2_snapshot.poly_up_id).split('\0').next().unwrap_or("").to_string();
                        let new_down = String::from_utf8_lossy(&l2_snapshot.poly_down_id).split('\0').next().unwrap_or("").to_string();
                        println!("{} [ROLL] Market rotation. New UP: {}, New DOWN: {}, Strike: {:.2}", get_utc_ts(), new_up, new_down, l2_snapshot.strike_price);
                        
                        // Cancel orders for the old token_ids
                        let strat_clone_for_cancel = strat.client.clone();
                        let db_conn_clone_for_cancel = strat.db_conn.clone();
                        let open_limit_orders_clone_for_cancel = strat.open_limit_orders.clone();
                        tokio::spawn(async move {
                            if let Some(client) = strat_clone_for_cancel {
                                let orders_to_cancel = {
                                    let orders = open_limit_orders_clone_for_cancel.lock().unwrap();
                                    orders.keys().cloned().collect::<Vec<String>>()
                                };
                                for order_id in orders_to_cancel {
                                    if client.cancel_order(&order_id).await.is_ok() {
                                        if let Some(conn_mutex) = &db_conn_clone_for_cancel {
                                            let _ = persistence::delete_order(&conn_mutex.lock().unwrap(), &order_id);
                                        }
                                        open_limit_orders_clone_for_cancel.lock().unwrap().remove(&order_id);
                                    }
                                }
                            }
                        });

                        // Check and immediately liquidate lingering old positions prior to swapping token IDs on strat
                        if strat.internal_up_position > 0.01 || strat.internal_down_position > 0.01 {
                            eprintln!("{} [ROLL_RISK] Lingering old position detected during rotation! Forcing aggressive liquidation.", get_utc_ts());
                            let client_clone = strat.client.clone();
                            let up_token = strat.token_id_up.clone();
                            let up_pos = strat.internal_up_position;
                            let down_token = strat.token_id_down.clone();
                            let down_pos = strat.internal_down_position;
                            
                            if strat.is_shadow {
                                println!("{} [ROLL_RISK_SHADOW] Simulating shadow liquidation of lingering positions: UP={:.2}, DOWN={:.2}", get_utc_ts(), up_pos, down_pos);
                                // Assume they are liquidated at average prices of 0.50 for simulation, credit the proceeds to virtual available collateral
                                let proceeds = (up_pos + down_pos) * 0.50;
                                strat.available_collateral_internal += proceeds;
                                strat.internal_up_position = 0.0;
                                strat.internal_down_position = 0.0;

                                // Log UP shadow liquidation to trades.log
                                if up_pos > 0.01 {
                                    audit::log_event(&audit::new_order_event(
                                        asset_name_clone.clone(),
                                        audit::OrderDetail {
                                            token_id: up_token.clone(),
                                            order_type: "MARKET".to_string(),
                                            side: "Sell".to_string(),
                                            quantity_tokens: up_pos * 0.99,
                                            price: 0.50,
                                            exchange_order_id: Some("SHADOW_LIQ_UP".to_string()),
                                        },
                                        audit::ReasonDetail { p_theo: 0.50, p_market: 0.50, edge: 0.0, kelly_fraction: 0.0, other_signals: std::collections::HashMap::new() },
                                        audit::OutcomeDetail { status: "SUCCESS".to_string(), error_message: None, fill_price: Some(0.50), fill_quantity: Some(up_pos * 0.99), fees: Some(0.0) }
                                    ), None);
                                }
                                // Log DOWN shadow liquidation to trades.log
                                if down_pos > 0.01 {
                                    audit::log_event(&audit::new_order_event(
                                        asset_name_clone.clone(),
                                        audit::OrderDetail {
                                            token_id: down_token.clone(),
                                            order_type: "MARKET".to_string(),
                                            side: "Sell".to_string(),
                                            quantity_tokens: down_pos * 0.99,
                                            price: 0.50,
                                            exchange_order_id: Some("SHADOW_LIQ_DOWN".to_string()),
                                        },
                                        audit::ReasonDetail { p_theo: 0.50, p_market: 0.50, edge: 0.0, kelly_fraction: 0.0, other_signals: std::collections::HashMap::new() },
                                        audit::OutcomeDetail { status: "SUCCESS".to_string(), error_message: None, fill_price: Some(0.50), fill_quantity: Some(down_pos * 0.99), fees: Some(0.0) }
                                    ), None);
                                }
                            } else {
                                let asset_name_log = asset_name_clone.clone();
                                tokio::spawn(async move {
                                    if let Some(client) = client_clone {
                                        if up_pos > 0.01 {
                                            match client.submit_market_order(&up_token, up_pos * 0.99, polymarket_client_sdk_v2::clob::types::Side::Sell, 100).await {
                                                Ok(resp) => {
                                                    audit::log_event(&audit::new_order_event(
                                                        asset_name_log.clone(),
                                                        audit::OrderDetail {
                                                            token_id: up_token.clone(),
                                                            order_type: "MARKET".to_string(),
                                                            side: "Sell".to_string(),
                                                            quantity_tokens: up_pos * 0.99,
                                                            price: 0.0,
                                                            exchange_order_id: Some(resp.order_id),
                                                        },
                                                        audit::ReasonDetail { p_theo: 0.0, p_market: 0.0, edge: 0.0, kelly_fraction: 0.0, other_signals: std::collections::HashMap::new() },
                                                        audit::OutcomeDetail { status: "SUCCESS".to_string(), error_message: None, fill_price: None, fill_quantity: None, fees: None }
                                                    ), None);
                                                }
                                                Err(e) => {
                                                    audit::log_event(&audit::new_order_event(
                                                        asset_name_log.clone(),
                                                        audit::OrderDetail {
                                                            token_id: up_token.clone(),
                                                            order_type: "MARKET".to_string(),
                                                            side: "Sell".to_string(),
                                                            quantity_tokens: up_pos * 0.99,
                                                            price: 0.0,
                                                            exchange_order_id: None,
                                                        },
                                                        audit::ReasonDetail { p_theo: 0.0, p_market: 0.0, edge: 0.0, kelly_fraction: 0.0, other_signals: std::collections::HashMap::new() },
                                                        audit::OutcomeDetail { status: "FAILURE".to_string(), error_message: Some(e.to_string()), fill_price: None, fill_quantity: None, fees: None }
                                                    ), None);
                                                }
                                            }
                                        }
                                        if down_pos > 0.01 {
                                            match client.submit_market_order(&down_token, down_pos * 0.99, polymarket_client_sdk_v2::clob::types::Side::Sell, 100).await {
                                                Ok(resp) => {
                                                    audit::log_event(&audit::new_order_event(
                                                        asset_name_log.clone(),
                                                        audit::OrderDetail {
                                                            token_id: down_token.clone(),
                                                            order_type: "MARKET".to_string(),
                                                            side: "Sell".to_string(),
                                                            quantity_tokens: down_pos * 0.99,
                                                            price: 0.0,
                                                            exchange_order_id: Some(resp.order_id),
                                                        },
                                                        audit::ReasonDetail { p_theo: 0.0, p_market: 0.0, edge: 0.0, kelly_fraction: 0.0, other_signals: std::collections::HashMap::new() },
                                                        audit::OutcomeDetail { status: "SUCCESS".to_string(), error_message: None, fill_price: None, fill_quantity: None, fees: None }
                                                    ), None);
                                                }
                                                Err(e) => {
                                                    audit::log_event(&audit::new_order_event(
                                                        asset_name_log.clone(),
                                                        audit::OrderDetail {
                                                            token_id: down_token.clone(),
                                                            order_type: "MARKET".to_string(),
                                                            side: "Sell".to_string(),
                                                            quantity_tokens: down_pos * 0.99,
                                                            price: 0.0,
                                                            exchange_order_id: None,
                                                        },
                                                        audit::ReasonDetail { p_theo: 0.0, p_market: 0.0, edge: 0.0, kelly_fraction: 0.0, other_signals: std::collections::HashMap::new() },
                                                        audit::OutcomeDetail { status: "FAILURE".to_string(), error_message: Some(e.to_string()), fill_price: None, fill_quantity: None, fees: None }
                                                    ), None);
                                                }
                                            }
                                        }
                                    }
                                });
                            }
                        }

                        strat.token_id_up = new_up;
                        strat.token_id_down = new_down;
                        strat.internal_up_position = 0.0;
                        strat.internal_down_position = 0.0;
                        strat.is_cancelling_bid_up = false;
                        strat.is_cancelling_ask_up = false;
                        strat.is_cancelling_bid_down = false;
                        strat.is_cancelling_ask_down = false;
                        strat.strike_price = l2_snapshot.strike_price;
                        last_rotation_ts = l2_snapshot.rotation_ts;
                        strat.circuit_breaker_tripped.store(false, Ordering::Release);
                    } else if l2_snapshot.strike_price > 0.0 && l2_snapshot.strike_price != strat.strike_price {
                        println!("{} [SYNC] Strike Anchored: {:.2}", get_utc_ts(), l2_snapshot.strike_price);
                        strat.strike_price = l2_snapshot.strike_price;
                    }

                    let cog = cog_reader.as_ref().map(|cr| &*cr.ptr);
                    let acc = acc_reader.as_ref().map(|ar| &*ar.ptr).unwrap_or(&mock_acc);
                    
                    if let Err(e) = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        strat.tick(&l2_snapshot, cog, acc, &mut pos_info_writer, &mut global_risk_writer)
                    })) {
                        eprintln!("{} [PANIC_DETECTED] Strategy tick panicked: {:?}", get_utc_ts(), e);
                    }
                } else {
                    std::hint::spin_loop();
                }
            }
        }
    }).await;
} // This closes the tokio::task::spawn_blocking block
