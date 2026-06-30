import os
import aiohttp
from dotenv import load_dotenv
from utils.logger import get_logger

load_dotenv()
logger = get_logger(__name__)

async def send_alert(message: str, level: str = "ERROR"):
    """
    Sends an alert to the configured webhook URL.
    """
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        logger.warning(f"Alert not sent (no webhook URL configured): [{level}] {message}")
        return

    payload = {
        "text": f"*{level}*: {message}"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    logger.error(f"Failed to send alert. Status code: {response.status}")
                else:
                    logger.info(f"Alert sent successfully: {message}")
    except Exception as e:
        logger.error(f"Error sending alert: {e}")
