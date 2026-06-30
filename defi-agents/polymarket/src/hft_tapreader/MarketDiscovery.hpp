#pragma once
#include <string>
#include <thread>
#include <atomic>
#include <memory>
#include <vector>
#include <map>
#include <unordered_map>
#include "ThreadSafeQueue.hpp"
#include "L2BookStruct.hpp"
#include "SharedMemoryManager.hpp"
#include "MarketIds.hpp"

// Manages discovery of active Polymarket CLOB token IDs via the Gamma API.
class MarketDiscovery {
public:
    MarketDiscovery(
        const std::string& asset_name, 
        std::vector<std::shared_ptr<ThreadSafeQueue<MarketIds>>> market_id_queues
    );

    ~MarketDiscovery();

    void Run();
    void Stop();

private:
    void DiscoveryLoop();
    uint64_t GetCurrentIntervalTimestamp(uint64_t interval_minutes);

    std::string asset_name_;
    std::atomic<bool> keep_running_;
    std::thread worker_thread_;

    // Queues to push new token discovery info to other threads.
    std::vector<std::shared_ptr<ThreadSafeQueue<MarketIds>>> market_id_queues_;
};

#include "SpscRingBuffer.hpp"
#include <mutex>

// Manages the WebSocket connection to Polymarket's CLOB.
class PolymarketBridge {
public:
    PolymarketBridge(
        L2BookStruct* book,
        std::shared_ptr<ThreadSafeQueue<MarketIds>> market_id_queue,
        SpscRingBuffer<L2BookStruct, 2048>* ring_buffer,
        std::mutex* ring_mutex
    );
    ~PolymarketBridge();

    void Run();
    void Stop();

private:
    void ConnectionLoop();
    void UpdateSHM();
    void UpdateSHM(int64_t poly_processing_latency_ns);
    void prune_distant_orders();
    
    L2BookStruct* shared_book_;
    SpscRingBuffer<L2BookStruct, 2048>* ring_buffer_;
    std::mutex* ring_mutex_;
    std::atomic<bool> keep_running_;
    std::thread worker_thread_;
    std::string ws_url_;

    // Local book state: asset_id -> {price -> size}
    std::unordered_map<std::string, std::map<double, double, std::greater<double>>> bids_;
    std::unordered_map<std::string, std::map<double, double>> asks_;

    // Counter for updates since last prune
    size_t update_count_since_last_prune = 0;
    static const size_t PRUNE_INTERVAL = 1000;

    // Queue to receive new token ID pairs from the MarketDiscovery thread.
    std::shared_ptr<ThreadSafeQueue<MarketIds>> market_id_queue_;
    MarketIds current_market_ids_;
};
