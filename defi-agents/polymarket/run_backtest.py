"""
Nautilus Trader: HFT Backtest Runner
Orchestrates high-fidelity simulation for Polymarket-Hyperliquid Lead-Lag strategies.
"""
import os
from dotenv import load_dotenv
from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.model.enums import OmsType, AccountType
from nautilus_trader.model.identifiers import Venue, InstrumentId
from nautilus_trader.model.currencies import USD
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.objects import Price, Quantity, Money

from utils.nautilus_utils import PolymarketFeeModel
from nautilus_strategy_adapter import HighFidelityHawkesArb, HighFidelityHawkesArbConfig

load_dotenv()

def run_simulation():
    # 1. Setup Engine & Catalog
    catalog_path = os.environ.get("NAUTILUS_CATALOG_PATH", "nautilus_catalog")
    initial_balance = float(os.environ.get("INITIAL_COLLATERAL", "10000.0"))
    
    config = BacktestEngineConfig(trader_id="HFT-REPLAY-MVP")
    engine = BacktestEngine(config=config)
    catalog = ParquetDataCatalog(catalog_path)

    # 2. Add Venues
    engine.add_venue(Venue("POLY"), OmsType.HEDGING, AccountType.MARGIN, [Money(initial_balance, USD)])
    engine.add_venue(Venue("HL"), OmsType.HEDGING, AccountType.MARGIN, [Money(initial_balance, USD)])

    # 3. Load & Add Instruments
    poly_id = InstrumentId.from_str("BTC-UPDOWN-15M.POLY")
    hl_id = InstrumentId.from_str("BTC-PERP.HL")
    
    # These must exist in the catalog (ingested by catalog_ingestion.py)
    poly_inst = catalog.instruments(instrument_ids=[poly_id])[0]
    hl_inst = catalog.instruments(instrument_ids=[hl_id])[0]
    
    engine.add_instrument(poly_inst)
    engine.add_instrument(hl_inst)

    # 4. Assign Custom Fee Model to Polymarket
    # engine.set_fee_model(Venue("POLY"), PolymarketFeeModel(winning_fee_bps=200))

    # 5. Add Strategy
    strat_config = HighFidelityHawkesArbConfig(
        asset_ticker="BTC",
    )
    engine.add_strategy(HighFidelityHawkesArb(config=strat_config))

    # 6. Load Data & Execute
    # We load all ticks for both instruments
    poly_data = catalog.quote_ticks(instrument_ids=[poly_id])
    hl_data = catalog.quote_ticks(instrument_ids=[hl_id])
    
    engine.add_data(poly_data)
    engine.add_data(hl_data)

    print("Starting high-fidelity backtest simulation...")
    engine.run()
    
    # 7. Results
    result = engine.get_result()
    print("\n--- Backtest MVP Report ---")
    print(result)

if __name__ == "__main__":
    run_simulation()
