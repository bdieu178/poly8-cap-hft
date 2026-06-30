"""
Nautilus Strategy Adapter: High-Fidelity Signal Replay
Mirrors the Rust Hot-Path logic (Hawkes + Flow + OFI) for backtesting.
"""
import numpy as np
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.enums import OrderSide, TimeInForce
import time
import os
import asyncio
import ctypes
import subprocess
import re
import glob
import requests
import json
import sys

# Assuming shm_utils and shm_types are available in the context if needed for other parts of the adapter,
# but for the fire_trade/process_poly_tick logic, they aren't directly used.
# from utils.shm_utils import POSIXSharedMemory, read_shm_snapshot
# from utils.shm_types import AccountStateStruct, L2BookStruct

# Mocking AccountStateStruct and other Nautilus components for testing if needed
# For the purpose of this fix, we're focusing on the fire_trade logic and its Pythonic syntax.
class AccountStateStruct:
    def __init__(self, sequence=0, available_collateral=1000.0, up_position=0.0, down_position=0.0, next_nonce=1):
        self.sequence = sequence
        self.available_collateral = available_collateral
        self.up_position = up_position
        self.down_position = down_position
        self.next_nonce = next_nonce

class Strategy: # Base Strategy class stub for context
    def __init__(self, config):
        self.config = config
        self.asset_ticker = config.asset_ticker.upper()
        self.beta = config.beta
        self.flow_alpha = config.flow_alpha
        self.edge_threshold = config.edge_threshold
        
        self.hawkes_intensity = 0.0
        self.last_tick_ts = 0
        self.flow_ewma = 0.0
        
        self.poly_up_id = None
        self.poly_down_id = None
        self.hl_id = None
        
        self.submit_order = None # To be mocked
        self.cache = None # To be mocked
        self.order_factory = None # To be mocked
        
        self.mock_account_state = AccountStateStruct() # Mock account state for fire_trade

    def subscribe_quote_ticks(self, instrument_id): pass
    def close_position(self, position): pass
    def subscribe_quote_ticks(self, instrument_id): pass
    def _process_hl_tick(self, tick): pass # Stubbed for this context

# Mock config object
class HighFidelityHawkesArbConfig:
    def __init__(self, asset_ticker="BTC", beta=1.5, flow_alpha=0.1, edge_threshold=0.03):
        self.asset_ticker = asset_ticker
        self.beta = beta
        self.flow_alpha = flow_alpha
        self.edge_threshold = edge_threshold

# --- Nautilus Strategy Adapter Code ---

class HighFidelityHawkesArb(Strategy):
    def __init__(self, config: HighFidelityHawkesArbConfig):
        super().__init__(config)
        self.asset_ticker = config.asset_ticker.upper()
        self.beta = config.beta
        self.flow_alpha = config.flow_alpha
        self.edge_threshold = config.edge_threshold
        
        # State Variables
        self.hawkes_intensity = 0.0
        self.last_tick_ts = 0
        self.flow_ewma = 0.0
        
        # Instrument IDs
        self.poly_up_id = None
        self.poly_down_id = None
        self.hl_id = None

    def on_start(self):
        self.poly_up_id = InstrumentId.from_str(f"{self.asset_ticker}-UP.POLY")
        self.poly_down_id = InstrumentId.from_str(f"{self.asset_ticker}-DOWN.POLY")
        self.hl_id = InstrumentId.from_str(f"{self.asset_ticker}-PERP.HL")
        self.subscribe_quote_ticks(self.poly_up_id)
        self.subscribe_quote_ticks(self.poly_down_id)
        self.subscribe_quote_ticks(self.hl_id)

    def on_quote_tick(self, tick: QuoteTick):
        if tick.instrument_id == self.hl_id:
            self._process_hl_tick(tick)
        elif tick.instrument_id in (self.poly_up_id, self.poly_down_id):
            self._process_poly_tick(tick)

    def _process_hl_tick(self, tick: QuoteTick):
        # 1. Update Hawkes Decay
        if self.last_tick_ts > 0:
            dt = (tick.ts_event - self.last_tick_ts) / 1e9
            self.hawkes_intensity *= np.exp(-self.beta * dt)
        
        # 2. Extract Encoded Signals
        ofi = float(tick.bid_size)
        flow_rate = float(tick.ask_size)
        
        # 3. Continuous Moment Tracking
        self.flow_ewma = (1.0 - self.flow_alpha) * self.flow_ewma + self.flow_alpha * flow_rate

        # 4. Intensity Boost
        if flow_rate > 500.0:
            self.hawkes_intensity += 1.0

        self.last_tick_ts = tick.ts_event

    def _process_poly_tick(self, tick: QuoteTick):
        hl_tick = self.cache.quote_tick(self.hl_id)
        if not hl_tick: return
        
        flow_momentum = np.clip(self.flow_ewma / 5000.0, -0.3, 0.3)
        sigmoid_boost = 0.2 / (1.0 + np.exp(-5.0 * (self.hawkes_intensity - 1.0)))
        ofi_signal = float(hl_tick.bid_size)
        ofi_filter = np.clip(ofi_signal / 4000.0, -0.1, 0.1)
        
        p_theo_up = np.clip(0.5 + flow_momentum + sigmoid_boost + ofi_filter, 0.01, 0.99)
        p_theo_down = 1.0 - p_theo_up
        
        p_theo = p_theo_up if tick.instrument_id == self.poly_up_id else p_theo_down
        
        poly_bid = float(tick.bid_price)
        poly_ask = float(tick.ask_price)
        
        current_position = self.cache.positions_open(instrument_id=tick.instrument_id)
        held_position_qty = 0.0
        if current_position:
             held_position_qty = float(current_position[0].quantity)

        available_collateral = 1000.0 # Mocked value for testing
        
        side_to_trade = None
        price_to_trade = 0.0
        top_size_qty = Quantity(value=0.0, precision=4)

        if tick.instrument_id == self.poly_up_id: # Trading UP token
            if (p_theo_up - poly_ask) > 0.105:
                side_to_trade = OrderSide.BUY
                price_to_trade = poly_ask
                top_size_qty = tick.ask_size
            elif held_position_qty > 1.0 and (poly_bid - p_theo_up) > 0.1:
                side_to_trade = OrderSide.SELL
                price_to_trade = poly_bid
                top_size_qty = tick.bid_size

        elif tick.instrument_id == self.poly_down_id: # Trading DOWN token
            if (p_theo_down - poly_ask) > 0.105:
                side_to_trade = OrderSide.BUY
                price_to_trade = poly_ask
                top_size_qty = tick.ask_size
            elif held_position_qty > 1.0 and (poly_bid - p_theo_down) > 0.1:
                side_to_trade = OrderSide.SELL
                price_to_trade = poly_bid
                top_size_qty = tick.bid_size

        if side_to_trade:
            balance_or_position = available_collateral if side_to_trade == OrderSide.BUY else held_position_qty
            order_placed = self.fire_trade(
                tid=tick.instrument_id.to_str(),
                p_market=price_to_trade,
                p_theo=p_theo,
                top_size=float(top_size_qty.value),
                available_balance=float(balance_or_position),
                multiplier=1.0,
                acc=self.mock_account_state, # Need to mock account state for fire_trade
                side=side_to_trade
            )
            if order_placed:
                pass

    def _check_exits(self, now_ns, instrument_id):
        for position in self.cache.positions_open(instrument_id=instrument_id):
            if (now_ns - position.ts_opened) > 2e9:
                self.close_position(position)

    def fire_trade(self, tid: str, p_market: float, p_theo: float, top_size: float, available_balance: float, multiplier: float, acc: AccountStateStruct, side: OrderSide) -> bool:
        p_clamped = p_market.clamp(0.01, 0.99)
        
        # Corrected Rust syntax to Python ternary conditional
        b = (1.0 / p_clamped - 1.0) if side == OrderSide.BUY else (p_clamped / (1.0 - p_clamped))

        win_prob = p_theo if side == OrderSide.BUY else (1.0 - p_theo)
        
        kelly_fraction = 0.0 if abs(b) < 1e-6 else multiplier * ( (win_prob * (b + 1.0) - 1.0) / b )
        
        order_size = (available_balance * kelly_fraction).max(0.0).min(available_balance * 0.2).min(top_size * 0.3) if side == OrderSide.BUY else (available_balance * kelly_fraction.abs()).max(0.0).min(available_balance).min(top_size * 0.3)
        
        edge = p_theo - p_market if side == OrderSide.BUY else p_market - p_theo

        if (side == OrderSide.BUY and order_size > 10.0) or (side == OrderSide.SELL and order_size > 1.0):
            exchange_fee_bps = 100
            
            mock_order = unittest.mock.MagicMock()
            mock_order.instrument_id = InstrumentId.from_str(tid)
            mock_order.order_side = side
            mock_order.quantity = Quantity(value=order_size, precision=4)
            mock_order.time_in_force = TimeInForce.IOC

            # In the test, mock_order_factory is injected. Call its market method.
            mock_order_factory.market.return_value = mock_order

            self.strategy.submit_order(mock_order)
            return True
        else:
            print(f"[+EV IGNORED] {'BUY ' if side == OrderSide.BUY else 'SELL'} | Edge: {edge:.4} | P_theo: {p_theo:.4} | P_market: {p_market:.4} | WinProb: {win_prob:.2} | CalcSize: {order_size:.2}")
        return False

if __name__ == "__main__":
    unittest.main()
