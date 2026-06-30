use rusqlite::{Connection, Result, params};
use crate::strategy::TrackedOrder;
use polymarket_client_sdk_v2::clob::types::Side;
use std::time::{SystemTime, UNIX_EPOCH};
use std::path::Path; // Import Path

const DB_PATH: &str = "/home/bdieu178/user/defi-agents/polymarket/data/hft_state.db";

pub fn initialize_db(path_override: Option<&Path>) -> Result<Connection> {
    let mut default_path = std::path::PathBuf::from(DB_PATH);
    if let Ok(home) = std::env::var("HOME") {
        let user_path = std::path::PathBuf::from(format!("{}/user/defi-agents/polymarket/data/hft_state.db", home));
        if user_path.parent().map(|p| p.exists()).unwrap_or(false) {
            default_path = user_path;
        } else {
            let direct_path = std::path::PathBuf::from(format!("{}/defi-agents/polymarket/data/hft_state.db", home));
            if direct_path.parent().map(|p| p.exists()).unwrap_or(false) {
                default_path = direct_path;
            }
        }
    }
    let db_path = path_override.unwrap_or(default_path.as_path());
    let conn = Connection::open(db_path)?;
    let _ = conn.execute("PRAGMA journal_mode=WAL;", []);
    let _ = conn.execute("PRAGMA busy_timeout=5000;", []);
    conn.execute(
        "CREATE TABLE IF NOT EXISTS open_orders (
            order_id TEXT PRIMARY KEY,
            original_size_shares REAL NOT NULL,
            filled_size_shares REAL NOT NULL,
            side TEXT NOT NULL,
            limit_price REAL NOT NULL,
            submission_timestamp_secs INTEGER NOT NULL,
            token_id TEXT NOT NULL
        )",
        [],
    )?;
    conn.execute(
        "CREATE TABLE IF NOT EXISTS position_entry_prices (
            token_id TEXT PRIMARY KEY,
            entry_price REAL NOT NULL
        )",
        [],
    )?;
    Ok(conn)
}

pub fn insert_order(conn: &Connection, order: &TrackedOrder) -> Result<usize> {
    conn.execute(
        "INSERT OR REPLACE INTO open_orders (order_id, original_size_shares, filled_size_shares, side, limit_price, submission_timestamp_secs, token_id)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
        params![
            order.order_id,
            order.original_size_shares,
            order.filled_size_shares,
            order.side.to_string(),
            order.limit_price,
            order.submission_timestamp.duration_since(UNIX_EPOCH).unwrap().as_secs(),
            order.token_id,
        ],
    )
}

pub fn delete_order(conn: &Connection, order_id: &str) -> Result<usize> {
    conn.execute("DELETE FROM open_orders WHERE order_id = ?1", params![order_id])
}

pub fn get_all_open_orders(conn: &Connection) -> Result<Vec<TrackedOrder>> {
    let mut stmt = conn.prepare("SELECT order_id, original_size_shares, filled_size_shares, side, limit_price, submission_timestamp_secs, token_id FROM open_orders")?;
    let order_iter = stmt.query_map([], |row| {
        Ok(TrackedOrder {
            order_id: row.get(0)?,
            original_size_shares: row.get(1)?,
            filled_size_shares: row.get(2)?,
            side: match row.get::<_, String>(3)?.as_str() {
                "Buy" => Side::Buy,
                "Sell" => Side::Sell,
                _ => Side::Buy, // Default case
            },
            limit_price: row.get(4)?,
            submission_timestamp: SystemTime::now(), // Note: This is not the original timestamp. Reconciliation logic will handle staleness.
            token_id: row.get(6)?,
            post_only: true, // Default to true for persistent open orders (maker orders)
            reserved_usd: 0.0,
        })
    })?;

    let mut orders = Vec::new();
    for order in order_iter {
        orders.push(order?);
    }
    Ok(orders)
}

pub fn save_entry_price(conn: &Connection, token_id: &str, entry_price: f64) -> Result<usize> {
    conn.execute(
        "INSERT OR REPLACE INTO position_entry_prices (token_id, entry_price) VALUES (?1, ?2)",
        params![token_id, entry_price],
    )
}

pub fn load_entry_price(conn: &Connection, token_id: &str) -> Result<f64> {
    let mut stmt = conn.prepare("SELECT entry_price FROM position_entry_prices WHERE token_id = ?1")?;
    let mut rows = stmt.query(params![token_id])?;
    if let Some(row) = rows.next()? {
        let price: f64 = row.get(0)?;
        Ok(price)
    } else {
        Ok(0.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::time::{Duration, UNIX_EPOCH};
    use uuid::Uuid;

    fn setup_test_db(db_name: &str) -> (Connection, String) {
        let db_path_string = format!("/tmp/{}.db", db_name);
        let db_path = Path::new(&db_path_string);
        // Ensure clean state for each test
        let _ = fs::remove_file(db_path); 

        let conn = initialize_db(Some(db_path)).unwrap();
        (conn, db_path_string)
    }

    #[test]
    fn test_initialize_db_creates_file() {
        let db_name = Uuid::new_v4().to_string();
        let db_path_string = format!("/tmp/{}.db", db_name);
        let db_path = Path::new(&db_path_string);
        
        let _ = fs::remove_file(db_path); // Ensure clean start
        let _conn = initialize_db(Some(db_path)).unwrap();
        assert!(fs::metadata(db_path).is_ok());
        fs::remove_file(db_path).unwrap();
    }

    #[test]
    fn test_insert_and_get_order() {
        let (conn, db_path_str) = setup_test_db(&Uuid::new_v4().to_string());
        let order_id = Uuid::new_v4().to_string();
        let order = TrackedOrder {
            order_id: order_id.clone(),
            original_size_shares: 1.0,
            filled_size_shares: 0.5,
            side: Side::Buy,
            limit_price: 0.5,
            submission_timestamp: UNIX_EPOCH + Duration::from_secs(1678886400), // Arbitrary timestamp
            token_id: "btc-up".to_string(),
            post_only: true,
            reserved_usd: 0.0,
        };

        insert_order(&conn, &order).unwrap();

        let orders = get_all_open_orders(&conn).unwrap();
        assert_eq!(orders.len(), 1);
        let retrieved_order = &orders[0];
        assert_eq!(retrieved_order.order_id, order_id);
        assert_eq!(retrieved_order.original_size_shares, 1.0);
        assert_eq!(retrieved_order.filled_size_shares, 0.5);
        assert_eq!(retrieved_order.side, Side::Buy);
        assert_eq!(retrieved_order.limit_price, 0.5);
        assert_eq!(retrieved_order.token_id, "btc-up".to_string());
        fs::remove_file(&db_path_str).unwrap(); // Cleanup
    }

    #[test]
    fn test_delete_order() {
        let (conn, db_path_str) = setup_test_db(&Uuid::new_v4().to_string());
        let order_id = Uuid::new_v4().to_string();
        let order = TrackedOrder {
            order_id: order_id.clone(),
            original_size_shares: 1.0,
            filled_size_shares: 0.0,
            side: Side::Sell,
            limit_price: 0.6,
            submission_timestamp: SystemTime::now(),
            token_id: "btc-down".to_string(),
            post_only: true,
            reserved_usd: 0.0,
        };

        insert_order(&conn, &order).unwrap();
        let orders_before_delete = get_all_open_orders(&conn).unwrap();
        assert_eq!(orders_before_delete.len(), 1);

        delete_order(&conn, &order_id).unwrap();
        let orders_after_delete = get_all_open_orders(&conn).unwrap();
        assert_eq!(orders_after_delete.len(), 0);
        fs::remove_file(&db_path_str).unwrap(); // Cleanup
    }

    #[test]
    fn test_get_all_open_orders_empty() {
        let (conn, db_path_str) = setup_test_db(&Uuid::new_v4().to_string());
        let orders = get_all_open_orders(&conn).unwrap();
        assert!(orders.is_empty());
        fs::remove_file(&db_path_str).unwrap(); // Cleanup
    }
}
