import ctypes
import mmap
import os
from utils.shm_types import L2BookStruct, AccountStateStruct, CognitionStateStruct, SpscRingBufferStruct

# POSIX Shared Memory Constants
O_CREAT = 0x0040
O_RDWR = 0x0002

libc = ctypes.CDLL("libc.so.6", use_errno=True)
shm_open = libc.shm_open
shm_open.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
shm_open.restype = ctypes.c_int

shm_unlink = libc.shm_unlink
shm_unlink.argtypes = [ctypes.c_char_p]
shm_unlink.restype = ctypes.c_int

class POSIXSharedMemory:
    def __init__(self, name, size):
        if not name.startswith('/'):
            name = '/' + name
        self.name = name.encode('utf-8')
        self.size = size
        
        # Try opening existing first
        self.fd = shm_open(self.name, O_RDWR, 0o666)
        if self.fd < 0:
            # If not found, create it
            self.fd = shm_open(self.name, O_CREAT | O_RDWR, 0o666)
            if self.fd < 0:
                raise OSError(f"Failed to open or create SHM segment {name}: errno {ctypes.get_errno()}")
        
        # Ensure size is correct (ftruncate)
        os.ftruncate(self.fd, self.size)
        self.buf = mmap.mmap(self.fd, self.size)

    def close(self):
        try:
            if hasattr(self, 'buf') and self.buf:
                self.buf.close()
            if hasattr(self, 'fd') and self.fd >= 0:
                os.close(self.fd)
        except BufferError:
            # Pointers still exist, common in HFT hot-paths
            pass

    def unlink(self):
        shm_unlink(self.name)

def read_shm_snapshot(shm_buf, struct_class):
    """Read a consistent snapshot from the seqlock-protected shared memory."""
    struct_size = ctypes.sizeof(struct_class)
    buf = memoryview(shm_buf)
    
    while True:
        # 1. Read sequence before
        seq1 = ctypes.c_uint64.from_buffer(buf[:8]).value
        if seq1 % 2 != 0:
            # Writer is currently writing, busy wait
            continue
            
        # 2. Copy the whole struct
        snapshot = struct_class.from_buffer_copy(buf[:struct_size])
        
        # 3. Read sequence after
        seq2 = ctypes.c_uint64.from_buffer(buf[:8]).value
        
        # 4. Validate
        if seq1 == seq2:
            return snapshot

def read_spsc_ring_buffer_snapshot(shm_buf):
    """Read the latest written snapshot from the SpscRingBuffer."""
    buf = memoryview(shm_buf)
    write_index = ctypes.c_uint64.from_buffer(buf[:8]).value
    if write_index == 0:
        return L2BookStruct()
        
    slot_idx = (write_index - 1) % 2048
    offset = 128 + slot_idx * 1280
    return L2BookStruct.from_buffer_copy(buf[offset : offset + 1280])

