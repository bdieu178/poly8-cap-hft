#pragma once
#include <atomic>
#include <cstdint>

// A RAII guard to manage the seqlock sequence number in shared memory.
// It increments the sequence to an odd number on construction (indicating write in progress)
// and to an even number on destruction (indicating write complete), even if exceptions occur.
class SequenceGuard {
public:
    // Constructor: Takes a reference to the atomic sequence number.
    // Increments the sequence number to an odd value, marking the start of a write operation.
    explicit SequenceGuard(std::atomic<uint64_t>& sequence_ref, const std::string& component_name = "Unknown")
        : sequence_(sequence_ref), component_name_(component_name) {
        
        // Atomically load and increment sequence number to odd.
        // Loop until we successfully transition from an even state to (even + 1) which is odd.
        uint64_t expected_seq = sequence_.load(std::memory_order_relaxed);
        size_t spin_count = 0;
        while (true) {
            if (expected_seq % 2 == 1) {
                spin_count++;
                if (spin_count % 1000000 == 0) { // Log every ~1M spins
                    LOG_ERR << "[SequenceGuard] " << component_name_ << " encountered odd sequence " << expected_seq << " on entry. Waiting. (Spins: " << spin_count << ")" << std::endl;
                }
                if (spin_count > 10000000) { // Emergency recovery after ~10s of spinning
                    LOG_ERR << "[SequenceGuard] CRITICAL: Deadlock detected in " << component_name_ << ". Emergency resetting sequence to even." << std::endl;
                    sequence_.store(expected_seq + 1, std::memory_order_release);
                    expected_seq = expected_seq + 1;
                    continue;
                }
                std::this_thread::yield();
                expected_seq = sequence_.load(std::memory_order_relaxed);
                continue;
            }
            if (sequence_.compare_exchange_weak(expected_seq, expected_seq + 1,
                                                std::memory_order_acquire,
                                                std::memory_order_relaxed)) {
                break;
            }
        }
    }

    // Destructor: Increments the sequence number to an even value, marking the end of a write.
    // This is guaranteed to run even if exceptions are thrown during the guarded block.
    ~SequenceGuard() {
        // Increment the sequence number by 1 to make it even again.
        // This is the final step of the seqlock write.
        // Use memory_order_release to ensure all prior writes are visible before this store.
        uint64_t final_seq = sequence_.fetch_add(1, std::memory_order_release);
        // LOG_OUT << "[SequenceGuard] " << component_name_ << " released, sequence: " << final_seq + 1 << std::endl;
    }


    // Prevent copy and move operations to ensure unique ownership of the guarded sequence.
    SequenceGuard(const SequenceGuard&) = delete;
    SequenceGuard& operator=(const SequenceGuard&) = delete;
    SequenceGuard(SequenceGuard&&) = delete;
    SequenceGuard& operator=(SequenceGuard&&) = delete;

private:
    std::atomic<uint64_t>& sequence_;
    std::string component_name_; // Declare component_name_ here
};