"""
Python-Based Live TapReader: Quicknode to SHM Bridge
Upgraded to L4 Book: Tracks individual orders, OIDs, and User Addresses.
Integrated pUSD Balance Sync for Polymarket V2 Readiness.
"""
import os
import time
import asyncio
import json
import ctypes
import websockets
import aiohttp
import numpy as np
import signal
import sys
import grpc
import heapq
import orderbook_pb2
import orderbook_pb2_grpc
import traceback
from web3 import Web3
from utils.logger import get_logger
from utils.shm_types import L2BookStruct, AccountStateStruct, PriceLevel, MAX_LEVELS, MAX_POLY_LEVELS
from utils.shm_utils import POSIXSharedMemory

logger = get_logger(__name__)

# Constants
ASSET = os.environ.get("ASSET", "btc")
SHM_NAME = os.environ.get("SHM_NAME", f"/hl_l2_book_{ASSET}") 
ACC_SHM_NAME = os.environ.get("ACC_SHM_NAME", f"/poly_account_{ASSET}")

# Contract Addresses (Polygon Mainnet)
USDC_ADDRESS = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
PUSD_ADDRESS = Web3.to_checksum_address("0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb") # Verified pUSD
CTF_ADDRESS = Web3.to_checksum_address("0x4D97DCd97eC945f40cF65F87097ACe5EA0476045")
ONRAMP_ADDRESS = Web3.to_checksum_address("0x93070a847efef7f70739046a929d47a521f5b8ee")

ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"}
]
CTF_ABI = [
    {"constant":True,"inputs":[{"name":"account","type":"address"},{"name":"id","type":"uint256"}],"name":"balanceOf","outputs":[{"name":"value","type":"uint256"}],"type":"function"}
]

# Load libc for shm_open and shm_unlink
libc = ctypes.CDLL("libc.so.6", use_errno=True)
shm_open = libc.shm_open
shm_open.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
shm_open.restype = ctypes.c_int
shm_unlink = libc.shm_unlink
shm_unlink.argtypes = [ctypes.c_char_p]
shm_unlink.restype = ctypes.c_int

# --- Atomic Seqlock Bridge ---
# To prevent tearing, we need a memory barrier for the sequence increment.
# Python ctypes does not provide an atomic store-release.
SHM_BARRIER_PATH = "/tmp/shm_barrier.so"
if not os.path.exists(SHM_BARRIER_PATH):
    import subprocess
    c_source = """
    #include <stdint.h>
    void atomic_store_release(uint64_t *ptr, uint64_t val) {
        __atomic_store_n(ptr, val, __ATOMIC_RELEASE);
    }
    """
    with open("/tmp/shm_barrier.c", "w") as f: f.write(c_source)
    subprocess.run(["gcc", "-O3", "-fPIC", "-shared", "-o", SHM_BARRIER_PATH, "/tmp/shm_barrier.c"], check=True)

libbarrier = ctypes.CDLL(SHM_BARRIER_PATH)
atomic_store_release = libbarrier.atomic_store_release
atomic_store_release.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_uint64]

def set_seq_atomic(struct_ptr, val):
    # Use the address of the first field (sequence)
    ptr = ctypes.cast(ctypes.addressof(struct_ptr), ctypes.POINTER(ctypes.c_uint64))
    atomic_store_release(ptr, val)
# -----------------------------

GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"

class L4Book:
    """Manages full order book state from StreamL4Book gRPC with incremental aggregation."""
    def __init__(self):
        self.bids = {} # oid -> order_dict
        self.asks = {} # oid -> order_dict
        self.bid_levels = {} # price -> total_size
        self.ask_levels = {} # price -> total_size
        self.height = 0
        self.time = 0

    def apply_snapshot(self, snapshot):
        self.height = snapshot.height
        self.time = snapshot.time
        self.bids = {o.oid: self._order_to_dict(o) for o in snapshot.bids}
        self.asks = {o.oid: self._order_to_dict(o) for o in snapshot.asks}
        self.bid_levels = {}
        for o in self.bids.values():
            px = float(o['px'])
            self.bid_levels[px] = self.bid_levels.get(px, 0.0) + float(o['sz'])
        self.ask_levels = {}
        for o in self.asks.values():
            px = float(o['px'])
            self.ask_levels[px] = self.ask_levels.get(px, 0.0) + float(o['sz'])
        logger.info(f"L4 Snapshot applied at height {self.height}. Bids: {len(self.bid_levels)} levels, Asks: {len(self.ask_levels)} levels")

    def apply_diff(self, diff):
        self.height = diff.height
        self.time = diff.time
        try:
            data = json.loads(diff.data)
            for d in data.get('book_diffs', []):
                oid_raw = d.get('oid')
                if oid_raw is None: continue
                oid = int(oid_raw)
                side = d.get('side')
                sz_str = d.get('sz') or d.get('size')
                sz = float(sz_str) if sz_str else 0.0
                if side == 'B':
                    if sz == 0:
                        old_order = self.bids.pop(oid, None)
                        if old_order:
                            px = float(old_order['px'])
                            self.bid_levels[px] -= float(old_order['sz'])
                            if self.bid_levels[px] <= 1e-9: self.bid_levels.pop(px)
                    else: 
                        order = self._diff_to_order(d, fallback_ts=self.time)
                        if order:
                            old_order = self.bids.get(oid)
                            if old_order: self.bid_levels[float(old_order['px'])] -= float(old_order['sz'])
                            self.bids[oid] = order
                            px = float(order['px'])
                            self.bid_levels[px] = self.bid_levels.get(px, 0.0) + float(order['sz'])
                elif side == 'A':
                    if sz == 0:
                        old_order = self.asks.pop(oid, None)
                        if old_order:
                            px = float(old_order['px'])
                            self.ask_levels[px] -= float(old_order['sz'])
                            if self.ask_levels[px] <= 1e-9: self.ask_levels.pop(px)
                    else: 
                        order = self._diff_to_order(d, fallback_ts=self.time)
                        if order:
                            old_order = self.asks.get(oid)
                            if old_order: self.ask_levels[float(old_order['px'])] -= float(old_order['sz'])
                            self.asks[oid] = order
                            px = float(order['px'])
                            self.ask_levels[px] = self.ask_levels.get(px, 0.0) + float(order['sz'])
            for s in data.get('order_statuses', []):
                oid_raw = s.get('oid')
                if oid_raw is None: continue
                oid = int(oid_raw)
                status = s.get('status')
                if status in ['Filled', 'Canceled', 'Rejected']:
                    old_bid = self.bids.pop(oid, None)
                    if old_bid:
                        px = float(old_bid['px'])
                        self.bid_levels[px] -= float(old_bid['sz'])
                        if self.bid_levels[px] <= 1e-9: self.bid_levels.pop(px)
                    old_ask = self.asks.pop(oid, None)
                    if old_ask:
                        px = float(old_ask['px'])
                        self.ask_levels[px] -= float(old_ask['sz'])
                        if self.ask_levels[px] <= 1e-9: self.ask_levels.pop(px)
        except Exception as e:
            logger.error(f"L4 Diff Application Error: {e}")

    def get_aggregated_l2(self, max_levels=10):
        agg_bids = heapq.nlargest(max_levels, self.bid_levels.items(), key=lambda x: x[0])
        agg_asks = heapq.nsmallest(max_levels, self.ask_levels.items(), key=lambda x: x[0])
        return agg_bids, agg_asks

    def get_best_order_info(self, side='B'):
        orders = self.bids if side == 'B' else self.asks
        if not orders: return None
        try:
            valid_orders = [o for o in orders.values() if o.get('px') is not None and o.get('sz') is not None and o.get('ts') is not None]
            if not valid_orders: return None
            best_px = max(float(o['px']) for o in valid_orders) if side == 'B' else min(float(o['px']) for o in valid_orders)
            candidates = [o for o in valid_orders if float(o['px']) == best_px]
            best_order = min(candidates, key=lambda x: int(x['ts']))
            whale_sz = max(float(o['sz']) for o in candidates)
            return best_order, len(candidates), whale_sz
        except: return None

    def _order_to_dict(self, o): return {'px': o.limit_px, 'sz': o.sz, 'ts': o.timestamp, 'user': o.user, 'oid': o.oid}
    def _diff_to_order(self, d, fallback_ts=None):
        px = d.get('limit_px') or d.get('px')
        sz = d.get('sz') or d.get('size')
        ts = d.get('timestamp') or d.get('ts') or fallback_ts
        oid = d.get('oid')
        if any(v is None for v in [px, sz, ts, oid]): return None
        return {'px': px, 'sz': sz, 'ts': ts, 'user': d.get('user', '0x0000'), 'oid': int(oid)}

async def hl_bridge(book):
    target = os.environ.get("HYPERLIQUID_GRPC_TARGET", "dark-wider-sanctuary.hype-mainnet.quiknode.pro:10000")
    token = os.environ.get("HYPERLIQUID_AUTH_TOKEN", "").strip()
    l4_state = L4Book()
    
    # Kinetic Accumulators
    acc_flow = 0.0
    acc_ofi = 0.0
    max_I = 0.0 # Peak execution flow for p_max_i tracking
    
    last_update_ts = 0
    retry_delay = 5
    while True:
        try:
            logger.info(f"Connecting to Hyperliquid L4 gRPC: {target}")
            host = target.split(":")[0]
            MAX_MESSAGE_LENGTH = 64 * 1024 * 1024
            options = [
                ('grpc.max_receive_message_length', MAX_MESSAGE_LENGTH),
                ('grpc.max_send_message_length', MAX_MESSAGE_LENGTH),
                ('grpc.ssl_target_name_override', host),
                ('grpc.default_authority', host)
            ]
            credentials = grpc.ssl_channel_credentials()
            async with grpc.aio.secure_channel(target, credentials, options=options) as channel:
                stub = orderbook_pb2_grpc.OrderBookStreamingStub(channel)
                metadata = [('x-token', token), ('authorization', f'Bearer {token}')]
                request = orderbook_pb2.L4BookRequest(coin=ASSET.upper())
                stream = stub.StreamL4Book(request, metadata=metadata)
                last_flush_ts = time.time()
                logger.info(f"Stream opened for {ASSET.upper()}, waiting for updates...")
                
                async for update in stream:
                    try:
                        retry_delay = 5
                        t_recv = time.time_ns()
                        
                        # Process updates and accumulate kinetic signals
                        if update.HasField('snapshot'):
                            l4_state.apply_snapshot(update.snapshot)
                            acc_flow, acc_ofi = 0.0, 0.0 # Reset on snapshot
                        elif update.HasField('diff'):
                            # 1. Parse diff data to extract kinetic energy before applying to state
                            data = json.loads(update.diff.data)
                            for d in data.get('book_diffs', []):
                                sz = float(d.get('sz') or d.get('size') or 0.0)
                                side = d.get('side')
                                oid = int(d.get('oid', 0))
                                
                                # Find change in size for this specific order
                                old_sz = 0.0
                                if side == 'B' and oid in l4_state.bids: old_sz = float(l4_state.bids[oid]['sz'])
                                elif side == 'A' and oid in l4_state.asks: old_sz = float(l4_state.asks[oid]['sz'])
                                
                                delta_sz = sz - old_sz
                                acc_flow += abs(delta_sz)
                                if side == 'B': acc_ofi += delta_sz
                                else: acc_ofi -= delta_sz
                                
                            l4_state.apply_diff(update.diff)
                        
                        # 2. Throttled Flush to Shared Memory
                        curr_time = time.time()
                        if curr_time - last_flush_ts < 0.01: continue
                        
                        dt_wall = curr_time - last_flush_ts
                        last_flush_ts = curr_time
                        
                        seq = book.hl_sequence
                        book.hl_sequence = seq + 1
                        
                        # Write Microstructure Alphas
                        book.current_ofi = acc_ofi
                        # Execution Flow is tokens per second
                        current_I = (0.8 * book.execution_flow_rate) + (0.2 * (acc_flow / dt_wall))
                        book.execution_flow_rate = current_I
                        
                        if current_I > max_I:
                            max_I = current_I
                            if l4_state.bid_levels and l4_state.ask_levels:
                                bids, asks = l4_state.get_aggregated_l2(1)
                                book.p_max_i = (bids[0][0] + asks[0][0]) / 2.0
                        
                        max_I *= 0.999 # Decay the local peak threshold
                        
                        # Reset accumulators for next window
                        acc_flow, acc_ofi = 0.0, 0.0
                        
                        book.hl_timestamp, book.hl_l4_height = l4_state.time, l4_state.height
                        book.hot_path_latency_ns = time.time_ns() - t_recv
                        
                        # Aggregate for L2 visibility
                        bids, asks = l4_state.get_aggregated_l2(MAX_LEVELS)
                        if bids and asks:
                            for i in range(MAX_LEVELS):
                                if i < len(bids): book.hl_bids[i].price, book.hl_bids[i].size = bids[i]
                                else: book.hl_bids[i].price, book.hl_bids[i].size = 0.0, 0.0
                                if i < len(asks): book.hl_asks[i].price, book.hl_asks[i].size = asks[i]
                                else: book.hl_asks[i].price, book.hl_asks[i].size = 0.0, 0.0
                        
                        # Queue metrics
                        best_bid = l4_state.get_best_order_info('B')
                        if best_bid:
                            _, cnt, whale = best_bid
                            book.bid_order_count, book.whale_bid_size = cnt, whale
                            top_size = bids[0][1] if bids else 1.0
                            book.bid_concentration = whale / top_size
                            
                        best_ask = l4_state.get_best_order_info('A')
                        if best_ask:
                            _, cnt, whale = best_ask
                            book.ask_order_count, book.whale_ask_size = cnt, whale
                            top_size = asks[0][1] if asks else 1.0
                            book.ask_concentration = whale / top_size

                        set_seq_atomic(book, seq + 2)
                    except Exception as loop_e:
                        logger.error(f"Error in gRPC processing loop: {loop_e}")
                        continue
        except Exception as e:
            logger.error(f"HL L4 Bridge Error: {e}. Retrying in {retry_delay}s...")
            await asyncio.sleep(retry_delay)

def get_current_interval_timestamp(interval_minutes):
    now = int(time.time())
    return (now // (interval_minutes * 60) + 1) * (interval_minutes * 60)

async def fetch_active_token_ids(session):
    token_ids = []
    # Use global ASSET for isolation
    for timeframe in ["5m", "15m"]:
        ts = get_current_interval_timestamp(5 if timeframe == "5m" else 15)
        slug = f"{ASSET}-updown-{timeframe}-{ts}"
        try:
            url = f"{GAMMA_API_URL}?slug={slug}"
            logger.info(f"Fetching token IDs for slug: {slug}")
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and len(data) > 0:
                        clob_ids = json.loads(data[0].get("clobTokenIds", "[]"))
                        logger.info(f"Found {len(clob_ids)} token IDs for {slug}")
                        outcomes = json.loads(data[0].get("outcomes", "[]"))
                        
                        up_id, down_id = None, None
                        for i, outcome in enumerate(outcomes):
                            if i >= len(clob_ids): break
                            if outcome.lower() == "up": up_id = clob_ids[i]
                            elif outcome.lower() == "down": down_id = clob_ids[i]
                        
                        if up_id and down_id:
                            token_ids.extend([up_id, down_id])
                        else:
                            logger.warning(f"Failed to map outcomes for {slug}, skipping.")
                    else:
                        logger.warning(f"No market data found for slug: {slug}")
                else:
                    logger.error(f"Gamma API error for {slug}: Status {response.status}")
        except Exception as e:
            logger.error(f"Error fetching token IDs for {slug}: {e}")
    return token_ids

async def poly_bridge(book):
    ws_url = os.environ.get("POLY_CLOB_WS_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/market")
    logger.info(f"Connecting to Polymarket WebSocket: {ws_url}")
    
    # State for sorted book tracking
    # asset_id -> {"bids": {price: size}, "asks": {price: size}}
    local_books = {}

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                token_ids = await fetch_active_token_ids(session)
                if not token_ids:
                    logger.warning("No active Polymarket token IDs found. Retrying in 30s...")
                    await asyncio.sleep(30); continue
                
                primary_up = token_ids[0]
                primary_down = token_ids[1]
                
                # Initialize local book states
                local_books.clear()
                for tid in token_ids:
                    local_books[tid] = {"bids": {}, "asks": {}}

                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as websocket:
                    subscribe_msg = {"type": "market", "operation": "subscribe", "assets_ids": token_ids, "initial_dump": True}
                    await websocket.send(json.dumps(subscribe_msg))
                    
                    last_token_refresh = time.time()
                    consecutive_timeouts = 0
                    
                    while True:
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=5)
                            consecutive_timeouts = 0
                            msg = json.loads(message)
                            updates = msg if isinstance(msg, list) else [msg]
                            for update in updates:
                                event_type = update.get("event_type")
                                
                                if event_type == "book":
                                    asset_id = update.get("asset_id")
                                    if asset_id in local_books:
                                        # Use update instead of msg to avoid confusion in nested loops
                                        bids = update.get("bids", [])
                                        asks = update.get("asks", [])
                                        # Correctly handle list-based levels [price, size]
                                        local_books[asset_id]["bids"] = {float(b[0] if isinstance(b, list) else b.get("price")): float(b[1] if isinstance(b, list) else b.get("size")) for b in bids}
                                        local_books[asset_id]["asks"] = {float(a[0] if isinstance(a, list) else a.get("price")): float(a[1] if isinstance(a, list) else a.get("size")) for a in asks}
                                elif "price_changes" in update:
                                    for c in update["price_changes"]:
                                        c_tid = c.get("asset_id")
                                        if c_tid not in local_books: continue
                                        px, sz = float(c["price"]), float(c["size"])
                                        side_map = "bids" if c["side"] == "BUY" else "asks"
                                        if sz == 0:
                                            local_books[c_tid][side_map].pop(px, None)
                                        else:
                                            local_books[c_tid][side_map][px] = sz
                                else:
                                    continue

                                # Targeted Update to SHM
                                for asset_id, data in local_books.items():
                                    is_up = asset_id == primary_up
                                    is_down = asset_id == primary_down
                                    if not is_up and not is_down: continue

                                    seq = book.poly_sequence
                                    book.poly_sequence = seq + 1
                                    
                                    if is_up:
                                        book.poly_up_timestamp = int(time.time()*1000)
                                        shm_bids, shm_asks = book.poly_up_bids, book.poly_up_asks
                                    else:
                                        book.poly_down_timestamp = int(time.time()*1000)
                                        shm_bids, shm_asks = book.poly_down_bids, book.poly_down_asks
                                    
                                    bids_sorted = sorted(data["bids"].items(), key=lambda x: x[0], reverse=True)[:MAX_POLY_LEVELS]
                                    asks_sorted = sorted(data["asks"].items(), key=lambda x: x[0])[:MAX_POLY_LEVELS]
                                    
                                    for i in range(MAX_POLY_LEVELS):
                                        if i < len(bids_sorted): shm_bids[i].price, shm_bids[i].size = bids_sorted[i]
                                        else: shm_bids[i].price, shm_bids[i].size = 0.0, 0.0
                                        
                                        if i < len(asks_sorted): shm_asks[i].price, shm_asks[i].size = asks_sorted[i]
                                        else: shm_asks[i].price, shm_asks[i].size = 0.0, 0.0
                                    
                                    set_seq_atomic(book, seq + 2)

                        except asyncio.TimeoutError:
                            consecutive_timeouts += 1
                            logger.warning(f"Polymarket WebSocket timeout ({consecutive_timeouts}/10)")
                            if consecutive_timeouts >= 10:
                                logger.error("Too many consecutive Polymarket WebSocket timeouts. Reconnecting...")
                                break
                            continue
                        
                        if time.time() - last_token_refresh > 300:
                            new_token_ids = await fetch_active_token_ids(session)
                            if new_token_ids and set(new_token_ids) != set(token_ids):
                                logger.info("Market rotation detected. Reconnecting Polymarket Bridge...")
                                break 
                            last_token_refresh = time.time()

        except Exception as e:
            logger.error(f"Polymarket Bridge Error: {e}")
            logger.error(traceback.format_exc())
            await asyncio.sleep(5)

async def sync_account_state(acc):
    rpc_url = os.environ.get("POLYGON_RPC_URL", "https://polygon-rpc.com")
    wallet_raw = os.environ.get("POLY_PROXY_WALLET") or os.environ.get("POLY_WALLET_ADDRESS")
    if not wallet_raw: return
    try:
        wallet_address = Web3.to_checksum_address(wallet_raw)
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        pusd_contract = w3.eth.contract(address=PUSD_ADDRESS, abi=ERC20_ABI)
        ctf_contract = w3.eth.contract(address=CTF_ADDRESS, abi=CTF_ABI)
        
        while True:
            try:
                # Use to_thread for blocking Web3 calls
                raw_balance = await asyncio.to_thread(pusd_contract.functions.balanceOf(wallet_address).call)
                balance_usd = float(raw_balance) / 1e6
                
                async with aiohttp.ClientSession() as session:
                    token_ids = await fetch_active_token_ids(session)
                    up_bal, down_bal = 0.0, 0.0
                    if len(token_ids) >= 2:
                        tid_up = int(token_ids[0])
                        tid_down = int(token_ids[1])
                        
                        raw_up = await asyncio.to_thread(ctf_contract.functions.balanceOf(wallet_address, tid_up).call)
                        raw_down = await asyncio.to_thread(ctf_contract.functions.balanceOf(wallet_address, tid_down).call)
                        
                        up_bal = float(raw_up) / 1e6
                        down_bal = float(raw_down) / 1e6

                seq = acc.sequence
                set_seq_atomic(acc, seq + 1)
                acc.available_collateral = balance_usd
                acc.total_equity = balance_usd + up_bal + down_bal
                acc.up_position = up_bal
                acc.down_position = down_bal
                acc.last_update_ts = int(time.time())
                set_seq_atomic(acc, seq + 2)
                logger.info(f"SYNC: pUSD: ${balance_usd:.2f}, UP: {up_bal:.2f}, DOWN: {down_bal:.2f}")
            except Exception as e:
                logger.error(f"Failed to sync balance: {e}")
            await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"Account state task failed: {e}")

async def watchdog_pulse():
    while True:
        logger.debug("WATCHDOG PULSE")
        await asyncio.sleep(60)

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", help="Asset name for isolation (e.g. btc, eth)")
    args, _ = parser.parse_known_args()
    
    global ASSET, SHM_NAME, ACC_SHM_NAME
    if args.asset:
        ASSET = args.asset.lower()
        SHM_NAME = f"/hl_l2_book_{ASSET}"
        ACC_SHM_NAME = f"/poly_account_{ASSET}"
        logger.info(f"Isolation Mode: {ASSET.upper()} (SHM: {SHM_NAME})")

    shm, shm_acc = None, None
    try:
        shm = POSIXSharedMemory(SHM_NAME, ctypes.sizeof(L2BookStruct))
        book = L2BookStruct.from_buffer(shm.buf)
        
        # Initialize Defaults to prevent signal suppression
        book.regime_multiplier = 1.0
        book.regime_state_enum = 1 # Active
        
        shm_acc = POSIXSharedMemory(ACC_SHM_NAME, 64)
        acc = AccountStateStruct.from_buffer(shm_acc.buf)
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM): loop.add_signal_handler(sig, stop_event.set)
        tasks = [asyncio.create_task(hl_bridge(book)), asyncio.create_task(poly_bridge(book)), asyncio.create_task(sync_account_state(acc)), asyncio.create_task(watchdog_pulse())]
        await stop_event.wait()
        for t in tasks: t.cancel()
    finally:
        if shm: shm.close()
        if shm_acc: shm_acc.close()

if __name__ == "__main__":
    asyncio.run(main())
