import ctypes
import mmap
import time
import os

from utils.shm_types import SpscRingBufferStruct

shm_name = "/hl_l2_book_eth"
size = ctypes.sizeof(SpscRingBufferStruct)

fd = os.open(f"/dev/shm{shm_name}", os.O_RDONLY)
buf = mmap.mmap(fd, size, mmap.MAP_SHARED, mmap.PROT_READ)

while True:
    shm_struct = SpscRingBufferStruct.from_buffer_copy(buf)
    write_idx = shm_struct.write_index
    read_idx = shm_struct.read_index
    dropped = shm_struct.dropped_count
    
    if write_idx > 0:
        latest_slot = (write_idx - 1) % 2048
        snapshot = shm_struct.buffer[latest_slot]
        print(f"WriteIdx: {write_idx}, ReadIdx: {read_idx}, Dropped: {dropped}")
        print(f"  SeqHL: {snapshot.hl_sequence}, SeqPoly: {snapshot.poly_sequence}, OFI: {snapshot.current_ofi:7.4f}, Flow: {snapshot.execution_flow_rate:7.4f}")
        print(f"  Strike: {snapshot.strike_price:.2f}, RotationTS: {snapshot.rotation_ts}")
        print(f"  POLY-UP Ask: {snapshot.poly_up_asks[0].price:.4f} (sz: {snapshot.poly_up_asks[0].size:.2f})")
        print(f"  POLY-DN Ask: {snapshot.poly_down_asks[0].price:.4f} (sz: {snapshot.poly_down_asks[0].size:.2f})")
    else:
        print("SPSC Buffer is empty.")
    time.sleep(1)
