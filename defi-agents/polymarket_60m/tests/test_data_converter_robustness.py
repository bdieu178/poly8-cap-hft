import unittest
import os
import polars as pl
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.test_kit.providers import TestInstrumentProvider

# Add project root to path to allow imports
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from nautilus_data_converter import ParquetToNautilusDataConverter

class TestDataConverterRobustness(unittest.TestCase):
    def setUp(self):
        self.converter = ParquetToNautilusDataConverter(asset_ticker="TEST")
        self.test_dir = "/tmp/test_converter_data"
        os.makedirs(self.test_dir, exist_ok=True)

    def tearDown(self):
        for f in os.listdir(self.test_dir):
            os.remove(os.path.join(self.test_dir, f))
        os.rmdir(self.test_dir)

    def create_mock_parquet(self, file_name, data):
        df = pl.DataFrame(data)
        path = os.path.join(self.test_dir, file_name)
        df.write_parquet(path)
        return path

    def test_handles_missing_outcome_field(self):
        """
        If 'outcome' is missing, it should default to 'up' as per the implementation.
        """
        path = self.create_mock_parquet("missing_outcome.parquet", [
            {"source": "polymarket", "timestamp_ms": 1000, "poly_bid_px_0": 0.5, "poly_ask_px_0": 0.51, "poly_bid_sz_0": 10, "poly_ask_sz_0": 10},
        ])
        
        ticks = self.converter.convert_file(path)
        
        self.assertEqual(len(ticks), 1)
        self.assertEqual(ticks[0].instrument_id, self.converter.poly_up_id)

    def test_handles_null_outcome_field(self):
        """
        If 'outcome' is null, it should also default to 'up'.
        """
        path = self.create_mock_parquet("null_outcome.parquet", [
            {"source": "polymarket", "timestamp_ms": 1000, "poly_bid_px_0": 0.5, "poly_ask_px_0": 0.51, "poly_bid_sz_0": 10, "poly_ask_sz_0": 10, "outcome": None},
        ])
        
        ticks = self.converter.convert_file(path)
        
        self.assertEqual(len(ticks), 1)
        self.assertEqual(ticks[0].instrument_id, self.converter.poly_up_id)

    def test_correctly_assigns_up_and_down_instruments(self):
        """
        Verifies that 'up' and 'down' outcomes are assigned to the correct instrument IDs.
        """
        path = self.create_mock_parquet("mixed_outcomes.parquet", [
            {"source": "polymarket", "timestamp_ms": 1000, "poly_bid_px_0": 0.5, "poly_ask_px_0": 0.51, "poly_bid_sz_0": 10, "poly_ask_sz_0": 10, "outcome": "up"},
            {"source": "polymarket", "timestamp_ms": 1001, "poly_bid_px_0": 0.49, "poly_ask_px_0": 0.50, "poly_bid_sz_0": 10, "poly_ask_sz_0": 10, "outcome": "down"},
        ])
        
        ticks = self.converter.convert_file(path)
        
        self.assertEqual(len(ticks), 2)
        self.assertEqual(ticks[0].instrument_id, self.converter.poly_up_id)
        self.assertEqual(ticks[1].instrument_id, self.converter.poly_down_id)

if __name__ == "__main__":
    unittest.main()
