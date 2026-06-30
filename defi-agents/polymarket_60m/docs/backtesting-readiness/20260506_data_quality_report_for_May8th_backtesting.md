# Data Quality Report for May 8th Backtesting - 2026-05-06

## Executive Summary
A comprehensive audit of the `realtime` data directory reveals a critical discrepancy between wall-clock collection time and effective high-fidelity duration. While the pipeline has been active for **43.07 hours**, only **7.86 hours** contain synchronized dual-venue data (Hyperliquid L4 + Polymarket L2). The remaining 35.21 hours suffer from Polymarket venue silence due to the previously identified process anomalies and gRPC congestion.

## 1. High-Fidelity Coverage Audit
- **Wall-Clock Duration:** 43.07h (Start: 2026-05-05 00:56 | End: 2026-05-06 20:28)
- **High-Fidelity Duration:** **7.86h (10.9% of 72h goal)**
- **Stabilization Start:** **2026-05-06 16:52:44 UTC** (Continuous stable collection resumed).
- **Fidelity Definition:** Concurrent presence of both `hyperliquid` and `polymarket` sources in a single Parquet segment.

## 2. Major Low-Fidelity Windows (Missing Polymarket)
The following windows contain Hyperliquid signals but lack the Polymarket L2 snapshots required for backtesting the lead-lag relationship:

| Window Start (UTC) | Window End (UTC) | Duration | Impact |
| :--- | :--- | :--- | :--- |
| 2026-05-05 02:32 | 2026-05-05 16:26 | 13.89h | Critical gap in May 5th London/NY sessions. |
| 2026-05-06 00:18 | 2026-05-06 05:57 | 5.65h | Loss of early morning May 6th Asian session. |
| 2026-05-06 06:18 | 2026-05-06 10:13 | 3.92h | Loss of May 6th London open. |
| 2026-05-06 14:33 | 2026-05-06 16:49 | 2.27h | Loss of May 6th NY open. |

## 3. Root Cause Analysis
1.  **Orphaned Process Contention:** Redundant `live_tapreader.py` instances (up to 6 concurrent workers detected) caused lock contention in Shared Memory, specifically blocking the Polymarket WebSocket bridge.
2.  **gRPC/asyncio Saturation:** Per-message L2 aggregation and verbose logging in `live_tapreader.py` saturated the event loop, triggering "slow client" disconnects from Hyperliquid gRPC and starving the Polymarket WebSocket consumer.
3.  **Supervisor Loops:** Redundant `pipeline_supervisor.sh` instances were aggressively restarting already-stalled processes, exacerbating resource exhaustion.

## 4. Resolution Path & Recovery Strategy

### Immediate Technical Mitigations (Status: COMPLETED)
- **Deployment of `hft-infrastructure-guard`:** Automated hourly checks now purge redundant processes and verify SHM health.
- **Closed-Loop Self-Healing:** The system now confirms recovery within 30s of a restart.
- **Log Enrichment:** Standardized timestamps now allow for millisecond-precision drift analysis.

### Data Recovery Strategy (Status: REQUIRED)
- **Polymarket Backfill:** Use `historical_ingestion.py` to scrape blockchain-level `OrderFilled` and `PriceChange` logs for the 35.21h missing window.
- **Signal Synthetic Reconstruction:** Use Hyperliquid OFI/Flow signals from the existing low-fidelity data combined with backfilled trade logs to approximate the book state for backtesting.

### Next Steps to Reach May 8th Deadline
1.  **Throttling Implementation:** Update `live_tapreader.py` to aggregate L2 and log metrics at 100ms intervals (Eliminate loop saturation).
2.  **Backfill Execution:** Run bulk ingestion for missing Polymarket timestamps.
3.  **Converter Finalization:** Map dual-venue schema to Nautilus fields via `nautilus_data_converter.py`.

## Recommendation
**DELAY BACKTEST VALIDATION** until at least 24h of continuous high-fidelity data is accumulated (Expected by May 7th 20:00 UTC). The current 7.86h sample is insufficient to validate the Hawkes process parameters across multiple regimes.
