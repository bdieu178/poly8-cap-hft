
import ctypes
import os

MAX_LEVELS = 10
MAX_POLY_LEVELS = 5

class PriceLevel(ctypes.Structure):
    _fields_ = [("price", ctypes.c_double), ("size", ctypes.c_double)]

class AccountStateStruct(ctypes.Structure):
    _fields_ = [
        ("sequence", ctypes.c_uint64),
        ("available_collateral", ctypes.c_double),
        ("total_equity", ctypes.c_double),
        ("total_maint_margin", ctypes.c_double),
        ("up_position", ctypes.c_double),
        ("down_position", ctypes.c_double),
        ("next_nonce", ctypes.c_uint64),
        ("last_update_ts", ctypes.c_uint64),
    ]

class CognitionStateStruct(ctypes.Structure):
    _fields_ = [
        ("sequence", ctypes.c_uint64),
        ("regime_multiplier", ctypes.c_double),
        ("regime_state_enum", ctypes.c_uint32),
        ("padding", ctypes.c_uint32), # Align to 8 bytes
    ]

class PositionInfoStruct(ctypes.Structure):
    _fields_ = [
        ("up_position_entry_price", ctypes.c_uint64),
        ("down_position_entry_price", ctypes.c_uint64),
        ("realized_pnl", ctypes.c_uint64),
        ("cumulative_fees", ctypes.c_uint64),
        ("is_exiting_up", ctypes.c_uint64),
        ("is_exiting_down", ctypes.c_uint64),
        ("up_position", ctypes.c_uint64),
        ("down_position", ctypes.c_uint64),
    ]

class GlobalRiskStruct(ctypes.Structure):
    _fields_ = [
        ("sequence", ctypes.c_uint64),
        ("global_gross_exposure", ctypes.c_uint64),
        ("global_net_pnl", ctypes.c_uint64),
        ("daily_stop_loss_triggered", ctypes.c_uint64),
        ("last_update_ts", ctypes.c_uint64),
    ]

class L2BookStruct(ctypes.Structure):
    _fields_ = [
        ("hl_sequence", ctypes.c_uint64),
        ("poly_sequence", ctypes.c_uint64),
        ("hl_timestamp", ctypes.c_uint64),
        ("hl_bids", PriceLevel * MAX_LEVELS),
        ("hl_asks", PriceLevel * MAX_LEVELS),
        
        ("poly_up_timestamp", ctypes.c_uint64),
        ("poly_up_bids", PriceLevel * MAX_POLY_LEVELS),
        ("poly_up_asks", PriceLevel * MAX_POLY_LEVELS),
        
        ("poly_down_timestamp", ctypes.c_uint64),
        ("poly_down_bids", PriceLevel * MAX_POLY_LEVELS),
        ("poly_down_asks", PriceLevel * MAX_POLY_LEVELS),

        ("strike_price", ctypes.c_double),
        ("rotation_ts", ctypes.c_uint64),
        ("poly_up_id", ctypes.c_char * 128),
        ("poly_down_id", ctypes.c_char * 128),
        
        ("current_ofi", ctypes.c_double),
        ("execution_flow_rate", ctypes.c_double),
        ("p_max_i", ctypes.c_double),
        ("signed_flow_rate", ctypes.c_double),
        
        ("event_flags", ctypes.c_uint32),
        ("padding0", ctypes.c_uint32),
        ("last_event_ts", ctypes.c_uint64),
        
        ("regime_multiplier", ctypes.c_double),
        ("regime_state_enum", ctypes.c_uint32),
        ("padding1", ctypes.c_uint32),
        
        ("last_update_local_ns", ctypes.c_uint64),
        ("hot_path_latency_ns", ctypes.c_uint64),
        ("hl_e2e_latency_ns", ctypes.c_int64),
        ("poly_processing_latency_ns", ctypes.c_int64),
        
        ("hl_l4_height", ctypes.c_uint64),
        ("bid_order_count", ctypes.c_uint32),
        ("ask_order_count", ctypes.c_uint32),
        
        ("whale_bid_size", ctypes.c_double),
        ("whale_ask_size", ctypes.c_double),
        ("bid_concentration", ctypes.c_double),
        ("ask_concentration", ctypes.c_double),
        
        ("best_bid_ts", ctypes.c_uint64),
        ("best_ask_ts", ctypes.c_uint64),
        
        ("timeframe_minutes", ctypes.c_uint32),
        ("padding_final_u32", ctypes.c_uint32),
        ("padding_final", ctypes.c_uint8 * 32),
    ]

class SpscRingBufferStruct(ctypes.Structure):
    _fields_ = [
        ("write_index", ctypes.c_uint64),
        ("_pad1", ctypes.c_uint8 * 56),
        ("read_index", ctypes.c_uint64),
        ("_pad2", ctypes.c_uint8 * 56),
        ("buffer", L2BookStruct * 2048),
        ("dropped_count", ctypes.c_uint64),
        ("_pad3", ctypes.c_uint8 * 56),
    ]

# Consistency Checks
if __name__ == "__main__":
    print(f"L2BookStruct size: {ctypes.sizeof(L2BookStruct)}")
    print(f"AccountStateStruct size: {ctypes.sizeof(AccountStateStruct)}")
    print(f"CognitionStateStruct size: {ctypes.sizeof(CognitionStateStruct)}")
    print(f"PositionInfoStruct size: {ctypes.sizeof(PositionInfoStruct)}")
    print(f"GlobalRiskStruct size: {ctypes.sizeof(GlobalRiskStruct)}")
    print(f"SpscRingBufferStruct size: {ctypes.sizeof(SpscRingBufferStruct)}")
    assert ctypes.sizeof(L2BookStruct) == 1152
    assert ctypes.sizeof(AccountStateStruct) == 64
    assert ctypes.sizeof(CognitionStateStruct) == 24
    assert ctypes.sizeof(PositionInfoStruct) == 64
    assert ctypes.sizeof(GlobalRiskStruct) == 40
    assert ctypes.sizeof(SpscRingBufferStruct) == 2359488

