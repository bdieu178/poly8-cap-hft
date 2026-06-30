#pragma once
#include <string>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stdexcept>
#include <atomic>

template<typename T>
class SharedMemoryManager {
private:
    std::string shm_name;
    int shm_fd;
    T* mapped_ptr;
    bool is_creator;

public:
    SharedMemoryManager(const std::string& name, bool create = false) 
        : shm_name(name), is_creator(create), mapped_ptr(nullptr) {
        
        int flags = create ? (O_CREAT | O_RDWR) : O_RDWR;
        shm_fd = shm_open(shm_name.c_str(), flags, 0666);
        if (shm_fd == -1) {
            throw std::runtime_error("Failed to open shared memory: " + shm_name);
        }

        if (create) {
            if (ftruncate(shm_fd, sizeof(T)) == -1) {
                close(shm_fd);
                shm_unlink(shm_name.c_str());
                throw std::runtime_error("Failed to set size of shared memory");
            }
        }

        mapped_ptr = static_cast<T*>(mmap(nullptr, sizeof(T), PROT_READ | PROT_WRITE, MAP_SHARED, shm_fd, 0));
        if (mapped_ptr == MAP_FAILED) {
            close(shm_fd);
            if (create) shm_unlink(shm_name.c_str());
            throw std::runtime_error("Failed to mmap shared memory");
        }

        if (create) {
            new (mapped_ptr) T();
        }
    }

    ~SharedMemoryManager() {
        if (mapped_ptr != MAP_FAILED) {
            munmap(mapped_ptr, sizeof(T));
        }
        if (shm_fd != -1) {
            close(shm_fd);
        }
        if (is_creator) {
            shm_unlink(shm_name.c_str());
        }
    }

    T* get() {
        return mapped_ptr;
    }
};
