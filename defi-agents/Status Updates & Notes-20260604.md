# Status Update - 2026-06-04

## Progress Made
- Fixed the empty-book clamping bug where `calculate_buy_trade_usd` defaulted to a price of `$0.01` when the orderbook was thin, which triggered silent aborts as the resulting order sizes fell under Polymarket's 5.0 share minimum limit.
- Modified the execution logic to use theoretical fallback prices when the orderbook is empty.
- Updated `config.toml` to disable pure market making (`market_making = false`) and switched to directional betting, lowering `min_edge_usd` to `$0.01` to capture EV off the Hyperliquid L4 signals more efficiently on sparse 5m/15m markets.
- Orders are now verified to be successfully hitting the Polymarket exchange.
- Decoupled portfolio EV risk tracking by routing real-time hot-path telemetry (`p_theo_up`, `p_theo_down`, `equity`) directly from the execution loop. Fixed logic in `portfolio_manager` to evaluate EV stop-loss/trailing-stops using the model's actual probability outputs, correcting severe negative EV false alarms.

## Next Steps / Active Tasks
- Continue monitoring the latest trading data post-switch to directional betting.
- **Portfolio Management Module**: Deploy and verify the secondary `portfolio_manager` daemon and sync pipeline. Check live metrics stream for database insertion rates.
