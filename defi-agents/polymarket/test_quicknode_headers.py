import grpc
import os
from dotenv import load_dotenv
import orderbook_pb2
import orderbook_pb2_grpc

load_dotenv()

def test_quicknode():
    target = os.environ.get("HYPERLIQUID_GRPC_TARGET")
    token = os.environ.get("HYPERLIQUID_AUTH_TOKEN")
    
    print(f"Testing Quicknode gRPC: {target}")
    
    # Try different headers
    headers = [
        ('x-token', token),
        ('x-api-key', token),
        ('authorization', f'Bearer {token}')
    ]
    
    for key, val in headers:
        print(f"Trying header: {key}")
        try:
            channel = grpc.secure_channel(target, grpc.ssl_channel_credentials())
            stub = orderbook_pb2_grpc.OrderBookStreamingStub(channel)
            metadata = ((key, val),)
            
            request = orderbook_pb2.L2BookRequest(coin="BTC", n_levels=1)
            # Try to get one update
            responses = stub.StreamL2Book(request, metadata=metadata)
            for response in responses:
                print(f"SUCCESS with {key}! Time: {response.time}")
                return
        except Exception as e:
            print(f"Failed with {key}: {e}")

if __name__ == "__main__":
    test_quicknode()
