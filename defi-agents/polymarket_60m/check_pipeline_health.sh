#!/bin/bash
# Pipeline Health Check: Functional Throughput Verification
# Checks if Hyperliquid and Polymarket data is actually advancing in SHM.

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$SCRIPT_DIR" # Define PROJECT_ROOT locally
PYTHON_ENV="$PROJECT_ROOT/.venv/bin/python"
SHM_HEALTH_CHECK_SCRIPT="$PROJECT_ROOT/utils/shm_health_check.py"
ASSET_NAME=$1
THRESHOLD_SECONDS=${2:-10} # Default to 10 seconds freshness

export PYTHONPATH=$PROJECT_ROOT # Export PYTHONPATH within this script's context

echo "--- Pipeline Health Check [$ASSET_NAME] ---"

# 1. Run SHM Freshness Check
$PYTHON_ENV $SHM_HEALTH_CHECK_SCRIPT $ASSET_NAME $THRESHOLD_SECONDS
SHM_STATUS=$?

if [ $SHM_STATUS -eq 0 ]; then
    echo "STATUS: Pipeline [$ASSET_NAME] is HEALTHY."
    exit 0
else
    echo "STATUS: Pipeline [$ASSET_NAME] is STALLED or SHM not found. Action required."
    exit 1
fi
