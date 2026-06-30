
import polars as pl
import os
import glob
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity

class ParquetToNautilusDataConverter:
    """
    Converts Dual-Venue HFT Parquet recordings into Nautilus QuoteTicks.
    Maps L4 signals (OFI, Flow) into QuoteTick fields for strategy replay.
    """
    def __init__(self, asset_ticker="BTC"):
        self.asset_ticker = asset_ticker.upper()
        self.hl_id = InstrumentId.from_str(f"{self.asset_ticker}-PERP.HL")
        self.poly_up_id = InstrumentId.from_str(f"{self.asset_ticker}-UP.POLY")
        self.poly_down_id = InstrumentId.from_str(f"{self.asset_ticker}-DOWN.POLY")

    def convert_file(self, parquet_path):
        df = pl.read_parquet(parquet_path)
        ticks = []
        
        # We sort by timestamp to ensure chronological replay
        df = df.sort("timestamp_ms")
        
        for row in df.to_dicts():
            ts_ns = int(row["timestamp_ms"] * 1_000_000)
            
            if row["source"] == "hyperliquid":
                # Latency-Aware Backtest: ts_init = ts_event + measurement_latency
                latency = int(row.get("hot_path_latency_ns", 0) or 0)
                ts_init = ts_ns + latency
                
                # Encode OFI and Flow into sizes for the adapter
                # bid_size = abs(OFI), ask_size = Flow Rate
                # Ensure consistent and valid precision (max 8 decimal places)
                tick = QuoteTick(
                    instrument_id=self.hl_id,
                    bid_price=Price.from_str(f"{row['hl_bid_px_0'] or 0:.2f}"),
                    ask_price=Price.from_str(f"{row['hl_ask_px_0'] or 0:.2f}"),
                    bid_size=Quantity.from_str(f"{abs(row['current_ofi'] or 0):.4f}"),
                    ask_size=Quantity.from_str(f"{row['execution_flow_rate'] or 0:.4f}"),
                    ts_event=ts_ns,
                    ts_init=ts_init
                )
                ticks.append(tick)
            
            elif row["source"] == "polymarket":
                latency = int(row.get("hot_path_latency_ns", 0) or 0)
                ts_init = ts_ns + latency
                
                # Use bifurcated IDs based on the recorded outcome
                outcome_val = row.get("outcome")
                if not outcome_val:
                    outcome_val = "up"
                outcome = outcome_val.lower()
                poly_id = self.poly_up_id if outcome == "up" else self.poly_down_id
                
                tick = QuoteTick(
                    instrument_id=poly_id,
                    bid_price=Price.from_str(f"{row['poly_bid_px_0'] or 0:.4f}"),
                    ask_price=Price.from_str(f"{row['poly_ask_px_0'] or 0:.4f}"),
                    bid_size=Quantity.from_str(f"{row['poly_bid_sz_0'] or 0:.4f}"),
                    ask_size=Quantity.from_str(f"{row['poly_ask_sz_0'] or 0:.4f}"),
                    ts_event=ts_ns,
                    ts_init=ts_init
                )
                ticks.append(tick)
        
        # Nautilus requires ts_init to be monotonic
        ticks.sort(key=lambda x: x.ts_init)
        
        return ticks

if __name__ == "__main__":
    # Example usage / Test
    converter = ParquetToNautilusDataConverter()
    print("Converter initialized. Ready for batch processing of 72h dataset.")
