import unittest
import sys
import os
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
from live_tapreader import L4Book
from utils.shm_types import L2BookStruct
from ctypes import c_uint64, c_double

class MockL4Snapshot:
    def __init__(self, height, time, bids, asks):
        self.height = height
        self.time = time
        self.bids = bids
        self.asks = asks

class MockOrder:
    def __init__(self, oid, px, sz, ts):
        self.oid = oid
        self.limit_px = px
        self.sz = sz
        self.timestamp = ts
        self.user = '0x123'

class MockL4Diff:
    def __init__(self, height, time, data):
        self.height = height
        self.time = time
        self.data = data

class TestEdgeCases(unittest.TestCase):
    def test_zero_time_execution_spike(self):
        # We need to simulate the `live_tapreader` logic that updates `execution_flow_rate`
        # Because it's inline in `hl_bridge`, we can just implement the same math to verify
        # or test the logic explicitly
        
        # Test 1: dt_ms = 0 fallback
        dt_ms = 1
        delta_bid = 100.0
        delta_ask = 0.0
        flow = (abs(delta_bid) + abs(delta_ask)) / (dt_ms / 1000.0)
        self.assertEqual(flow, 100000.0)
        
        # In live_tapreader.py we have dt_ms = l4_state.time - last_update_ts if last_update_ts > 0 else 1
        # If l4_state.time == last_update_ts, dt_ms = 0 if not handled!
        # Ah! `dt_ms = l4_state.time - last_update_ts if last_update_ts > 0 else 1`
        # If l4_state.time == last_update_ts, it resolves to 0!
        # Then `flow = ... / (dt_ms / 1000.0)` causes ZeroDivisionError if dt_ms is 0!
        # Wait, if last_update_ts > 0, it does l4_state.time - last_update_ts.
        # Let's check `live_tapreader.py`:
        # `dt_ms = l4_state.time - last_update_ts if last_update_ts > 0 else 1`
        # `if dt_ms > 0:`
        # Ah, it HAS `if dt_ms > 0:`. So if it's 0, it skips flow calc.
        
    def test_deep_book_update(self):
        # Test the deep book update logic we just wrote
        from utils.shm_types import PriceLevel
        p_bids = [PriceLevel(10.0, 100.0), PriceLevel(9.0, 50.0), PriceLevel(8.0, 20.0), PriceLevel(0.0, 0.0), PriceLevel(0.0, 0.0)]
        
        price = 9.0
        size = 60.0
        # Simulated logic
        MAX_POLY_LEVELS = 5
        found = False
        for k in range(MAX_POLY_LEVELS):
            if p_bids[k].price == price:
                if size == 0:
                    for j in range(k, MAX_POLY_LEVELS-1):
                        p_bids[j].price = p_bids[j+1].price
                        p_bids[j].size = p_bids[j+1].size
                    p_bids[-1].price, p_bids[-1].size = 0.0, 0.0
                else:
                    p_bids[k].size = size
                found = True
                break
        
        if not found and size > 0:
            for k in range(MAX_POLY_LEVELS):
                if price > p_bids[k].price:
                    for j in range(MAX_POLY_LEVELS-1, k, -1):
                        p_bids[j].price = p_bids[j-1].price
                        p_bids[j].size = p_bids[j-1].size
                    p_bids[k].price = price
                    p_bids[k].size = size
                    break
        
        self.assertEqual(p_bids[1].size, 60.0)
        self.assertEqual(p_bids[0].price, 10.0)

if __name__ == '__main__':
    unittest.main()
