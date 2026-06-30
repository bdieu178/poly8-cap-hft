"""
Synthetic Data Generator: High-Fidelity HFT Simulation
Creates aligned Parquet files with simulated Hawkes singularities for backtest validation.
"""
import os
import polars as pl
import numpy as np
import time

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data', 'realtime')
os.makedirs(DATA_DIR, exist_ok=True)

def generate_synthetic_hft_data(ticks=1000):
    print(f"Generating {ticks} synthetic high-fidelity ticks...")
    
    start_ts = int(time.time() * 1000)
    timestamps = [start_ts + (i * 10) for i in range(ticks)] # 10ms intervals
    
    # 1. Simulate HL Mid Price (Random Walk + Singularity Jumps)
    hl_prices = 65000 + np.cumsum(np.random.normal(0, 0.5, ticks))
    flow_rates = np.random.exponential(10, ticks)
    
    # Inject a "Liquidity Explosion" singularity at mid-point
    singularity_idx = ticks // 2
    hl_prices[singularity_idx:] += 100.0 # Sudden $100 jump
    flow_rates[singularity_idx] = 500.0 # Massive flow rate spike
    
    # 2. Simulate Poly Price (Lagged response to HL)
    poly_prices = 0.55 + (hl_prices - hl_prices[0]) * 0.00001
    # Poly is slower: add 200ms lag
    poly_prices = np.roll(poly_prices, 20) 
    poly_prices[:20] = 0.55

    # 3. Construct DataFrame
    data = []
    for i in range(ticks):
        # Hyperliquid Record
        data.append({
            "source": "hyperliquid",
            "timestamp_ms": timestamps[i],
            "hl_bid_px_0": float(hl_prices[i] - 0.25),
            "hl_ask_px_0": float(hl_prices[i] + 0.25),
            "current_ofi": float(np.random.normal(0, 50)),
            "execution_flow_rate": float(flow_rates[i]),
            "p_max_i": float(hl_prices[i] if i <= singularity_idx else hl_prices[singularity_idx]),
            "event_flags": 1 if i == singularity_idx else 0,
            "hot_path_latency_ns": 150000 # 150us
        })
        
        # Polymarket Record (Every 5th tick to simulate slower book)
        if i % 5 == 0:
            data.append({
                "source": "polymarket",
                "timestamp_ms": timestamps[i],
                "target_bid_price_poly": float(poly_prices[i] - 0.005),
                "target_ask_price_poly": float(poly_prices[i] + 0.005),
                "target_bid_size_poly": 1000.0,
                "target_ask_size_poly": 1000.0,
                "event_type": "order_book"
            })

    df = pl.DataFrame(data)
    out_path = os.path.join(DATA_DIR, "synthetic_high_fidelity_aligned.parquet")
    df.write_parquet(out_path)
    print(f"Synthetic recording saved to {out_path}")

if __name__ == "__main__":
    generate_synthetic_hft_data()
