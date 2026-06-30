import unittest
from unittest import mock
import polars as pl
import os
import asyncio
import tempfile
import shutil
from historical_ingestion import get_block_number_by_timestamp, align_and_store
import catalog_ingestion
from catalog_ingestion import ingest_high_fidelity_data as ingest_data
import data_harvester
from data_harvester import process_and_flush

class TestRobustness(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, "data")
        self.catalog_dir = os.path.join(self.test_dir, "catalog")
        os.makedirs(self.data_dir)
        os.makedirs(self.catalog_dir)
        
        # Patch the constants in the modules
        self.patch_data_dir = mock.patch("catalog_ingestion.DATA_DIR", self.data_dir)
        self.patch_catalog_dir = mock.patch("catalog_ingestion.CATALOG_DIR", self.catalog_dir)
        self.patch_data_dir.start()
        self.patch_catalog_dir.start()

    def tearDown(self):
        self.patch_data_dir.stop()
        self.patch_catalog_dir.stop()
        shutil.rmtree(self.test_dir)

    def test_binary_search_retries(self):
        mock_w3 = mock.Mock()
        # Fail twice, then succeed
        mock_w3.eth.get_block.side_effect = [Exception("Fail"), Exception("Fail"), mock.Mock(timestamp=100)]
        mock_w3.eth.block_number = 10
        
        block = get_block_number_by_timestamp(100, mock_w3, max_retries=3)
        self.assertTrue(block >= 0)
        self.assertEqual(mock_w3.eth.get_block.call_count, 3)

    def test_catalog_ingestion_validation(self):
        file_path = os.path.join(self.data_dir, "aligned_historical_20260401_20260424.parquet")
        # Create data with nulls and invalid prices
        df = pl.DataFrame({
            "timestamp_ms": [1000, 2000, 3000, 4000],
            "target_bid_price_poly": [0.5, None, -0.1, 0.55],
            "target_ask_price_poly": [0.5, 0.51, 0.0, 0.56],
            "poly_slippage_estimate": [0.01, 0.02, 0.03, 0.04]
        })
        df.write_parquet(file_path)
        
        # Should not crash now, should filter out 2nd and 3rd rows
        ingest_data()
        
        # Verify catalog was created
        self.assertTrue(os.path.exists(self.catalog_dir))

class TestAsyncRobustness(unittest.IsolatedAsyncioTestCase):
    async def test_process_and_flush_stale_detection(self):
        self.test_dir = tempfile.mkdtemp()
        try:
            queue = asyncio.Queue()
            # Add data with a large gap
            queue.put_nowait({"source": "polymarket", "timestamp_ms": 1000, "target_bid_price_poly": 0.5, "target_ask_price_poly": 0.51})
            queue.put_nowait({"source": "polymarket", "timestamp_ms": 100000, "target_bid_price_poly": 0.52, "target_ask_price_poly": 0.53})
            
            # Patch data_harvester.DATA_DIR
            with mock.patch("data_harvester.DATA_DIR", self.test_dir):
                # We need to control time precisely
                # 1. last_flush_time = time.time() (0)
                # 2. Iter 1: queue.get(), time.time() (0) -> no flush
                # 3. Iter 2: queue.get(), time.time() (100) -> flush happens
                with mock.patch("data_harvester.time.time") as mock_time:
                    mock_time.side_effect = [0, 0, 100, 100, 100, 100, 100]
                    with mock.patch("data_harvester.logger") as mock_logger:
                        try:
                            task = asyncio.create_task(process_and_flush(queue))
                            # Wait until queue is empty
                            for _ in range(10):
                                if queue.empty():
                                    break
                                await asyncio.sleep(0.1)
                            
                            # Give it a bit more time to finish the loop
                            await asyncio.sleep(0.2)
                            task.cancel()
                            await task
                        except asyncio.CancelledError:
                            pass
                        
                        # Check if warning was logged for large gap
                        warnings = [str(args[0]) for args, _ in mock_logger.warning.call_args_list]
                        self.assertTrue(any("large data gap" in w for w in warnings), f"Warnings found: {warnings}")
        finally:
            shutil.rmtree(self.test_dir)

if __name__ == "__main__":
    unittest.main()
