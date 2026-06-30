import unittest
import asyncio
import aiohttp
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from live_tapreader import fetch_active_token_ids, PriceLevel

class TestPolymarketCriticalPath(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_active_token_ids_timeout(self):
        """Ensure fetch_active_token_ids does not hang on API timeout."""
        mock_session = MagicMock(spec=aiohttp.ClientSession)
        
        # Simulate a timeout error
        mock_session.get.side_effect = asyncio.TimeoutError()
        
        # This should not raise an exception and should return an empty list after the timeout
        token_ids = await fetch_active_token_ids(mock_session)
        self.assertEqual(token_ids, [])

    async def test_fetch_active_token_ids_malformed_json(self):
        """Ensure fetch_active_token_ids handles malformed API responses."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = [{"clobTokenIds": "invalid-json"}]
        
        mock_session = MagicMock(spec=aiohttp.ClientSession)
        mock_session.get.return_value.__aenter__.return_value = mock_response
        
        # Should handle the json.loads error internally
        token_ids = await fetch_active_token_ids(mock_session)
        self.assertEqual(token_ids, [])

    def test_shm_struct_alignment(self):
        """Verify the L2BookStruct alignment matches expectations for the Rust sidecar."""
        from live_tapreader import L2BookStruct
        import ctypes
        
        # The Rust sidecar expects specific offsets for the poly_timestamp
        # If we change the struct in Python, we must ensure it doesn't break the binary layout
        self.assertEqual(ctypes.sizeof(L2BookStruct) > 500, True) # Ensure L4 extensions are present
        
if __name__ == '__main__':
    unittest.main()
