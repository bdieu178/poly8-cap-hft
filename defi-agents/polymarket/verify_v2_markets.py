import urllib.request
import json
import time

GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"

def get_current_interval_timestamp(interval_minutes):
    now = int(time.time())
    interval_seconds = interval_minutes * 60
    return (now // interval_seconds + 1) * interval_seconds

def verify_markets():
    targets = [
        ("btc", "5m"),
        ("btc", "15m"),
        ("eth", "5m"),
        ("eth", "15m")
    ]
    
    print(f"Verifying Polymarket V2 Markets at {time.strftime('%Y-%m-%d %H:%M:%S')} UTC...")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    for asset, timeframe in targets:
        minutes = 5 if timeframe == "5m" else 15
        timestamp = get_current_interval_timestamp(minutes)
        slug = f"{asset}-updown-{timeframe}-{timestamp}"
        
        url = f"{GAMMA_API_URL}?slug={slug}"
        print(f"Checking slug: {slug}")
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    if data and len(data) > 0:
                        market = data[0]
                        cid = market.get("conditionId")
                        # Some Gamma markets might have a list of tokens
                        print(f"  [SUCCESS] Found conditionId: {cid}")
                        print(f"            Question: {market.get('question')}")
                    else:
                        print(f"  [FAILED] Slug found but data empty or market not yet created.")
                else:
                    print(f"  [ERROR] Gamma API returned status {response.status}")
        except Exception as e:
            print(f"  [ERROR] Request failed: {e}")

if __name__ == "__main__":
    verify_markets()
