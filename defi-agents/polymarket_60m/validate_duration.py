import polars as pl
import glob
import os

def validate_actual_duration():
    files = sorted(glob.glob("/home/user/defi-agents/polymarket/data/realtime/*.parquet"))
    if not files:
        print("No files found.")
        return

    total_duration_ms = 0
    file_count = 0
    
    for f in files:
        try:
            # Use scan_parquet for efficiency
            df = pl.scan_parquet(f).select("timestamp_ms").collect()
            if not df.is_empty():
                duration = df["timestamp_ms"].max() - df["timestamp_ms"].min()
                total_duration_ms += duration
                file_count += 1
        except Exception as e:
            print(f"Error processing {f}: {e}")

    total_hours = total_duration_ms / (1000 * 60 * 60)
    print(f"Total files processed: {file_count}")
    print(f"Actual accumulated duration (sum of files): {total_hours:.2f} hours")
    
    # Check the span for comparison
    try:
        first_ts = pl.scan_parquet(files[0]).select("timestamp_ms").collect()["timestamp_ms"].min()
        last_ts = pl.scan_parquet(files[-1]).select("timestamp_ms").collect()["timestamp_ms"].max()
        span_hours = (last_ts - first_ts) / (1000 * 60 * 60)
        print(f"Wall-clock span (first to last timestamp): {span_hours:.2f} hours")
    except:
        pass

if __name__ == "__main__":
    validate_actual_duration()
