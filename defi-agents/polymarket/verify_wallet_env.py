import os
from dotenv import load_dotenv

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

wallet_raw = os.environ.get("POLY_PROXY_WALLET") or os.environ.get("POLY_WALLET_ADDRESS")
print(f"Detected Wallet: {wallet_raw}")

if not wallet_raw:
    print("❌ ERROR: No wallet address detected!")
else:
    print("✅ SUCCESS: Wallet address detected.")
