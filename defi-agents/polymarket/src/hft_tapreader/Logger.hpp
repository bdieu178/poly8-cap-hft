#pragma once
#include <iostream>
#include <iomanip>
#include <chrono>
#include <string>
#include <sstream>
#include <mutex>

inline std::string GetTimestamp() {
    auto now = std::chrono::system_clock::now();
    auto in_time_t = std::chrono::system_clock::to_time_t(now);
    std::stringstream ss;
    ss << "[" << std::put_time(std::gmtime(&in_time_t), "%Y-%m-%d %H:%M:%S") << " UTC] ";
    return ss.str();
}

class ThreadSafeLogger {
public:
    static ThreadSafeLogger& getInstance() {
        static ThreadSafeLogger instance;
        return instance;
    }

    void log(const std::string& msg, bool is_error = false) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (is_error) {
            std::cerr << GetTimestamp() << msg << std::flush;
        } else {
            std::cout << GetTimestamp() << msg << std::flush;
        }
    }

private:
    std::mutex mutex_;
    ThreadSafeLogger() = default;
};

// Macro-like helper to handle stream-style logging
struct LogSession {
    std::stringstream ss;
    bool is_error;
    LogSession(bool err) : is_error(err) {}
    ~LogSession() {
        ThreadSafeLogger::getInstance().log(ss.str(), is_error);
    }
    template<typename T>
    LogSession& operator<<(const T& msg) {
        ss << msg;
        return *this;
    }
    // Handle manipulators like std::endl
    LogSession& operator<<(std::ostream& (*manip)(std::ostream&)) {
        ss << manip;
        return *this;
    }
};

#define LOG_OUT LogSession(false)
#define LOG_ERR LogSession(true)

#include <pthread.h>
#include <sched.h>

inline void pin_thread_to_core(int core_id) {
    int target_core = core_id;
    if (const char* env_offset = std::getenv("CORE_OFFSET")) {
        try {
            int offset = std::stoi(env_offset);
            target_core = core_id + offset;
        } catch (...) {
            // Ignore parse errors
        }
    }
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(target_core, &cpuset);
    pthread_t current_thread = pthread_self();
    int rc = pthread_setaffinity_np(current_thread, sizeof(cpu_set_t), &cpuset);
    if (rc != 0) {
        std::cerr << "[AFFINITY] Error calling pthread_setaffinity_np for core " << target_core << ": " << rc << std::endl;
    } else {
        std::cout << "[AFFINITY] Pinned thread to CPU core " << target_core << std::endl;
    }
}

