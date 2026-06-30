#pragma once
#include <atomic>
#include <cstdint>

// Memory layout for Polymarket account state.
// MUST be kept in sync with the Rust definition in `shm.rs`.
// Total size: 64 bytes
struct AccountStateStruct {
    // --- [0-7] ---
    std::atomic<uint64_t> sequence;

    // --- [8-15] ---
    double available_collateral;

    // --- [16-23] ---
    double total_equity;
    
    // --- [24-31] ---
    double total_maint_margin; // Not currently used, but reserved

    // --- [32-39] ---
    double up_position;

    // --- [40-47] ---
    double down_position;

    // --- [48-55] ---
    // The next nonce to be used for an order submission.
    // Atomically incremented by the Rust executor.
    std::atomic<uint64_t> next_nonce;
    
    // --- [56-63] ---
    // Millisecond timestamp of the last successful balance update.
    uint64_t last_update_ts;
};

// Verify struct size and layout to prevent memory corruption.
static_assert(sizeof(AccountStateStruct) == 64, "AccountStateStruct size mismatch. Alignment error.");
static_assert(offsetof(AccountStateStruct, up_position) == 32, "AccountStateStruct: up_position offset mismatch.");
static_assert(offsetof(AccountStateStruct, next_nonce) == 48, "AccountStateStruct: next_nonce offset mismatch.");
