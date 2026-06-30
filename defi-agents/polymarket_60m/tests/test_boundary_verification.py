# Boundary Verification Test Suite
# Validates exact ctypes struct sizes and field offsets to guarantee safe IPC memory layout.
# CREATED: 2026-05-18 00:07:10 UTC
# EDITED: 2026-05-18 00:07:10 UTC

import unittest
import ctypes
from utils.shm_types import (
    L2BookStruct,
    AccountStateStruct,
    CognitionStateStruct,
    PositionInfoStruct,
    GlobalRiskStruct
)

class TestBoundaryVerification(unittest.TestCase):

    def test_struct_sizes(self):
        """Verify struct sizes align exactly with Rust/C++ target boundaries."""
        self.assertEqual(ctypes.sizeof(L2BookStruct), 1152)
        self.assertEqual(ctypes.sizeof(AccountStateStruct), 64)
        self.assertEqual(ctypes.sizeof(PositionInfoStruct), 48)
        self.assertEqual(ctypes.sizeof(CognitionStateStruct), 24)
        self.assertEqual(ctypes.sizeof(GlobalRiskStruct), 40)

    def test_l2_book_offsets(self):
        """Verify field offsets inside L2BookStruct align perfectly with C++/Rust expectations."""
        self.assertEqual(L2BookStruct.hl_sequence.offset, 0)
        self.assertEqual(L2BookStruct.poly_sequence.offset, 8)
        self.assertEqual(L2BookStruct.hl_timestamp.offset, 16)
        self.assertEqual(L2BookStruct.strike_price.offset, 680)
        self.assertEqual(L2BookStruct.poly_up_id.offset, 696)
        self.assertEqual(L2BookStruct.current_ofi.offset, 952)
        self.assertEqual(L2BookStruct.last_update_local_ns.offset, 1016)
        self.assertEqual(L2BookStruct.hot_path_latency_ns.offset, 1024)
        self.assertEqual(L2BookStruct.hl_e2e_latency_ns.offset, 1032)
        self.assertEqual(L2BookStruct.poly_processing_latency_ns.offset, 1040)
        self.assertEqual(L2BookStruct.best_bid_ts.offset, 1096)
        self.assertEqual(L2BookStruct.best_ask_ts.offset, 1104)
        self.assertEqual(L2BookStruct.padding_final.offset, 1112)

    def test_account_state_offsets(self):
        """Verify field offsets inside AccountStateStruct align perfectly."""
        self.assertEqual(AccountStateStruct.sequence.offset, 0)
        self.assertEqual(AccountStateStruct.available_collateral.offset, 8)
        self.assertEqual(AccountStateStruct.up_position.offset, 32)
        self.assertEqual(AccountStateStruct.down_position.offset, 40)
        self.assertEqual(AccountStateStruct.next_nonce.offset, 48)
        self.assertEqual(AccountStateStruct.last_update_ts.offset, 56)

    def test_position_info_offsets(self):
        """Verify field offsets inside PositionInfoStruct align perfectly."""
        self.assertEqual(PositionInfoStruct.up_position_entry_price.offset, 0)
        self.assertEqual(PositionInfoStruct.down_position_entry_price.offset, 8)
        self.assertEqual(PositionInfoStruct.realized_pnl.offset, 16)
        self.assertEqual(PositionInfoStruct.cumulative_fees.offset, 24)
        self.assertEqual(PositionInfoStruct.is_exiting_up.offset, 32)
        self.assertEqual(PositionInfoStruct.is_exiting_down.offset, 40)

if __name__ == "__main__":
    unittest.main()
