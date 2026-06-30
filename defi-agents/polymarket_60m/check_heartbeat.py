
import time
import os
import ctypes
from utils.shm_types import L2BookStruct, AccountStateStruct, SpscRingBufferStruct
from utils.shm_utils import POSIXSharedMemory, read_shm_snapshot, read_spsc_ring_buffer_snapshot

def check_heartbeats():
    shm_l2 = None
    shm_acc = None
    try:
        shm_l2 = POSIXSharedMemory(os.environ.get("SHM_NAME", "/hl_l2_book_v2"), ctypes.sizeof(SpscRingBufferStruct))
        shm_acc = POSIXSharedMemory(os.environ.get("ACC_SHM_NAME", "/poly_account_state"), 64)
        
        while True:
            l2 = read_spsc_ring_buffer_snapshot(shm_l2.buf)
            acc = read_shm_snapshot(shm_acc.buf, AccountStateStruct)
            
            hl_age = (time.time() * 1000 - l2.hl_timestamp) / 1000.0
            poly_up_age = (time.time() * 1000 - l2.poly_up_timestamp) / 1000.0
            poly_down_age = (time.time() * 1000 - l2.poly_down_timestamp) / 1000.0
            acc_age = time.time() - acc.last_update_ts
            
            print(f"\r[HEARTBEAT] HL: {hl_age:.2f}s | Poly UP: {poly_up_age:.2f}s | Poly DOWN: {poly_down_age:.2f}s | Acc: {acc_age:.2f}s", end="")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping heartbeat check.")
    finally:
        if shm_l2: shm_l2.close()
        if shm_acc: shm_acc.close()

if __name__ == "__main__":
    check_heartbeats()
