use std::collections::VecDeque;
use rusqlite::{Connection, params};
use std::time::{SystemTime, UNIX_EPOCH};

pub struct TkgModel {
    pub ofi_window_size: usize,
    pub ofi_history: VecDeque<f64>,
    pub rolling_ofi_sums: VecDeque<f64>,
    pub max_sums_history: usize,
    pub current_regime: u32,
    pub current_multiplier: f64,
    pub last_transition_ts: u64,
}

impl TkgModel {
    pub fn new(ofi_window_size: usize, max_sums_history: usize) -> Self {
        Self {
            ofi_window_size,
            ofi_history: VecDeque::with_capacity(ofi_window_size),
            rolling_ofi_sums: VecDeque::with_capacity(max_sums_history),
            max_sums_history,
            current_regime: 0,
            current_multiplier: 1.0,
            last_transition_ts: 0,
        }
    }

    pub fn update(&mut self, current_ofi: f64, fast_vol: f64, vol_threshold: f64, db_tx: &Option<flume::Sender<TransitionLogEvent>>) -> Option<(u32, f64)> {
        // 1. Maintain ofi_history
        if self.ofi_history.len() >= self.ofi_window_size {
            self.ofi_history.pop_front();
        }
        self.ofi_history.push_back(current_ofi);

        // 2. Sum the rolling window
        let ofi_sum: f64 = self.ofi_history.iter().sum();

        // 3. Maintain rolling_ofi_sums
        if self.rolling_ofi_sums.len() >= self.max_sums_history {
            self.rolling_ofi_sums.pop_front();
        }
        self.rolling_ofi_sums.push_back(ofi_sum);

        // 4. Calculate mean and std dev of rolling sums
        let count = self.rolling_ofi_sums.len() as f64;
        if count < 10.0 {
            // Not enough history, default to range-bound
            return None;
        }

        let mean: f64 = self.rolling_ofi_sums.iter().sum::<f64>() / count;
        let variance: f64 = self.rolling_ofi_sums.iter().map(|&x| {
            let diff = x - mean;
            diff * diff
        }).sum::<f64>() / count;
        let std_dev = variance.sqrt().max(0.0001);

        // 5. Calculate Z-score
        let z_score = (ofi_sum - mean) / std_dev;

        // 6. Classify regime:
        // - Regime 2 (Momentum): Z-score of OFI sum > 3.0 std dev
        // - Regime 1 (Mean Reversion): Volatility > threshold
        // - Regime 0 (Range-Bound): Else
        let (new_regime, new_multiplier) = if z_score.abs() > 3.0 {
            (2, 2.0)
        } else if fast_vol > vol_threshold {
            (1, 1.0)
        } else {
            (0, 1.0)
        };

        let now_ms = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis() as u64;

        if new_regime != self.current_regime {
            // Apply hysteresis: require at least 5 seconds dwell time
            if self.last_transition_ts > 0 && now_ms.saturating_sub(self.last_transition_ts) < 5000 {
                return None;
            }

            let prev_regime = self.current_regime;
            self.current_regime = new_regime;
            self.current_multiplier = new_multiplier;
            self.last_transition_ts = now_ms;

            // Send event to database log queue
            if let Some(tx) = db_tx {
                let _ = tx.send(TransitionLogEvent {
                    timestamp_ms: now_ms,
                    from_regime: prev_regime,
                    to_regime: new_regime,
                    ofi_sum,
                    z_score,
                    price_volatility: fast_vol,
                });
            }

            Some((new_regime, new_multiplier))
        } else {
            None
        }
    }
}

pub struct TransitionLogEvent {
    pub timestamp_ms: u64,
    pub from_regime: u32,
    pub to_regime: u32,
    pub ofi_sum: f64,
    pub z_score: f64,
    pub price_volatility: f64,
}

pub fn log_transition_to_db(conn: &Connection, event: &TransitionLogEvent) -> rusqlite::Result<()> {
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tkg_transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_ms INTEGER NOT NULL,
            from_regime INTEGER NOT NULL,
            to_regime INTEGER NOT NULL,
            ofi_sum REAL NOT NULL,
            z_score REAL NOT NULL,
            price_volatility REAL NOT NULL
        )",
        [],
    )?;

    conn.execute(
        "INSERT INTO tkg_transitions (timestamp_ms, from_regime, to_regime, ofi_sum, z_score, price_volatility)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        params![
            event.timestamp_ms,
            event.from_regime,
            event.to_regime,
            event.ofi_sum,
            event.z_score,
            event.price_volatility,
        ],
    )?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tkg_transitions() {
        let mut model = TkgModel::new(10, 20);
        let mut trigger_count = 0;
        
        // Push 15 identical/flat OFI values to build up base
        for _ in 0..15 {
            model.update(10.0, 0.05, 0.10, &None);
        }

        // Push a major anomaly to trigger Regime 2 (Momentum)
        for _ in 0..5 {
            if model.update(500.0, 0.05, 0.10, &None).is_some() {
                trigger_count += 1;
            }
        }
        
        assert!(trigger_count > 0, "Regime change should have been detected");
        assert_eq!(model.current_regime, 2, "Regime should be 2 (Momentum)");
    }
}
