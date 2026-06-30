# 2026-05-09 Status Updates & Notes (Part C)

## Comprehensive Codebase Trace & Risk Assessment

Based on a deep-dive trace of the full codebase—specifically probing the boundaries between the asynchronous Python ingestion, the POSIX Shared Memory interface, and the Rust execution spin-loop—I have mapped the system's true behavior under the hood. 

While the "happy path" orchestration is robust, the trace has surfaced several critical **edge cases and live deployment risks** that contradict the safety assumptions outlined in the recent changelog.

---

### 1. Codebase Trace: The Hidden Asynchronous Boundaries

**A. The Hyperliquid L4 Bridge (`live_tapreader.py`)**
*   **Behavior**: Maintains a high-bandwidth (64MB message limit) gRPC stream to Quicknode. It incrementally builds an L4 state, tracking individual Order IDs (OIDs), and aggregates them into the `MAX_LEVELS` (10) for SHM.
*   **Boundary Execution**: It calculates Order Flow Imbalance (OFI) and Execution Flow Rate ($dV/dt$). If timestamps resolve to the exact same millisecond, it hardcodes `dt_ms = 1` to prevent division by zero before applying an EWMA smooth.

**B. The Polymarket L2 Bridge (`live_tapreader.py`)**
*   **Behavior**: Polls the Gamma API to discover active `clobTokenIds` based on the time-based market slug, then subscribes to the CLOB WebSocket.
*   **Boundary Execution**: It parses `book` (snapshots) and `price_changes` (deltas) events, directly writing the data into the `poly_up` and `poly_down` structs in Shared Memory based on the `asset_id`.

**C. The Rust Execution Spin-Loop (`rust_executor/src/main.rs` & `strategy.rs`)**
*   **Behavior**: A dedicated thread runs a `std::hint::spin_loop()` checking the `sequence` integer in SHM. If the lock is clean, it copies the 912-byte struct and evaluates the mathematical strategy.
*   **Boundary Execution**: Calculates $P_{theo}$ using the Hawkes intensity (decaying via $\Delta t$) and the execution flow EWMA. If $P_{theo}$ diverges from Polymarket L2 by > 5%, it dynamically sizes an order using the Kelly Criterion and submits it asynchronously via the `alloy` EIP-712 signer.

---

### 2. Ideated Tests (Unit & Integration Edge Cases)

To achieve the "Boundary Verification" standard mandated in your project rules, the following tests must be authored:

1.  **Integration (Zero-Time Execution Spike):**
    *   *Scenario:* Hyperliquid sends a massive L4 diff with the *exact same timestamp* as the previous packet.
    *   *Test:* Verify that `dt_ms = 1` combined with a large `delta_bid` does not cause `execution_flow_rate` to spike to infinity and prematurely trigger the `p_max_i` fading logic.
2.  **Unit (Unconstrained Kelly Sell):**
    *   *Scenario:* We hold `1.5` UP tokens. The market bid size is `100.0` tokens.
    *   *Test:* Verify that the `fire_trade(Side::Sell)` function correctly bounds the order size to `1.5`, rather than attempting to sell a fraction of the `100.0` top-of-book size (which would result in exchange rejection for insufficient balance).
3.  **Unit (Stale Collateral State):**
    *   *Scenario:* The Python Web3 RPC connection fails, stalling the `acc.last_update_ts`.
    *   *Test:* Verify the Rust executor refuses to trade if `SystemTime::now()` is more than 30 seconds ahead of `acc.last_update_ts`. (Currently, this logic does not exist).
4.  **Unit (Deep-Book Polymarket Update):**
    *   *Scenario:* A `price_changes` event arrives for Polymarket L2 with a price *worse* than the current top-of-book, but with `size > 0`.
    *   *Test:* Assert that this update modifies `p_bids[index > 0]` and does *not* overwrite `p_bids[0]` (Top of Book).

---

### 3. Critical Risks for Live Deployment (BLOCKERS)

If graduated to live trading right now, the system faces severe behavioral risks:

🚨 **Risk 1: Top-of-Book Data Corruption (The "Clobber" Bug)**
*   **Location:** `live_tapreader.py` (Lines ~378-386)
*   **Issue:** When processing Polymarket `price_changes`, the logic states: `if size > 0 or price == p_bids[0].price: p_bids[0].price, p_bids[0].size = price, size`. 
*   **Impact:** If an order is placed at the 5th level of the order book (e.g., $0.01), `size > 0` evaluates to true, and it **overwrites the top-of-book** with $0.01. The Rust executor will instantly see a massive pricing anomaly and fire a false arbitrage trade.

🚨 **Risk 2: Synchronous Thread Blocking in the HFT Spin-Loop**
*   **Location:** `rust_executor/src/main.rs` (Lines ~112-132)
*   **Issue:** Inside the `std::hint::spin_loop()`, there is a block of code that runs every 60 seconds to fetch new tokens: `rt.block_on(GammaClient::default().market_by_slug(...))`.
*   **Impact:** `block_on` pauses the entire thread while waiting for an HTTP response from the Gamma REST API (100ms - 500ms). During this freeze, the seqlock is ignored, Hawkes intensity stops decaying, and the system is entirely blind to the market.

🚨 **Risk 3: Oversized Sell Orders (Unbounded Liquidation)**
*   **Location:** `rust_executor/src/strategy.rs` (Lines 111-118)
*   **Issue:** In `fire_trade`, the sell order sizing logic is: `(top_size * kelly_fraction.abs()).max(0.0).min(top_size)`. It completely ignores `acc.up_position` or `acc.down_position`. 
*   **Impact:** The agent will attempt to sell a percentage of the *market maker's bid size* rather than the tokens it actually owns. This guarantees an `Insufficient Balance` error on every profitable exit, trapping the agent in the position until expiration.

🚨 **Risk 4: Phantom MEV Gas Oracle**
*   **Location:** `main.rs` and `gas_oracle.rs`
*   **Issue:** The `GasOracle` is instantiated and polls Polygon base/priority fees, but it is only used in a `println!` statement. The actual `priority_fee_bps` passed to the `PolymarketClient` is statically hardcoded to 10 or 50. 
*   **Impact:** The system believes it is bidding for block inclusion during high-intensity events, but it is actually just overpaying the Polymarket protocol fee, providing zero latency advantage on the blockchain.

### Recommendation
**Do not engage real capital.** We must fix the WebSocket parsing logic (`live_tapreader.py`), move the Gamma token discovery out of the Rust spin-loop to a background thread (`main.rs`), and properly bound the Sell order logic (`strategy.rs`) before graduation.