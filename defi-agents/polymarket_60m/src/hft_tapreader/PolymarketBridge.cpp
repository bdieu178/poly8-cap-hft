#include "MarketDiscovery.hpp" // Includes PolymarketBridge definition
#include "Logger.hpp"
#include "SequenceGuard.hpp"
#include <boost/beast/core.hpp>
#include <boost/beast/websocket.hpp>
#include <boost/beast/ssl.hpp>
#include <boost/asio/connect.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <cstring>
#include <iostream>
#include <nlohmann/json.hpp>
#include <sys/time.h>
#include <sys/socket.h>

namespace beast = boost::beast;
namespace http = beast::http;
namespace websocket = beast::websocket;
namespace net = boost::asio;
namespace ssl = net::ssl;
using tcp = net::ip::tcp;
using json = nlohmann::json;

PolymarketBridge::PolymarketBridge(
    L2BookStruct* book,
    std::shared_ptr<ThreadSafeQueue<MarketIds>> market_id_queue,
    SpscRingBuffer<L2BookStruct, 2048>* ring_buffer,
    std::mutex* ring_mutex)
    : shared_book_(book),
      ring_buffer_(ring_buffer),
      ring_mutex_(ring_mutex),
      market_id_queue_(market_id_queue),
      keep_running_(false)
{
    char* url = std::getenv("POLY_CLOB_WS_URL");
    ws_url_ = url ? std::string(url) : "wss://ws-subscriptions-clob.polymarket.com/ws/market";
}

PolymarketBridge::~PolymarketBridge() {
    if (keep_running_.load()) {
        Stop();
    }
}

void PolymarketBridge::Run() {
    keep_running_.store(true);
    worker_thread_ = std::thread(&PolymarketBridge::ConnectionLoop, this);
}

void PolymarketBridge::Stop() {
    keep_running_.store(false);
    if (worker_thread_.joinable()) {
        worker_thread_.join();
    }
}

void PolymarketBridge::UpdateSHM() {
    UpdateSHM(0);
}

void PolymarketBridge::UpdateSHM(int64_t poly_processing_latency_ns) {
    std::lock_guard<std::mutex> lock(*ring_mutex_);
    
    // Increment poly_sequence monotonically for diagnostic/observability sequencing
    uint64_t seq = shared_book_->poly_sequence.load(std::memory_order_relaxed);
    shared_book_->poly_sequence.store(seq + 1, std::memory_order_relaxed);

    auto now = std::chrono::system_clock::now();
    uint64_t now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();
    shared_book_->last_update_local_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count();
    if (poly_processing_latency_ns > 0) {
        shared_book_->poly_processing_latency_ns = poly_processing_latency_ns;
    }

    // Late Anchoring: If strike is -1.0, attempt to anchor to current HL mid
    if (current_market_ids_.strike < 0) {
        double hl_mid = (shared_book_->hl_bids[0].price + shared_book_->hl_asks[0].price) / 2.0;
        if (hl_mid > 100.0) {
            current_market_ids_.strike = hl_mid;
            LOG_OUT << "[PolyBridge] Late-anchoring relative strike to HL Mid: " << hl_mid << std::endl;
        }
    }

    auto update_asset = [&](const std::string& asset_id, uint64_t& ts_dest, PriceLevel* bids_dest, PriceLevel* asks_dest) {
        ts_dest = now_ms;
        
        auto& bids = bids_[asset_id];
        int i = 0;
        for (auto const& [px, sz] : bids) {
            if (i >= MAX_POLY_LEVELS) break;
            bids_dest[i].price = px; bids_dest[i].size = sz; i++;
        }
        while (i < MAX_POLY_LEVELS) { bids_dest[i] = {0.0, 0.0}; i++; }

        auto& asks = asks_[asset_id];
        i = 0;
        for (auto const& [px, sz] : asks) {
            if (i >= MAX_POLY_LEVELS) break;
            asks_dest[i].price = px; asks_dest[i].size = sz; i++;
        }
        while (i < MAX_POLY_LEVELS) { asks_dest[i] = {0.0, 0.0}; i++; }
    };

    if (!current_market_ids_.up.empty()) {
        update_asset(current_market_ids_.up, shared_book_->poly_up_timestamp, shared_book_->poly_up_bids, shared_book_->poly_up_asks);
    }
    if (!current_market_ids_.down.empty()) {
        update_asset(current_market_ids_.down, shared_book_->poly_down_timestamp, shared_book_->poly_down_bids, shared_book_->poly_down_asks);
    }
    shared_book_->strike_price = current_market_ids_.strike;
    shared_book_->rotation_ts = current_market_ids_.rotation_ts;
    
    char* env_tf = std::getenv("TIMEFRAME_MINUTES");
    shared_book_->timeframe_minutes = env_tf ? std::stoul(env_tf) : 15;

    // Push Token IDs to SHM for Rust Executor synchronization
    snprintf(shared_book_->poly_up_id, sizeof(shared_book_->poly_up_id), "%s", current_market_ids_.up.c_str());
    snprintf(shared_book_->poly_down_id, sizeof(shared_book_->poly_down_id), "%s", current_market_ids_.down.c_str());

    // Push the updated local book onto the SPSC Ring Buffer!
    ring_buffer_->push(*shared_book_);
}

void PolymarketBridge::ConnectionLoop() {
    pin_thread_to_core(3);
    LOG_OUT << "[PolyBridge] Starting connection manager..." << std::endl;
    int backoff_ms = 1000;
    
    while(keep_running_.load()) {
        try {
            // Block until we get the first market ID
            if (current_market_ids_.up.empty()) {
                LOG_OUT << "[PolyBridge] Waiting for initial market IDs..." << std::endl;
                market_id_queue_->WaitAndPop(current_market_ids_);
            }

            std::string host = "ws-subscriptions-clob.polymarket.com";
            std::string port = "443";
            
            net::io_context ioc;
            ssl::context ctx{ssl::context::sslv23_client}; 
            tcp::resolver resolver{ioc};
            websocket::stream<beast::ssl_stream<tcp::socket>> ws{ioc, ctx};

            LOG_OUT << "[PolyBridge] Attempting to connect to " << host << ":" << port << std::endl;
            auto const results = resolver.resolve(host, port);
            
            if(! SSL_set_tlsext_host_name(ws.next_layer().native_handle(), host.c_str())) {
                throw beast::system_error(
                    beast::error_code(static_cast<int>(::ERR_get_error()), net::error::get_ssl_category()),
                    "Failed to set SNI Hostname");
            }

            net::connect(ws.next_layer().next_layer(), results);
            
            // Set receive timeout to 65 seconds to prevent blocking indefinitely during quiet periods
            struct timeval tv;
            tv.tv_sec = 65;
            tv.tv_usec = 0;
            setsockopt(beast::get_lowest_layer(ws).native_handle(), SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
            
            LOG_OUT << "[PolyBridge] TCP Connected. Performing SSL handshake..." << std::endl;
            
            ws.next_layer().handshake(ssl::stream_base::client);
            LOG_OUT << "[PolyBridge] SSL Handshake successful. Performing WS handshake..." << std::endl;
            
            ws.handshake(host, "/ws/market");
            
            json sub_msg = {
                {"type", "subscribe"},
                {"channels", {"order_book"}},
                {"assets_ids", {current_market_ids_.up, current_market_ids_.down}}
            };
            std::string sub_str = sub_msg.dump();
            ws.write(net::buffer(sub_str));

            LOG_OUT << "[PolyBridge] WS Handshake successful. Subscribing with: " << sub_str << std::endl;
            backoff_ms = 1000; 

            // Clear local state for new connection
            bids_.clear(); asks_.clear(); update_count_since_last_prune = 0;

            beast::flat_buffer buffer;
            while(keep_running_.load()) {
                MarketIds new_ids;
                if(market_id_queue_->TryPop(new_ids)) {
                    if (new_ids.up != current_market_ids_.up) {
                        LOG_OUT << "[PolyBridge] Market rotation detected. Reconnecting..." << std::endl;
                        current_market_ids_ = new_ids;
                        
                        // Relative Strike Anchoring: If strike is -1.0, use current HL mid
                        if (current_market_ids_.strike < 0) {
                            double hl_mid = (shared_book_->hl_bids[0].price + shared_book_->hl_asks[0].price) / 2.0;
                            if (hl_mid > 100.0) {
                                current_market_ids_.strike = hl_mid;
                                LOG_OUT << "[PolyBridge] Anchoring relative strike to HL Mid: " << hl_mid << std::endl;
                            }
                        }
                        UpdateSHM(); // Ensure executor gets new tokens and anchored strike immediately
                        break; 
                    }
                }

                ws.read(buffer);
                auto t_recv = std::chrono::high_resolution_clock::now();
                std::string msg = beast::buffers_to_string(buffer.data());
                buffer.consume(buffer.size());
                
                json update = json::parse(msg);
                bool updated = false;

                if (update.is_array()) {
                    for(const auto& item : update) {
                        if (item.contains("asset_id") && item["asset_id"].is_string()) {
                            std::string asset_id = item["asset_id"].get<std::string>();
                            if (item.contains("bids") && item["bids"].is_array()) {
                                bids_[asset_id].clear();
                                for (const auto& b : item["bids"]) {
                                    try {
                                        if (b.is_array() && b.size() >= 2 && b[0].is_string() && b[1].is_string()) {
                                            bids_[asset_id][std::stod(b[0].get<std::string>())] = std::stod(b[1].get<std::string>());
                                        } else if (b.is_object() && b.contains("price") && b["price"].is_string() && b.contains("size") && b["size"].is_string()) {
                                            bids_[asset_id][std::stod(b["price"].get<std::string>())] = std::stod(b["size"].get<std::string>());
                                        }
                                    } catch (...) {}
                                }
                            }
                            if (item.contains("asks") && item["asks"].is_array()) {
                                asks_[asset_id].clear();
                                for (const auto& a : item["asks"]) {
                                    try {
                                        if (a.is_array() && a.size() >= 2 && a[0].is_string() && a[1].is_string()) {
                                            asks_[asset_id][std::stod(a[0].get<std::string>())] = std::stod(a[1].get<std::string>());
                                        } else if (a.is_object() && a.contains("price") && a["price"].is_string() && a.contains("size") && a["size"].is_string()) {
                                            asks_[asset_id][std::stod(a["price"].get<std::string>())] = std::stod(a["size"].get<std::string>());
                                        }
                                    } catch (...) {}
                                }
                            }
                            updated = true;
                        }
                    }
                } else if (update.contains("event_type") && update["event_type"].is_string()) {
                    std::string event_type = update["event_type"].get<std::string>();
                    if (event_type == "book") {
                        if (update.contains("asset_id") && update["asset_id"].is_string()) {
                            std::string asset_id = update["asset_id"].get<std::string>();
                            if (update.contains("bids") && update["bids"].is_array()) {
                                bids_[asset_id].clear();
                                for (const auto& b : update["bids"]) {
                                    try {
                                        if (b.is_array() && b.size() >= 2 && b[0].is_string() && b[1].is_string()) {
                                            bids_[asset_id][std::stod(b[0].get<std::string>())] = std::stod(b[1].get<std::string>());
                                        } else if (b.is_object() && b.contains("price") && b["price"].is_string() && b.contains("size") && b["size"].is_string()) {
                                            bids_[asset_id][std::stod(b["price"].get<std::string>())] = std::stod(b["size"].get<std::string>());
                                        }
                                    } catch (...) {}
                                }
                            }
                            if (update.contains("asks") && update["asks"].is_array()) {
                                asks_[asset_id].clear();
                                for (const auto& a : update["asks"]) {
                                    try {
                                        if (a.is_array() && a.size() >= 2 && a[0].is_string() && a[1].is_string()) {
                                            asks_[asset_id][std::stod(a[0].get<std::string>())] = std::stod(a[1].get<std::string>());
                                        } else if (a.is_object() && a.contains("price") && a["price"].is_string() && a.contains("size") && a["size"].is_string()) {
                                            asks_[asset_id][std::stod(a["price"].get<std::string>())] = std::stod(a["size"].get<std::string>());
                                        }
                                    } catch (...) {}
                                }
                            }
                            updated = true;
                        }
                    } else if (event_type == "price_change") {
                        if (update.contains("asset_id") && update["asset_id"].is_string() && update.contains("price") && update["price"].is_string() && update.contains("size") && update["size"].is_string()) {
                            std::string asset_id = update["asset_id"].get<std::string>();
                            double px = std::stod(update["price"].get<std::string>());
                            double sz = std::stod(update["size"].get<std::string>());
                            std::string side = update.value("side", "");
                            if (side == "BUY") {
                                if (sz <= 1e-9) bids_[asset_id].erase(px);
                                else bids_[asset_id][px] = sz;
                            } else if (side == "SELL") {
                                if (sz <= 1e-9) asks_[asset_id].erase(px);
                                else asks_[asset_id][px] = sz;
                            }
                            updated = true;
                        }
                    }
                } else if (update.contains("price_changes") && update["price_changes"].is_array()) {
                    for (const auto& c : update["price_changes"]) {
                        if (c.contains("asset_id") && c["asset_id"].is_string() && c.contains("price") && c["price"].is_string() && c.contains("size") && c["size"].is_string()) {
                            std::string asset_id = c["asset_id"].get<std::string>();
                            double px = std::stod(c["price"].get<std::string>());
                            double sz = std::stod(c["size"].get<std::string>());
                            std::string side = c.value("side", "");
                            if (side == "BUY") {
                                if (sz <= 1e-9) bids_[asset_id].erase(px);
                                else bids_[asset_id][px] = sz;
                            } else if (side == "SELL") {
                                if (sz <= 1e-9) asks_[asset_id].erase(px);
                                else asks_[asset_id][px] = sz;
                            }
                        }
                    }
                    updated = true;
                }
                auto t_processed = std::chrono::high_resolution_clock::now();
                int64_t poly_processing_latency = std::chrono::duration_cast<std::chrono::nanoseconds>(t_processed - t_recv).count();

                if (updated) {
                    update_count_since_last_prune++;
                    if (update_count_since_last_prune >= PRUNE_INTERVAL) {
                        prune_distant_orders();
                        update_count_since_last_prune = 0;
                    }
                }
                
                // Always update SHM timestamp if we received any valid message from the server,
                // even if no book data changed. This prevents "stale data" trips during quiet periods.
                UpdateSHM(poly_processing_latency);
            }
        } catch (const std::exception& e) {
            LOG_ERR << "[PolyBridge] Connection error: " << e.what() << ". Reconnecting in " << backoff_ms << "ms." << std::endl;
            std::this_thread::sleep_for(std::chrono::milliseconds(backoff_ms));
            backoff_ms = std::min(backoff_ms * 2, 30000);
        }
    }
}

void PolymarketBridge::prune_distant_orders() {
    for (auto& [asset_id, asset_bids] : bids_) {
        auto& asset_asks = asks_[asset_id];
        if (asset_bids.empty() || asset_asks.empty()) continue;

        double mid = (asset_bids.begin()->first + asset_asks.begin()->first) / 2.0;
        double threshold = mid * 0.05;

        auto prune = [&](auto& levels) {
            size_t count = 0;
            for (auto it = levels.begin(); it != levels.end(); ) {
                if (std::abs(it->first - mid) > threshold) {
                    it = levels.erase(it);
                    count++;
                } else {
                    ++it;
                }
            }
            return count;
        };

        size_t pruned = prune(asset_bids) + prune(asset_asks);
        if (pruned > 0) {
            LOG_OUT << "[PolyBridge] Pruned " << pruned << " distant orders for asset " << asset_id << std::endl;
        }
    }
}
