#pragma once
#include <atomic>
#include <cstdint>
#include <cstddef>

template <typename T, size_t CAPACITY>
class SpscRingBuffer {
    static_assert((CAPACITY & (CAPACITY - 1)) == 0, "Capacity must be a power of two");

private:
    // Aligned to 64 bytes to prevent false sharing between producer and consumer
    alignas(64) std::atomic<uint64_t> write_index{0};
    alignas(64) std::atomic<uint64_t> read_index{0};
    
    // Aligned padding to isolate indexes from buffer data
    alignas(64) T buffer[CAPACITY];

    // Diagnostic dropped packets counter
    alignas(64) std::atomic<uint64_t> dropped_count{0};

public:
    SpscRingBuffer() = default;

    // Push item to the ring buffer. Returns false if the buffer is full (backpressure).
    bool push(const T& item) {
        uint64_t current_write = write_index.load(std::memory_order_relaxed);
        uint64_t current_read = read_index.load(std::memory_order_acquire);

        if (current_write - current_read == CAPACITY) {
            dropped_count.fetch_add(1, std::memory_order_relaxed);
            return false;
        }

        // Relaxed write directly into the slot (synchronized via release on write_index)
        buffer[current_write & (CAPACITY - 1)] = item;
        write_index.store(current_write + 1, std::memory_order_release);
        return true;
    }

    // Try to pop an item (primarily for testing inside C++ or if needed in bidirectional components)
    bool pop(T& item) {
        uint64_t current_read = read_index.load(std::memory_order_relaxed);
        uint64_t current_write = write_index.load(std::memory_order_acquire);

        if (current_read == current_write) {
            return false; // Empty
        }

        item = buffer[current_read & (CAPACITY - 1)];
        read_index.store(current_read + 1, std::memory_order_release);
        return true;
    }

    uint64_t size() const {
        uint64_t w = write_index.load(std::memory_order_relaxed);
        uint64_t r = read_index.load(std::memory_order_relaxed);
        return (w >= r) ? (w - r) : 0;
    }

    uint64_t get_dropped_count() const {
        return dropped_count.load(std::memory_order_relaxed);
    }

    void reset() {
        write_index.store(0, std::memory_order_relaxed);
        read_index.store(0, std::memory_order_relaxed);
        dropped_count.store(0, std::memory_order_relaxed);
    }
};
