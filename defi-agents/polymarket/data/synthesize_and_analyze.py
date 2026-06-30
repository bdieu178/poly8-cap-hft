import numpy as np
import pandas as pd
import duckdb
import time

print("Synthesizing 7-day historical dataset...")
np.random.seed(42)

# 7 days of data, 1 tick per 2 seconds to keep size manageable (~300k rows)
num_days = 7
ticks_per_min = 30
total_minutes = num_days * 24 * 60
total_rows = total_minutes * ticks_per_min

start_ts = int(time.time() * 1000) - (num_days * 24 * 3600 * 1000)
timestamps = np.arange(start_ts, start_ts + total_rows * 2000, 2000)

df = pd.DataFrame({'timestamp_ms': timestamps})
df['asset'] = 'btc'
df['strike_price'] = 65000.0
df['q_up'] = 0.0
df['q_down'] = 0.0
df['equity'] = 1000.0

# Base parameters
l4_intensity = np.random.normal(20, 5, total_rows)
p_theo_up = np.zeros(total_rows)
p_theo_up[0] = 0.50
spread = np.random.normal(0.01, 0.002, total_rows)

# Generate base random walk
rw = np.random.normal(0, 0.001, total_rows)
p_theo_up = 0.50 + np.cumsum(rw)
p_theo_up = np.clip(p_theo_up, 0.10, 0.90)

# Inject Archetypes into minute chunks
minutes_array = np.arange(total_minutes)
np.random.shuffle(minutes_array)

# Archetype distribution
chop_mins = int(total_minutes * 0.84)
mixed_mins = int(total_minutes * 0.10)
bleed_mins = int(total_minutes * 0.03)
squeeze_mins = int(total_minutes * 0.02)
pingpong_mins = int(total_minutes * 0.01)

def apply_archetype(mins_subset, intensity_val, spread_val, p_shift_func):
    for m in mins_subset:
        start_idx = m * ticks_per_min
        end_idx = start_idx + ticks_per_min
        l4_intensity[start_idx:end_idx] = np.random.normal(intensity_val, intensity_val*0.2, ticks_per_min)
        spread[start_idx:end_idx] = np.random.normal(spread_val, spread_val*0.1, ticks_per_min)
        p_theo_up[start_idx:end_idx] += p_shift_func()

idx = 0
# Sideways Chop (already base, just ensure it's tight)
chop_indices = minutes_array[idx:idx+chop_mins]
idx += chop_mins

# Mixed
mixed_indices = minutes_array[idx:idx+mixed_mins]
apply_archetype(mixed_indices, 60, 0.02, lambda: np.random.normal(0, 0.05, ticks_per_min))
idx += mixed_mins

# Macro Bleed (Continuous drop)
bleed_indices = minutes_array[idx:idx+bleed_mins]
apply_archetype(bleed_indices, 40, 0.03, lambda: np.linspace(0, -0.25, ticks_per_min))
idx += bleed_mins

# Flash Squeeze (Sudden spike and hold/drop)
squeeze_indices = minutes_array[idx:idx+squeeze_mins]
def squeeze_shift():
    s = np.zeros(ticks_per_min)
    s[5:15] = np.linspace(0, 0.35, 10)
    s[15:] = 0.35
    return s
apply_archetype(squeeze_indices, 120, 0.04, squeeze_shift)
idx += squeeze_mins

# Volatility Ping Pong (Massive up and down)
pingpong_indices = minutes_array[idx:idx+pingpong_mins]
def pingpong_shift():
    s = np.zeros(ticks_per_min)
    s[0:10] = np.linspace(0, -0.40, 10)
    s[10:20] = np.linspace(-0.40, 0.40, 10)
    s[20:30] = np.linspace(0.40, 0, 10)
    return s
apply_archetype(pingpong_indices, 200, 0.10, pingpong_shift)

# Assign arrays back
df['l4_intensity'] = l4_intensity
df['p_theo_up'] = np.clip(p_theo_up, 0.01, 0.99)
df['p_theo_down'] = 1.0 - df['p_theo_up']
spread = np.clip(spread, 0.01, 0.20)
df['p_market_up_ask'] = df['p_theo_up'] + spread/2
df['p_market_up_bid'] = df['p_theo_up'] - spread/2
df['p_market_down_ask'] = df['p_theo_down'] + spread/2
df['p_market_down_bid'] = df['p_theo_down'] - spread/2

print("Writing to Parquet...")
df.to_parquet('/home/bdieu178/user/defi-agents/polymarket/data/synthetic_history.parquet')

print("Importing into DuckDB...")
con = duckdb.connect("/home/bdieu178/user/defi-agents/polymarket/data/analytics.duckdb")
con.execute("DROP TABLE IF EXISTS telemetry;")
con.execute("CREATE TABLE telemetry AS SELECT * FROM read_parquet('/home/bdieu178/user/defi-agents/polymarket/data/synthetic_history.parquet');")

print("Running corrected segmentation analysis...")
query = """
WITH raw_diff AS (
    SELECT 
        timestamp_ms,
        CAST(timestamp_ms / 60000 AS BIGINT) AS minute_bin,
        asset,
        p_theo_up,
        l4_intensity,
        (p_market_up_ask - p_market_up_bid) AS spread,
        ABS(p_theo_up - LAG(p_theo_up) OVER (PARTITION BY asset ORDER BY timestamp_ms)) AS p_travel
    FROM telemetry
),
minute_bins AS (
    SELECT 
        minute_bin,
        asset,
        MIN(p_theo_up) as min_p,
        MAX(p_theo_up) as max_p,
        AVG(l4_intensity) as avg_intensity,
        MAX(l4_intensity) as max_intensity,
        AVG(spread) as avg_spread,
        MAX(spread) as max_spread,
        ABS(LAST(p_theo_up ORDER BY timestamp_ms) - FIRST(p_theo_up ORDER BY timestamp_ms)) as net_p_change,
        SUM(COALESCE(p_travel, 0)) as total_p_travel,
        COUNT(*) as tick_count
    FROM raw_diff
    GROUP BY minute_bin, asset
),
classified_bins AS (
    SELECT *,
        CASE
            WHEN max_intensity > 150 AND total_p_travel > 0.60 THEN 'Volatility Ping-Pong'
            WHEN max_intensity > 90 AND max_p - min_p > 0.25 AND total_p_travel < 0.60 THEN 'Flash Squeeze'
            WHEN avg_intensity > 30 AND avg_intensity <= 60 AND net_p_change > 0.15 THEN 'Macro Bleed'
            WHEN max_intensity < 35 AND max_spread < 0.02 AND max_p - min_p < 0.10 THEN 'Sideways Chop'
            ELSE 'Unclassified / Mixed Volatility'
        END AS archetype
    FROM minute_bins
)
SELECT 
    archetype, 
    COUNT(*) as total_minutes, 
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM minute_bins), 2) as percentage,
    ROUND(AVG(avg_intensity), 2) as mean_intensity, 
    ROUND(AVG(total_p_travel), 3) as mean_p_travel,
    ROUND(AVG(max_spread), 3) as mean_max_spread
FROM classified_bins
GROUP BY archetype
ORDER BY total_minutes DESC;
"""

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)
result = con.execute(query).fetchdf()
print(result)
