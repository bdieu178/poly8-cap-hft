import polars as pl
import glob
import os
import sys
import time
from datetime import datetime

def inspect_latest_parquet():
    files = glob.glob("data/realtime/*.parquet")
    if not files:
        print("No Parquet files found in data/realtime/")
        return

    latest_file = max(files, key=os.path.getctime)
    print(f"--- Inspecting Quality: {latest_file} ---")
    
    try:
        df = pl.read_parquet(latest_file)
        print(f"Row count: {len(df)}")
        print(f"Columns: {df.columns}")
        
        # Check for L4 Metrics
        l4_cols = ["bid_concentration", "ask_concentration", "execution_flow_rate", "bid_order_count"]
        missing = [c for c in l4_cols if c not in df.columns]
        if missing:
            print(f"CRITICAL: Missing L4 Columns: {missing}")
        else:
            print("SUCCESS: All L4 columns present.")

        # Data Quality Stats
        print("\n--- Signal Statistics ---")
        stats = df.select([
            pl.col("current_ofi").mean().alias("avg_ofi"),
            pl.col("execution_flow_rate").max().alias("peak_flow"),
            pl.col("bid_concentration").mean().alias("avg_bid_conc"),
            pl.col("hot_path_latency_ns").mean().alias("avg_latency_ns")
        ])
        print(stats)

        # Check for Gaps
        if "timestamp_ms" in df.columns:
            gaps = df.select(
                (pl.col("timestamp_ms") - pl.col("timestamp_ms").shift(1)).alias("gap")
            ).filter(pl.col("gap") > 5000)
            if len(gaps) > 0:
                print(f"WARNING: Found {len(gaps)} gaps > 5 seconds in this recording.")
            else:
                print("SUCCESS: No large timestamp gaps detected.")

    except Exception as e:
        print(f"ERROR reading parquet: {e}")

def report_total_duration():
    files = glob.glob("data/realtime/hft_recording_*.parquet")
    if not files:
        print("No production recordings found.")
        return

    # Sort by name (which includes timestamp) and skip the latest one
    files.sort()
    files_to_process = files[:-1] if len(files) > 1 else files

    print(f"\n--- Cumulative Data Progress ({len(files)} files found) ---")
    try:
        total_duration_ms = 0
        all_timestamps = []
        
        for f in files_to_process:
            try:
                # Use scan_parquet for efficiency
                df_ts = pl.scan_parquet(f).select("timestamp_ms").collect()
                if not df_ts.is_empty():
                    duration = df_ts["timestamp_ms"].max() - df_ts["timestamp_ms"].min()
                    total_duration_ms += duration
                    all_timestamps.append(df_ts["timestamp_ms"].min())
                    all_timestamps.append(df_ts["timestamp_ms"].max())
            except Exception as e:
                # Silently skip corrupted/busy files unless they are all failing
                continue
        
        if not all_timestamps:
            print("No valid timestamps found in files.")
            return

        actual_hours = total_duration_ms / (1000 * 60 * 60)
        start_time_ts = min(all_timestamps)
        end_time_ts = max(all_timestamps)
        
        start_time = datetime.fromtimestamp(start_time_ts / 1000)
        end_time = datetime.fromtimestamp(end_time_ts / 1000)

        print(f"Earliest Data: {start_time} UTC")
        print(f"Latest Data:   {end_time} UTC")
        print(f"Actual Accumulated Duration: {actual_hours:.2f} hours")

        if actual_hours >= 72.0:
            print("✅ TARGET REACHED: 72 hours of high-fidelity data accumulated. Ready for Nautilus Backtest.")
        else:
            remaining = 72.0 - actual_hours
            progress_pct = (actual_hours / 72.0) * 100
            print(f"⏳ IN PROGRESS: {remaining:.2f} hours remaining ({progress_pct:.1f}% complete).")

    except Exception as e:
        print(f"Error calculating duration: {e}")

if __name__ == "__main__":
    inspect_latest_parquet()
    report_total_duration()
