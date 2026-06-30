use serde::{Deserialize, Serialize};
use std::fs;
use std::io;
use std::path::Path; // Added this import

#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(default)]
pub struct RiskParams {
    pub global_max_exposure_usd: f64,
    pub portfolio_max_gross_exposure_usd: f64,
    pub daily_drawdown_limit_usd: f64,
    pub stale_data_threshold_ms: u64,
    pub pending_collateral_timeout_ms: u64,
    pub stop_loss_roi_threshold: f64, // e.g., 0.15 for 15% loss
    pub error_cooldown_ms: u64, // 1000 for 1 second cooldown
    pub max_notional_usd: f64, // e.g., 100.0 for $100 max per order
    pub max_size_deviation_multiplier: f64, // e.g., 5.0 for 5x moving average
    pub max_collateral_per_trade_frac: f64, // e.g., 0.5 for 50% of available
    pub slow_vol_ema_alpha: f64,
    pub vol_modifier_min: f64,
    pub vol_modifier_max: f64,
}

impl Default for RiskParams {
    fn default() -> Self {
        RiskParams {
            global_max_exposure_usd: 2500.0,
            portfolio_max_gross_exposure_usd: 5000.0,
            daily_drawdown_limit_usd: -2000.0,
            stale_data_threshold_ms: 500,
            pending_collateral_timeout_ms: 30000,
            stop_loss_roi_threshold: 0.15,
            error_cooldown_ms: 500,
            max_notional_usd: 1000.0,
            max_size_deviation_multiplier: 10.0,
            max_collateral_per_trade_frac: 0.50,
            slow_vol_ema_alpha: 0.001,
            vol_modifier_min: 0.5,
            vol_modifier_max: 1.5,
        }
    }
}

#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(default)]
pub struct StrategyParams {
    pub kelly_sizing_multiplier: f64,
    pub min_order_size_usd: f64,
    pub min_edge_usd: f64,
    pub gamma_fade_window_secs: u64,
    pub gamma_explosion_zone_secs: u64,
    pub bid_ask_concentration_threshold: f64,
    pub high_order_count_threshold: u32,
    pub ofi_normalization_factor: f64,
    pub flow_normalization_factor: f64,
    pub hawkes_beta: f64,
    pub flow_ewma_alpha: f64,
    pub min_signal_ticks: u32,
    pub order_cooldown_ms: u64,
    pub quote_reprice_threshold: f64,
    pub market_making: bool,
    pub risk_aversion_gamma: f64,
    pub spread_expansion_kappa: f64,
    pub path_momentum_coeff: f64,
    pub timeframe_minutes: u64,
    pub taker_slippage_allowance: f64,
    pub time_fade_freeze_secs: u64,
    pub time_fade_settle_secs: u64,
    pub tkg_volatility_threshold: f64,
    pub take_profit_roi_threshold: f64,
    pub take_profit_edge_decay_threshold: f64,
}

impl Default for StrategyParams {
    fn default() -> Self {
        StrategyParams {
            kelly_sizing_multiplier: 1.0,
            min_order_size_usd: 1.0, 
            min_edge_usd: 0.019,
            gamma_fade_window_secs: 60,
            gamma_explosion_zone_secs: 6,
            bid_ask_concentration_threshold: 0.7,
            high_order_count_threshold: 100,
            ofi_normalization_factor: 4000.0,
            flow_normalization_factor: 2500.0,
            hawkes_beta: 1.5,
            flow_ewma_alpha: 0.1,
            min_signal_ticks: 5,
            order_cooldown_ms: 3000,
            quote_reprice_threshold: 0.03,
            market_making: true,
            risk_aversion_gamma: 0.002,
            spread_expansion_kappa: 0.01,
            path_momentum_coeff: 0.10,
            timeframe_minutes: 15,
            taker_slippage_allowance: 0.02,
            time_fade_freeze_secs: 300,
            time_fade_settle_secs: 60,
            tkg_volatility_threshold: 0.10,
            take_profit_roi_threshold: 0.10,
            take_profit_edge_decay_threshold: 0.02,
        }
    }
}

#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(default)]
pub struct Config {
    pub risk_params: RiskParams,
    pub strategy_params: StrategyParams,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            risk_params: RiskParams::default(),
            strategy_params: StrategyParams::default(),
        }
    }
}

impl Config {
    pub fn load(path: &Path) -> io::Result<Self> {
        let contents = fs::read_to_string(path)?;
        toml::from_str(&contents).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e.to_string()))
    }

    pub fn save(&self, path: &Path) -> io::Result<()> {
        let toml_string = toml::to_string_pretty(self)
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e.to_string()))?;
        fs::write(path, toml_string)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use uuid::Uuid;

    fn get_temp_config_path() -> PathBuf {
        PathBuf::from(format!("/tmp/test_config_{}.toml", Uuid::new_v4()))
    }

    #[test]
    fn test_default_config_creation_and_save() {
        let config = Config::default();
        let path = get_temp_config_path();
        config.save(&path).unwrap();

        assert!(path.exists());
        let loaded_config = Config::load(&path).unwrap();
        assert_eq!(config.risk_params.daily_drawdown_limit_usd, loaded_config.risk_params.daily_drawdown_limit_usd);
        
        fs::remove_file(&path).unwrap();
    }

    #[test]
    fn test_config_load() {
        let path = get_temp_config_path();
        let original_config = Config::default();
        original_config.save(&path).unwrap();

        let loaded_config = Config::load(&path).unwrap();

        assert_eq!(original_config.risk_params.global_max_exposure_usd, loaded_config.risk_params.global_max_exposure_usd);
        assert_eq!(original_config.strategy_params.min_order_size_usd, loaded_config.strategy_params.min_order_size_usd);
        assert_eq!(original_config.risk_params.stale_data_threshold_ms, loaded_config.risk_params.stale_data_threshold_ms);

        fs::remove_file(&path).unwrap();
    }

    #[test]
    fn test_config_missing_file() {
        let path = get_temp_config_path();
        let error = Config::load(&path).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::NotFound);
    }
}
