#pragma once
#include <string>
#include <thread>
#include <atomic>
#include <future>
#include <cpr/cpr.h>
#include "AccountStateStruct.hpp"
#include "SharedMemoryManager.hpp"
#include "ThreadSafeQueue.hpp"
#include "MarketIds.hpp"

// Forward declaration
class PolymarketBridge;

// Manages the 1Hz polling of the Polygon RPC to fetch and update account balances.
class AccountSync {
public:
    AccountSync(
        const std::string& asset_name, 
        const std::string& rpc_url,
        const std::string& wallet_addr,
        std::shared_ptr<ThreadSafeQueue<MarketIds>> market_id_queue
    );

    ~AccountSync();

    void Run();
    void Stop();

private:
    void SyncLoop();
    cpr::AsyncResponse FetchBalanceAsync(const std::string& contract_address, const std::string& data_payload);

    std::string asset_name_;
    std::string rpc_url_;
    std::string wallet_address_;
    std::string pusd_address_;
    std::string ctf_address_;
    
    std::atomic<bool> keep_running_;
    std::thread worker_thread_;
    
    // Allows this thread to get the latest token IDs for balance checking
    std::shared_ptr<ThreadSafeQueue<MarketIds>> market_id_queue_;
    MarketIds current_market_ids_;

    SharedMemoryManager<AccountStateStruct> shm_manager_;
};
