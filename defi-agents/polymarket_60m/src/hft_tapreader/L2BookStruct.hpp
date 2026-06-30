#pragma once
#include <atomic>
#include <cstdint>
#include <cstddef>
#include <algorithm>
#include <iterator>
#include <cstring>

constexpr size_t MAX_LEVELS = 10;
constexpr size_t MAX_POLY_LEVELS = 5;

struct PriceLevel {
    double price;
    double size;
};

// Seqlock protected L2/L4 Book for Zero-Copy inter-process reads
// Synchronized with Rust (shm.rs) and Python (live_tapreader.py)
struct L2BookStruct {
    // --- [0-15] ---
    // Sequence locks: Odd means writer is writing, Even means writer is done.
    std::atomic<uint64_t> hl_sequence;
    std::atomic<uint64_t> poly_sequence;
    
    // --- [16-343] Hyperliquid state (L2 Aggregated) ---
    uint64_t hl_timestamp;
    PriceLevel hl_bids[MAX_LEVELS];
    PriceLevel hl_asks[MAX_LEVELS];
    
    // --- [344-511] Polymarket UP Token state ---
    uint64_t poly_up_timestamp;
    PriceLevel poly_up_bids[MAX_POLY_LEVELS];
    PriceLevel poly_up_asks[MAX_POLY_LEVELS];
    
    // --- [512-679] Polymarket DOWN Token state ---
    uint64_t poly_down_timestamp;
    PriceLevel poly_down_bids[MAX_POLY_LEVELS];
    PriceLevel poly_down_asks[MAX_POLY_LEVELS];

    // --- [680-951] Discovery & Rotation ---
    double strike_price;
    uint64_t rotation_ts;
    char poly_up_id[128];
    char poly_down_id[128];
    
    // --- [952-983] Microstructure metrics ---
    double current_ofi;
    double execution_flow_rate; 
    double p_max_i; 
    double signed_flow_rate;

    // --- [984-999] Event flags ---
    uint32_t event_flags;
    uint32_t padding0; 
    uint64_t last_event_ts;

    // --- [1000-1015] Cognition Layer Feedback ---
    double regime_multiplier;
    uint32_t regime_state_enum; 
    uint32_t padding1; 

    // --- [1016-1031] Observability Metrics ---
    uint64_t last_update_local_ns; 
    uint64_t hot_path_latency_ns;
    int64_t hl_e2e_latency_ns;
    int64_t poly_processing_latency_ns;

    // --- [1032-1039] L4 Insights ---
    uint64_t hl_l4_height;
    
    // --- [1040-1047] Queue Counts ---
    uint32_t bid_order_count; 
    uint32_t ask_order_count;
    
    // --- [1048-1079] Scaling Alphas ---
    double whale_bid_size;   
    double whale_ask_size;   
    double bid_concentration;
    double ask_concentration;

    // --- [1080-1095] Queue Age Tracking ---
    uint64_t best_bid_ts;
    uint64_t best_ask_ts;

    // --- [1096-1151] Padding to maintain 1152-byte target ---
    uint32_t timeframe_minutes;
    uint32_t padding_final_u32;
    uint8_t padding_final[32];

    L2BookStruct() 
        : hl_sequence(0),
          poly_sequence(0),
          hl_timestamp(0),
          poly_up_timestamp(0),
          poly_down_timestamp(0),
          strike_price(0.0),
          rotation_ts(0),
          current_ofi(0.0),
          execution_flow_rate(0.0),
          p_max_i(0.0),
          signed_flow_rate(0.0),
          event_flags(0),
          padding0(0),
          last_event_ts(0),
          regime_multiplier(1.0),
          regime_state_enum(0),
          padding1(0),
          last_update_local_ns(0),
          hot_path_latency_ns(0),
          hl_e2e_latency_ns(0),
          poly_processing_latency_ns(0),
          hl_l4_height(0),
          bid_order_count(0),
          ask_order_count(0),
          whale_bid_size(0.0),
          whale_ask_size(0.0),
          bid_concentration(0.0),
          ask_concentration(0.0),
          best_bid_ts(0),
          best_ask_ts(0),
          timeframe_minutes(15),
          padding_final_u32(0)
    {
        for (size_t i = 0; i < MAX_LEVELS; ++i) {
            hl_bids[i] = {0.0, 0.0};
            hl_asks[i] = {0.0, 0.0};
        }
        for (size_t i = 0; i < MAX_POLY_LEVELS; ++i) {
            poly_up_bids[i] = {0.0, 0.0};
            poly_up_asks[i] = {0.0, 0.0};
            poly_down_bids[i] = {0.0, 0.0};
            poly_down_asks[i] = {0.0, 0.0};
        }
        std::memset(poly_up_id, 0, sizeof(poly_up_id));
        std::memset(poly_down_id, 0, sizeof(poly_down_id));
        std::memset(padding_final, 0, sizeof(padding_final));
    }


    // Custom copy constructor
    L2BookStruct(const L2BookStruct& other) {
        hl_sequence.store(other.hl_sequence.load(std::memory_order_relaxed), std::memory_order_relaxed);
        poly_sequence.store(other.poly_sequence.load(std::memory_order_relaxed), std::memory_order_relaxed);
        hl_timestamp = other.hl_timestamp;
        std::copy(std::begin(other.hl_bids), std::end(other.hl_bids), std::begin(hl_bids));
        std::copy(std::begin(other.hl_asks), std::end(other.hl_asks), std::begin(hl_asks));
        poly_up_timestamp = other.poly_up_timestamp;
        std::copy(std::begin(other.poly_up_bids), std::end(other.poly_up_bids), std::begin(poly_up_bids));
        std::copy(std::begin(other.poly_up_asks), std::end(other.poly_up_asks), std::begin(poly_up_asks));
        poly_down_timestamp = other.poly_down_timestamp;
        std::copy(std::begin(other.poly_down_bids), std::end(other.poly_down_bids), std::begin(poly_down_bids));
        std::copy(std::begin(other.poly_down_asks), std::end(other.poly_down_asks), std::begin(poly_down_asks));
        strike_price = other.strike_price;
        rotation_ts = other.rotation_ts;
        std::copy(std::begin(other.poly_up_id), std::end(other.poly_up_id), std::begin(poly_up_id));
        std::copy(std::begin(other.poly_down_id), std::end(other.poly_down_id), std::begin(poly_down_id));
        current_ofi = other.current_ofi;
        execution_flow_rate = other.execution_flow_rate;
        p_max_i = other.p_max_i;
        signed_flow_rate = other.signed_flow_rate;
        event_flags = other.event_flags;
        padding0 = other.padding0;
        last_event_ts = other.last_event_ts;
        regime_multiplier = other.regime_multiplier;
        regime_state_enum = other.regime_state_enum;
        padding1 = other.padding1;
        last_update_local_ns = other.last_update_local_ns;
        hot_path_latency_ns = other.hot_path_latency_ns;
        hl_e2e_latency_ns = other.hl_e2e_latency_ns;
        poly_processing_latency_ns = other.poly_processing_latency_ns;
        hl_l4_height = other.hl_l4_height;
        bid_order_count = other.bid_order_count;
        ask_order_count = other.ask_order_count;
        whale_bid_size = other.whale_bid_size;
        whale_ask_size = other.whale_ask_size;
        bid_concentration = other.bid_concentration;
        ask_concentration = other.ask_concentration;
        best_bid_ts = other.best_bid_ts;
        best_ask_ts = other.best_ask_ts;
        timeframe_minutes = other.timeframe_minutes;
        padding_final_u32 = other.padding_final_u32;
        std::copy(std::begin(other.padding_final), std::end(other.padding_final), std::begin(padding_final));
    }

    // Custom copy assignment operator
    L2BookStruct& operator=(const L2BookStruct& other) {
        if (this != &other) {
            hl_sequence.store(other.hl_sequence.load(std::memory_order_relaxed), std::memory_order_relaxed);
            poly_sequence.store(other.poly_sequence.load(std::memory_order_relaxed), std::memory_order_relaxed);
            hl_timestamp = other.hl_timestamp;
            std::copy(std::begin(other.hl_bids), std::end(other.hl_bids), std::begin(hl_bids));
            std::copy(std::begin(other.hl_asks), std::end(other.hl_asks), std::begin(hl_asks));
            poly_up_timestamp = other.poly_up_timestamp;
            std::copy(std::begin(other.poly_up_bids), std::end(other.poly_up_bids), std::begin(poly_up_bids));
            std::copy(std::begin(other.poly_up_asks), std::end(other.poly_up_asks), std::begin(poly_up_asks));
            poly_down_timestamp = other.poly_down_timestamp;
            std::copy(std::begin(other.poly_down_bids), std::end(other.poly_down_bids), std::begin(poly_down_bids));
            std::copy(std::begin(other.poly_down_asks), std::end(other.poly_down_asks), std::begin(poly_down_asks));
            strike_price = other.strike_price;
            rotation_ts = other.rotation_ts;
            std::copy(std::begin(other.poly_up_id), std::end(other.poly_up_id), std::begin(poly_up_id));
            std::copy(std::begin(other.poly_down_id), std::end(other.poly_down_id), std::begin(poly_down_id));
            current_ofi = other.current_ofi;
            execution_flow_rate = other.execution_flow_rate;
            p_max_i = other.p_max_i;
            signed_flow_rate = other.signed_flow_rate;
            event_flags = other.event_flags;
            padding0 = other.padding0;
            last_event_ts = other.last_event_ts;
            regime_multiplier = other.regime_multiplier;
            regime_state_enum = other.regime_state_enum;
            padding1 = other.padding1;
            last_update_local_ns = other.last_update_local_ns;
            hot_path_latency_ns = other.hot_path_latency_ns;
            hl_e2e_latency_ns = other.hl_e2e_latency_ns;
            poly_processing_latency_ns = other.poly_processing_latency_ns;
            hl_l4_height = other.hl_l4_height;
            bid_order_count = other.bid_order_count;
            ask_order_count = other.ask_order_count;
            whale_bid_size = other.whale_bid_size;
            whale_ask_size = other.whale_ask_size;
            bid_concentration = other.bid_concentration;
            ask_concentration = other.ask_concentration;
            best_bid_ts = other.best_bid_ts;
            best_ask_ts = other.best_ask_ts;
            timeframe_minutes = other.timeframe_minutes;
            padding_final_u32 = other.padding_final_u32;
            std::copy(std::begin(other.padding_final), std::end(other.padding_final), std::begin(padding_final));
        }
        return *this;
    }
};

static_assert(sizeof(L2BookStruct) == 1152, "L2BookStruct size mismatch. Alignment error.");
static_assert(offsetof(L2BookStruct, strike_price) == 680, "L2BookStruct: strike_price offset mismatch.");
static_assert(offsetof(L2BookStruct, poly_up_id) == 696, "L2BookStruct: poly_up_id offset mismatch.");
static_assert(offsetof(L2BookStruct, current_ofi) == 952, "L2BookStruct: current_ofi offset mismatch.");
