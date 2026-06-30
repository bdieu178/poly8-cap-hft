#include <gtest/gtest.h>
#include "../SpscRingBuffer.hpp"
#include "../L2BookStruct.hpp"
#include <thread>
#include <vector>
#include <atomic>

TEST(SpscRingBufferTest, BasicPushPop) {
    SpscRingBuffer<int, 4> ring;
    EXPECT_EQ(ring.size(), 0);

    int val = 0;
    EXPECT_FALSE(ring.pop(val)); // Empty pop should fail

    EXPECT_TRUE(ring.push(1));
    EXPECT_TRUE(ring.push(2));
    EXPECT_TRUE(ring.push(3));
    EXPECT_EQ(ring.size(), 3);

    EXPECT_TRUE(ring.pop(val));
    EXPECT_EQ(val, 1);
    EXPECT_EQ(ring.size(), 2);

    EXPECT_TRUE(ring.pop(val));
    EXPECT_EQ(val, 2);
    EXPECT_TRUE(ring.pop(val));
    EXPECT_EQ(val, 3);
    EXPECT_EQ(ring.size(), 0);
    EXPECT_FALSE(ring.pop(val));
}

TEST(SpscRingBufferTest, BackpressureAndDrop) {
    SpscRingBuffer<int, 4> ring;

    // Fill the buffer
    EXPECT_TRUE(ring.push(10));
    EXPECT_TRUE(ring.push(20));
    EXPECT_TRUE(ring.push(30));
    EXPECT_TRUE(ring.push(40));

    EXPECT_EQ(ring.size(), 4);
    EXPECT_EQ(ring.get_dropped_count(), 0);

    // This push should fail due to capacity limit
    EXPECT_FALSE(ring.push(50));
    EXPECT_EQ(ring.get_dropped_count(), 1);
    EXPECT_EQ(ring.size(), 4);

    int val = 0;
    EXPECT_TRUE(ring.pop(val));
    EXPECT_EQ(val, 10);
    EXPECT_EQ(ring.size(), 3);

    // Now we can push again
    EXPECT_TRUE(ring.push(50));
    EXPECT_EQ(ring.size(), 4);
}

TEST(SpscRingBufferTest, ConcurrentStress) {
    SpscRingBuffer<uint64_t, 2048> ring;
    constexpr uint64_t num_items = 1000000;
    std::atomic<bool> start_signal{false};

    std::thread producer([&]() {
        while (!start_signal.load(std::memory_order_relaxed)) {
            std::this_thread::yield();
        }
        for (uint64_t i = 0; i < num_items; ) {
            if (ring.push(i)) {
                i++;
            } else {
                std::this_thread::yield(); // Backoff on full
            }
        }
    });

    std::thread consumer([&]() {
        while (!start_signal.load(std::memory_order_relaxed)) {
            std::this_thread::yield();
        }
        uint64_t expected = 0;
        while (expected < num_items) {
            uint64_t val = 0;
            if (ring.pop(val)) {
                EXPECT_EQ(val, expected);
                expected++;
            } else {
                std::this_thread::yield(); // Backoff on empty
            }
        }
    });

    start_signal.store(true);
    producer.join();
    consumer.join();

    EXPECT_EQ(ring.size(), 0);
    EXPECT_GE(ring.get_dropped_count(), 0);
}
