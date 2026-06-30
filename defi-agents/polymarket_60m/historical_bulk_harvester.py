"""
High-Fidelity Production Harvester: Continuous L2 Recording
Records real-time L2 data from the Hot-Path (Quicknode) for the 3-month rolling backtest.
No OHLC or trade-log proxies used.
"""
import os
import time
import asyncio
import ctypes
import polars as pl
from datetime import datetime, UTC
from utils.logger import get_logger
from utils.shm_types import L2BookStruct, MAX_LEVELS, SpscRingBufferStruct
from utils.shm_utils import POSIXSharedMemory, read_shm_snapshot, read_spsc_ring_buffer_snapshot

logger = get_logger(__name__)

import argparse

# Constants
parser = argparse.ArgumentParser()
parser.add_argument("--asset", default="v2", help="Asset name for isolation")
args, unknown = parser.parse_known_args()

ASSET = args.asset
SHM_NAME = os.environ.get("SHM_NAME", f"/hl_l2_book_{ASSET}")
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data', 'realtime', ASSET)
os.makedirs(DATA_DIR, exist_ok=True)

async def continuous_harvest():
    logger.info(f"Starting High-Fidelity Production Harvester for {ASSET} on {SHM_NAME}")
    shm = None
    buffer = []
    last_hl_ts = 0
    last_poly_up_ts = 0
    last_poly_down_ts = 0
    last_flush_time = time.time()
    
    while True:
        try:
            shm = POSIXSharedMemory(SHM_NAME, ctypes.sizeof(SpscRingBufferStruct))
            logger.info(f"Connected to SHM: {SHM_NAME}")
            break
        except OSError:
            logger.warning(f"Waiting for SHM {SHM_NAME} to be created by TapReader...")
            await asyncio.sleep(5)
    
    try:
        while True:
            snapshot = read_spsc_ring_buffer_snapshot(shm.buf)
            
            if snapshot.hl_timestamp > last_hl_ts:
                data_point = {
                    "source": "hyperliquid",
                    "timestamp_ms": snapshot.hl_timestamp,
                    "hl_bid_px_0": snapshot.hl_bids[0].price, "hl_bid_sz_0": snapshot.hl_bids[0].size,
                    "hl_ask_px_0": snapshot.hl_asks[0].price, "hl_ask_sz_0": snapshot.hl_asks[0].size,
                    "current_ofi": snapshot.current_ofi,
                    "execution_flow_rate": snapshot.execution_flow_rate,
                    "p_max_i": snapshot.p_max_i,
                    "bid_order_count": snapshot.bid_order_count,
                    "ask_order_count": snapshot.ask_order_count,
                    "whale_bid_size": snapshot.whale_bid_size,
                    "whale_ask_size": snapshot.whale_ask_size,
                    "bid_concentration": snapshot.bid_concentration,
                    "ask_concentration": snapshot.ask_concentration,
                    "hot_path_latency_ns": snapshot.hot_path_latency_ns,
                    "poly_bid_px_0": None, "poly_bid_sz_0": None,
                    "poly_ask_px_0": None, "poly_ask_sz_0": None,
                    "outcome": "perpetual",
                    "event_type": "L2_UPDATE"
                }
                buffer.append(data_point)
                last_hl_ts = snapshot.hl_timestamp
            
            if snapshot.poly_up_timestamp > last_poly_up_ts:
                data_point = {
                    "source": "polymarket",
                    "timestamp_ms": snapshot.poly_up_timestamp,
                    "hl_bid_px_0": None, "hl_bid_sz_0": None,
                    "hl_ask_px_0": None, "hl_ask_sz_0": None,
                    "current_ofi": None,
                    "execution_flow_rate": None,
                    "p_max_i": None,
                    "bid_order_count": None,
                    "ask_order_count": None,
                    "whale_bid_size": None,
                    "whale_ask_size": None,
                    "bid_concentration": None,
                    "ask_concentration": None,
                    "hot_path_latency_ns": None,
                    "poly_bid_px_0": snapshot.poly_up_bids[0].price,
                    "poly_bid_sz_0": snapshot.poly_up_bids[0].size,
                    "poly_ask_px_0": snapshot.poly_up_asks[0].price,
                    "poly_ask_sz_0": snapshot.poly_up_asks[0].size,
                    "outcome": "up",
                    "event_type": "ORDER_BOOK"
                }
                buffer.append(data_point)
                last_poly_up_ts = snapshot.poly_up_timestamp

            if snapshot.poly_down_timestamp > last_poly_down_ts:
                data_point = {
                    "source": "polymarket",
                    "timestamp_ms": snapshot.poly_down_timestamp,
                    "hl_bid_px_0": None, "hl_bid_sz_0": None,
                    "hl_ask_px_0": None, "hl_ask_sz_0": None,
                    "current_ofi": None,
                    "execution_flow_rate": None,
                    "p_max_i": None,
                    "bid_order_count": None,
                    "ask_order_count": None,
                    "whale_bid_size": None,
                    "whale_ask_size": None,
                    "bid_concentration": None,
                    "ask_concentration": None,
                    "hot_path_latency_ns": None,
                    "poly_bid_px_0": snapshot.poly_down_bids[0].price,
                    "poly_bid_sz_0": snapshot.poly_down_bids[0].size,
                    "poly_ask_px_0": snapshot.poly_down_asks[0].price,
                    "poly_ask_sz_0": snapshot.poly_down_asks[0].size,
                    "outcome": "down",
                    "event_type": "ORDER_BOOK"
                }
                buffer.append(data_point)
                last_poly_down_ts = snapshot.poly_down_timestamp

            # Rotation / Flush Logic
            if time.time() - last_flush_time > 60 or len(buffer) >= 10000: # 60 Seconds or 10K items
                if buffer:
                    # Define explicit schema to prevent Polars type inference mismatches between HL and Poly rows
                    schema = {
                        "source": pl.String,
                        "timestamp_ms": pl.UInt64,
                        "hl_bid_px_0": pl.Float64, "hl_bid_sz_0": pl.Float64,
                        "hl_ask_px_0": pl.Float64, "hl_ask_sz_0": pl.Float64,
                        "current_ofi": pl.Float64,
                        "execution_flow_rate": pl.Float64,
                        "p_max_i": pl.Float64,
                        "bid_order_count": pl.UInt32,
                        "ask_order_count": pl.UInt32,
                        "whale_bid_size": pl.Float64,
                        "whale_ask_size": pl.Float64,
                        "bid_concentration": pl.Float64,
                        "ask_concentration": pl.Float64,
                        "hot_path_latency_ns": pl.UInt64,
                        "poly_bid_px_0": pl.Float64,
                        "poly_bid_sz_0": pl.Float64,
                        "poly_ask_px_0": pl.Float64,
                        "poly_ask_sz_0": pl.Float64,
                        "outcome": pl.String,
                        "event_type": pl.String
                    }
                    
                    filename = f"hft_recording_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.parquet"
                    tmp_path = os.path.join(DATA_DIR, f"{filename}.tmp")
                    final_path = os.path.join(DATA_DIR, filename)
                    
                    df = pl.DataFrame(buffer, schema=schema)
                    df.write_parquet(tmp_path)
                    os.rename(tmp_path, final_path)
                    logger.info(f"Flushed {len(buffer)} ticks to {final_path}")
                    buffer = []
                    last_flush_time = time.time()
                
            await asyncio.sleep(0.01)

    except OSError as e:
        logger.error(f"SHM Error: {e}. Start TapReader first.")
    except Exception as e:
        logger.error(f"Harvester Fatal Error: {e}")
    finally:
        if shm: shm.close()

if __name__ == "__main__":
    asyncio.run(continuous_harvest())
