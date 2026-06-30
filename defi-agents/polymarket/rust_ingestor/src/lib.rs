use std::env;
use std::str::FromStr;
use std::time::{SystemTime, Duration};
use std::sync::{Arc, Mutex, atomic::Ordering};
use polymarket_client_sdk_v2::clob::ws::Client as PolyWsClient;
use polymarket_client_sdk_v2::clob::ws::types::response::BookUpdate;
use alloy::primitives::{U256, B256};
use futures::stream::StreamExt;
use tokio::sync::mpsc;
use clap::Parser;
use std::future::Future;

pub mod shm;
pub mod market_discovery;
pub mod web3_client;
pub mod hl_client;

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
pub struct Args {
   /// Asset name for isolation (e.g. btc, eth)
   #[arg(long)]
   pub asset: String,
}

// Enum to wrap messages from different sources
#[derive(Debug)]
pub enum IngestMessage {
    PolyBook(BookUpdate),
    HlBook(hl_client::orderbook::L2BookUpdate),
    AccountUpdate(web3_client::AccountBalances),
}

pub async fn run(args: Args, shutdown_signal: impl Future<Output = ()> + Send + 'static) -> Result<(), String> {
    dotenvy::from_path("../.env").expect("Failed to read .env file from parent directory");
    println!("Starting Rust Ingestor for asset: {}", args.asset);

    // --- Environment Variables ---
    let asset = args.asset.clone();
    let polygon_rpc_url = env::var("POLYGON_RPC_URL").expect("POLYGON_RPC_URL must be set");
    let wallet_address = env::var("POLY_WALLET_ADDRESS").expect("POLY_WALLET_ADDRESS must be set");
    let pusd_address = env::var("PUSD_ADDRESS").unwrap_or_else(|_| "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb".to_string());
    let ctf_address = env::var("CTF_ADDRESS").unwrap_or_else(|_| "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045".to_string());
    let hl_grpc_url = env::var("HYPERLIQUID_GRPC_TARGET").expect("HYPERLIQUID_GRPC_TARGET must be set");
    let hl_auth_token = env::var("HYPERLIQUID_AUTH_TOKEN").expect("HYPERLIQUID_AUTH_TOKEN must be set");
    let gamma_api_url = env::var("GAMMA_API_URL").unwrap_or_else(|_| "https://gamma-api.polymarket.com".to_string());

    // --- Market Discovery ---
    let (up_id, down_id) = market_discovery::fetch_active_token_ids(&gamma_api_url, &asset).await.map_err(|e| e.to_string())?;
    let up_id_u256 = U256::from_str(&up_id).map_err(|e| e.to_string())?;
    let down_id_u256 = U256::from_str(&down_id).map_err(|e| e.to_string())?;
    println!("Found Polymarket UP ID: {}, DOWN ID: {}", up_id, down_id);

    // --- Shared Memory Setup ---
    let l2_shm_name = format!("/hl_l2_book_{}", asset);
    let l2_shm_writer = Arc::new(Mutex::new(shm::ShmWriter::<shm::L2BookStruct>::new(&l2_shm_name).map_err(|e| e.to_string())?));
    println!("L2 Book SHM writer created for {}", l2_shm_name);

    let acc_shm_name = format!("/poly_account_{}", asset);
    let acc_shm_writer = Arc::new(Mutex::new(shm::ShmWriter::<shm::AccountStateStruct>::new(&acc_shm_name).map_err(|e| e.to_string())?));
    println!("Account State SHM writer created for {}", acc_shm_name);

    // --- MPSC Channel for Merging Streams ---
    let (tx, mut rx) = mpsc::channel(100);

    // --- Task for Polymarket WebSocket ---
    let poly_tx = tx.clone();
    let poly_up_id = up_id_u256;
    let poly_down_id = down_id_u256;
    tokio::spawn(async move {
        println!("Connecting to Polymarket WebSocket...");
        let client = PolyWsClient::default();
        let stream = client.subscribe_orderbook(vec![poly_up_id, poly_down_id]).unwrap();
        let mut pinned_stream = Box::pin(stream);
        println!("Subscribed to Polymarket order book stream.");

        while let Some(book_update_result) = pinned_stream.next().await {
            match book_update_result {
                Ok(book_update) => {
                    if poly_tx.send(IngestMessage::PolyBook(book_update)).await.is_err() {
                        eprintln!("Failed to send Polymarket book update to channel.");
                        break;
                    }
                }
                Err(e) => eprintln!("Error receiving Polymarket book update: {}", e),
            }
        }
    });

    // --- Task for Hyperliquid gRPC ---
    if env::var("TEST_DISABLE_HL").is_err() {
        let hl_tx = tx.clone();
        let asset_clone_hl = asset.clone();
        tokio::spawn(async move {
            println!("Connecting to Hyperliquid gRPC at {}...", hl_grpc_url);
            match hl_client::stream_l2_book(hl_grpc_url, asset_clone_hl, hl_auth_token).await {
                Ok(response) => {
                    let mut stream = response.into_inner();
                    println!("Subscribed to Hyperliquid L2 book stream.");
                    while let Ok(Some(l2_update)) = stream.message().await {
                        if hl_tx.send(IngestMessage::HlBook(l2_update)).await.is_err() {
                            eprintln!("Failed to send Hyperliquid book update to channel.");
                            break;
                        }
                    }
                }
                Err(e) => eprintln!("Failed to connect to Hyperliquid gRPC: {}", e),
            }
        });
    }

    // --- Task for Web3 Account Sync ---
    if env::var("TEST_DISABLE_WEB3").is_err() {
        let web3_tx = tx.clone();
        let up_id_clone_web3 = up_id_u256;
        let down_id_clone_web3 = down_id_u256;
        tokio::spawn(async move {
            loop {
                println!("Fetching account balances...");
                match web3_client::fetch_balances(
                    &polygon_rpc_url,
                    &wallet_address,
                    &pusd_address,
                    &ctf_address,
                    up_id_clone_web3,
                    down_id_clone_web3,
                ).await {
                    Ok(balances) => {
                        if web3_tx.send(IngestMessage::AccountUpdate(balances)).await.is_err() {
                            eprintln!("Failed to send account update to channel.");
                            break;
                        }
                    }
                    Err(e) => eprintln!("Failed to fetch balances: {}", e),
                }
                tokio::time::sleep(Duration::from_secs(15)).await;
            }
        });
    }

    // --- Main Processing Loop ---
    println!("Waiting for combined data stream...");
    tokio::select! {
        _ = shutdown_signal => {
            println!("Shutdown signal received, terminating ingestor.");
        }
        res = async {
            while let Some(message) = rx.recv().await {
                match message {
                    IngestMessage::PolyBook(book_update) => {
                        let mut writer_guard = l2_shm_writer.lock().unwrap();
                        let book = unsafe { &mut *writer_guard.ptr };
                        let current_seq = book.poly_sequence.load(Ordering::Relaxed);
                        book.poly_sequence.store(current_seq + 1, Ordering::Relaxed);
                        
                        let is_up = book_update.asset_id == up_id_u256;
                        let (target_bids, target_asks, timestamp_field) = if is_up {
                            (&mut book.poly_up_bids, &mut book.poly_up_asks, &mut book.poly_up_timestamp)
                        } else {
                            (&mut book.poly_down_bids, &mut book.poly_down_asks, &mut book.poly_down_timestamp)
                        };
                        let now_ms = SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).map_err(|e| e.to_string())?.as_millis() as u64;
                        *timestamp_field = now_ms;
                        book.last_update_local_ns = now_ms * 1_000_000;

                        let mut bids_sorted: Vec<_> = book_update.bids.iter().map(|l| (l.price, l.size)).collect();
                        bids_sorted.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
                        
                        let mut asks_sorted: Vec<_> = book_update.asks.iter().map(|l| (l.price, l.size)).collect();
                        asks_sorted.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));

                        for i in 0..shm::MAX_POLY_LEVELS {
                            if i < bids_sorted.len() {
                                target_bids[i].price = bids_sorted[i].0.try_into().unwrap_or(0.0);
                                target_bids[i].size = bids_sorted[i].1.try_into().unwrap_or(0.0);
                            } else {
                                target_bids[i] = shm::PriceLevel::default();
                            }
                            if i < asks_sorted.len() {
                                target_asks[i].price = asks_sorted[i].0.try_into().unwrap_or(0.0);
                                target_asks[i].size = asks_sorted[i].1.try_into().unwrap_or(0.0);
                            } else {
                                target_asks[i] = shm::PriceLevel::default();
                            }
                        }
                        book.poly_sequence.store(current_seq + 2, Ordering::Release);
                        println!("Wrote Poly book update to SHM (Seq: {})", current_seq + 2);
                    }
                    IngestMessage::HlBook(l2_update) => {
                        let mut writer_guard = l2_shm_writer.lock().unwrap();
                        let book = unsafe { &mut *writer_guard.ptr };
                        let current_seq = book.hl_sequence.load(Ordering::Relaxed);
                        book.hl_sequence.store(current_seq + 1, Ordering::Relaxed);
                        
                        let now_ms = SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).map_err(|e| e.to_string())?.as_millis() as u64;
                        book.hl_timestamp = l2_update.time;
                        book.last_update_local_ns = now_ms * 1_000_000;
                        
                        for i in 0..shm::MAX_LEVELS {
                            if i < l2_update.bids.len() {
                                book.hl_bids[i].price = l2_update.bids[i].px.parse::<f64>().unwrap_or(0.0);
                                book.hl_bids[i].size = l2_update.bids[i].sz.parse::<f64>().unwrap_or(0.0);
                            } else {
                                book.hl_bids[i] = shm::PriceLevel::default();
                            }
                            if i < l2_update.asks.len() {
                                book.hl_asks[i].price = l2_update.asks[i].px.parse::<f64>().unwrap_or(0.0);
                                book.hl_asks[i].size = l2_update.asks[i].sz.parse::<f64>().unwrap_or(0.0);
                            } else {
                                book.hl_asks[i] = shm::PriceLevel::default();
                            }
                        }
                        book.hl_sequence.store(current_seq + 2, Ordering::Release);
                        println!("Wrote HL book update to SHM (Seq: {})", current_seq + 2);
                    }
                    IngestMessage::AccountUpdate(balances) => {
                        let mut writer_guard = acc_shm_writer.lock().unwrap();
                        let acc = unsafe { &mut *writer_guard.ptr };
                        let current_seq = acc.sequence.load(Ordering::Relaxed);
                        acc.sequence.store(current_seq + 1, Ordering::Relaxed);
                        
                        acc.available_collateral = balances.pusd_balance;
                        acc.up_position = balances.up_balance;
                        acc.down_position = balances.down_balance;
                        acc.total_equity = balances.pusd_balance + balances.up_balance + balances.down_balance;
                        acc.last_update_ts = SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).map_err(|e| e.to_string())?.as_millis() as u64;
                        
                        acc.sequence.store(current_seq + 2, Ordering::Release);
                        println!("Wrote account update to SHM (Seq: {})", current_seq + 2);
                    }
                }
            }
            Ok(())
        } => if let Err(e) = res { return Err(e); }
    }
    Ok(())
}

#[cfg(test)]
pub use self::run_test::run_test;

#[cfg(test)]
mod run_test {
    use super::*;
    use polymarket_client_sdk_v2::clob::ws::types::response::BookUpdate;
    use alloy::primitives::B256;

    pub async fn run_test(args: Args, shutdown_signal: impl Future<Output = ()> + Send + 'static) -> Result<(), String> {
        dotenvy::from_path("../.env").expect("Failed to read .env file from parent directory");
        println!("Starting Rust Ingestor for asset: {}", args.asset);

        // --- Environment Variables ---
        let asset = args.asset.clone();
        let up_id_u256 = U256::from(111);
        let down_id_u256 = U256::from(222);

        // --- Shared Memory Setup ---
        let l2_shm_name = format!("/hl_l2_book_{}", asset);
        let l2_shm_writer = Arc::new(Mutex::new(shm::ShmWriter::<shm::L2BookStruct>::new(&l2_shm_name).map_err(|e| e.to_string())?));
        println!("L2 Book SHM writer created for {}", l2_shm_name);

        let acc_shm_name = format!("/poly_account_{}", asset);
        let acc_shm_writer = Arc::new(Mutex::new(shm::ShmWriter::<shm::AccountStateStruct>::new(&acc_shm_name).map_err(|e| e.to_string())?));
        println!("Account State SHM writer created for {}", acc_shm_name);

        // --- MPSC Channel for Merging Streams ---
        let (tx, mut rx) = mpsc::channel(100);

        // --- Task for Dummy Data ---
        let dummy_tx = tx.clone();
        tokio::spawn(async move {
            // Send a dummy book update
            let book_update = BookUpdate::builder()
                .asset_id(up_id_u256)
                .market(B256::ZERO)
                .timestamp(1)
                .bids(vec![])
                .asks(vec![])
                .hash(None)
                .build()
                .unwrap();
            dummy_tx.send(IngestMessage::PolyBook(book_update)).await.unwrap();

            // Send a dummy account update
            let balances = web3_client::AccountBalances {
                pusd_balance: 100.0,
                up_balance: 10.0,
                down_balance: 0.0,
            };
            dummy_tx.send(IngestMessage::AccountUpdate(balances)).await.unwrap();
        });


        // --- Main Processing Loop ---
        println!("Waiting for combined data stream...");
        tokio::select! {
            _ = shutdown_signal => {
                println!("Shutdown signal received, terminating ingestor.");
            }
            res = async {
                while let Some(message) = rx.recv().await {
                    match message {
                        IngestMessage::PolyBook(book_update) => {
                            let mut writer_guard = l2_shm_writer.lock().unwrap();
                            let book = unsafe { &mut *writer_guard.ptr };
                            let current_seq = book.sequence.load(Ordering::Relaxed);
                            book.sequence.store(current_seq + 1, Ordering::Relaxed);
                            
                            let is_up = book_update.asset_id == up_id_u256;
                            let (target_bids, target_asks, timestamp_field) = if is_up {
                                (&mut book.poly_up_bids, &mut book.poly_up_asks, &mut book.poly_up_timestamp)
                            } else {
                                (&mut book.poly_down_bids, &mut book.poly_down_asks, &mut book.poly_down_timestamp)
                            };
                            *timestamp_field = SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).map_err(|e| e.to_string())?.as_millis() as u64;

                            for i in 0..shm::MAX_POLY_LEVELS {
                                    target_bids[i] = shm::PriceLevel::default();
                                    target_asks[i] = shm::PriceLevel::default();
                            }
                            book.sequence.store(current_seq + 2, Ordering::Release);
                            println!("Wrote Poly book update to SHM (Seq: {})", current_seq + 2);
                        }
                        IngestMessage::HlBook(_) => {} // Ignore for this test
                        IngestMessage::AccountUpdate(balances) => {
                            let mut writer_guard = acc_shm_writer.lock().unwrap();
                            let acc = unsafe { &mut *writer_guard.ptr };
                            let current_seq = acc.sequence.load(Ordering::Relaxed);
                            acc.sequence.store(current_seq + 1, Ordering::Relaxed);
                            
                            acc.available_collateral = balances.pusd_balance;
                            acc.up_position = balances.up_balance;
                            acc.down_position = balances.down_balance;
                            acc.total_equity = balances.pusd_balance + balances.up_balance + balances.down_balance;
                            acc.last_update_ts = SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).map_err(|e| e.to_string())?.as_millis() as u64;
                            
                            acc.sequence.store(current_seq + 2, Ordering::Release);
                            println!("Wrote account update to SHM (Seq: {})", current_seq + 2);
                        }
                    }
                }
                Ok(())
            } => if let Err(e) = res { return Err(e); }
        }
        Ok(())
    }
}
