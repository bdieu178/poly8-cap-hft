"""
TKG Builder (Quant Researcher Agent)
Analyzes Cold Path Parquet files, updates the TKG, and emits state to Shared Memory.
"""
import os
import time
import ctypes
import polars as pl
from multiprocessing import shared_memory
from graph_db import TemporalKnowledgeGraph
import sys

# Append parent dir to path to import utils
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import get_logger

logger = get_logger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'realtime')

class CognitionStateStruct(ctypes.Structure):
    _fields_ = [
        ("sequence", ctypes.c_uint64),
        ("regime_multiplier", ctypes.c_double),
        ("regime_state_enum", ctypes.c_uint32),
    ]

def analyze_and_update():
    tkg = TemporalKnowledgeGraph(db_path=os.path.join(os.path.dirname(__file__), "..", "data", "cognition", "tkg.gpickle"))
    
    # 1. Analyze Cold Path
    # In a real scenario, this would load the latest parquet files
    # For demonstration, we'll simulate analyzing recent OFI variance
    logger.info("QuantResearcher: Analyzing recent Parquet data for regime shifts...")
    
    # Simulated regime identification based on "data"
    # Regime 0: Normal (1.0x), Regime 1: High Vol / Herding (2.0x)
    current_time = int(time.time() * 1000)
    
    # Example logic: Toggling regime every run for demonstration
    prev_regime = tkg.get_current_regime()
    new_enum = 1 if (not prev_regime or prev_regime['regime_enum'] == 0) else 0
    new_multiplier = 2.0 if new_enum == 1 else 1.0
    
    metrics = {
        "ofi_variance": 500.0 if new_enum == 1 else 100.0,
        "hawkes_baseline": 0.5
    }
    
    # 2. Update TKG
    tkg.add_regime_state(current_time, new_enum, new_multiplier, metrics)
    tkg.save()
    logger.info(f"QuantResearcher: TKG Updated. New Regime -> Enum: {new_enum}, Multiplier: {new_multiplier}x")
    
    # 3. Emit State to Shared Memory
    shm_name = "/hl_cognition_state"
    try:
        shm = shared_memory.SharedMemory(name=shm_name, create=False)
    except FileNotFoundError:
        # Create it if Rust hasn't (or if we're running isolated)
        shm = shared_memory.SharedMemory(name=shm_name, create=True, size=ctypes.sizeof(CognitionStateStruct))
        
    try:
        # Avoid BufferError from ctypes holding the memoryview
        # We'll read the first 8 bytes for the sequence
        import struct
        current_seq_bytes = bytes(shm.buf[:8])
        seq = struct.unpack("Q", current_seq_bytes)[0]
        
        # Construct the new struct in pure Python memory
        new_struct = CognitionStateStruct(
            sequence=seq + 2,
            regime_multiplier=new_multiplier,
            regime_state_enum=new_enum
        )
        
        # Copy the bytes directly into the shared memory buffer
        shm.buf[:ctypes.sizeof(CognitionStateStruct)] = bytes(new_struct)
        logger.info("QuantResearcher: Successfully injected new regime into Shared Memory hot-path.")
        
    finally:
        shm.close()

if __name__ == "__main__":
    analyze_and_update()
