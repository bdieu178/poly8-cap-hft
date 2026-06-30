#include <gtest/gtest.h>
#include "../SharedMemoryManager.hpp"
#include "../L2BookStruct.hpp" // Include for L2BookStruct and MAX_LEVELS
#include <thread>
#include <vector>

TEST(SharedMemoryTest, CreateAndOpen) {
    std::string shm_path = "/test_shm_create";
    shm_unlink(shm_path.c_str()); // Ensure clean start

    {
        SharedMemoryManager<L2BookStruct> creator(shm_path, true); // Specify template argument
        EXPECT_NE(creator.get(), nullptr);
        creator.get()->current_ofi = 123.45;
    }

    // Manager was destroyed, but shm_unlink was called in destructor for creator
    // Let's test non-creator opening
    {
        SharedMemoryManager<L2BookStruct> creator(shm_path, true); // Specify template argument
        SharedMemoryManager<L2BookStruct> opener(shm_path, false); // Specify template argument
        EXPECT_EQ(opener.get()->current_ofi, 0.0); // freshly initialized by creator
        creator.get()->current_ofi = 99.9;
        EXPECT_EQ(opener.get()->current_ofi, 99.9);
    }
    shm_unlink(shm_path.c_str());
}

TEST(SharedMemoryTest, SeqlockIntegrity) {
    std::string shm_path = "/test_shm_seqlock";
    shm_unlink(shm_path.c_str());
    
    SharedMemoryManager<L2BookStruct> shm(shm_path, true); // Specify template argument
    L2BookStruct* book = shm.get();

    bool stop = false;
    // Writer thread: continuously updates
    std::thread writer([&]() {
        double val = 1.0;
        while (!stop) {
            uint64_t seq = book->hl_sequence.load(std::memory_order_relaxed);
            book->hl_sequence.store(seq + 1, std::memory_order_release);
            
            book->current_ofi = val;
            for(int j=0; j<MAX_LEVELS; ++j) {
                book->hl_bids[j].price = val;
            }
            
            book->hl_sequence.store(seq + 2, std::memory_order_release);
            val += 1.0;
        }
    });

    // Reader thread: ensures it never reads a torn state
    std::thread reader([&]() {
        for (int i = 0; i < 10000; ++i) {
            uint64_t s1, s2;
            double ofi;
            std::vector<double> prices(MAX_LEVELS);
            
            do {
                s1 = book->hl_sequence.load(std::memory_order_acquire);
                while (s1 & 1) { // Busy wait if writer is active
                    std::this_thread::yield();
                    s1 = book->hl_sequence.load(std::memory_order_acquire);
                }
                
                ofi = book->current_ofi;
                for(int j=0; j<MAX_LEVELS; ++j) {
                    prices[j] = book->hl_bids[j].price;
                }
                
                s2 = book->hl_sequence.load(std::memory_order_acquire);
            } while (s1 != s2);

            // Verify all data is consistent with the same 'val'
            EXPECT_EQ(ofi, prices[0]);
            for(int j=1; j<MAX_LEVELS; ++j) {
                EXPECT_EQ(prices[0], prices[j]);
            }
        }
    });

    std::this_thread::sleep_for(std::chrono::milliseconds(500));
    stop = true;
    writer.join();
    reader.join();
    shm_unlink(shm_path.c_str());
}
