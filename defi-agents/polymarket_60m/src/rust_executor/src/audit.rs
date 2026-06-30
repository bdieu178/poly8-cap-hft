
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::{File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf}; // Import PathBuf
use uuid::Uuid;

// --- Data Structures for Audit Logging ---

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct OrderDetail {
    pub token_id: String,
    pub order_type: String, // e.g., "MARKET", "LIMIT"
    pub side: String,       // e.g., "BUY", "SELL"
    pub quantity_tokens: f64,
    pub price: f64, // The limit price for the order
    #[serde(skip_serializing_if = "Option::is_none")]
    pub exchange_order_id: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct ReasonDetail {
    pub p_theo: f64,
    pub p_market: f64,
    pub edge: f64,
    pub kelly_fraction: f64,
    pub other_signals: HashMap<String, f64>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct OutcomeDetail {
    pub status: String, // "SUCCESS", "FAILURE", "FILLED", "PARTIALLY_FILLED"
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error_message: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fill_price: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fill_quantity: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fees: Option<f64>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct AuditEvent {
    pub timestamp_utc: String,
    pub decision_id: String,
    pub asset: String,
    pub event_type: String, // e.g., "NEW_ORDER_SENT", "RISK_GUARD_BLOCK", "STOP_LOSS_TRIGGERED"
    #[serde(skip_serializing_if = "Option::is_none")]
    pub order_details: Option<OrderDetail>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<ReasonDetail>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub outcome: Option<OutcomeDetail>,
}

// --- Logger Implementation ---

const AUDIT_LOG_PATH: &str = "/home/bdieu178/user/defi-agents/polymarket/logs/audit/trades.log";

/// Resolves the audit log path dynamically using the HOME env var.
pub fn get_audit_log_path() -> PathBuf {
    if let Ok(home) = std::env::var("HOME") {
        let user_path = PathBuf::from(format!("{}/user/defi-agents/polymarket/logs/audit/trades.log", home));
        if user_path.parent().map(|p| p.exists()).unwrap_or(false) {
            return user_path;
        }
        let direct_path = PathBuf::from(format!("{}/defi-agents/polymarket/logs/audit/trades.log", home));
        if direct_path.parent().map(|p| p.exists()).unwrap_or(false) {
            return direct_path;
        }
    }
    PathBuf::from(AUDIT_LOG_PATH)
}

/// Initializes the audit log directory.
pub fn initialize_audit_log(path_override: Option<&Path>) -> io::Result<()> {
    let binding = get_audit_log_path();
    let log_path = path_override.unwrap_or_else(|| binding.as_path());
    if let Some(parent_dir) = log_path.parent() {
        std::fs::create_dir_all(parent_dir)?;
    }
    Ok(())
}

/// Logs a structured audit event to the dedicated trade log file.
///
/// # Arguments
///
/// * `event` - An `AuditEvent` struct containing all relevant information.
pub fn log_event(event: &AuditEvent, path_override: Option<&Path>) {
    let binding = get_audit_log_path();
    let log_path = path_override.unwrap_or_else(|| binding.as_path());
    match serde_json::to_string(event) {
        Ok(json_string) => {
            if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(log_path) {
                if let Err(e) = writeln!(file, "{}", json_string) {
                    eprintln!("[AUDIT_ERROR] Failed to write to trade log: {}", e);
                }
            } else {
                eprintln!("[AUDIT_ERROR] Failed to open trade log file: {:?}", log_path);
            }
        }
        Err(e) => {
            eprintln!("[AUDIT_ERROR] Failed to serialize audit event to JSON: {}", e);
        }
    }
}

// --- Helper functions to build events ---

pub fn new_order_event(
    asset: String,
    details: OrderDetail,
    reason: ReasonDetail,
    outcome: OutcomeDetail,
) -> AuditEvent {
    AuditEvent {
        timestamp_utc: Utc::now().to_rfc3339(),
        decision_id: Uuid::new_v4().to_string(),
        asset,
        event_type: "NEW_ORDER_SENT".to_string(),
        order_details: Some(details),
        reason: Some(reason),
        outcome: Some(outcome),
    }
}

pub fn new_risk_guard_event(asset: String, block_reason: String, reason: ReasonDetail) -> AuditEvent {
    AuditEvent {
        timestamp_utc: Utc::now().to_rfc3339(),
        decision_id: Uuid::new_v4().to_string(),
        asset,
        event_type: "RISK_GUARD_BLOCK".to_string(),
        order_details: None,
        reason: Some(reason),
        outcome: Some(OutcomeDetail {
            status: "BLOCKED".to_string(),
            error_message: Some(block_reason),
            fill_price: None,
            fill_quantity: None,
            fees: None,
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::io::Read;
    use std::collections::HashMap;

    // Helper to generate a unique test directory and log file path within it
    fn get_test_paths() -> (PathBuf, PathBuf) {
        let test_dir = PathBuf::from(format!("/tmp/test_audit_dir_{}", Uuid::new_v4().to_string()));
        let test_log_file = test_dir.join("trades.log");
        (test_dir, test_log_file)
    }

    #[test]
    fn test_log_event_writes_file() {
        let (test_dir, test_log_file_path) = get_test_paths();
        
        // Ensure clean slate
        let _ = fs::remove_dir_all(&test_dir);
        fs::create_dir_all(&test_dir).unwrap(); // Manually create directory for this test

        initialize_audit_log(Some(&test_log_file_path)).unwrap(); // Initialize with the test path

        let asset = "btc".to_string();
        let order_details = OrderDetail {
            token_id: "btcup".to_string(),
            order_type: "LIMIT".to_string(),
            side: "BUY".to_string(),
            quantity_tokens: 0.01,
            price: 0.5,
            exchange_order_id: Some("exchange-123".to_string()),
        };
        let mut other_signals = HashMap::new();
        other_signals.insert("signal_x".to_string(), 1.23);
        let reason_detail = ReasonDetail {
            p_theo: 0.6,
            p_market: 0.5,
            edge: 0.1,
            kelly_fraction: 0.05,
            other_signals,
        };
        let outcome_detail = OutcomeDetail {
            status: "SUCCESS".to_string(),
            error_message: None,
            fill_price: Some(0.501),
            fill_quantity: Some(0.01),
            fees: Some(0.0001),
        };

        let event = new_order_event(asset.clone(), order_details, reason_detail, outcome_detail);
        let expected_json = serde_json::to_string(&event).unwrap();

        log_event(&event, Some(&test_log_file_path));

        let mut file = fs::File::open(&test_log_file_path).unwrap();
        let mut contents = String::new();
        file.read_to_string(&mut contents).unwrap();

        assert_eq!(contents.trim(), expected_json.trim());

        // Cleanup
        fs::remove_file(&test_log_file_path).unwrap();
        fs::remove_dir_all(&test_dir).unwrap();
    }

    #[test]
    fn test_initialize_audit_log_creates_dir() {
        let (test_dir, test_log_file_path) = get_test_paths();

        // Ensure no leftover from previous runs
        let _ = fs::remove_dir_all(&test_dir);

        initialize_audit_log(Some(&test_log_file_path)).unwrap();
        assert!(test_dir.is_dir());

        // Cleanup
        fs::remove_dir_all(&test_dir).unwrap();
    }
}
