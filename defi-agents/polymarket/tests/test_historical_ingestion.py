from unittest import mock
import polars as pl
from tests.test_helpers import BaseTestCase
from historical_ingestion import get_block_number_by_timestamp, get_polygon_logs, get_hyperliquid_l2

class TestHistoricalIngestion(BaseTestCase):
    def test_get_block_number_by_timestamp(self):
        mock_w3 = mock.Mock()
        mock_w3.eth.block_number = 100
        
        def side_effect(block_num):
            b = mock.Mock()
            b.timestamp = block_num * 10
            return b
            
        mock_w3.eth.get_block.side_effect = side_effect
        
        block = get_block_number_by_timestamp(500, mock_w3)
        self.assertEqual(block, 50)
        
    @mock.patch("historical_ingestion.w3")
    def test_get_polygon_logs_empty(self, mock_w3):
        mock_w3.eth.block_number = 10
        mock_w3.eth.get_block.return_value.timestamp = 0
        
        df = get_polygon_logs(100, 200)
        self.assertEqual(len(df), 0)
        self.assertIn("target_bid_price_poly", df.columns)

    def test_get_hyperliquid_l2(self):
        df = get_hyperliquid_l2(100, 200)
        self.assertTrue(len(df) > 0)
        self.assertIn("ref_bid_price_hl", df.columns)
