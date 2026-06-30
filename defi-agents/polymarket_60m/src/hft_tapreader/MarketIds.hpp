#pragma once
#include <string>

// Struct to pass market discovery information between threads.
struct MarketIds {
    std::string up;
    std::string down;
    double strike;
    uint64_t rotation_ts;

    // Default constructor for ThreadSafeQueue compatibility
    MarketIds() : up(""), down(""), strike(0.0), rotation_ts(0) {}
    
    MarketIds(const std::string& u, const std::string& d, double s, uint64_t r)
        : up(u), down(d), strike(s), rotation_ts(r) {}
};
