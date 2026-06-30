#include "AccountSync.hpp"
#include "Logger.hpp"
#include "SequenceGuard.hpp"
#include <cpr/cpr.h>
#include <nlohmann/json.hpp>
#include <iostream>
#include <iomanip>
#include <sstream>
#include <chrono>
#include <optional>
#include <boost/multiprecision/cpp_int.hpp>

using json = nlohmann::json;
using namespace boost::multiprecision;

// --- Helper for Balance Parsing ---
double ParseBalanceHex(const std::string& hex_val) {
    if (hex_val.length() <= 2) return 0.0;
    try {
        uint256_t val(hex_val);
        return static_cast<double>(val); 
    } catch (...) {
        return 0.0;
    }
}

// --- Helper for ABI Encoding ---
// Converts a hex string address (e.g., "0x...") to a 32-byte zero-padded hex string.
std::string PadAddress(const std::string& addr) {
    std::string stripped = addr.substr(0, 2) == "0x" ? addr.substr(2) : addr;
    if (stripped.length() > 64) stripped = stripped.substr(stripped.length() - 64);
    return std::string(64 - stripped.length(), '0') + stripped;
}

// Converts a token ID string to its 32-byte hex representation.
std::string TokenIdToPaddedHex(const std::string& token_id) {
    if (token_id.empty()) return std::string(64, '0');
    try {
        uint256_t value(token_id);
        std::stringstream ss;
        ss << std::hex << std::setfill('0') << std::setw(64) << value;
        return ss.str();
    } catch (...) {
        return std::string(64, '0');
    }
}

AccountSync::AccountSync(
    const std::string& asset_name, 
    const std::string& rpc_url,
    const std::string& wallet_addr,
    std::shared_ptr<ThreadSafeQueue<MarketIds>> market_id_queue)
    : asset_name_(asset_name),
      rpc_url_(rpc_url),
      wallet_address_(wallet_addr),
      market_id_queue_(market_id_queue),
      keep_running_(false),
      shm_manager_(("/poly_account_" + asset_name), true)
{
    char* pusd = std::getenv("PUSD_ADDRESS");
    pusd_address_ = pusd ? pusd : "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb";
    
    char* ctf = std::getenv("CTF_ADDRESS");
    ctf_address_ = ctf ? ctf : "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045";
}

AccountSync::~AccountSync() {
    if (keep_running_.load()) {
        Stop();
    }
}

void AccountSync::Run() {
    keep_running_.store(true);
    worker_thread_ = std::thread(&AccountSync::SyncLoop, this);
}

void AccountSync::Stop() {
    keep_running_.store(false);
    if (worker_thread_.joinable()) {
        worker_thread_.join();
    }
}

void AccountSync::SyncLoop() {
    pin_thread_to_core(4);
    LOG_OUT << "[AccountSync] Starting 1Hz balance polling for " << asset_name_ << std::endl;
    
    while (keep_running_.load()) {
        try {
            // Block until we get the first market ID if we don't have them yet
            if (current_market_ids_.up.empty()) {
                LOG_OUT << "[AccountSync] Waiting for initial market IDs..." << std::endl;
                market_id_queue_->WaitAndPop(current_market_ids_);
            }
            
            // Check for updated market IDs without blocking
            market_id_queue_->TryPop(current_market_ids_);

            // Dispatch concurrent requests
            auto f_pusd = FetchBalanceAsync(pusd_address_, "0x70a08231" + PadAddress(wallet_address_));
            
            std::optional<cpr::AsyncResponse> f_up;
            bool up_active = !current_market_ids_.up.empty();
            if (up_active) {
                f_up = FetchBalanceAsync(ctf_address_, "0x00fdd58e" + PadAddress(wallet_address_) + TokenIdToPaddedHex(current_market_ids_.up));
            }
            
            std::optional<cpr::AsyncResponse> f_down;
            bool down_active = !current_market_ids_.down.empty();
            if (down_active) {
                f_down = FetchBalanceAsync(ctf_address_, "0x00fdd58e" + PadAddress(wallet_address_) + TokenIdToPaddedHex(current_market_ids_.down));
            }

            // Helper to get result from async response
            auto get_balance = [](auto& f, bool active) -> std::optional<double> {
                if (!active) return 0.0; // If contract ID is not set/active, balance is 0.0
                
                cpr::Response r;
                if constexpr (std::is_same_v<std::decay_t<decltype(f)>, std::optional<cpr::AsyncResponse>>) {
                    if (!f.has_value()) return 0.0;
                    r = f->get();
                } else {
                    r = f.get();
                }
                
                if (r.status_code == 200) {
                    try {
                        json result = json::parse(r.text);
                        if (result.contains("result")) {
                            return ParseBalanceHex(result["result"].get<std::string>());
                        }
                    } catch (...) {}
                }
                return std::nullopt; // Indicate transient fetch/RPC failure
            };

            std::optional<double> pusd_balance = get_balance(f_pusd, true);
            std::optional<double> up_balance = get_balance(f_up, up_active);
            std::optional<double> down_balance = get_balance(f_down, down_active);

            if (pusd_balance.has_value() && pusd_balance.value() > 0.0) {
                LOG_OUT << "[AccountSync] " << asset_name_ << " | Wallet: " << wallet_address_ << " | pUSD: $" << (pusd_balance.value() / 1e6) << std::endl;
            }

            // Write to SHM
            AccountStateStruct* acc = shm_manager_.get();
            SequenceGuard sg(acc->sequence, "AccountSync"); // Acquire seqlock
            try {
                if (pusd_balance.has_value()) {
                    acc->available_collateral = pusd_balance.value() / 1e6; // 6 decimals
                }
                if (up_balance.has_value()) {
                    acc->up_position = up_balance.value() / 1e6;
                }
                if (down_balance.has_value()) {
                    acc->down_position = down_balance.value() / 1e6;
                }
                acc->total_equity = acc->available_collateral + acc->up_position + acc->down_position;
                acc->last_update_ts = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
            } catch (const std::exception& ex) {
                LOG_ERR << "[AccountSync] Exception during SHM update: " << ex.what() << std::endl;
            }

        } catch (const std::exception& e) {
            LOG_ERR << "[AccountSync] Error in loop: " << e.what() << std::endl;
        }

        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
}

cpr::AsyncResponse AccountSync::FetchBalanceAsync(const std::string& contract_address, const std::string& data_payload) {
    json payload = {
        {"jsonrpc", "2.0"},
        {"method", "eth_call"},
        {"params", {{
            {"to", contract_address},
            {"data", data_payload}
        }, "latest"}},
        {"id", 1}
    };

    return cpr::PostAsync(cpr::Url{rpc_url_},
                          cpr::Body{payload.dump()},
                          cpr::Header{{"Content-Type", "application/json"}});
}
