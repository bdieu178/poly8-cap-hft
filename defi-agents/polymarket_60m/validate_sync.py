"""
Validation & Drift Analysis Script
"""
import os
import polars as pl
import matplotlib.pyplot as plt
from utils.logger import get_logger

logger = get_logger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data', 'historical')

def analyze_drift():
    file_path = os.path.join(DATA_DIR, "aligned_historical_20260401_20260424.parquet")
    
    if not os.path.exists(file_path):
        logger.info(f"No data file found at {file_path}")
        return

    df = pl.read_parquet(file_path)
    
    logger.info("--- Drift Analysis ---")
    # 1. Clock Drift: Diff between updates (mock)
    df = df.with_columns([
        (pl.col("timestamp_ms").diff()).alias("time_gap_ms")
    ])
    
    avg_gap = df["time_gap_ms"].mean()
    logger.info(f"Average time gap between events: {avg_gap} ms")
    
    # 2. Flag gaps where FFill exceeds 5 consecutive seconds
    large_gaps = df.filter(pl.col("time_gap_ms") > 5000)
    logger.info(f"Identified {len(large_gaps)} instances where gap > 5 seconds.")
    
    # 3. Price Discovery Lead/Lag (Polymarket vs Hyperliquid Mid-Price)
    # We can plot this
    df = df.with_columns([
        ((pl.col("target_bid_price_poly") + pl.col("target_ask_price_poly")) / 2).alias("poly_mid"),
        ((pl.col("hl_bid_px_0") + pl.col("hl_ask_px_0")) / 2).alias("hl_mid")
    ])
    
    logger.info("Analysis complete. Check plots (mocked).")
    
    # Optionally save plots
    plt.figure(figsize=(10, 5))
    plt.plot(df['timestamp_ms'], df['poly_mid'], label='Poly Mid')
    # plt.plot(df['timestamp_ms'], df['hl_mid'], label='HL Mid') # Scales differ drastically (0.5 vs 65000)
    plt.legend()
    plt.title("Price Discovery Lead/Lag")
    plt.savefig(os.path.join(DATA_DIR, "price_discovery.png"))

if __name__ == "__main__":
    analyze_drift()
