import os
import mmap
import ctypes
import time

# Mirroring L2BookStruct from C++
class PriceLevel(ctypes.Structure):
    _fields_ = [("price", ctypes.c_double), ("size", ctypes.c_double)]

MAX_LEVELS = 10

class L2BookStruct(ctypes.Structure):
    _fields_ = [
        ("sequence", ctypes.c_uint64),
        ("hl_timestamp", ctypes.c_uint64),
        ("hl_bids", PriceLevel * MAX_LEVELS),
        ("hl_asks", PriceLevel * MAX_LEVELS),
        ("poly_timestamp", ctypes.c_uint64),
        ("poly_bids", PriceLevel * MAX_LEVELS),
        ("poly_asks", PriceLevel * MAX_LEVELS),
        ("current_ofi", ctypes.c_double),
        ("execution_flow_rate", ctypes.c_double),
        ("p_max_i", ctypes.c_double),
        ("event_flags", ctypes.c_uint32),
        ("padding0", ctypes.c_uint32),
        ("last_event_ts", ctypes.c_uint64),
        ("regime_multiplier", ctypes.c_double),
        ("regime_state_enum", ctypes.c_uint32),
        ("padding1", ctypes.c_uint32),
        ("last_update_local_ns", ctypes.c_uint64),
        ("hot_path_latency_ns", ctypes.c_uint64),
        # --- L4 Extensions ---
        ("hl_l4_height", ctypes.c_uint64),
        ("best_bid_oid", ctypes.c_uint64),
        ("best_bid_user", ctypes.c_char * 42),
        ("padding_bid", ctypes.c_uint8 * 6),
        ("best_bid_ts", ctypes.c_uint64),
        ("best_ask_oid", ctypes.c_uint64),
        ("best_ask_user", ctypes.c_char * 42),
        ("padding_ask", ctypes.c_uint8 * 6),
        ("best_ask_ts", ctypes.c_uint64),
        ("bid_order_count", ctypes.c_uint32),
        ("ask_order_count", ctypes.c_uint32),
        ("whale_bid_size", ctypes.c_double),
        ("whale_ask_size", ctypes.c_double),
    ]

def read_shm(shm_path="/dev/shm/hl_l2_book_v2"):
    print(f"Using SHM at {shm_path}, Struct Size: {ctypes.sizeof(L2BookStruct)}")
    
    with open(shm_path, "r+b") as f:
        mm = mmap.mmap(f.fileno(), ctypes.sizeof(L2BookStruct))
        book = L2BookStruct.from_buffer(mm)
        
        while True:
            # SeqLock read pattern
            s1 = book.sequence
            if s1 % 2 != 0:
                continue
            
            ts = book.hl_timestamp
            ofi = book.current_ofi
            bid0_px = book.hl_bids[0].price
            poly_bid0_px = book.poly_bids[0].price
            
            s2 = book.sequence
            if s1 != s2:
                continue
                
            print(f"[{ts}] OFI: {ofi:7.2f} | HL Bid0: {bid0_px:8.2f} | Poly Bid0: {poly_bid0_px:5.4f}")
            time.sleep(0.5)

if __name__ == "__main__":
    read_shm()
