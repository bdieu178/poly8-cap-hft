cmake_minimum_required(VERSION 3.10)
project(HFT_TapReader)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED True)

# Latency optimizations
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O3 -march=native -pthread")

# Find Dependencies
find_package(Threads REQUIRED)
find_package(Protobuf REQUIRED)
find_package(gRPC REQUIRED)
find_package(Boost 1.71.0 REQUIRED COMPONENTS system)
find_package(OpenSSL REQUIRED)

# Fetch and build cpr dependency internally
include(FetchContent)
FetchContent_Declare(
  cpr
  GIT_REPOSITORY https://github.com/libcpr/cpr.git
  GIT_TAG 1.10.5
)
FetchContent_MakeAvailable(cpr)

# Generated Proto files
set(PROTO_SRCS 
    orderbook.pb.cc
    orderbook.grpc.pb.cc
)

# Source files for the unified ingestor
set(INGESTOR_SRCS
    TapReader.cpp
    AccountSync.cpp
    MarketDiscovery.cpp
    PolymarketBridge.cpp
    ${PROTO_SRCS}
)

# Unified Ingestor Executable
add_executable(unified_ingestor ${INGESTOR_SRCS})
target_include_directories(unified_ingestor PRIVATE /usr/include/nlohmann ${Boost_INCLUDE_DIRS})
target_link_libraries(unified_ingestor
    gRPC::grpc++
    protobuf::libprotobuf
    Boost::system
    cpr::cpr
    OpenSSL::SSL
    OpenSSL::Crypto
    Threads::Threads
    rt
)

# Keep the old tapreader for backwards compatibility / testing if needed
add_executable(tapreader_legacy TapReader.cpp ${PROTO_SRCS} AccountSync.cpp MarketDiscovery.cpp PolymarketBridge.cpp)
target_include_directories(tapreader_legacy PRIVATE /usr/include/nlohmann ${Boost_INCLUDE_DIRS})
target_link_libraries(tapreader_legacy
    gRPC::grpc++
    protobuf::libprotobuf
    Boost::system
    cpr::cpr
    OpenSSL::SSL
    OpenSSL::Crypto
    Threads::Threads
    rt
)

add_executable(grpc_test_client grpc_test_client.cpp ${PROTO_SRCS})
target_link_libraries(grpc_test_client
    gRPC::grpc++
    protobuf::libprotobuf
    OpenSSL::SSL
    OpenSSL::Crypto
    Threads::Threads
    rt
)

option(BUILD_MOCK "Build with mock data for testing" OFF)
if(BUILD_MOCK)
    add_definitions(-DTEST_MOCK)
endif()

add_subdirectory(tests)
