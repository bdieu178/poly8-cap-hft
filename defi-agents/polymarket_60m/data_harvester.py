
"""
Real-time Data Harvester for Polymarket and Hyperliquid via Shared Memory.
Aligned with the zero-copy "Hot Path" architecture.
"""
import os
import time
import asyncio
import ctypes
from datetime import datetime, UTC
import polars as pl
from utils.logger import get_logger
from utils.shm_types import L2BookStruct, MAX_LEVELS, SpscRingBufferStruct
from utils.shm_utils import POSIXSharedMemory, read_shm_snapshot, read_spsc_ring_buffer_snapshot

logger = get_logger(__name__)

# Constants
SHM_NAME = os.environ.get("SHM_NAME", "/hl_l2_book_v2")
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data', 'realtime')
os.makedirs(DATA_DIR, exist_ok=True)

async def poll_shared_memory(queue):
    """Polls shared memory and pushes updates to the processing queue."""
    logger.info(f"Connecting to Shared Memory: {SHM_NAME}")
    
    shm = None
    while shm is None:
        try:
            shm = POSIXSharedMemory(SHM_NAME, ctypes.sizeof(SpscRingBufferStruct))
        except OSError:
            logger.warning(f"Waiting for SHM {SHM_NAME} to be created...")
            await asyncio.sleep(5)
    
    last_hl_ts = 0
    last_poly_up_ts = 0
    last_poly_down_ts = 0
    
    try:
        while True:
            # 1. Take a consistent snapshot
            snapshot = read_spsc_ring_buffer_snapshot(shm.buf)
            
            # 2. Check for changes in Hyperliquid
            if snapshot.hl_timestamp > last_hl_ts:
                data = {
                    "source": "hyperliquid",
                    "timestamp_ms": snapshot.hl_timestamp,
                    "mid_price": (snapshot.hl_bids[0].price + snapshot.hl_asks[0].price) / 2.0 if snapshot.hl_asks[0].price > 0 else 0,
                    "ofi": snapshot.current_ofi,
                    "flow": snapshot.execution_flow_rate,
                    "p_max_i": snapshot.p_max_i,
                    "bid_concentration": snapshot.bid_concentration,
                    "ask_concentration": snapshot.ask_concentration,
                    "bid_order_count": snapshot.bid_order_count,
                    "ask_order_count": snapshot.ask_order_count
                }
                # Capture Top 5 HL Depth
                for i in range(5):
                    data[f"hl_bid_px_{i}"] = snapshot.hl_bids[i].price
                    data[f"hl_bid_sz_{i}"] = snapshot.hl_bids[i].size
                    data[f"hl_ask_px_{i}"] = snapshot.hl_asks[i].price
                    data[f"hl_ask_sz_{i}"] = snapshot.hl_asks[i].size
                
                queue.put_nowait(data)
                last_hl_ts = snapshot.hl_timestamp

            # 3. Check for changes in Polymarket (UP)
            if snapshot.poly_up_timestamp > last_poly_up_ts:
                data = {
                    "source": "polymarket_up",
                    "timestamp_ms": snapshot.poly_up_timestamp,
                    "target_bid_price_poly": snapshot.poly_up_bids[0].price,
                    "target_ask_price_poly": snapshot.poly_up_asks[0].price,
                }
                queue.put_nowait(data)
                last_poly_up_ts = snapshot.poly_up_timestamp

            # 4. Check for changes in Polymarket (DOWN)
            if snapshot.poly_down_timestamp > last_poly_down_ts:
                data = {
                    "source": "polymarket_down",
                    "timestamp_ms": snapshot.poly_down_timestamp,
                    "target_bid_price_poly": snapshot.poly_down_bids[0].price,
                    "target_ask_price_poly": snapshot.poly_down_asks[0].price,
                }
                queue.put_nowait(data)
                last_poly_down_ts = snapshot.poly_down_timestamp
                
            await asyncio.sleep(0.01) # 100Hz poll
    finally:
        if shm: shm.close()

async def process_and_flush(queue):
    """Aligns and flushes to Parquet with stale data detection."""
    buffer = []
    last_flush_time = time.time()
    last_event_ts = 0
    
    while True:
        try:
            data = await asyncio.wait_for(queue.get(), timeout=5.0)
            
            # Stale data / Data Gap detection
            current_ts = data.get("timestamp_ms", 0)
            if last_event_ts > 0 and current_ts > last_event_ts + 10000: # 10s gap
                logger.warning(f"Detected large data gap of {current_ts - last_event_ts}ms in {data.get('source')} stream")
            last_event_ts = current_ts
            
            buffer.append(data)
            
            # Periodic flush to Parquet (Every 1 minute or 1000 items)
            if time.time() - last_flush_time > 60 or len(buffer) >= 1000:
                if buffer:
                    df = pl.DataFrame(buffer)
                    timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                    file_path = os.path.join(DATA_DIR, f"harvest_{timestamp_str}.parquet")
                    df.write_parquet(file_path)
                    logger.info(f"Flushed {len(buffer)} events to {file_path}")
                    buffer = []
                    last_flush_time = time.time()
        except asyncio.TimeoutError:
            if buffer:
                logger.info("Harvester timeout, force-flushing buffer...")
                df = pl.DataFrame(buffer)
                timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                file_path = os.path.join(DATA_DIR, f"harvest_{timestamp_str}_timeout.parquet")
                df.write_parquet(file_path)
                buffer = []
                last_flush_time = time.time()

async def main():
    logger.info("Initializing Real-time Data Harvester...")
    queue = asyncio.Queue()
    try:
        await asyncio.gather(
            poll_shared_memory(queue),
            process_and_flush(queue)
        )
    except asyncio.CancelledError:
        logger.info("Harvester shutting down...")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
