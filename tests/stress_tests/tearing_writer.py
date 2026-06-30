import os
import ctypes
import time
import subprocess
import signal

# Mock L2BookStruct for testing
class PriceLevel(ctypes.Structure):
    _fields_ = [("price", ctypes.c_double), ("size", ctypes.c_double)]

class L2BookStruct(ctypes.Structure):
    _fields_ = [
        ("sequence", ctypes.c_uint64),
        ("hl_timestamp", ctypes.c_uint64),
        ("hl_bids", PriceLevel * 10),
        ("hl_asks", PriceLevel * 10),
    ]

# Setup Atomic Bridge
SHM_BARRIER_PATH = "/tmp/shm_barrier.so"
libbarrier = ctypes.CDLL(SHM_BARRIER_PATH)
atomic_store_release = libbarrier.atomic_store_release
atomic_store_release.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_uint64]

def set_seq_atomic(struct_ptr, val):
    ptr = ctypes.cast(ctypes.addressof(struct_ptr), ctypes.POINTER(ctypes.c_uint64))
    atomic_store_release(ptr, val)

# Setup SHM
libc = ctypes.CDLL("libc.so.6", use_errno=True)
shm_open = libc.shm_open
shm_open.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
shm_open.restype = ctypes.c_int
ftruncate = libc.ftruncate
ftruncate.argtypes = [ctypes.c_int, ctypes.c_long]
mmap = libc.mmap
mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]
mmap.restype = ctypes.c_void_p

SHM_NAME = b"/test_atomic_tearing"
fd = shm_open(SHM_NAME, 0x42, 0o666) # O_RDWR | O_CREAT
ftruncate(fd, ctypes.sizeof(L2BookStruct))
ptr = mmap(None, ctypes.sizeof(L2BookStruct), 1 | 2, 1, fd, 0) # PROT_READ | PROT_WRITE, MAP_SHARED

book = L2BookStruct.from_address(ptr)
book.sequence = 0

print("Starting Atomic Tearing Writer...")
try:
    val = 1.0
    for i in range(2000000):
        seq = book.sequence
        set_seq_atomic(book, seq + 1)
        
        # Fill all levels with the same value to detect tearing
        for j in range(10):
            book.hl_bids[j].price = val
            book.hl_bids[j].size = val
            
        set_seq_atomic(book, seq + 2)
        val += 1.0
        if i % 500000 == 0:
            print(f"Writer progress: {i} updates...")
finally:
    print("Writer stopping.")
