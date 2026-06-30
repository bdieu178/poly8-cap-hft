# Redundant Data Archive - May 5, 2026

## Overview
This directory contains HFT Parquet files that were identified as redundant recordings. 

## Reason for Archival
An audit on May 5, 2026, revealed that three concurrent harvester processes were running simultaneously between May 4, 22:31 UTC and May 5, 18:00 UTC. This resulted in triple-redundant data for each minute of recording.

## Usage Warning
**DO NOT USE THIS DATA FOR BACKTESTING.**
Including these files in a backtest dataset will:
1.  **Inflate Duration Metrics:** Artificially double or triple the apparent duration of the dataset.
2.  **Bias Statistical Analysis:** Introduce repetitive samples that skew OFI, flow rate, and other microstructure signals.
3.  **Cause Duplicate Events:** Nautilus and other backtest engines may process the same market events multiple times if these files are ingested together.

The primary, deduplicated dataset remains in the parent `data/realtime/` directory.
