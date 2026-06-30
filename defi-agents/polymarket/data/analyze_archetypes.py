import duckdb
import pandas as pd

con = duckdb.connect("/home/bdieu178/user/defi-agents/polymarket/data/analytics.duckdb")

query = """
WITH raw_diff AS (
    SELECT 
        timestamp_ms,
        (timestamp_ms / 60000) AS minute_bin,
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
        (LAST(p_theo_up ORDER BY timestamp_ms) - FIRST(p_theo_up ORDER BY timestamp_ms)) as net_p_change,
        SUM(p_travel) as total_p_travel,
        COUNT(*) as tick_count
    FROM raw_diff
    GROUP BY minute_bin, asset
),
classified_bins AS (
    SELECT *,
        CASE
            WHEN max_intensity > 50 AND total_p_travel > 0.40 AND ABS(net_p_change) < 0.15 THEN 'Volatility Ping-Pong'
            WHEN max_intensity > 50 AND ABS(net_p_change) > 0.15 AND total_p_travel < ABS(net_p_change) * 1.8 THEN 'Flash Squeeze'
            WHEN avg_intensity > 25 AND ABS(net_p_change) > 0.10 AND total_p_travel < ABS(net_p_change) * 2.5 THEN 'Macro Bleed'
            WHEN avg_spread > 0.015 AND max_p - min_p > 0.10 AND total_p_travel > 0.15 AND ABS(net_p_change) < 0.10 THEN 'Absorption Reversal'
            WHEN max_intensity < 40 AND max_p - min_p < 0.15 THEN 'Sideways Chop'
            ELSE 'Unclassified / Mixed Volatility'
        END AS archetype
    FROM minute_bins
)
SELECT 
    archetype, 
    COUNT(*) as total_minutes, 
    ROUND(AVG(avg_intensity), 2) as mean_intensity, 
    ROUND(AVG(max_spread), 3) as mean_max_spread
FROM classified_bins
GROUP BY archetype
ORDER BY total_minutes DESC;
"""

print(con.execute(query).fetchdf())
