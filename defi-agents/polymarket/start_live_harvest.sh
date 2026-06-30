#!/bin/bash
# High-Fidelity HFT Harvesting Launcher (VPN Isolated)
# This script ensures the Hot-Path runs behind WireGuard in the 'polymask' namespace.

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
# Load environment variables robustly
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
else
    echo "Error: .env file not found at $SCRIPT_DIR/.env"
    exit 1
fi

# Create logs directory if it doesn't exist
mkdir -p logs

# Ensure VPN is up (Bypassed in Ireland)
echo "Running direct connection in Ireland (bypassing VPN namespace)..."

# Get asset from argument, default to BTC
ASSET=${1:-BTC}

echo "[$(date)] --- Starting HFT Pipeline in Background (Asset: $ASSET) ---"

# 1. Start the C++ Unified Ingestor (Hot Path Bridge)
# Backed by SpscRingBuffer lock-free queue
/bin/bash -c "set -a && source $SCRIPT_DIR/.env && set +a && nohup $SCRIPT_DIR/src/hft_tapreader/build/unified_ingestor $ASSET > $SCRIPT_DIR/logs/unified_ingestor.log 2>&1 &"
echo "[$(date)] [1/2] C++ Unified Ingestor ($ASSET) started directly - Logging to logs/unified_ingestor.log"

# 2. Start the High-Fidelity Harvester (Cold Path Recorder)
# Running in main namespace with sudo for SHM access
sudo nohup .venv/bin/python historical_bulk_harvester.py --asset "$ASSET" > logs/harvester.log 2>&1 &
echo "[$(date)] [2/2] Harvester started - Logging to logs/harvester.log"

sleep 2
if pgrep -f "unified_ingestor" > /dev/null && pgrep -f "historical_bulk_harvester.py" > /dev/null; then
    echo "[$(date)] --- All systems live. ---"
else
    echo "[$(date)] --- WARNING: One or more processes failed to start. Check logs/ ---"
fi
