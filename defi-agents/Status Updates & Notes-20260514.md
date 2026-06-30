# Status Update: May 14, 2026

**Completed: Unified C++ HFT Ingestor Architecture**

The hybrid Python/Rust/C++ ingestion pipeline has been deprecated and replaced with a single, high-performance, multi-threaded C++ binary (`unified_ingestor`).

**Key Engineering Decision: Full Switch to Unified C++**
Following the evaluation of the [20260513 C++ Counter-Proposal](docs/eng-design/planning/live_tapreader_refactor/cpp_counter_proposal/20260513_cpp_proposal.md), we have decided to consolidate all data ingestion into C++. 
- **Rationale:** Minimizing "photon-to-strategy" latency requires a single, predictable memory model. C++'s proven performance in the Hyperliquid "Hot Path" is now extended to account sync and market discovery, eliminating the overhead of cross-language Shared Memory (SHM) synchronization and the complexity of maintaining redundant Python/Rust ingestors.
- **Impact:** 
    - Elimination of `ctypes` and `tonic` transport bottlenecks.
    - Simplified supervisor logic (fewer moving parts).
    - Unified resilience patterns (standardized exponential backoff).

**Technical Achievements:**
- **Compilation & Stability:** Resolved critical C++ compilation errors related to `__int128` type mismatches and ABI padding.
- **Resilience:** Implemented exponential backoff for all network connections (gRPC, WS, HTTP).
- **Verification:** Successfully ran the complete test suite (12/12 tests PASSED), covering SHM Seqlock integrity and Polymarket L2 parsing.

**Next Steps:**
- Update `scripts/launch_isolated_pipeline.sh` to transition to the C++ ingestor.
- Final integration test with the Rust Executor in the `polymask` namespace.
