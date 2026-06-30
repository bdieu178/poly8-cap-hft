#pragma once
#include <string_view>
#include <charconv>
#include <vector>
#include "L2BookStruct.hpp"

// High-speed "No-DOM" parser for Polymarket CLOB V2 WebSocket frames.
// Optimized for latency by directly scanning for the best bid/ask prices.
namespace HotPath {

inline bool fast_stod(std::string_view s, double& val) {
    auto res = std::from_chars(s.data(), s.data() + s.size(), val);
    return res.ec == std::errc();
}

class PolymarketParser {
public:
    static bool ParseL2(std::string_view json, L2BookStruct* book) {
        if (json.size() < 20) return false;
        
        size_t bids_pos = json.find("\"bids\":[[");
        size_t asks_pos = json.find("\"asks\":[[");
        
        if (bids_pos == std::string_view::npos || asks_pos == std::string_view::npos) {
            return false;
        }

        auto extract_price = [&](size_t pos, double& target) -> bool {
            size_t start = json.find('"', pos + 9);
            if (start == std::string_view::npos) return false;
            size_t end = json.find('"', start + 1);
            if (end == std::string_view::npos) return false;
            return HotPath::fast_stod(json.substr(start + 1, end - start - 1), target);
        };

        if (!extract_price(bids_pos, book->poly_up_bids[0].price)) return false;
        if (!extract_price(asks_pos, book->poly_up_asks[0].price)) return false;

        return true;
    }
};

} // namespace HotPath
