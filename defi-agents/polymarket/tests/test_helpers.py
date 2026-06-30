import os
import tempfile
import unittest
from unittest import mock

class BaseTestCase(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for any file writes
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        
        # Patch environment variables to avoid real side effects
        self.env_patcher = mock.patch.dict(os.environ, {
            "POLYGON_RPC_URL": "http://mock-rpc-url.com",
            "SLACK_WEBHOOK_URL": "http://mock-webhook-url.com",
            "ALCHEMY_API_KEY": "mock_key"
        })
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

class BaseAsyncTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        
        self.env_patcher = mock.patch.dict(os.environ, {
            "POLYGON_RPC_URL": "http://mock-rpc-url.com",
            "SLACK_WEBHOOK_URL": "http://mock-webhook-url.com",
            "ALCHEMY_API_KEY": "mock_key"
        })
        self.env_patcher.start()

    async def asyncTearDown(self):
        self.env_patcher.stop()
        self.temp_dir.cleanup()
