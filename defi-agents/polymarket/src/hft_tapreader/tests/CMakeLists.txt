cmake_minimum_required(VERSION 3.10)
project(HFT_TapReader_Tests)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED True)

# Add UNIT_TEST definition to allow exposing private members and skipping main()
add_definitions(-DUNIT_TEST)

find_package(GTest REQUIRED)
find_package(Protobuf REQUIRED)
find_package(gRPC REQUIRED)
find_package(Threads REQUIRED)
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

set(PROTO_SRCS 
    ../orderbook.pb.cc
    ../orderbook.grpc.pb.cc
)

add_executable(run_tests 
    SharedMemoryTests.cpp 
    IngestorTests.cpp 
    ParserTests.cpp
    AccountTests.cpp
    SpscRingBufferTests.cpp
    ../AccountSync.cpp
    ../MarketDiscovery.cpp
    ../PolymarketBridge.cpp
    ${PROTO_SRCS}
)

target_include_directories(run_tests PRIVATE /usr/include/nlohmann ${Boost_INCLUDE_DIRS})

target_link_libraries(run_tests
    GTest::gtest_main
    gRPC::grpc++
    protobuf::libprotobuf
    Boost::system
    cpr::cpr
    OpenSSL::SSL
    OpenSSL::Crypto
    Threads::Threads
    rt
)

enable_testing()
add_test(NAME AllTests COMMAND run_tests)
