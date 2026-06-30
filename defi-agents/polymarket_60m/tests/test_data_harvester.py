import time
import asyncio
import ctypes
from unittest import mock
import polars as pl
from tests.test_helpers import BaseTestCase, BaseAsyncTestCase
from data_harvester import poll_shared_memory, process_and_flush, L2BookStruct
import data_harvester

class TestDataHarvester(BaseTestCase):
    def test_placeholder(self):
        pass

class TestDataHarvesterAsync(BaseAsyncTestCase):
    @mock.patch("data_harvester.POSIXSharedMemory")
    @mock.patch("data_harvester.read_spsc_ring_buffer_snapshot")
    async def test_poll_shared_memory(self, mock_read, mock_shm):
        mock_shm_inst = mock.Mock()
        mock_shm_inst.buf = b'\x00' * ctypes.sizeof(data_harvester.SpscRingBufferStruct)
        mock_shm.return_value = mock_shm_inst
        
        s1 = L2BookStruct()
        s1.hl_timestamp = 1000
        s1.hl_bids[0].price = 65000.0
        s1.hl_asks[0].price = 65000.5
        s1.poly_up_timestamp = 2000
        s1.poly_up_bids[0].price = 0.55
        s1.poly_up_asks[0].price = 0.56
        s1.current_ofi = 120.0
        s1.execution_flow_rate = 50.0
        s1.p_max_i = 65000.25
        s1.event_flags = 2
        
        mock_read.side_effect = [s1, Exception("Stop")]
        
        queue = asyncio.Queue()
        with self.assertRaises(Exception) as cm:
            await poll_shared_memory(queue)
            
        self.assertEqual(str(cm.exception), "Stop")
        self.assertEqual(queue.qsize(), 2)
        
        item1 = queue.get_nowait()
        self.assertEqual(item1["source"], "hyperliquid")
        self.assertEqual(item1["ofi"], 120.0)
        
        item2 = queue.get_nowait()
        self.assertEqual(item2["source"], "polymarket_up")

    async def test_process_and_flush(self):
        original_data_dir = data_harvester.DATA_DIR
        data_harvester.DATA_DIR = self.temp_dir.name
        
        try:
            queue = mock.AsyncMock()
            queue.get.side_effect = [
                {
                    "source": "hyperliquid", "timestamp_ms": 1000,
                    "ref_bid_price_hl": 65000.0, "ref_ask_price_hl": 65000.5, "event_type": "L2_UPDATE"
                },
                Exception("Stop")
            ]
            
            with self.assertRaises(Exception) as cm:
                await process_and_flush(queue)
            
            self.assertEqual(str(cm.exception), "Stop")
        finally:
            data_harvester.DATA_DIR = original_data_dir
