import time
import ctypes
from multiprocessing import shared_memory
import sys
import os

# Align with L2BookStruct in live_tapreader.py
MAX_LEVELS = 10
class PriceLevel(ctypes.Structure):
    _fields_ = [("price", ctypes.c_double), ("size", ctypes.c_double)]

class L2BookStruct(ctypes.Structure):
    _fields_ = [
        ("sequence", ctypes.c_uint64),
        ("hl_timestamp", ctypes.c_uint64),
        ("hl_bids", PriceLevel * MAX_LEVELS),
        ("hl_asks", PriceLevel * MAX_LEVELS),
        ("poly_timestamp", ctypes.c_uint64),
        ("poly_bids", PriceLevel * MAX_LEVELS),
        ("poly_asks", PriceLevel * MAX_LEVELS),
        # ... rest of struct ...
    ]

def check_freshness():
    shm_name = "hl_l2_book_v2"
    try:
        shm = shared_memory.SharedMemory(name=shm_name)
    except FileNotFoundError:
        print(f"FAILED: Shared memory {shm_name} not found.")
        sys.exit(1)

    buf = shm.buf
    
    print(f"Monitoring SHM: {shm_name} for 10 seconds...")
    
    start_time = time.time()
    initial_hl_ts = ctypes.c_uint64.from_buffer(buf[8:16]).value
    initial_poly_ts = ctypes.c_uint64.from_buffer(buf[336:344]).value # Offset for poly_timestamp
    
    hl_updated = False
    poly_updated = False
    
    while time.time() - start_time < 10:
        curr_hl_ts = ctypes.c_uint64.from_buffer(buf[8:16]).value
        curr_poly_ts = ctypes.c_uint64.from_buffer(buf[336:344]).value
        
        if curr_hl_ts > initial_hl_ts:
            hl_updated = True
        if curr_poly_ts > initial_poly_ts:
            poly_updated = True
            
        if hl_updated and poly_updated:
            break
        time.sleep(0.5)

    shm.close()
    
    if hl_updated and poly_updated:
        print("SUCCESS: Both Hyperliquid and Polymarket feeds are actively updating SHM.")
        sys.exit(0)
    else:
        if not hl_updated:
            print("FAILED: Hyperliquid timestamp is STALE.")
        if not poly_updated:
            print("FAILED: Polymarket timestamp is STALE.")
        sys.exit(1)

if __name__ == "__main__":
    check_freshness()
