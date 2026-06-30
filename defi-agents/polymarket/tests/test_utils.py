import logging
from unittest import mock
from tests.test_helpers import BaseTestCase, BaseAsyncTestCase
from utils.logger import get_logger
from utils.alerting import send_alert

class TestLogger(BaseTestCase):
    @mock.patch("utils.logger.logging.FileHandler")
    def test_get_logger(self, mock_file_handler):
        logger = get_logger("test_logger_123")
        self.assertEqual(logger.name, "test_logger_123")
        self.assertEqual(logger.level, logging.INFO)
        self.assertTrue(len(logger.handlers) >= 1)

class TestAlerting(BaseAsyncTestCase):
    @mock.patch("utils.alerting.aiohttp.ClientSession.post")
    async def test_send_alert_success(self, mock_post):
        mock_response = mock.AsyncMock()
        mock_response.status = 200
        mock_post.return_value.__aenter__.return_value = mock_response

        await send_alert("Test message", level="INFO")
        
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "http://mock-webhook-url.com")
        self.assertEqual(kwargs["json"]["text"], "*INFO*: Test message")

    @mock.patch("utils.alerting.aiohttp.ClientSession.post")
    @mock.patch("utils.alerting.logger.error")
    async def test_send_alert_failure(self, mock_logger_error, mock_post):
        mock_response = mock.AsyncMock()
        mock_response.status = 500
        mock_post.return_value.__aenter__.return_value = mock_response

        await send_alert("Test failure", level="ERROR")
        mock_logger_error.assert_called_with("Failed to send alert. Status code: 500")

    @mock.patch.dict("os.environ", {"SLACK_WEBHOOK_URL": ""}, clear=True)
    @mock.patch("utils.alerting.logger.warning")
    async def test_send_alert_no_webhook(self, mock_logger_warning):
        await send_alert("Test message")
        mock_logger_warning.assert_called_once()
