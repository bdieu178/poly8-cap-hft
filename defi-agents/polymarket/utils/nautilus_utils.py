"""
Custom Nautilus Models for Polymarket Backtesting
"""
from nautilus_trader.backtest.models.fee import FeeModel
from nautilus_trader.model.objects import Money
from nautilus_trader.model.enums import OrderSide

class PolymarketFeeModel(FeeModel):
    """
    Polymarket CLOB V2 Fee Model.
    Charges 2% of winnings (asymmetric fee).
    Approximated as 2% commission on closing trades where exit price = 1.0.
    """
    def __init__(self, winning_fee_bps: int = 200):
        super().__init__()
        self.winning_fee_bps = winning_fee_bps

    def calculate_fees(self, order, fill):
        # We model this as a commission on the fill.
        # If it's a 'win' (price is 1.0), we take 2%. 
        # Note: True Polymarket fees are handled at settlement, 
        # but for HFT backtesting, we apply them at trade exit.
        
        instrument = fill.instrument_id
        if fill.price >= 0.99: # Simplified: any exit near 1.0 is a win
            fee_amount = fill.value * (self.winning_fee_bps / 10000.0)
            return Money(fee_amount, fill.currency)
        
        return Money(0, fill.currency)

    def __repr__(self):
        return f"PolymarketFeeModel(winning_fee_bps={self.winning_fee_bps})"
