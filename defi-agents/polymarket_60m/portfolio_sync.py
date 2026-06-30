import os
import sys
import json
import sqlite3
import requests
from web3 import Web3

PROJECT_ROOT = "/home/bdieu178/user/defi-agents/polymarket"
sys.path.append(PROJECT_ROOT)

def load_env_file():
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                parts = line.split("=", 1)
                os.environ[parts[0].strip()] = parts[1].strip().strip('"').strip("'")

def query_onchain_balance(w3, wallet, ctf_address, token_id):
    if not token_id:
        return 0.0
    try:
        wallet_padded = wallet.lower().replace("0x", "").rjust(64, '0')
        token_hex = hex(int(token_id))[2:].rjust(64, '0')
        # balanceOf(address,uint256) -> selector 0x00fdd58e
        data = "0x00fdd58e" + wallet_padded + token_hex
        res = w3.eth.call({"to": ctf_address, "data": data}, "latest")
        return int(res.hex(), 16) / 1e6 if res else 0.0
    except Exception as e:
        print(f"[SYNC] Error querying balance for token {token_id[:15]}...: {e}")
        return 0.0

def get_market_details(token_id):
    # Query Gamma API
    url = f"https://gamma-api.polymarket.com/markets?clob_token_ids={token_id}"
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data and len(data) > 0:
                mkt = data[0]
                clob_ids = mkt.get("clobTokenIds", "[]")
                if isinstance(clob_ids, str):
                    try: clob_ids = json.loads(clob_ids)
                    except Exception: clob_ids = []
                outcomes = mkt.get("outcomes", "[]")
                if isinstance(outcomes, str):
                    try: outcomes = json.loads(outcomes)
                    except Exception: outcomes = []
                
                side = "UP"
                if token_id in clob_ids:
                    idx = clob_ids.index(token_id)
                    if idx < len(outcomes):
                        outcome_str = outcomes[idx].upper()
                        if outcome_str == "DOWN":
                            side = "DOWN"
                
                # Determine asset
                slug = mkt.get("slug", "").lower()
                question = mkt.get("question", "").lower()
                asset = "eth"
                if "btc" in slug or "bitcoin" in question:
                    asset = "btc"
                    
                return {
                    "asset": asset,
                    "token_id": token_id,
                    "side": side,
                    "active": mkt.get("active", True)
                }
    except Exception as e:
        print(f"[SYNC] Gamma API fetch failed for {token_id[:15]}...: {e}")
    return None

def main():
    load_env_file()
    rpc_url = os.environ.get("POLYGON_RPC_URL")
    wallet = os.environ.get("POLY_PROXY_WALLET", "0xD9E76753BD90422f9d056c7Af80f4A7b33f84Dc1")
    
    if not rpc_url:
        print("[SYNC] Error: POLYGON_RPC_URL not found.")
        return
        
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    ctf_address = Web3.to_checksum_address("0x4D97DCd97eC945f40cF65F87097ACe5EA0476045")
    
    print(f"[SYNC] Connected to RPC. safe: {w3.is_connected()}")
    print(f"[SYNC] Running State Reconciler for wallet: {wallet}")
    
    candidate_tokens = set()
    
    # 1. Extract from trades.log (limit to last 48 hours to optimize candidate count)
    trades_log = os.path.join(PROJECT_ROOT, "logs", "audit", "trades.log")
    if os.path.exists(trades_log):
        try:
            import time
            from datetime import datetime, timezone
            limit_dt = datetime.fromtimestamp(time.time() - 48 * 3600, timezone.utc)
            limit_str = limit_dt.isoformat().replace("T", " ")
            with open(trades_log, "r") as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        ts_str = data.get("timestamp_utc")
                        if ts_str:
                            ts_clean = ts_str.strip().replace("T", " ")
                            if ts_clean < limit_str:
                                continue
                        
                        tid = data.get("order_details", {}).get("token_id")
                        if tid:
                            tid_clean = tid.split('\x00')[0].strip()
                            if tid_clean.isdigit():
                                candidate_tokens.add(tid_clean)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[SYNC] Error reading trades log: {e}")
            
    # 2. Extract from hft_state.db
    db_path = os.path.join(PROJECT_ROOT, "data", "hft_state.db")
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT token_id FROM open_orders;")
            for r in cursor.fetchall():
                if r[0]:
                    tid_clean = r[0].split('\x00')[0].strip()
                    if tid_clean.isdigit():
                        candidate_tokens.add(tid_clean)
            conn.close()
        except Exception as e:
            print(f"[SYNC] Error reading SQLite: {e}")
            
    # 3. Scan recent transfer events (last 20,000 blocks ~11 hours)
    try:
        latest_block = w3.eth.block_number
        from_block = max(0, latest_block - 20000)
        wallet_padded = "0x" + wallet.lower().replace("0x", "").rjust(64, '0')
        transfer_single_topic = "0xc3d581efc5ce9c6902527588708b7607acd21fb7e803fb29a285d96f7c3ac1c7"
        
        # Query incoming transfers to wallet in chunks of 2000 blocks
        logs_in = []
        chunk_size = 2000
        for start in range(from_block, latest_block + 1, chunk_size):
            end = min(latest_block, start + chunk_size - 1)
            try:
                chunk_logs = w3.eth.get_logs({
                    "fromBlock": start,
                    "toBlock": end,
                    "address": ctf_address,
                    "topics": [transfer_single_topic, None, None, wallet_padded]
                })
                logs_in.extend(chunk_logs)
            except Exception as ce:
                print(f"[SYNC] Error scanning block chunk {start}-{end}: {ce}")
                
        for log in logs_in:
            if log.data:
                # ERC1155 TransferSingle data: uint256 id, uint256 value
                try:
                    data_bytes = log.data
                    token_id_val = int(data_bytes[:32].hex(), 16)
                    candidate_tokens.add(str(token_id_val))
                except Exception:
                    pass
        print(f"[SYNC] Scanned last 20,000 blocks, found {len(logs_in)} incoming TransferSingle logs.")
    except Exception as e:
        print(f"[SYNC] Error scanning events: {e}")
        
    # 3.5. Determine currently active market token IDs using slug generation to filter candidates
    active_tokens = set()
    try:
        import time
        now_secs = int(time.time())
        timeframes = [5, 15]
        assets = ["btc", "eth"]
        for asset in assets:
            for tf in timeframes:
                seconds = tf * 60
                expiration_rounded = (now_secs // seconds + 1) * seconds
                for offset in [-1, 0, 1]:
                    exp_time = expiration_rounded + offset * seconds
                    timeframe_str = "15m" if tf == 15 else "5m"
                    slug = f"{asset}-updown-{timeframe_str}-{exp_time}"
                    url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
                    try:
                        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
                        if r.status_code == 200:
                            data = r.json()
                            if data and len(data) > 0:
                                mkt = data[0]
                                clob_ids = mkt.get("clobTokenIds", "[]")
                                if isinstance(clob_ids, str):
                                    try: clob_ids = json.loads(clob_ids)
                                    except Exception: clob_ids = []
                                for tid in clob_ids:
                                    if tid:
                                        active_tokens.add(str(tid).strip())
                    except Exception:
                        pass
        print(f"[SYNC] Resolved {len(active_tokens)} active tokens from current/adjacent market windows.")
    except Exception as e:
        print(f"[SYNC] Error generating active tokens: {e}")

    if active_tokens:
        candidate_tokens = candidate_tokens.intersection(active_tokens).union(active_tokens)
        
    print(f"[SYNC] Total candidate token IDs to check after active filtering: {len(candidate_tokens)}")
    
    active_positions = []
    for tid in sorted(candidate_tokens):
        bal = query_onchain_balance(w3, wallet, ctf_address, tid)
        if bal > 0.01:
            print(f"[SYNC] Found non-zero balance: {bal:.4f} shares for token {tid[-12:]}")
            mkt_details = get_market_details(tid)
            if mkt_details:
                # Add to active positions if the market is active
                if mkt_details["active"]:
                    pos = {
                        "asset": mkt_details["asset"],
                        "token_id": tid,
                        "side": mkt_details["side"],
                        "quantity": bal
                    }
                    active_positions.append(pos)
                    print(f"  [ACTIVE] Added active position: {pos}")
                else:
                    print(f"  [EXPIRED] Skipping expired/closed market.")
                    
    # Write to active_positions.json
    out_path = os.path.join(PROJECT_ROOT, "data", "active_positions.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(active_positions, f, indent=4)
        
    print(f"[SYNC] State reconciler complete. Synced {len(active_positions)} active positions to {out_path}")

if __name__ == "__main__":
    main()
