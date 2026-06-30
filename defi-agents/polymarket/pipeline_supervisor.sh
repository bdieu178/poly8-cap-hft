#!/bin/bash
# Pipeline Supervisor: Ensures TapReader and Harvester stay alive for the 72h window.

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

LOG_FILE="logs/supervisor.log"
mkdir -p logs

echo "[$(date)] Supervisor started." >> "$LOG_FILE"

while true; do
    # Check C++ Unified Ingestor
    if ! pgrep -f "unified_ingestor" > /dev/null; then
        echo "[$(date)] Unified Ingestor down. Restarting..." >> "$LOG_FILE"
        ./start_live_harvest.sh >> "$LOG_FILE" 2>&1
    fi

    # Check Harvester
    if ! pgrep -f "historical_bulk_harvester.py" > /dev/null; then
        echo "[$(date)] Harvester down. Restarting..." >> "$LOG_FILE"
        ./start_live_harvest.sh >> "$LOG_FILE" 2>&1
    fi

    sleep 60
done
