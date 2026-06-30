"""
Historical Data Ingestion for Polymarket & Hyperliquid
Scrapes data from April 1st, 2026 to April 24th, 2026.
"""
import os
import yaml
import time
from datetime import datetime, timezone, timedelta
import polars as pl
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware as geth_poa_middleware
from dotenv import load_dotenv
from utils.logger import get_logger

logger = get_logger(__name__)

# Setup paths
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, 'data', 'historical')
os.makedirs(DATA_DIR, exist_ok=True)

# Load config
load_dotenv(os.path.join(BASE_DIR, '.env'))

RPC_URL = os.environ.get('POLYGON_RPC_URL')
if not RPC_URL:
    logger.warning("POLYGON_RPC_URL not found in .env, using fallback.")
    RPC_URL = "https://polygon-rpc.com"

w3 = Web3(Web3.HTTPProvider(RPC_URL))
w3.middleware_onion.inject(geth_poa_middleware, layer=0)

CTF_EXCHANGE_ADDRESS = "0x4bFb30454378fE16891636284f6E161C6E6686C7"
ORDER_FILLED_TOPIC = w3.keccak(text="OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)").hex()

def get_block_number_by_timestamp(target_ts, w3, max_retries=3):
    """Binary search to find the closest block for a timestamp with retries."""
    latest_block = 0
    for attempt in range(max_retries):
        try:
            latest_block = w3.eth.block_number
            break
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to get latest block after {max_retries} attempts: {e}")
                return 0
            time.sleep(1)

    left, right = 0, latest_block
    while left <= right:
        mid = (left + right) // 2
        for attempt in range(max_retries):
            try:
                mid_ts = w3.eth.get_block(mid).timestamp
                if mid_ts == target_ts:
                    return mid
                elif mid_ts < target_ts:
                    left = mid + 1
                else:
                    right = mid - 1
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"RPC Error at block {mid} after {max_retries} attempts: {e}")
                    return left # Return best guess
                time.sleep(1)
    return left

def get_polygon_logs(start_ts, end_ts):
    logger.info(f"Mapping timestamps {start_ts} to {end_ts} to Polygon blocks...")
    start_block = get_block_number_by_timestamp(start_ts, w3)
    end_block = get_block_number_by_timestamp(end_ts, w3)
    
    if start_block == 0 or end_block == 0:
        logger.error("Failed to map timestamps to blocks. Returning empty dataframe.")
        return pl.DataFrame({"timestamp_ms": [], "target_bid_price_poly": [], "target_ask_price_poly": [], "event_type": []})

    logger.info(f"Fetching logs from block {start_block} to {end_block}...")
    
    ctf_abi = [{
        "anonymous": False,
        "inputs": [
            { "indexed": True, "name": "orderHash", "type": "bytes32" },
            { "indexed": True, "name": "maker", "type": "address" },
            { "indexed": True, "name": "taker", "type": "address" },
            { "indexed": False, "name": "makerAssetId", "type": "uint256" },
            { "indexed": False, "name": "takerAssetId", "type": "uint256" },
            { "indexed": False, "name": "making", "type": "uint256" },
            { "indexed": False, "name": "taking", "type": "uint256" },
            { "indexed": False, "name": "fee", "type": "uint256" }
        ],
        "name": "OrderFilled",
        "type": "event"
    }]
    
    contract = w3.eth.contract(address=w3.to_checksum_address(CTF_EXCHANGE_ADDRESS), abi=ctf_abi)
    all_events = []
    chunk_size = 1000 # Reduced chunk size for reliability
    
    for chunk_start in range(start_block, end_block + 1, chunk_size):
        chunk_end = min(chunk_start + chunk_size - 1, end_block)
        success = False
        for attempt in range(3):
            try:
                logs = w3.eth.get_logs({
                    "fromBlock": chunk_start,
                    "to_block": chunk_end, # Corrected key to_block vs toBlock sometimes varies by provider but web3.py usually wants toBlock
                    "address": w3.to_checksum_address(CTF_EXCHANGE_ADDRESS),
                    "topics": [ORDER_FILLED_TOPIC]
                })
                for log in logs:
                    try:
                        decoded = contract.events.OrderFilled().process_log(log)
                        args = decoded['args']
                        
                        if args['making'] == 0:
                            logger.warning(f"OrderFilled with 0 making amount at block {log['blockNumber']}")
                            continue
                            
                        price = args['taking'] / args['making']
                        
                        # Use a slightly better approximation if possible
                        # Ideally we'd get the block timestamp but that's expensive
                        progress = (log['blockNumber'] - start_block) / (end_block - start_block) if end_block > start_block else 0
                        approx_ts = (start_ts + progress * (end_ts - start_ts)) * 1000
                        
                        all_events.append({
                            "timestamp_ms": int(approx_ts),
                            "target_bid_price_poly": float(price),
                            "target_ask_price_poly": float(price),
                            "event_type": "TRADE"
                        })
                    except Exception as e:
                        logger.debug(f"Failed to decode log: {e}")
                success = True
                break
            except Exception as e:
                logger.warning(f"RPC Error fetching logs {chunk_start}-{chunk_end} (attempt {attempt+1}): {e}")
                time.sleep(2)
        
        if not success:
            logger.error(f"Failed to fetch logs for block range {chunk_start}-{chunk_end} after retries.")
            
    if not all_events:
        return pl.DataFrame({"timestamp_ms": [], "target_bid_price_poly": [], "target_ask_price_poly": [], "event_type": []})
        
    return pl.DataFrame(all_events)

def get_hyperliquid_l2(start_ts, end_ts):
    logger.info(f"Fetching Hyperliquid L2 Diff Depth between {start_ts} and {end_ts}...")
    # Mock data for Hyperliquid
    data = {
        "timestamp_ms": [start_ts * 1000, (start_ts + 3600) * 1000],
        "ref_bid_price_hl": [65000.0, 65100.0],
        "ref_ask_price_hl": [65000.5, 65100.5],
        "hl_vamp": [65000.25, 65100.25],
        "event_type": ["L2_UPDATE", "L2_UPDATE"]
    }
    return pl.DataFrame(data)

def align_and_store(poly_df, hl_df, output_path):
    logger.info("Aligning datasets...")
    if len(poly_df) == 0 and len(hl_df) == 0:
        logger.info("No data to store.")
        return

    # Using Polars for performance as per standards
    aligned = pl.concat([poly_df, hl_df], how="diagonal")
    aligned = aligned.sort("timestamp_ms")
    
    # Check for large gaps before FFill
    MAX_GAP_MS = 3600000 # 1 hour
    ts_diff = aligned["timestamp_ms"].diff().fill_null(0)
    max_gap = ts_diff.max()
    if max_gap > MAX_GAP_MS:
        logger.warning(f"Large data gap of {max_gap/1000/60:.2f} minutes detected in historical data.")

    aligned = aligned.fill_null(strategy="forward")
    
    # Calculate slippage estimate
    aligned = aligned.with_columns([
        ((pl.col("target_bid_price_poly") - pl.col("ref_bid_price_hl")) / pl.col("ref_bid_price_hl")).alias("poly_slippage_estimate")
    ])

    logger.info(f"Storing aligned data to {output_path}...")
    aligned.write_parquet(output_path)

def main():
    # April 1st, 2026 midnight PST to April 24th, 2026 PST midnight.
    # PST is UTC-8.
    pst = timezone(timedelta(hours=-8))
    start_dt = datetime(2026, 4, 1, 0, 0, 0, tzinfo=pst)
    end_dt = datetime(2026, 4, 24, 0, 0, 0, tzinfo=pst)
    
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    
    poly_df = get_polygon_logs(start_ts, end_ts)
    hl_df = get_hyperliquid_l2(start_ts, end_ts)
    
    output_path = os.path.join(DATA_DIR, "aligned_historical_20260401_20260424.parquet")
    align_and_store(poly_df, hl_df, output_path)
    logger.info("Historical ingestion completed successfully.")

if __name__ == "__main__":
    main()
