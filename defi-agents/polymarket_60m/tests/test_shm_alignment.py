import unittest
import ctypes
from utils.shm_types import L2BookStruct, AccountStateStruct

class TestShmAlignment(unittest.TestCase):
    def test_l2_book_alignment(self):
        self.assertEqual(ctypes.sizeof(L2BookStruct), 1152)
        self.assertEqual(L2BookStruct.hl_sequence.offset, 0)
        self.assertEqual(L2BookStruct.poly_sequence.offset, 8)
        self.assertEqual(L2BookStruct.hl_timestamp.offset, 16)
        self.assertEqual(L2BookStruct.strike_price.offset, 680)
        self.assertEqual(L2BookStruct.poly_up_id.offset, 696)
        self.assertEqual(L2BookStruct.current_ofi.offset, 952)
        self.assertEqual(L2BookStruct.last_update_local_ns.offset, 1016)
        self.assertEqual(L2BookStruct.hot_path_latency_ns.offset, 1024)

    def test_account_state_alignment(self):
        self.assertEqual(ctypes.sizeof(AccountStateStruct), 64)
        self.assertEqual(AccountStateStruct.sequence.offset, 0)
        self.assertEqual(AccountStateStruct.available_collateral.offset, 8)
        self.assertEqual(AccountStateStruct.up_position.offset, 32)
        self.assertEqual(AccountStateStruct.down_position.offset, 40)
        self.assertEqual(AccountStateStruct.next_nonce.offset, 48)
        self.assertEqual(AccountStateStruct.last_update_ts.offset, 56)

if __name__ == "__main__":
    unittest.main()
