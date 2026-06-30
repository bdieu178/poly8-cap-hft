# HFT Data Fidelity Guide

This guide assists researchers and automated agents in selecting high-fidelity datasets from this directory for backtesting and microstructure analysis.

## 1. Fidelity Classification

### High-Fidelity (HF)
*   **Definition:** Concurrent presence of both `hyperliquid` and `polymarket` sources in a single Parquet file.
*   **Use Case:** Suitable for lead-lag analysis, cross-venue arbitrage backtesting, and Hawkes process parameter estimation.
*   **Stabilization Point:** Continuous, high-fidelity data collection stabilized on **2026-05-06 16:52:44 UTC**. All data after this timestamp is considered production-grade.

### Low-Fidelity (LF)
*   **Definition:** Missing `polymarket` L2 snapshots or `hyperliquid` L4 signals.
*   **Use Case:** Suitable for single-venue signal research (Hyperliquid only) but **not** for full strategy backtesting.
*   **Location:** Mostly found in `realtime/` files prior to the stabilization point.

## 2. High-Fidelity Windows (Audited)

As of 2026-05-06 20:30 UTC, the following windows are confirmed High-Fidelity:

| Start (UTC) | End (UTC) | Duration | Notes |
| :--- | :--- | :--- | :--- |
| 2026-05-05 01:04 | 2026-05-05 01:32 | 0.47h | Early test segment. |
| 2026-05-06 10:14 | 2026-05-06 10:47 | 0.54h | Post-optimization test. |
| **2026-05-06 16:52** | **Ongoing** | **--** | **Production Stable Window.** |

*Total HF Duration Audited:* **7.86h**

## 3. Directory Mapping

- `realtime/`: Contains all raw recordings. Use the `source` column in Parquet files to filter for HF data.
- `archive_missing_poly/`: Contains historical recordings where Polymarket data was confirmed missing during early development phases.
- `historical/`: Reserved for backfilled data (blockchain logs).

## 4. How to Filter for High-Fidelity Data (Python)

```python
import polars as pl
import glob

def is_high_fidelity(file_path):
    sources = pl.scan_parquet(file_path).select("source").unique().collect()["source"].to_list()
    return "hyperliquid" in sources and "polymarket" in sources

# Example: Get all HF files
hf_files = [f for f in glob.glob("realtime/*.parquet") if is_high_fidelity(f)]
```

## 5. Resolution Path
Data gaps in the `realtime/` directory (specifically between 2026-05-05 02:32 and 2026-05-06 16:52) are scheduled for backfilling via `historical_ingestion.py` using blockchain logs.
