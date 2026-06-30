# HFT Pipeline Status Updates & Notes - 2026-06-05

**Author:** Antigravity HFT Team  
**Status:** Performance Verification & Volatility Tuning Completed  
**Current Sizing Regime:** Volatility-Normalized Path Momentum with Timeframe Adaptation  
**Virtual Collateral Footprint:** $500.00 USD  

---

## 1. Accomplishments & System Modifications

Today, we optimized the Rust strategy and C++ ingestor modules to resolve asset scaling issues (BTC vs. ETH) and support multi-timeframe regime trading:

1. **Volatility-Normalized Path Momentum**:
   * **Problem**: An absolute change in BTC (e.g., $10) has a significantly different nominal value impact than the same change in ETH. Raw momentum scaling resulted in excessive trading on BTC and under-trading on ETH.
   * **Solution**: Normalised the raw momentum signal (`path_delta`) by dividing it by the rolling price volatility EMA (`fast_price_vol_ema`), transforming it into a standardized statistical Z-score:
     $$\text{normalized\_path\_delta} = \frac{\text{path\_delta}}{\text{fast\_price\_vol\_ema}}$$
     This is then scaled by `path_momentum_coeff` and clamped to $[-0.2, 0.2]$. This guarantees uniform momentum scaling across BTC and ETH scales.

2. **Timeframe-Adaptive EMA Decay ($\tau$)**:
   * Integrated dynamic smoothing constants based on the active timeframe (`5m`, `15m`, `1h`):
     * **5m**: $\tau = 0.05$ (50ms decay, highly sensitive to micro-fluctuations).
     * **15m**: $\tau = 0.25$ (250ms decay, balances speed and noise filtering).
     * **1h**: $\tau = 1.00$ (1000ms decay, smooth trend capture).

3. **Regime-Aware Spread & Edge Modifications**:
   * Upgraded the quoting engine to raise entry requirements during momentum/trend phases to avoid chasing noise:
     * **Trend/Momentum Regime (`regime_state_enum == 2`)**: Increases the required entry edge by `+0.015` USD and activates aggressive post-only bypass (taker mode) to lock in positions instantly.
     * **Mean-Reverting Regime (`regime_state_enum == 1`)**: Widens required spreads to `0.035` USD and raises entry edge requirement by `+0.005` USD.

4. **1-Hour Slug Discovery Integration**:
   * Updated `MarketDiscovery.cpp` and `main.rs` to generate and query target market slugs using the `"1h"` format (e.g., `btc-updown-1h-[timestamp]`). Verified that the Polymarket Gamma API maps this suffix properly.

5. **Legacy Compiler Signature Fixes**:
   * Corrected `Strategy::new` signature mismatches (E0061) across all legacy unit tests by passing the telemetry channel parameters (`None` or `order_tx`), fixing compile failures under incremental builds.

6. **Manual Executor vs. Supervisor Timeframe Mismatch Mitigation**:
   * **Problem**: If the C++ ingestor supervisor launches in 15m mode, but an operator manually starts the Rust executor in 60m mode, the executor will read mismatched pricing, OFI, and volatility metrics, resulting in adverse selection and incorrect execution.
   * **Solution**: Serialized the active ingestor `timeframe_minutes` in the `L2BookStruct` shared memory segment (C++ to Rust). Shrank the final structure padding from 40 bytes to 32 bytes to strictly preserve the 1152-byte layout constraint. Added an assertion check in the executor (`main.rs`) to immediately abort (exit code 1) on the first tick if the ingestor's timeframe in SHM deviates from the executor's configuration.

7. **Dynamic Time-Fade Scaling**:
   * **Problem**: The static time-fade settlement and freeze windows (60s and 300s) caused severe distortion when timeframes changed. In 15m markets, the bot spent 33% of its duration frozen from buying; in 5m markets, buy order entry was blocked entirely.
   * **Solution**: Refactored `strategy.rs` to compute the freeze, settle, fade window, and explosion parameters dynamically based on the active `timeframe_minutes` (e.g. 120s freeze and 30s settle for 15m contracts; 60s freeze and 15s settle for 5m contracts), optimizing uptime.

8. **On-Chain State Reconciler Upgrade**:
   * **Solution**: Redesigned `portfolio_sync.py` to crawl local `trades.log` audit databases, SQLite open orders, and block logs for recent token transfers within a 20,000 block window. It performs a Gamma API active-check to verify contract status before syncing active holdings.

9. **SQLite Cost-Basis Persistence**:
   * **Solution**: Added persistent SQLite state tracking to store and retrieve cost basis (`position_entry_prices`), allowing the hot-path strategy to recover average entry cost for open positions across restarts.

---

## 2. Verification of Today's Enhancements

* **Unit Testing**: Added `test_path_momentum_normalization` in `strategy.rs` which demonstrates that equivalent relative volatility moves on BTC and ETH produce the exact same normalized theoretical pricing signal.
* **Build Correctness**: Confirmed that all 20 tests compile and pass successfully using `cargo test`.
* **Shared Memory Binary Parity Verification**: Re-compiled the C++ Unified Ingestor (`make unified_ingestor -j`) and the Rust Executor (`cargo build`). Ran the automated structure verification tests on both C++ (GTest `StructTest.Alignment`) and Rust (Cargo `shm::tests::test_struct_sizes` and `shm::tests::test_l2_book_offsets`), confirming that `timeframe_minutes` is mapped at offset 1112 and both packages share exact binary compatibility with zero layout size differences.
* **Latency Verification**: Verified that position tracking and stop-loss logic reside in the lock-free shared memory hot-path, bypassing RPC/CLOB network round-trips for evaluations.

---

## 3. Position Return & Hot-Path Risk Management Analysis

We verified the strategy's current position and risk awareness in the execution hot-path:

* **Real-time VWAP Calculation**: In `process_fills`, the average cost (VWAP) is dynamically updated upon buy-side fills and stored directly in shared memory (`PositionInfoStruct`).
* **Hot-Path ROI Evaluation**: On every tick, the strategy loads position entry prices and compares them against market bids. If the position ROI falls below the configured threshold (e.g., $-15\%$), it triggers the stop-loss flag (`stop_loss_up` / `stop_loss_down`).
* **Aggressive Taker Liquidation**: When the stop-loss or take-profit triggers, the bot sets `is_exiting_up`/`is_exiting_down` and submits a spread-crossing taker limit sell order (priced at $90\%$ of the bid) to exit the position immediately.
* **Daily Drawdown Guard**: If the realized net PnL drops below the daily drawdown limit, `daily_stop_loss_triggered` is written as `1`, causing the strategy to immediately abort subsequent ticks.

---

## 4. Option Probability Sizing & Reconciler Latency Fixes (Loser Hold Resolution)

To resolve the system's incorrect capital allocation ("loser hold" bug) and latency issues, we implemented and deployed the following hotfixes:

1. **Option Sizing & Probability Model Calibration**:
   * **Problem**: The standard deviation scaling factor was hardcoded to `0.005` (70x too small), representing a flat and incorrect distribution. This kept the baseline probability for out-of-the-money (OTM) losing contracts near `10%` instead of letting it decay to `0%` as the price moved further away from the strike. In addition, high-frequency microsecond flow signals (OFI, order flow) were added to the baseline directly, causing noise to dominate and trigger buy trades on contracts that had zero mathematical chance of winning.
   * **Solution & Impact**: Corrected the standard deviation scaling factor to `0.34` (standard Black-Scholes boundaries) in `calculate_base_p_theo`. We also added a `signal_fader` that decays short-term microsecond signals as time-to-expiry (`t_rem`) increases. This ensures that the model correctly evaluates far OTM contracts as having ~0% probability and stops purchasing losing positions.

2. **Reconciler Latency & Quicknode RPC Optimization**:
   * **Problem**: The state reconciler took over 4 minutes to run and triggered Quicknode `413 Request Entity Too Large` HTTP payload errors during full-scan RPC events on reboot.
   * **Solution & Impact**: Optimized `portfolio_sync.py` to query transaction logs in 2,000-block chunks to prevent payload overflows. We also filtered the log parsing to the last 48 hours and intersected candidate token IDs with deterministically generated active slugs for the current and adjacent trading intervals. This reduced the state reconciler's run time from 4 minutes to under 15 seconds, preventing pipeline startup timeouts.

3. **Cargo PATH Privilege Resolution**:
   * **Problem**: Executing compilation checks under privileged/sudo contexts in `bootstrap_production.sh` dropped user path configs, triggering `cargo command not found` errors.
   * **Solution & Impact**: Prepended `/home/$BUILD_USER/user/.cargo/bin` to the `PATH` during compilation blocks, ensuring a clean and automated compilation.

