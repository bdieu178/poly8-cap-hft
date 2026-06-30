# 2026-05-10 Status Updates & Notes (Part F)

## Strategy Sensitivity Calibration (v2.7.8)

Performed a targeted calibration of the execution engine to align with the current $80,000 BTC market regime and the observed 9ms hot-path latency.

### 1. Sensitivity Adjustments
| Variable | Old Value | New Value | Rationale |
| :--- | :--- | :--- | :--- |
| **Noise Threshold** | 20 Orders | **100 Orders** | Prevents suppression of institutional flow in high-liquidity L4 queues. |
| **Buy Alpha Edge** | 0.05 (5%) | **0.03 (3%)** | Captures frequent alpha windows that were previously missed due to 9ms lag. |
| **Flow Denominator**| 5000.0 | **2500.0** | Increases sensitivity to dollar-value momentum at higher BTC prices. |

### 2. Performance Verification
- **BTC Latency**: Identified at **9.27ms**. The reduced edge requirement (3%) ensures we still trigger on large Hawkes singularities that persist beyond this latency window.
- **ETH Latency**: Remained optimal at **0.66ms**.
- **Process Status**: All pipelines shut down safely before the calibration commit.

### 3. Deployment Status
Branch `feature/hft-infra-upgrade-calibrate` is now the active baseline. The system has been re-bootstrapped and is running with the v2.7.8 strategy.

---
**Next Step**: Monitor `executor.log` for +EV triggers under the relaxed 3% edge requirement.
