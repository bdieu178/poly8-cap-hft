import mmap
import ctypes
import os

O_CREAT = 0x0040
O_RDWR = 0x0002

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
        ("bid_concentration", ctypes.c_double),
        ("ask_concentration", ctypes.c_double),
    ]

libc = ctypes.CDLL("libc.so.6", use_errno=True)
shm_open = libc.shm_open
shm_open.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
shm_open.restype = ctypes.c_int

def main():
    shm_name = b"/test_shm_alignment"
    fd = shm_open(shm_name, O_CREAT | O_RDWR, 0o666)
    os.ftruncate(fd, ctypes.sizeof(L2BookStruct))
    buf = mmap.mmap(fd, ctypes.sizeof(L2BookStruct))
    book = L2BookStruct.from_buffer(buf)
    
    book.sequence = 12345
    book.current_ofi = 99.9
    book.bid_order_count = 42
    book.best_bid_user = b"0x0000000000000000000000000000000000000000"
    
    # We leave the buffer open and sleep so Rust can read it
    # But since this is a mock script invoked by Rust, we can just write and exit,
    # wait, if we exit, does POSIX shm persist? Yes, until unlinked.
    del book
    buf.close()
    os.close(fd)

if __name__ == "__main__":
    main()
