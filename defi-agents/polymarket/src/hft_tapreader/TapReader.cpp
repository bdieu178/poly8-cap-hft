#include "SharedMemoryManager.hpp"
#include "AccountStateStruct.hpp"
#include "L2BookStruct.hpp"
#include "ThreadSafeQueue.hpp"
#include "MarketDiscovery.hpp"
#include "AccountSync.hpp"
#include "PolymarketBridge.hpp"
#include "orderbook.grpc.pb.h"
#include "HotPathParser.hpp"
#include "SpscRingBuffer.hpp"
#include <mutex>

#include <grpcpp/grpcpp.h>
#include <nlohmann/json.hpp>
#include <iostream>
#include <thread>
#include <chrono>
#include <vector>
#include <string>
#include <csignal>
#include <atomic>
#include <map>
#include <unordered_map>
#include <iomanip>
#include <sstream>
#include <memory>

#include "Logger.hpp"
#include "SequenceGuard.hpp"

using json = nlohmann::json;
using grpc::Channel;
using grpc::ClientContext;
using grpc::ClientReader;
using hyperliquid::OrderBookStreaming;
using hyperliquid::L4BookRequest;
using hyperliquid::L4BookUpdate;
using hyperliquid::L4BookSnapshot;
using hyperliquid::L4BookDiff;
using hyperliquid::L4Order;

std::atomic<bool> keep_running(true);
void signal_handler(int signal) {
    LOG_OUT << "[SIGNAL] Received signal " << signal << ". Initiating shutdown." << std::endl;
    keep_running = false;
}

struct InternalOrder {
    double px;
    double sz;
    uint64_t ts;
    uint64_t oid;
    std::string user;
};

class L4BookManager {
public:
    std::unordered_map<uint64_t, InternalOrder> bids;
    std::unordered_map<uint64_t, InternalOrder> asks;
    std::map<double, double, std::greater<double>> bid_levels;
    std::map<double, double> ask_levels;
    uint64_t height = 0;
    uint64_t time = 0;

    // Pre-calculated metrics to minimize lock hold time
    uint32_t bid_order_count = 0;
    uint32_t ask_order_count = 0;
    double whale_bid_size = 0.0;
    double whale_ask_size = 0.0;
    double bid_concentration = 0.0;
    double ask_concentration = 0.0;
    uint64_t best_bid_ts = 0;
    uint64_t best_ask_ts = 0;

    static const size_t MAX_ORDERS_TO_TRACK = 10000; 
    
    size_t diff_count_since_last_clear = 0;
    static const size_t CLEAR_INTERVAL_DIFFS = 5000; 

    void apply_snapshot(const L4BookSnapshot& snapshot) {
        bids.clear(); asks.clear(); bid_levels.clear(); ask_levels.clear();
        height = snapshot.height(); time = snapshot.time();
        for (const auto& o : snapshot.bids()) add_order(o, true);
        for (const auto& o : snapshot.asks()) add_order(o, false);
        update_queue_metrics();
    }

    void apply_diff(const L4BookDiff& diff, double& acc_flow, double& acc_ofi, double& signed_flow) {
        height = diff.height(); time = diff.time();
        
        diff_count_since_last_clear++;
        if (diff_count_since_last_clear >= CLEAR_INTERVAL_DIFFS) {
            prune_distant_orders();
            diff_count_since_last_clear = 0;
        }
        try {
            double prev_best_bid_px = 0.0;
            double prev_best_bid_sz = 0.0;
            if (!bid_levels.empty()) {
                prev_best_bid_px = bid_levels.begin()->first;
                prev_best_bid_sz = bid_levels.begin()->second;
            }
            double prev_best_ask_px = 1e9;
            double prev_best_ask_sz = 0.0;
            if (!ask_levels.empty()) {
                prev_best_ask_px = ask_levels.begin()->first;
                prev_best_ask_sz = ask_levels.begin()->second;
            }

            json data = json::parse(diff.data());
            if (data.contains("book_diffs")) {
                for (const auto& d : data["book_diffs"]) {
                    try {
                        if (!d.contains("oid") || !d["oid"].is_number_integer()) continue;
                        uint64_t oid = d["oid"].get<uint64_t>();

                        if (!d.contains("side") || !d["side"].is_string()) continue;
                        std::string side = d["side"].get<std::string>();
                        
                        std::string sz_str = "";
                        if (d.contains("raw_book_diff")) {
                            const auto& raw_diff = d["raw_book_diff"];
                            if (raw_diff.is_string() && raw_diff.get<std::string>() == "remove") {
                                sz_str = "0.0";
                            } else if (raw_diff.is_object()) {
                                if (raw_diff.contains("update") && raw_diff["update"].is_object() && raw_diff["update"].contains("newSz") && raw_diff["update"]["newSz"].is_string()) {
                                    sz_str = raw_diff["update"]["newSz"].get<std::string>();
                                } else if (raw_diff.contains("new") && raw_diff["new"].is_object() && raw_diff["new"].contains("sz") && raw_diff["new"]["sz"].is_string()) {
                                    sz_str = raw_diff["new"]["sz"].get<std::string>();
                                } else if (raw_diff.contains("old") && raw_diff["old"].is_object() && raw_diff["old"].contains("sz") && raw_diff["old"]["sz"].is_string()) {
                                    sz_str = raw_diff["old"]["sz"].get<std::string>();
                                }
                            }
                        } else if (d.contains("sz") && d["sz"].is_string()) {
                            sz_str = d["sz"].get<std::string>();
                        } else if (d.contains("size") && d["size"].is_string()) {
                            sz_str = d["size"].get<std::string>();
                        }
                        
                        if (sz_str.empty()) continue;
                        double sz = std::stod(sz_str);
                        update_order(oid, sz, d, (side == "B"), acc_flow, acc_ofi, signed_flow);
                    } catch (...) {}
                }
            }
            if (data.contains("order_statuses")) {
                for (const auto& s : data["order_statuses"]) {
                    try {
                        if (!s.contains("status") || !s["status"].is_string()) continue;
                        std::string status = s["status"].get<std::string>();

                        if (status == "Filled" || status == "Canceled" || status == "Rejected") {
                            if (s.contains("order") && s["order"].is_object()) {
                                const auto& order_obj = s["order"];
                                if (order_obj.contains("oid") && order_obj["oid"].is_number_integer()) {
                                    uint64_t oid = order_obj["oid"].get<uint64_t>();
                                    remove_order(oid, acc_flow, acc_ofi, signed_flow);
                                }
                           }
                       }
                    } catch (...) {}
                }
            }
            update_queue_metrics();

            double curr_best_bid_px = 0.0;
            double curr_best_bid_sz = 0.0;
            if (!bid_levels.empty()) {
                curr_best_bid_px = bid_levels.begin()->first;
                curr_best_bid_sz = bid_levels.begin()->second;
            }
            double curr_best_ask_px = 1e9;
            double curr_best_ask_sz = 0.0;
            if (!ask_levels.empty()) {
                curr_best_ask_px = ask_levels.begin()->first;
                curr_best_ask_sz = ask_levels.begin()->second;
            }

            double delta_w_b = 0.0;
            if (curr_best_bid_px > prev_best_bid_px) {
                delta_w_b = curr_best_bid_sz;
            } else if (curr_best_bid_px == prev_best_bid_px) {
                delta_w_b = curr_best_bid_sz - prev_best_bid_sz;
            } else {
                delta_w_b = -prev_best_bid_sz;
            }

            double delta_w_a = 0.0;
            if (curr_best_ask_px < prev_best_ask_px) {
                delta_w_a = curr_best_ask_sz;
            } else if (curr_best_ask_px == prev_best_ask_px) {
                delta_w_a = curr_best_ask_sz - prev_best_ask_sz;
            } else {
                delta_w_a = -prev_best_ask_sz;
            }

            acc_ofi += (delta_w_b - delta_w_a);
        } catch (...) {}
    }

    void aggregate(L2BookStruct* shared_book) {
        int i = 0;
        for (auto const& [px, sz] : bid_levels) {
            if (i >= MAX_LEVELS) break;
            shared_book->hl_bids[i].price = px; shared_book->hl_bids[i].size = sz; i++;
        }
        while (i < MAX_LEVELS) { shared_book->hl_bids[i] = {0.0, 0.0}; i++; }
        i = 0;
        for (auto const& [px, sz] : ask_levels) {
            if (i >= MAX_LEVELS) break;
            shared_book->hl_asks[i].price = px; shared_book->hl_asks[i].size = sz; i++;
        }
        while (i < MAX_LEVELS) { shared_book->hl_asks[i] = {0.0, 0.0}; i++; }
        shared_book->hl_l4_height = height;

        shared_book->bid_order_count = bid_order_count;
        shared_book->ask_order_count = ask_order_count;
        shared_book->whale_bid_size = whale_bid_size;
        shared_book->whale_ask_size = whale_ask_size;
        shared_book->bid_concentration = bid_concentration;
        shared_book->ask_concentration = ask_concentration;
        shared_book->best_bid_ts = best_bid_ts;
        shared_book->best_ask_ts = best_ask_ts;
    }

    double get_top_5_depth_sum() const {
        double depth_sum = 0.0;
        int i = 0;
        for (auto const& [px, sz] : bid_levels) {
            if (i >= 5) break;
            depth_sum += sz;
            i++;
        }
        i = 0;
        for (auto const& [px, sz] : ask_levels) {
            if (i >= 5) break;
            depth_sum += sz;
            i++;
        }
        return depth_sum;
    }

private:
    void prune_distant_orders() {
        if (bid_levels.empty() || ask_levels.empty()) return;
        double mid = (bid_levels.begin()->first + ask_levels.begin()->first) / 2.0;
        double prune_threshold = mid * 0.05; 

        auto prune = [&](auto& orders, auto& levels) {
            size_t removed_count = 0;
            for (auto it = orders.begin(); it != orders.end(); ) {
                double dist = std::abs(it->second.px - mid);
                if (dist > prune_threshold) {
                    double px = it->second.px; double sz = it->second.sz;
                    levels[px] -= sz; if (levels[px] <= 1e-9) levels.erase(px);
                    it = orders.erase(it);
                    removed_count++;
                } else {
                    ++it;
                }
            }
            return removed_count;
        };
        size_t total_removed = prune(bids, bid_levels) + prune(asks, ask_levels);
        if (total_removed > 0) {
            LOG_OUT << "[L4BookManager] Pruned " << total_removed << " distant orders. Bids: " << bids.size() << ", Asks: " << asks.size() << std::endl;
        }
    }
    void add_order(const L4Order& o, bool is_bid) {
        double px = std::stod(o.limit_px()); double sz = std::stod(o.sz()); uint64_t oid = o.oid();
        InternalOrder io = {px, sz, o.timestamp(), oid, o.user()};
        if (is_bid) { bids[oid] = io; bid_levels[px] += sz; }
        else { asks[oid] = io; ask_levels[px] += sz; }
    }
    void update_order(uint64_t oid, double sz, const json& d, bool is_bid, double& acc_flow, double& acc_ofi, double& signed_flow) {
        auto& orders = is_bid ? bids : asks;
        double old_sz = 0.0; double px = 0.0;
        auto it = orders.find(oid);
        if (it != orders.end()) {
            old_sz = it->second.sz; px = it->second.px;
            if (is_bid) { bid_levels[px] -= old_sz; if (bid_levels[px] <= 1e-9) bid_levels.erase(px); }
            else { ask_levels[px] -= old_sz; if (ask_levels[px] <= 1e-9) ask_levels.erase(px); }
        } else {
            if (d.contains("limit_px") && d["limit_px"].is_string()) px = std::stod(d["limit_px"].get<std::string>());
            else if (d.contains("px") && d["px"].is_string()) px = std::stod(d["px"].get<std::string>());
            else if (d.contains("px") && d["px"].is_number()) px = d["px"].get<double>();
        }
        if (sz <= 1e-9) { orders.erase(oid); }
        else {
            orders[oid] = {px, sz, (uint64_t)d.value("timestamp", time), oid, d.value("user", "0x0")};
            if (is_bid) bid_levels[px] += sz; else ask_levels[px] += sz;
        }
        double delta_sz = sz - old_sz; acc_flow += std::abs(delta_sz);
        if (is_bid) { signed_flow += delta_sz; }
        else { signed_flow -= delta_sz; }
    }
    void remove_order(uint64_t oid, double& acc_flow, double& acc_ofi, double& signed_flow) {
        auto process_removal = [&](auto& orders, auto& levels, bool is_bid) {
            if (orders.count(oid)) {
                double px = orders[oid].px; double sz = orders[oid].sz;
                levels[px] -= sz; if (levels[px] <= 1e-9) levels.erase(px);
                orders.erase(oid);
                acc_flow += sz;
                if (is_bid) { signed_flow -= sz; }
                else { signed_flow += sz; }
                return true;
            }
            return false;
        };
        if (!process_removal(bids, bid_levels, true)) process_removal(asks, ask_levels, false);
    }
    void update_queue_metrics() {
        auto process_levels = [&](auto& levels, bool is_bid) {
            if (levels.empty()) {
                if (is_bid) { bid_order_count = 0; whale_bid_size = 0; bid_concentration = 0; best_bid_ts = 0; }
                else { ask_order_count = 0; whale_ask_size = 0; ask_concentration = 0; best_ask_ts = 0; }
                return;
            }
            double best_px = levels.begin()->first;
            uint32_t count = 0; double whale_sz = 0; double total_top_sz = levels.at(best_px);
            uint64_t oldest_ts = std::numeric_limits<uint64_t>::max();
            auto& orders = is_bid ? bids : asks;
            for (auto const& [oid, o] : orders) {
                if (o.px == best_px) { 
                    count++; 
                    if (o.sz > whale_sz) whale_sz = o.sz; 
                    if (o.ts < oldest_ts) oldest_ts = o.ts;
                }
            }
            if (oldest_ts == std::numeric_limits<uint64_t>::max()) oldest_ts = 0;
            
            if (is_bid) {
                bid_order_count = count; whale_bid_size = whale_sz;
                bid_concentration = total_top_sz > 0 ? whale_sz / total_top_sz : 0;
                best_bid_ts = oldest_ts;
            } else {
                ask_order_count = count; whale_ask_size = whale_sz;
                ask_concentration = total_top_sz > 0 ? whale_sz / total_top_sz : 0;
                best_ask_ts = oldest_ts;
            }
        };
        process_levels(bid_levels, true);
        process_levels(ask_levels, false);
    }
};

class GRPCIngestor {
private:
    L2BookStruct* shared_book_; L4BookManager l4_manager_;
    std::unique_ptr<OrderBookStreaming::Stub> stub_; std::string coin_;
    double acc_flow_ = 0.0; double acc_ofi_ = 0.0; double signed_flow_ = 0.0; double max_I_ = 0.0;
    const char* auth_token;
    bool event_pending_ = false;
    double hl_depth_ema_ = 0.0;

    // SPSC Ring Buffer members
    SpscRingBuffer<L2BookStruct, 2048>* ring_buffer_;
    std::mutex* ring_mutex_;

public:
    GRPCIngestor(L2BookStruct* book, std::shared_ptr<Channel> channel, const std::string& coin,
                 SpscRingBuffer<L2BookStruct, 2048>* ring_buffer, std::mutex* ring_mutex)
        : shared_book_(book), stub_(OrderBookStreaming::NewStub(channel)), coin_(coin),
          ring_buffer_(ring_buffer), ring_mutex_(ring_mutex) {}

    void Run() {
        pin_thread_to_core(2);
        char* token = std::getenv("HYPERLIQUID_AUTH_TOKEN");
        auth_token = token ? token : nullptr;
        int backoff_ms = 1000;
        std::string upper_coin = coin_;
        for (auto & c: upper_coin) c = toupper(c);

        while (keep_running) {
            L4BookRequest request; request.set_coin(upper_coin);
            ClientContext context;
            context.AddMetadata("content-type", "application/grpc");
            if (auth_token) {
                std::string token_str(auth_token);
                token_str.erase(token_str.find_last_not_of(" \n\r\t") + 1);
                context.AddMetadata("x-token", token_str);
                context.AddMetadata("authorization", "Bearer " + token_str);
            }
            auto reader = stub_->StreamL4Book(&context, request);
            LOG_OUT << "[GRPCIngestor] Connected to Hyperliquid L4 for " << upper_coin << ". Streaming..." << std::endl;

            L4BookUpdate update;
            auto last_flush = std::chrono::steady_clock::now();

            while (keep_running && reader->Read(&update)) {
                backoff_ms = 1000;
                auto t_recv = std::chrono::high_resolution_clock::now();
                if (update.has_snapshot()) {
                    LOG_OUT << "[GRPCIngestor] Received L4 Snapshot." << std::endl;
                    l4_manager_.apply_snapshot(update.snapshot()); acc_flow_ = 0.0; acc_ofi_ = 0.0; signed_flow_ = 0.0;
                } else if (update.has_diff()) {
                    l4_manager_.apply_diff(update.diff(), acc_flow_, acc_ofi_, signed_flow_);
                }
                event_pending_ = true;
                auto t_flush = std::chrono::steady_clock::now();
                if (std::chrono::duration_cast<std::chrono::milliseconds>(t_flush - last_flush).count() >= 10) {
                    UpdateSharedMemory(t_recv, t_flush); last_flush = t_flush;
                }
            }
            if (keep_running) {
                grpc::Status status = reader->Finish();
                LOG_ERR << "[GRPCIngestor] Stream closed for " << upper_coin << ". Code: " << status.error_code() << ". Reconnecting in " << backoff_ms << "ms..." << std::endl;
                std::this_thread::sleep_for(std::chrono::milliseconds(backoff_ms));
                backoff_ms = std::min(backoff_ms * 2, 30000);
            }
        }
    }

    void UpdateSharedMemory(std::chrono::high_resolution_clock::time_point t_recv, std::chrono::steady_clock::time_point t_flush) {
        static auto last_flush_real = std::chrono::steady_clock::now();
        auto now_real = std::chrono::steady_clock::now();
        double dt_wall = std::chrono::duration_cast<std::chrono::microseconds>(now_real - last_flush_real).count() / 1000000.0;
        if (dt_wall < 0.001) dt_wall = 0.01; 
        last_flush_real = now_real;

        std::lock_guard<std::mutex> lock(*ring_mutex_);
        try {
            // Increment hl_sequence monotonically for diagnostic/observability sequencing
            uint64_t seq = shared_book_->hl_sequence.load(std::memory_order_relaxed);
            shared_book_->hl_sequence.store(seq + 1, std::memory_order_relaxed);

            shared_book_->hl_timestamp = l4_manager_.time;
            
            // Reference Venue (Hyperliquid) Native Depth Normalization (Topic 1)
            double l1_depth = 0.0;
            if (!l4_manager_.bid_levels.empty()) {
                l1_depth += l4_manager_.bid_levels.begin()->second;
            }
            if (!l4_manager_.ask_levels.empty()) {
                l1_depth += l4_manager_.ask_levels.begin()->second;
            }
            if (hl_depth_ema_ < 0.001) {
                hl_depth_ema_ = l1_depth > 0.1 ? l1_depth : 10.0;
            } else {
                hl_depth_ema_ = (0.01 * l1_depth) + (0.99 * hl_depth_ema_);
            }
            hl_depth_ema_ = std::max(1.0, hl_depth_ema_);

            double raw_ofi = std::max(-5000.0, std::min(5000.0, acc_ofi_));
            shared_book_->current_ofi = raw_ofi / hl_depth_ema_;

            double raw_flow = acc_flow_ / dt_wall;
            double current_I = (0.8 * shared_book_->execution_flow_rate) + (0.2 * (raw_flow / hl_depth_ema_));
            shared_book_->execution_flow_rate = current_I;

            double raw_signed_flow = signed_flow_ / dt_wall;
            shared_book_->signed_flow_rate = (0.8 * shared_book_->signed_flow_rate) + (0.2 * (raw_signed_flow / hl_depth_ema_));

            shared_book_->event_flags = event_pending_ ? 1 : 0;
            event_pending_ = false;

            if (current_I > max_I_) {
                max_I_ = current_I;
                if (!l4_manager_.bid_levels.empty() && !l4_manager_.ask_levels.empty()) {
                    shared_book_->p_max_i = (l4_manager_.bid_levels.begin()->first + l4_manager_.ask_levels.begin()->first) / 2.0;
                }
            }
            max_I_ *= 0.999;

            l4_manager_.aggregate(shared_book_);
            acc_flow_ = 0.0; acc_ofi_ = 0.0; signed_flow_ = 0.0;

            auto t_end = std::chrono::high_resolution_clock::now();
            shared_book_->hot_path_latency_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(t_end - t_recv).count();
            shared_book_->hl_e2e_latency_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::system_clock::now().time_since_epoch()).count() - (l4_manager_.time * 1000000ULL);
            shared_book_->last_update_local_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::system_clock::now().time_since_epoch()).count();

            // Push the updated local master book onto the SPSC Ring Buffer!
            ring_buffer_->push(*shared_book_);

            static uint64_t tick_count = 0;
            if (++tick_count % 1000 == 0) {
                double mid = 0;
                if (!l4_manager_.bid_levels.empty() && !l4_manager_.ask_levels.empty()) mid = (l4_manager_.bid_levels.begin()->first + l4_manager_.ask_levels.begin()->first) / 2.0;
                LOG_OUT << "[SIGNAL] " << coin_ << " | Mid: " << std::fixed << std::setprecision(2) << mid << " | OFI: " << std::fixed << std::setprecision(4) << shared_book_->current_ofi << " | Flow: " << shared_book_->execution_flow_rate << std::endl;
            }
        } catch (...) {}
    }
};

#ifndef UNIT_TEST
int main(int argc, char** argv) {
    std::signal(SIGINT, signal_handler); std::signal(SIGTERM, signal_handler);
    if (argc < 2) { LOG_ERR << "Usage: unified_ingestor <asset_name>" << std::endl; return 1; }
    std::string asset_name = argv[1];
    LOG_OUT << "[MAIN] Initializing Unified C++ Ingestor for asset: " << asset_name << std::endl;

    char* hl_target_env = std::getenv("HYPERLIQUID_GRPC_TARGET");
    std::string hl_target_str = hl_target_env ? hl_target_env : "api.hyperliquid.xyz:443";
    char* poly_rpc_env = std::getenv("POLYGON_RPC_URL");
    std::string poly_rpc_str = poly_rpc_env ? poly_rpc_env : "https://polygon-rpc.com";
    char* wallet_env = std::getenv("POLY_PROXY_WALLET");
    if (!wallet_env || std::string(wallet_env).empty()) {
        wallet_env = std::getenv("POLY_WALLET_ADDRESS");
    }
    if (!wallet_env) { LOG_ERR << "CRITICAL: POLY_WALLET_ADDRESS or POLY_PROXY_WALLET not set." << std::endl; return 1; }
    std::string wallet_str = wallet_env;

    auto acc_sync_queue = std::make_shared<ThreadSafeQueue<MarketIds>>();
    auto poly_bridge_queue = std::make_shared<ThreadSafeQueue<MarketIds>>();

    // Open/Create the SPSC Ring Buffer in Shared Memory
    SharedMemoryManager<SpscRingBuffer<L2BookStruct, 2048>> l2_shm(("/hl_l2_book_" + asset_name), true);
    SpscRingBuffer<L2BookStruct, 2048>* ring_buffer = l2_shm.get();

    // Local master book and ring buffer serialization mutex
    auto book = std::make_unique<L2BookStruct>();
    std::mutex ring_mutex;

    auto market_discovery = std::make_unique<MarketDiscovery>(asset_name, std::vector{acc_sync_queue, poly_bridge_queue});
    auto account_sync = std::make_unique<AccountSync>(asset_name, poly_rpc_str, wallet_str, acc_sync_queue);
    auto poly_bridge = std::make_unique<PolymarketBridge>(book.get(), poly_bridge_queue, ring_buffer, &ring_mutex);

    grpc::ChannelArguments args;
    args.SetInt(GRPC_ARG_KEEPALIVE_TIME_MS, 10000);
    args.SetInt(GRPC_ARG_KEEPALIVE_TIMEOUT_MS, 5000);
    args.SetMaxReceiveMessageSize(100 * 1024 * 1024);
    auto channel = grpc::CreateCustomChannel(hl_target_str, grpc::SslCredentials(grpc::SslCredentialsOptions()), args);
    auto hl_ingestor = std::make_unique<GRPCIngestor>(book.get(), channel, asset_name, ring_buffer, &ring_mutex);

    LOG_OUT << "[MAIN] Starting all services..." << std::endl;
    
    // 10Hz Heartbeat to update local SHM timestamp, preventing false-positive staleness during quiet periods
    std::thread heartbeat_thread([book_ptr = book.get(), ring_buffer, &ring_mutex]() {
        LOG_OUT << "[Heartbeat] Started 10Hz observability loop." << std::endl;
        while (keep_running.load()) {
            auto now = std::chrono::system_clock::now();
            uint64_t now_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count();
            
            {
                std::lock_guard<std::mutex> lock(ring_mutex);
                book_ptr->last_update_local_ns = now_ns;
                ring_buffer->push(*book_ptr);
            }
            
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
        LOG_OUT << "[Heartbeat] Observability loop stopped." << std::endl;
    });

    try {
        market_discovery->Run(); account_sync->Run(); poly_bridge->Run();
        hl_ingestor->Run();
    } catch (const std::exception& e) { LOG_ERR << "[MAIN] Unhandled exception: " << e.what() << std::endl; }

    LOG_OUT << "[MAIN] Shutdown received. Stopping all services..." << std::endl;
    if (heartbeat_thread.joinable()) heartbeat_thread.join();
    market_discovery->Stop(); account_sync->Stop(); poly_bridge->Stop();
    LOG_OUT << "[MAIN] All services stopped. Exiting." << std::endl;
    return 0;
}
#endif
