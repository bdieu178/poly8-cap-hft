#include "MarketDiscovery.hpp"
#include "Logger.hpp"
#include <cpr/cpr.h>
#include <nlohmann/json.hpp>
#include <iostream>
#include <chrono>

using json = nlohmann::json;

MarketDiscovery::MarketDiscovery(
    const std::string& asset_name, 
    std::vector<std::shared_ptr<ThreadSafeQueue<MarketIds>>> market_id_queues)
    : asset_name_(asset_name),
      market_id_queues_(market_id_queues),
      keep_running_(false)
{}

MarketDiscovery::~MarketDiscovery() {
    if (keep_running_.load()) {
        Stop();
    }
}

void MarketDiscovery::Run() {
    keep_running_.store(true);
    worker_thread_ = std::thread(&MarketDiscovery::DiscoveryLoop, this);
}

void MarketDiscovery::Stop() {
    keep_running_.store(false);
    if (worker_thread_.joinable()) {
        worker_thread_.join();
    }
}

uint64_t MarketDiscovery::GetCurrentIntervalTimestamp(uint64_t interval_minutes) {
    auto now_s = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    return (now_s / (interval_minutes * 60) + 1) * (interval_minutes * 60);
}

void MarketDiscovery::DiscoveryLoop() {
    pin_thread_to_core(4);
    LOG_OUT << "[MarketDiscovery] Starting 30s polling loop for " << asset_name_ << std::endl;
    std::string current_up_id = "";
    int error_backoff_ms = 1000;

    while(keep_running_.load()) {
        try {
            // Resolve target timeframe from environment, default to 15m
            char* env_timeframe = std::getenv("TIMEFRAME_MINUTES");
            uint64_t target_timeframe = env_timeframe ? std::stoull(env_timeframe) : 15;
            if (target_timeframe != 15 && target_timeframe != 60) {
                target_timeframe = 15;
            }

            std::vector<std::pair<std::string, uint64_t>> target_slugs;
            uint64_t ts_tf = GetCurrentIntervalTimestamp(target_timeframe);
            if (target_timeframe == 60) {
                // 1h contracts suffix is "-1h-[timestamp]"
                target_slugs.push_back({asset_name_ + "-updown-1h-" + std::to_string(ts_tf), ts_tf});
            } else {
                target_slugs.push_back({asset_name_ + "-updown-15m-" + std::to_string(ts_tf), ts_tf});
            }

            bool found = false;
            for (const auto& [slug, ts] : target_slugs) {
                std::string url = "https://gamma-api.polymarket.com/markets?slug=" + slug;
                cpr::Response r = cpr::Get(cpr::Url{url});
                
                if (r.status_code == 200 && !r.text.empty()) {
                    error_backoff_ms = 1000; // Reset on any successful API contact
                    json markets = json::parse(r.text);
                    if (markets.is_array() && !markets.empty()) {
                        json market = markets[0];
                        if (market.contains("clobTokenIds") && market.contains("outcomes")) {
                            json clob_ids_json = json::parse(market["clobTokenIds"].get<std::string>());
                            json outcomes_json = json::parse(market["outcomes"].get<std::string>());
                            double strike = (market.contains("line") && !market["line"].is_null()) ? std::stod(market["line"].get<std::string>()) : -1.0;

                            if (clob_ids_json.size() >= 2 && outcomes_json.size() >= 2) {
                                std::string up_id = "";
                                std::string down_id = "";

                                for(size_t i = 0; i < outcomes_json.size(); ++i) {
                                    if (outcomes_json[i] == "Up") up_id = clob_ids_json[i];
                                    else if (outcomes_json[i] == "Down") down_id = clob_ids_json[i];
                                }

                                if (!up_id.empty() && !down_id.empty()) {
                                    if (up_id != current_up_id) {
                                        current_up_id = up_id;
                                        LOG_OUT << "[MarketDiscovery] Found active market IDs for slug " << slug << ". UP: " << up_id << ", DOWN: " << down_id << ", Strike: " << strike << ", Expiry: " << ts << std::endl;
                                        for (auto& q : market_id_queues_) {
                                            q->Push(MarketIds(up_id, down_id, strike, ts));
                                        }
                                    }
                                    found = true;
                                    break; // Successfully discovered active market, stop checking further slugs
                                }
                            }
                        }
                    }
                } else if (r.status_code != 0) {
                    LOG_ERR << "[MarketDiscovery] Gamma API error " << r.status_code << " for " << url << std::endl;
                }
            }

            if (found) {
                std::this_thread::sleep_for(std::chrono::seconds(30));
            } else {
                LOG_ERR << "[MarketDiscovery] No active " << target_timeframe << "m markets found for " << asset_name_ << ". Retrying in " << error_backoff_ms << "ms." << std::endl;
                std::this_thread::sleep_for(std::chrono::milliseconds(error_backoff_ms));
                error_backoff_ms = std::min(error_backoff_ms * 2, 30000);
            }

        } catch (const std::exception& e) {
            LOG_ERR << "[MarketDiscovery] Error in loop: " << e.what() << ". Retrying in " << error_backoff_ms << "ms." << std::endl;
            std::this_thread::sleep_for(std::chrono::milliseconds(error_backoff_ms));
            error_backoff_ms = std::min(error_backoff_ms * 2, 30000);
        }
    }
}
