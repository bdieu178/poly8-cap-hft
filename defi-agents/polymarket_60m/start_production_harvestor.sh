#!/bin/bash

# Kill any existing processes that might be holding the SHM segment
pkill -f 'tapreader|data_harvester|unified_ingestor'
sleep 2

# Kill the Rust executor
pkill -f RustStrategy
sleep 1

# Clear out old shared memory segments (requires root)
sudo rm -f /dev/shm/polymarket_tap_status.*

# Navigate to the directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

# Start the services
sudo ./start_live_harvest.sh

# Give it a moment to initialize and tail the logs
sleep 5
tail -n 20 logs/unified_ingestor.log