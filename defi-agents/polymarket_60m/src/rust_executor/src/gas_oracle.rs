use alloy::providers::Provider;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use tokio::time::sleep;

pub struct GasOracle<P> {
    provider: Arc<P>,
    base_fee: Arc<AtomicU64>,
    priority_fee: Arc<AtomicU64>,
}

impl<P: Provider + 'static + Send + Sync> GasOracle<P> {
    pub fn new(provider: Arc<P>) -> Self {
        Self {
            provider,
            base_fee: Arc::new(AtomicU64::new(0)),
            priority_fee: Arc::new(AtomicU64::new(0)),
        }
    }

    pub fn start(&self) {
        let provider = Arc::clone(&self.provider);
        let base_fee = Arc::clone(&self.base_fee);
        let priority_fee = Arc::clone(&self.priority_fee);

        tokio::spawn(async move {
            loop {
                // alloy get_fee_history signature: get_fee_history(block_count, newest_block, reward_percentiles)
                if let Ok(fee_history) = provider.get_fee_history(1, alloy::rpc::types::BlockNumberOrTag::Latest, &[25.0, 50.0, 75.0]).await {
                    if let Some(last_base) = fee_history.base_fee_per_gas.last() {
                        base_fee.store(*last_base as u64, Ordering::SeqCst);
                    }
                    if let Some(rewards) = fee_history.reward.as_ref().and_then(|r| r.last()) {
                        // Use the 50th percentile as our benchmark
                        priority_fee.store(rewards[1] as u64, Ordering::SeqCst);
                    }
                }
                sleep(Duration::from_secs(2)).await; // Sync with block times
            }
        });
    }

    pub fn get_current_fees(&self) -> (u64, u64) {
        (
            self.base_fee.load(Ordering::SeqCst),
            self.priority_fee.load(Ordering::SeqCst),
        )
    }
}
