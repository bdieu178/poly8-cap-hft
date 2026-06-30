"""
Hot Wallet Utility: Derive and Validate Polygon Credentials
"""
import os
from eth_account import Account
from dotenv import load_dotenv, set_key

def setup_wallet():
    env_path = os.path.join(os.path.dirname(__file__), '../.env')
    load_dotenv(env_path)
    
    secret = os.environ.get("POLY_SECRET")
    if not secret or secret.startswith("0x0000"):
        print("--- Generating New Hot Wallet ---")
        new_acc = Account.create()
        print(f"Address: {new_acc.address}")
        print(f"Secret:  {new_acc.key.hex()}")
        print("\n!!! SAVE THIS SECRET SECURELY. DO NOT COMMIT TO GIT !!!")
        
        # Optionally update .env automatically
        confirm = input("\nUpdate .env with this new wallet? (y/n): ")
        if confirm.lower() == 'y':
            set_key(env_path, "POLY_SECRET", new_acc.key.hex())
            set_key(env_path, "HOT_WALLET_ADDRESS", new_acc.address)
            print("Updated .env successfully.")
    else:
        try:
            acc = Account.from_key(secret)
            print(f"--- Wallet Validated ---")
            print(f"Signer Address: {acc.address}")
            
            proxy = os.environ.get("POLY_PROXY_WALLET")
            if proxy and proxy != "0x...":
                print(f"Proxy Wallet:  {proxy}")
            else:
                print("Note: No Proxy Wallet set. Using Signer Address as Maker.")
                
        except Exception as e:
            print(f"Error validating wallet: {e}")

if __name__ == "__main__":
    setup_wallet()
