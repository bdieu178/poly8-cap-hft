# Global Portfolio Manager & Analytical Architecture

To ensure the system continuously generates $3,000–$20,000 USD weekly and safely manages risk across overlapping 5m/15m markets, we will build an asynchronous **Global Portfolio Manager** in Rust. 

## 1. Core Architecture (Off Hot-Path)
The module will run as a standalone Rust binary (`portfolio_manager`) to ensure the primary `rust_executor` engine's latency remains uncompromised.
*   **Position Discovery:** It will continuously index the Gnosis Safe proxy wallet on the Polygon blockchain to detect all unsettled Polymarket ERC1155 tokens.
*   **Direct WS Connection:** Because the C++ hot-path ingestors only track the front-month market, the Portfolio Manager will establish its own direct WebSocket connection to Polymarket to stream L2 orderbooks for all older, overlapping tokens we hold.
*   **Tick-by-Tick EV Management:** As L2 updates arrive, it calculates the EV for every held position. If a position's EV drops below a threshold, it will independently sign and fire Gnosis Safe limit sell orders to the Polymarket CLOB to cut the loss.

## 2. Telemetry & Caching (Redis)
*   We will spin up a local **Redis** instance.
*   The `rust_executor` and `portfolio_manager` will publish ultra-fast JSON telemetry payloads to Redis channels (e.g., `pnl_ticks`, `ev_snapshots`, `order_latency`).
*   Redis will act as an in-memory buffer, preventing disk I/O bottlenecks in the trading loop.

## 3. Analytical Database (DuckDB / ClickHouse)
To understand our strategy's performance and tune our parameters to market dynamics, we need a high-performance OLAP (Analytical) database.
*   **Selection: DuckDB** (Highly Recommended)
    *   *Why:* DuckDB is the analytical equivalent of SQLite. It runs embedded directly inside the Rust data-pipeline process, requires zero external server management, and executes columnar analytical queries (like VWAP, Sharpe ratios, time-series aggregations) at lightning speed. It easily scales to gigabytes of tick data.
*   *Alternative: ClickHouse*
    *   *Why:* Industry standard for HFT tick data. Requires managing a standalone database server via Docker.

**Data Pipeline:** A dedicated Rust background thread will subscribe to the Redis streams, aggregate the tick-by-tick logs, and batch-insert them into the Analytical Database. This allows us to instantly query execution slippage, strategy EV drift, and fill-rates across millions of data points.

---
### Next Execution Steps
1. Spin up a local **Redis** instance via system packages/Docker.
2. Initialize a new Rust crate (`src/portfolio_manager`).
3. Implement the Redis pub/sub logging across our existing HFT stack.
4. Build the DuckDB aggregation pipeline and the EV management logic.
