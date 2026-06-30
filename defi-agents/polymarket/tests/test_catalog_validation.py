from unittest import mock
import os
import polars as pl
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
from tests.test_helpers import BaseTestCase
import catalog_ingestion
import validate_sync

class TestCatalogValidation(BaseTestCase):
    @mock.patch("catalog_ingestion.DataCatalog")
    @mock.patch("catalog_ingestion.glob.glob")
    @mock.patch("catalog_ingestion.pl.read_parquet")
    def test_catalog_ingestion(self, mock_read_parquet, mock_glob, mock_catalog):
        mock_glob.return_value = ["/mock/dir/hft_recording_20260507_120000.parquet"]
        
        df = pl.DataFrame({
            "timestamp_ms": [1000, 2000],
            "source": ["hyperliquid", "polymarket"],
            "hl_bid_px_0": [65000.0, 65001.0],
            "hl_ask_px_0": [65000.5, 65001.5],
            "current_ofi": [10.0, 20.0],
            "execution_flow_rate": [5.0, 10.0],
            "poly_bid_px_0": [0.54, 0.55],
            "poly_ask_px_0": [0.56, 0.57],
            "poly_bid_sz_0": [1000.0, 2000.0],
            "poly_ask_sz_0": [1500.0, 2500.0],
            "target_bid_price_poly": [0.54, 0.55],
            "target_ask_price_poly": [0.56, 0.57],
            "outcome": ["up", "down"]
        })
        mock_read_parquet.return_value = df
        
        mock_instance = mock.Mock()
        mock_catalog.return_value = mock_instance
        
        catalog_ingestion.ingest_high_fidelity_data()
        
        mock_instance.write_data.assert_called_once()
        
    @mock.patch("validate_sync.os.path.exists")
    @mock.patch("validate_sync.pl.read_parquet")
    @mock.patch("validate_sync.plt.savefig")
    def test_validate_sync(self, mock_savefig, mock_read_parquet, mock_exists):
        mock_exists.return_value = True
        
        df = pl.DataFrame({
            "timestamp_ms": [1000, 2000, 8000],
            "target_bid_price_poly": [0.5, 0.5, 0.5],
            "target_ask_price_poly": [0.6, 0.6, 0.6],
            "hl_bid_px_0": [60000, 60000, 60000],
            "hl_ask_px_0": [60001, 60001, 60001]
        })
        mock_read_parquet.return_value = df
        
        validate_sync.analyze_drift()
        mock_savefig.assert_called_once()
