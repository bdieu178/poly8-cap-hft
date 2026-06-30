use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;
use duckdb::{Connection, Result as DuckDBResult};
use redis::AsyncCommands;
use serde_json::Value;
use futures_util::stream::StreamExt;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::ffi::CString;
use libc::{shm_open, mmap, O_RDWR, PROT_READ, PROT_WRITE, MAP_SHARED};

#[repr(C)]
#[derive(Debug)]
pub struct GlobalRiskStruct {
    pub sequence: AtomicU64,
    pub global_gross_exposure: AtomicU64, // Notional USD (bits)
    pub global_net_pnl: AtomicU64,        // Realized PnL - Fees (bits)
    pub daily_stop_loss_triggered: AtomicU64, // 1 if triggered
    pub last_update_ts: AtomicU64,
}

pub struct ShmWriter<T> {
    pub ptr: *mut T,
}

impl<T> ShmWriter<T> {
    pub fn new(name: &str) -> Result<Self, String> {
        unsafe {
            let c_name = CString::new(name).unwrap();
            let fd = shm_open(c_name.as_ptr(), O_RDWR | libc::O_CREAT, 0o666);
            if fd < 0 {
                return Err(format!("Failed to open/create SHM segment {}: {}", name, fd));
            }
            if libc::ftruncate(fd, std::mem::size_of::<T>() as libc::off_t) == -1 {
                return Err(format!("Failed to ftruncate SHM segment {}", name));
            }
            let ptr = mmap(
                std::ptr::null_mut(),
                std::mem::size_of::<T>(),
                PROT_READ | PROT_WRITE,
                MAP_SHARED,
                fd,
                0,
            );
            if ptr == libc::MAP_FAILED {
                return Err(format!("Failed to mmap SHM segment {}", name));
            }
            // Zero out memory to initialize safely
            std::ptr::write_bytes(ptr, 0, std::mem::size_of::<T>());
            Ok(Self { ptr: ptr as *mut T })
        }
    }
}

#[derive(Debug, Clone, serde::Deserialize, PartialEq)]
pub struct ActivePosition {
    pub asset: String,
    pub token_id: String,
    pub side: String,
    pub quantity: f64,
}

#[derive(Debug, PartialEq)]
pub enum RiskAction {
    Hold,
    Liquidate(f64), // EV value
    TrailingStop(f64), // EV value
}

pub fn evaluate_position_risk(pos: &ActivePosition, latest_telemetry: &Value) -> RiskAction {
    let p_theo_key = format!("p_theo_{}", pos.side.to_lowercase());
    let p_theo = latest_telemetry[&p_theo_key].as_f64().unwrap_or(0.5);
    
    let market_bid_key = format!("p_market_{}_bid", pos.side.to_lowercase());
    let market_bid = latest_telemetry[&market_bid_key].as_f64().unwrap_or(0.0);
    let ev = p_theo - market_bid;

    if ev < -0.05 {
        RiskAction::Liquidate(ev)
    } else if ev > 0.10 {
        RiskAction::TrailingStop(ev)
    } else {
        RiskAction::Hold
    }
}

fn run_analytics_report(conn: &Connection) -> duckdb::Result<()> {
    let mut stmt = conn.prepare(
        "SELECT 
            asset,
            COUNT(*),
            AVG(l4_intensity),
            AVG(p_theo_up - p_market_up_ask),
            AVG(p_theo_down - p_market_down_ask)
         FROM telemetry 
         GROUP BY asset"
    )?;
    let mut rows = stmt.query([])?;
    println!("\n================ TELEMETRY ANALYTICAL REPORT ================");
    while let Some(row) = rows.next()? {
        let asset: String = row.get(0)?;
        let count: i64 = row.get(1)?;
        let avg_intensity: f64 = row.get(2).unwrap_or(0.0);
        let avg_up_edge: f64 = row.get(3).unwrap_or(0.0);
        let avg_dn_edge: f64 = row.get(4).unwrap_or(0.0);
        println!(
            "Asset: {} | Data Points: {} | Avg Hawkes Intensity: {:.4}\n  Avg UP Edge: {:.4} USD | Avg DOWN Edge: {:.4} USD",
            asset, count, avg_intensity, avg_up_edge, avg_dn_edge
        );
    }
    println!("=============================================================\n");
    Ok(())
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("[PORTFOLIO MANAGER] Starting Global Portfolio Manager...");

    // 1. DuckDB Init
    let db_path = "/home/bdieu178/user/defi-agents/polymarket/data/analytics.duckdb";
    let conn = Connection::open(db_path)?;
    conn.execute(
        "CREATE TABLE IF NOT EXISTS telemetry (
            timestamp_ms BIGINT,
            asset VARCHAR,
            strike_price DOUBLE,
            l4_intensity DOUBLE,
            p_market_up_bid DOUBLE,
            p_market_up_ask DOUBLE,
            p_market_down_bid DOUBLE,
            p_market_down_ask DOUBLE,
            p_theo_up DOUBLE,
            p_theo_down DOUBLE,
            q_up DOUBLE,
            q_down DOUBLE,
            equity DOUBLE
        )",
        [],
    )?;

    let db_conn = Arc::new(Mutex::new(conn));

    // 2. Redis Pub/Sub
    let redis_client = redis::Client::open("redis://127.0.0.1/")?;
    let mut pubsub_conn = redis_client.get_async_connection().await?.into_pubsub();
    pubsub_conn.subscribe("hft_telemetry").await?;
    
    // In-memory global state for pricing and positions
    let global_state: Arc<Mutex<HashMap<String, Value>>> = Arc::new(Mutex::new(HashMap::new()));
    let ingestion_state = global_state.clone();
    let ingestion_db = db_conn.clone();

    tokio::spawn(async move {
        let mut batch: Vec<Value> = Vec::new();
        let mut last_flush = tokio::time::Instant::now();
        let mut stream = pubsub_conn.on_message();

        while let Some(msg) = stream.next().await {
            let payload: String = match msg.get_payload() {
                Ok(p) => p,
                Err(_) => continue,
            };
            if let Ok(json) = serde_json::from_str::<Value>(&payload) {
                if let Some(asset) = json.get("asset").and_then(|v| v.as_str()) {
                    let mut state = ingestion_state.lock().await;
                    state.insert(asset.to_string(), json.clone());
                }
                batch.push(json);
            }

            if batch.len() >= 100 || last_flush.elapsed().as_secs() >= 5 {
                let conn = ingestion_db.lock().await;
                if let Ok(mut appender) = conn.appender("telemetry") {
                    for row in batch.drain(..) {
                        let _ = appender.append_row(duckdb::params![
                            row["timestamp_ms"].as_i64(),
                            row["asset"].as_str(),
                            row["strike_price"].as_f64(),
                            row["l4_intensity"].as_f64(),
                            row["p_market_up_bid"].as_f64(),
                            row["p_market_up_ask"].as_f64(),
                            row["p_market_down_bid"].as_f64(),
                            row["p_market_down_ask"].as_f64(),
                            row["p_theo_up"].as_f64(),
                            row["p_theo_down"].as_f64(),
                            row["q_up"].as_f64(),
                            row["q_down"].as_f64(),
                            row["equity"].as_f64()
                        ]);
                    }
                }
                last_flush = tokio::time::Instant::now();
            }
        }
    });

    // 3. Connect to Shared Memory Global Risk
    let risk_writer = ShmWriter::<GlobalRiskStruct>::new("/poly_global_risk").ok();

    println!("[PORTFOLIO MANAGER] DuckDB & Redis running. Engaging Global Risk Engine...");

    let mut tick_counter = 0;

    // 4. EV Exit Engine Loop
    loop {
        let mut total_exposure = 0.0;
        let positions_file = "/home/bdieu178/user/defi-agents/polymarket/data/active_positions.json";
        
        if let Ok(data) = tokio::fs::read_to_string(positions_file).await {
            if let Ok(positions) = serde_json::from_str::<Vec<ActivePosition>>(&data) {
                let state = global_state.lock().await;
                for pos in positions {
                    if let Some(latest_telemetry) = state.get(&pos.asset) {
                        let price_key = format!("p_market_{}_bid", pos.side.to_lowercase());
                        let price = latest_telemetry[&price_key].as_f64().unwrap_or(0.5);
                        total_exposure += pos.quantity * price;

                        let risk_action = evaluate_position_risk(&pos, latest_telemetry);
                        match risk_action {
                            RiskAction::Liquidate(ev) => {
                                println!("[RISK ENGINE] 🚨 SEVERE NEGATIVE EV DETECTED! Asset: {}, Token: {}, EV: {:.4}. (Native Hot-Path executor will handle liquidation)", pos.asset, pos.token_id, ev);
                            },
                            RiskAction::TrailingStop(ev) => {
                                println!("[RISK ENGINE] 📈 Position highly profitable! Tracking for trailing stop... Asset: {}, Token: {}, EV: {:.4}. (Native Hot-Path executor will handle Take Profit)", pos.asset, pos.token_id, ev);
                            },
                            RiskAction::Hold => {}
                        }
                    }
                }
            }
        }

        // Write to global risk in shared memory
        if let Some(ref writer) = risk_writer {
            unsafe {
                let gr = &mut *writer.ptr;
                gr.global_gross_exposure.store(total_exposure.to_bits(), Ordering::Release);
                
                // If gross exposure exceeds $5,000 threshold, trigger halt
                if total_exposure > 5000.0 {
                    println!("[RISK ENGINE] ⚠️ Global gross exposure limit exceeded! Exposure: ${:.2} > $5000.00. Triggering HALT.", total_exposure);
                    gr.daily_stop_loss_triggered.store(1, Ordering::Release);
                }
                gr.sequence.fetch_add(1, Ordering::Relaxed);
            }
        }

        tick_counter += 1;
        if tick_counter % 5 == 0 {
            // Run analytics query on DuckDB every 10 seconds
            let db_conn_lock = db_conn.lock().await;
            let _ = run_analytics_report(&db_conn_lock);
        }

        tokio::time::sleep(Duration::from_secs(2)).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_evaluate_position_risk_liquidate() {
        let pos = ActivePosition {
            asset: "btc".to_string(),
            token_id: "test_token".to_string(),
            side: "UP".to_string(),
            quantity: 10.0,
        };
        
        let telemetry = json!({
            "p_theo_up": 0.40,
            "p_market_up_bid": 0.50
        });

        let action = evaluate_position_risk(&pos, &telemetry);
        match action {
            RiskAction::Liquidate(ev) => assert!((ev - -0.10).abs() < 1e-9),
            _ => panic!("Expected Liquidation!"),
        }
    }

    #[test]
    fn test_evaluate_position_risk_trailing_stop() {
        let pos = ActivePosition {
            asset: "btc".to_string(),
            token_id: "test_token".to_string(),
            side: "DOWN".to_string(),
            quantity: 10.0,
        };
        
        let telemetry = json!({
            "p_theo_down": 0.65,
            "p_market_down_bid": 0.50
        });

        let action = evaluate_position_risk(&pos, &telemetry);
        match action {
            RiskAction::TrailingStop(ev) => assert!((ev - 0.15).abs() < 1e-9),
            _ => panic!("Expected Trailing Stop!"),
        }
    }
}
