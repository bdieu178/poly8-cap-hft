
import os
import time
import subprocess
import ctypes
import mmap

ASSET = os.environ.get("ASSET", "eth")
SHM_NAME = f"/hl_l2_book_{ASSET}"
SHM_SIZE = 1280
LATENCY_OFFSET = 1024 # Bytes

def get_process_stats(name, namespace=None):
    """Get CPU/Mem stats for a process, optionally in a network namespace."""
    cmd = []
    if namespace:
        cmd = ["sudo", "ip", "netns", "exec", namespace, "ps", "aux"]
    else:
        cmd = ["ps", "aux"]
    
    try:
        output = subprocess.check_output(cmd).decode()
        for line in output.splitlines():
            if name in line and "grep" not in line:
                parts = line.split()
                return {"cpu": parts[2], "mem": parts[3], "pid": parts[1]}
    except:
        pass
    return None

def get_throughput(log_path):
    """Calculate avg ticks per minute from the last few flushes."""
    try:
        # Use sudo for logs as they are root-owned in production
        cmd = ["sudo", "tail", "-n", "20", log_path]
        output = subprocess.check_output(cmd).decode()
        flushes = []
        for line in output.splitlines():
            if "Flushed" in line:
                try:
                    # Line format: ... Flushed 2102 ticks to ...
                    count = int(line.split("Flushed")[1].split()[0])
                    flushes.append(count)
                except:
                    continue
        if flushes:
            return sum(flushes) / len(flushes)
    except:
        pass
    return 0

def get_latency():
    """Read hot-path latency from Shared Memory."""
    try:
        libc = ctypes.CDLL("libc.so.6")
        fd = libc.shm_open(SHM_NAME.encode(), 0, 0)
        if fd == -1: return None
        
        buf = mmap.mmap(fd, SHM_SIZE, mmap.MAP_SHARED, mmap.PROT_READ)
        # Use from_buffer_copy to avoid writable requirement
        latency_bytes = buf[LATENCY_OFFSET : LATENCY_OFFSET + 8]
        latency_ns = int.from_bytes(latency_bytes, "little")
        return latency_ns
    except:
        return None

def main():
    print(f"--- HFT Pipeline Performance Monitor ---")
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    
    # 1. Process Health
    tapreader = get_process_stats("unified_ingestor", namespace=None)
    harvester = get_process_stats("historical_bulk_harvester.py")
    
    print("\n[Process Status]")
    if tapreader:
        print(f"TapReader:           PID {tapreader['pid']}, CPU {tapreader['cpu']}%, MEM {tapreader['mem']}%")
    else:
        print("TapReader: NOT RUNNING")
        
    if harvester:
        print(f"Harvester:           PID {harvester['pid']}, CPU {harvester['cpu']}%, MEM {harvester['mem']}%")
    else:
        print("Harvester: NOT RUNNING")
    
    # 2. Throughput
    log_path = "/home/user/defi-agents/polymarket/logs/harvester.log"
    avg_ticks = get_throughput(log_path)
    print(f"\n[Throughput]")
    print(f"Avg Ticks per Flush: {avg_ticks:.2f}")
    
    # 3. Latency
    latency_ns = get_latency()
    print(f"\n[Latency]")
    if latency_ns is not None:
        print(f"Hot-Path Latency:    {latency_ns / 1_000_000:.4f} ms ({latency_ns} ns)")
    else:
        print("Hot-Path Latency:    Unable to read SHM")
    
    print("-" * 40)

if __name__ == "__main__":
    main()
