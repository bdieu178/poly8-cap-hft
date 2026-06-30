#include <iostream>
#include <atomic>
#include <vector>
#include <thread>
#include <cstring>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

struct PriceLevel {
    double price;
    double size;
};

struct L2BookStruct {
    std::atomic<uint64_t> sequence;
    uint64_t hl_timestamp;
    PriceLevel hl_bids[10];
    PriceLevel hl_asks[10];
};

int main() {
    const char* shm_name = "/test_atomic_tearing";
    int fd = shm_open(shm_name, O_RDONLY, 0666);
    if (fd < 0) {
        perror("shm_open");
        return 1;
    }

    void* ptr = mmap(NULL, sizeof(L2BookStruct), PROT_READ, MAP_SHARED, fd, 0);
    if (ptr == MAP_FAILED) {
        perror("mmap");
        return 1;
    }

    L2BookStruct* book = (L2BookStruct*)ptr;
    std::cout << "Starting Atomic Tearing Reader..." << std::endl;

    uint64_t total_reads = 0;
    uint64_t torn_reads = 0;

    for (int i = 0; i < 1000000; ++i) {
        uint64_t s1, s2;
        PriceLevel local_bids[10];
        
        do {
            s1 = book->sequence.load(std::memory_order_acquire);
            while (s1 % 2 != 0) {
                std::this_thread::yield();
                s1 = book->sequence.load(std::memory_order_acquire);
            }

            std::memcpy(local_bids, book->hl_bids, sizeof(local_bids));

            s2 = book->sequence.load(std::memory_order_acquire);
        } while (s1 != s2);

        total_reads++;
        // Check for tearing: all prices should be the same in this test
        double first_price = local_bids[0].price;
        for (int j = 1; j < 10; ++j) {
            if (local_bids[j].price != first_price) {
                torn_reads++;
                std::cerr << "TORN READ DETECTED! Seq: " << s1 << " Level " << j 
                          << " Price: " << local_bids[j].price << " Expected: " << first_price << std::endl;
                break;
            }
        }
    }

    std::cout << "Test Complete. Total Reads: " << total_reads << ", Torn Reads: " << torn_reads << std::endl;
    
    munmap(ptr, sizeof(L2BookStruct));
    close(fd);
    return (torn_reads == 0) ? 0 : 1;
}
