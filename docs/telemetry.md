# Polymarket & Hyperliquid HFT Telemetry Requirements

This document defines the comprehensive telemetry, logging, and observability requirements for the Polymarket & Hyperliquid High-Frequency Trading Arbitrage pipeline. These requirements span the Live Execution Hot-Path, the PyTorch Cold-Path Training loop, and the Backtesting/Diagnostics pipeline, as mandated by the v2.0 Dual-Head GRU Inference integration.

## 1. Live Capital Trading (Hot Path)

The Rust executor and C++ ingestor operate within sub-microsecond constraints. Telemetry must be completely non-blocking (e.g., asynchronous ring-buffer logging or memory-mapped metrics).

### 1.1 Latency & Health Diagnostics
- **`hot_path_latency_ns`**: Measure end-to-end latency from network packet arrival at the C++ gRPC/WS interface to Rust execution decision. Budget: < 50μs.
- **Inference Latency**: Log the exact execution time of the 2.56M MACs GRU forward pass. Budget: < 10μs.
- **SPSC Buffer Backpressure (`dropped_count`)**: Track instances where the lock-free `SpscRingBuffer` fills up and drops packets, indicating a network spike or executor stall.
- **Staleness Tracking (`stale_flag`)**: Log when ingestion latency > 500ms. If data stales beyond 8 seconds, log the `STALENESS_HALT` trigger and the corresponding decay multiplier applied to `gru_hidden`.

### 1.2 Model & Pricing State Telemetry
- **Model Inputs**: Log the 15-feature input vector on critical state changes.
- **GRU Outputs**: Continuously record:
  - `signed_alpha`: The directional pricing offset output.
  - `nu_probs`: The 3-class Softmax probability distribution (Herding, Contrarian, Neutral).
- **Options Pricing & Friction Metrics**:
  - `variance_scaler`: The $p(1-p)$ liquidity anchor value replacing Black-Scholes decay.
  - `phase_lag`: Instantaneous spread between Hyperliquid-implied probability and Polymarket mid-price via the `PhaseLagTracker`.
  - `nu_regime`: The rolling estimate (-1.0, 0.0, +1.0) derived from cross-correlation.
  - **Friction Penalties**: Log any application of the `longshot_penalty` (when $p_{theo}$ is at extremes) or the `geometric_depth_discount`.

### 1.3 A/B Shadow Mode Validation
Before trading live, the system must log shadow mode validation metrics to `logs/{asset}/gru_shadow.log`:
- Legacy single-neuron `signed_alpha` vs. GRU `signed_alpha`.
- `nu_regime` classification and `phase_lag` values.

## 2. Model Training & Cold Path

The Python retraining pipeline (`train_gru.py`) runs every 6 hours and requires rigorous telemetry to prevent model degradation and spurious correlations.

### 2.1 Ingestion & Parquet Harvester
- **Feature Completeness**: Ensure `historical_bulk_harvester.py` accurately records all 15 features to `data/realtime/{asset}/hft_recording_*.parquet`.
- **Data Volume**: Log sequence counts, targeting ~2.4M sequences for a 2-week rolling window.

### 2.2 Validation Gates & Metric Logs
The training orchestrator must report the following metrics to `stdout` / `/var/log/gru_training.log` and refuse weight export if gates fail:
- **AUC-ROC**: Validation AUC-ROC (≥ 0.55) and Held-Out Test AUC (≥ 0.53).
- **Brier Score**: Must be ≤ 0.24 to confirm probability calibration.
- **Structural Break Recall**: Regime 4 & 5 (high volatility) recall must be ≥ 0.60.
- **ν-Regime Accuracy**: Auxiliary head accuracy must be ≥ 0.45.
- **Longshot False Positive Rate**: FP rate at extremes (<0.10 or >0.90) must be ≤ 15%.

### 2.3 Binary Weight Export Security
- **SHA-256 Checksums**: Every serialized binary `.bin` must log its SHA-256 hash payload. The Rust executor must verify this hash upon `SIGHUP` reload to ensure binary integrity.

## 3. Backtesting & Fallacy Diagnostics

Backtesting systems and nightly CI runners must enforce and log metrics ensuring the system hasn't learned known structural fallacies.

### 3.1 Ground Truth Label Collection
- **On-chain Logging**: Ensure the pipeline parsing Polygon RPC `OrderFilled` events correctly logs the `makerAssetId`/`takerAssetId` to establish aggressive direction labels. The WebSocket `change_side` field has a 59% failure rate and must NOT be used as ground truth.

### 3.2 Nightly Fallacy Regression Suite
The `test_no_fallacy_leakage` CI test suite must log and assert:
- **No `t_rem` Leakage (Fallacy 1)**: Assert time-to-resolution is not in feature columns.
- **No Block Clock Leakage (Fallacy 2)**: Assert Polygon block synchronization features are not used.
- **Monotonic Depth Cost (Fallacy 3)**: Verify the model predicts higher slippage costs for deep sweeps vs shallow sweeps.
- **Directional Quarantine (Fallacy 4)**: Assert that randomizing Polymarket-local features does not flip the sign of `signed_alpha` in >85% of cases.

## 4. Telemetry Infrastructure & Storage Layers

To cleanly separate concerns between low-latency execution, high-throughput analytics, and distributed coordination, telemetry data is routed to three distinct state storage layers:

### 4.1 Transactional SQLite Service (Trade Execution State)
Used by the Rust Hot-Path for durable, low-latency tracking of individual trades, account exposure, and PnL. It acts as the local system of record for capital allocation.
**Key Fields & Tables**:
- `Trades_Log`:
  - `execution_id` (UUID)
  - `market_id` (String - Polymarket condition ID)
  - `timestamp_ms` (UInt64)
  - `direction` (String - UP/DOWN)
  - `size_usd` (Float64)
  - `p_theo_at_execution` (Float64)
  - `actual_execution_p` (Float64)
  - `slippage_bps` (Int32)
  - `gas_cost_usd` (Float64)
  - `tx_hash` (String - Polygon transaction hash)
  - `status` (Enum - PENDING, FILLED, REJECTED)
- `Risk_Limits`:
  - `daily_drawdown_usd` (Float64)
  - `current_exposure_usd` (Float64)

### 4.2 Analytical DuckDB Service (Vectorized Backtesting)
Used for high-throughput vectorized querying of Parquet files. This service powers the PyTorch training pipeline, A/B shadow mode evaluations, and fallacy regression suites.
**Key Fields & Columns**:
- `GRUTickData` (Backed by Parquet):
  - `timestamp_ms` (UInt64 - Primary Index)
  - `market_id` (String - Indexed for partitioning)
  - `hl_mid`, `pm_spread`, `ofi_signal`, `signed_flow`, `variance_scaler`, `phase_lag` (All Float64 input features)
  - `stale_flag`, `whale_imbalance` (Float64)
  - `actual_outcome` (UInt8 - Label 1 or 0)
  - `nu_label` (Int8 - Target Regime -1, 0, 1)
  - `predicted_signed_alpha` (Float64 - logged from shadow mode)

### 4.3 Cold-Path Message Layer (Redis)
Used as a pub/sub event bus and ephemeral state cache to coordinate the distributed components (C++ ingestor, Rust executor, Python trainers, Web3 RPC pollers).
**Key Fields & Topics**:
- **Keys / Hash Maps**:
  - `system:state:latest_gru_hash`: String (SHA-256 of the active weights file).
  - `market:{asset}:metrics`: Hash containing instantaneous `signed_alpha`, `phase_lag`, `nu_probs_0/1/2`.
  - `pipeline:training_status`: String (e.g., `INGESTING`, `TRAINING`, `EXPORT_READY`).
- **Pub/Sub Channels**:
  - `events:staleness`: Emits payloads when `STALENESS_HALT` triggers (Payload: `{"timestamp": 123456, "latency_ms": 8200, "action": "HALT"}`).
  - `events:weight_reload`: Triggered by the cold path upon new binary export to notify the Rust process to swap pointers.
