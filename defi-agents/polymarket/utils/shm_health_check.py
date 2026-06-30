import ctypes
import os
import time
import sys
from utils.shm_utils import POSIXSharedMemory, read_shm_snapshot, read_spsc_ring_buffer_snapshot
from utils.shm_types import L2BookStruct, SpscRingBufferStruct

def check_shm_freshness(asset_name, threshold_seconds=10, check_type="all"):
    shm_name = f"/hl_l2_book_{asset_name}"

    try:
        shm = POSIXSharedMemory(shm_name, size=ctypes.sizeof(SpscRingBufferStruct))
        snapshot = read_spsc_ring_buffer_snapshot(shm.buf)
        shm.close()

        now_ms = int(time.time() * 1000)

        # Normalize hl_timestamp (Hyperliquid) - assume microseconds from C++ TapReader
        hl_ts_ms = (snapshot.hl_timestamp // 1_000) * 1000 if snapshot.hl_timestamp > 0 else 0 

        # Polymarket timestamps (poly_up_timestamp, poly_down_timestamp) - assume milliseconds from Python live_tapreader.py
        poly_up_ts_ms = snapshot.poly_up_timestamp if snapshot.poly_up_timestamp > 0 else 0
        poly_down_ts_ms = snapshot.poly_down_timestamp if snapshot.poly_down_timestamp > 0 else 0

        # Determine freshness based on check_type
        hl_fresh = hl_ts_ms > 0 and (now_ms - hl_ts_ms) < (threshold_seconds * 1000)
        poly_up_fresh = poly_up_ts_ms > 0 and (now_ms - poly_up_ts_ms) < (threshold_seconds * 1000)
        poly_down_fresh = poly_down_ts_ms > 0 and (now_ms - poly_down_ts_ms) < (threshold_seconds * 1000)

        # Debug prints for diagnostics
        print(f"DEBUG: now_ms: {now_ms}")
        print(f"DEBUG: hl_ts_raw: {snapshot.hl_timestamp}, hl_ts_ms_converted: {hl_ts_ms}, hl_fresh: {hl_fresh}")
        print(f"DEBUG: poly_up_ts_raw: {snapshot.poly_up_timestamp}, poly_up_ts_ms_converted: {poly_up_ts_ms}, poly_up_fresh: {poly_up_fresh}")
        print(f"DEBUG: poly_down_ts_raw: {snapshot.poly_down_timestamp}, poly_down_ts_ms_converted: {poly_down_ts_ms}, poly_down_fresh: {poly_down_fresh}")

        if check_type == "hl_only":
            if hl_fresh:
                print(f"[{asset_name.upper()}] SHM HEALTHY (HL only): Hyperliquid timestamp is fresh.")
                return True
            else:
                print(f"[{asset_name.upper()}] SHM STALE (HL only): HL ({(now_ms - hl_ts_ms)/1000:.1f}s). All < {threshold_seconds}s required.")
                return False
        else: # check_type == "all"
            if hl_fresh and poly_up_fresh and poly_down_fresh:
                print(f"[{asset_name.upper()}] SHM HEALTHY: Hyperliquid and Polymarket timestamps are fresh.")
                return True
            else:
                print(f"[{asset_name.upper()}] SHM STALE: HL ({(now_ms - hl_ts_ms)/1000:.1f}s), Poly UP ({(now_ms - poly_up_ts_ms)/1000:.1f}s), Poly DOWN ({(now_ms - poly_down_ts_ms)/1000:.1f}s). All < {threshold_seconds}s required.")
                return False
    except FileNotFoundError:
        print(f"[{asset_name.upper()}] SHM NOT FOUND: {shm_name}. Assuming pipeline is not up yet.")
        return False
    except Exception as e:
        print(f"[{asset_name.upper()}] SHM CHECK ERROR: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python shm_health_check.py <asset_name> [threshold_seconds] [check_type]")
        sys.exit(1)
    
    asset = sys.argv[1]
    threshold = int(sys.argv[2]) if len(sys.argv) > 2 else 10 # Default 10 seconds
    check_type = sys.argv[3] if len(sys.argv) > 3 else "all"

    if check_shm_freshness(asset, threshold, check_type):
        sys.exit(0)
    else:
        sys.exit(1)
