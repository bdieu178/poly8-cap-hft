"""
Nautilus Trader: Instrument Definitions for BTC & ETH
Initializes the catalog with standard contract specifications for HL and Poly.
"""
from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.instruments import TokenizedAsset, CryptoPerpetual
from nautilus_trader.model.enums import AssetClass, PriceType
from nautilus_trader.persistence.catalog import ParquetDataCatalog

def create_instruments():
    catalog = ParquetDataCatalog("nautilus_catalog")
    
    # 1. Polymarket BTC-UPDOWN Binary (Tokenized Asset)
    poly_btc = TokenizedAsset(
        instrument_id=InstrumentId.from_str("BTC-UPDOWN-15M.POLY"),
        raw_symbol=Symbol("BTC-UPDOWN-15M"),
        asset_class=AssetClass.EQUITY,
        base_currency=USD,
        quote_currency=USD,
        price_precision=2,
        size_precision=2,
        price_increment=Price.from_str("0.01"),
        size_increment=Quantity.from_str("0.01"),
        ts_event=0,
        ts_init=0,
        lot_size=Quantity.from_int(1),
    )
    
    # 2. Hyperliquid BTC-PERP
    hl_btc = CryptoPerpetual(
        instrument_id=InstrumentId.from_str("BTC-PERP.HL"),
        raw_symbol=Symbol("BTC-PERP"),
        base_currency=USD,
        quote_currency=USD,
        settlement_currency=USD,
        is_inverse=False,
        price_precision=2,
        size_precision=4,
        price_increment=Price.from_str("0.10"),
        size_increment=Quantity.from_str("0.0001"),
        ts_event=0,
        ts_init=0,
        multiplier=Quantity.from_int(1),
        lot_size=Quantity.from_str("0.0001"),
    )
    
    catalog.write_data([poly_btc, hl_btc])
    print("Instruments successfully written to catalog.")

if __name__ == "__main__":
    create_instruments()
