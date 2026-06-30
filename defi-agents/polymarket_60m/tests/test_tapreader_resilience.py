
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
import asyncio
import json
import os
import ctypes
from live_tapreader import poly_bridge, L2BookStruct

class TestTapReaderResilience(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.book = L2BookStruct()

    @patch('live_tapreader.websockets.connect')
    @patch('live_tapreader.fetch_active_token_ids', new_callable=AsyncMock)
    @patch('live_tapreader.aiohttp.ClientSession')
    async def test_polymarket_ws_stall_reconnect(self, mock_session, mock_fetch_tokens, mock_ws_connect):
        """
        Verifies that the poly_bridge reconnects after 10 consecutive timeouts.
        """
        mock_fetch_tokens.return_value = ["UP_ID", "DOWN_ID"]
        
        mock_ws = AsyncMock()
        # Simulate 11 timeouts, then success
        mock_ws.recv.side_effect = [asyncio.TimeoutError()] * 11 + [json.dumps({"event_type": "book", "asset_id": "UP_ID", "bids": [], "asks": []})]
        
        # websockets.connect returns an async context manager
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_ws
        mock_ws_connect.return_value = mock_ctx
        
        # We need to run poly_bridge but it has an infinite loop. 
        # We'll use a task and cancel it after it reconnects.
        task = asyncio.create_task(poly_bridge(self.book))
        
        # Give it some time to run through the timeouts. 
        # Since poly_bridge has an infinite loop, it will keep calling recv.
        # Each recv has a 5s timeout, but mock AsyncMock is fast.
        await asyncio.sleep(0.1) 
        
        # Check that connect was called at least twice (initial + 1 reconnection)
        self.assertGreaterEqual(mock_ws_connect.call_count, 2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

if __name__ == '__main__':
    unittest.main()
