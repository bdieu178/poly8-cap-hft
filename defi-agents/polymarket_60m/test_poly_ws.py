import asyncio
import websockets
import json
import time

async def test_poly():
    ws_url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    token_ids = ['86717279797987621468554542453073637871100407031802758618754860789759766470023', '1812850936838580029697189741475395281389189270197721882566538494465780819088', '87511491139419054269733167857533088198102227296190475399088341454254684713542', '89078166694772765589714136737025884603384124370996881854252264223095925829807']
    
    print(f"Connecting to {ws_url}...")
    try:
        async with websockets.connect(ws_url) as websocket:
            payload = {
                "type": "market",
                "operation": "subscribe",
                "markets": [],
                "assets_ids": token_ids,
                "initial_dump": True
            }
            print(f"Sending: {payload}")
            await websocket.send(json.dumps(payload))
            print(f"Sending: {payload}")
            await websocket.send(json.dumps(payload))
            
            start_time = time.time()
            while time.time() - start_time < 30:
                message = await asyncio.wait_for(websocket.recv(), timeout=10)
                print(f"Received: {message}")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_poly())
