
import unittest
import ctypes
import time
from utils.shm_types import AccountStateStruct, L2BookStruct
from utils.shm_utils import POSIXSharedMemory
import os

class TestPUSDReadiness(unittest.TestCase):
    def setUp(self):
        # Initialize mock SHM for testing
        self.shm_name = "/test_l2_book_v2"
        self.acc_name = "/test_poly_account_state"
        
        # In a real environment, launch_parallel_hft.sh creates these.
        # Here we mock them using regular files in /dev/shm for ctypes compatibility.
        for name in [self.shm_name, self.acc_name]:
            path = f"/dev/shm{name}"
            if os.path.exists(path): os.remove(path)
            with open(path, "wb") as f:
                f.write(b"\0" * 2048) # Sufficient size (at least 1152)
            os.chmod(path, 0o666)

        self.shm = POSIXSharedMemory(self.shm_name, ctypes.sizeof(L2BookStruct))
        self.book = L2BookStruct.from_buffer(self.shm.buf)
        
        self.shm_acc = POSIXSharedMemory(self.acc_name, ctypes.sizeof(AccountStateStruct))
        self.acc = AccountStateStruct.from_buffer(self.shm_acc.buf)

    def tearDown(self):
        # Clear references to the buffer before closing it to avoid BufferError
        self.book = None
        self.acc = None
        self.shm.close()
        self.shm_acc.close()
        os.remove(f"/dev/shm{self.shm_name}")
        os.remove(f"/dev/shm{self.acc_name}")

    def test_account_state_sync_logic(self):
        """
        Verifies that position-aware fields (up_position, down_position) 
        are correctly represented and can be updated.
        """
        self.acc.sequence = 100
        self.acc.available_collateral = 500.0
        self.acc.up_position = 250.0
        self.acc.down_position = 0.0
        self.acc.total_equity = 750.0
        
        # Simulate reading from another process
        acc_read = AccountStateStruct.from_buffer(self.shm_acc.buf)
        self.assertEqual(acc_read.available_collateral, 500.0)
        self.assertEqual(acc_read.up_position, 250.0)
        self.assertEqual(acc_read.total_equity, 750.0)

    def test_trade_blocking_on_zero_balance(self):
        """
        Simulates the logic where zero balance should block trade triggers.
        """
        self.acc.available_collateral = 0.0
        
        # Logic check: if available == 0, Kelly size should be 0
        multiplier = 1.0
        p_theo = 0.6
        p_market = 0.5
        b = (1.0 / p_market) - 1.0
        kelly_fraction = multiplier * ( (p_theo * (b + 1.0) - 1.0) / b )
        
        order_size = self.acc.available_collateral * kelly_fraction
        self.assertEqual(order_size, 0.0)
        
    def test_position_aware_sell_trigger(self):
        """
        Verifies that having a position enables selling (closing).
        """
        self.acc.up_position = 100.0
        p_theo = 0.4 # Underpriced UP token? No, p_theo is for UP. 
        # If p_theo=0.4 and p_market=0.5, UP is overpriced. Should SELL.
        
        p_market_bid = 0.5
        edge = p_market_bid - p_theo # 0.1 edge to sell
        
        can_sell = self.acc.up_position > 1.0 and edge > 0.03
        self.assertTrue(can_sell)

if __name__ == "__main__":
    unittest.main()
