#!/bin/bash
set -e

echo "--- 0. Cleaning up stale data ---"
rm -rf nautilus_catalog

echo "--- 1. Initializing Instrument Catalog ---"
uv run python create_instruments.py

echo "--- 2. Generating Synthetic High-Fidelity Data ---"
uv run python create_synthetic_data.py

echo "--- 3. Ingesting Data into Nautilus Catalog ---"
uv run python catalog_ingestion.py

echo "--- 4. Running HFT Backtest Simulation ---"
uv run python run_backtest.py

echo "--- 5. Setup Complete ---"
echo "Observability Dashboard available at http://localhost:33333"
