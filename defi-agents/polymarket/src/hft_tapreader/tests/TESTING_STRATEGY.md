# C++ Ingestor Resilience Testing Strategy

**CREATED:** 2026-05-19 00:00:00 UTC
**EDITED:** 2026-05-19 00:00:00 UTC

## 1. Overview

This document outlines the testing strategy for hardening the C++ data ingestors (`PolymarketBridge` and `GRPCIngestor`) against network failures. The primary goal is to simulate connection drops and timeouts to verify that our keepalive, timeout, and reconnection logic is robust.

The recommended approach is to use the **GoogleTest framework** (which is already in use) in combination with **GoogleMock** to create mock networking clients. This allows us to trigger specific error conditions in a controlled environment without relying on actual network failures.

## 2. Testing `PolymarketBridge` (WebSocket)

The main goal is to test the non-blocking read timeout and the keepalive ping mechanism.

### 2.1 Test Case: WebSocket Read Timeout

*   **Objective:** Verify that if the WebSocket `read` operation times out, the `PolymarketBridge` catches the exception and correctly initiates a reconnection sequence.

*   **Implementation Steps:**
    1.  **Create a Mock WebSocket Stream:**
        *   Define a `MockWebSocketStream` class that inherits from a base stream interface or uses templates.
        *   Using `gmock`, create a mock method `MOCK_METHOD(size_t, read, (boost::beast::flat_buffer&), ());`.
    2.  **Configure the Mock:**
        *   In the test case, set up the mock `read` method to throw a `boost::system::system_error` with the error code `boost::asio::error::operation_aborted` or a similar timeout-related error.
        *   ```cpp
          // Example gmock setup
          using ::testing::Throw;
          // ...
          mock_ws_stream.EXPECT_CALL(read, _)
              .WillOnce(Throw(boost::system::system_error(boost::asio::error::operation_aborted)));
          ```
    3.  **Inject the Mock:**
        *   Refactor `PolymarketBridge`'s constructor to accept a pointer or reference to a generic stream object rather than creating the `websocket::stream` internally. This is a standard dependency injection pattern.
    4.  **Execute and Assert:**
        *   Run the `ConnectionLoop` in a detached thread.
        *   The assertion can be done by monitoring the log output. The test should check for the `[PolyBridge] WebSocket error: ... Reconnecting...` log message. Alternatively, a mock logging singleton could be used to assert that the specific error message was logged.

### 2.2 Test Case: WebSocket Ping Mechanism

*   **Objective:** Verify that the bridge sends a `ping` frame after a period of inactivity.

*   **Implementation Steps:**
    1.  **Use the Mock WebSocket Stream:** from the previous test.
    2.  **Add a Mock `ping` Method:** Add `MOCK_METHOD(void, ping, (boost::beast::websocket::ping_data const&), ());` to the mock class.
    3.  **Configure and Execute:**
        *   Set up the mock `read` method to block for a duration longer than the ping interval (15 seconds). This can be done with `std::this_thread::sleep_for`.
        *   Set an expectation on the `ping` method: `EXPECT_CALL(mock_ws_stream, ping(_)).Times(1);`
        *   Run the `ConnectionLoop` and wait for a period greater than the ping interval.
    4.  **Assert:** The test will automatically pass if the `ping` method is called exactly once, as expected.

## 3. Testing `GRPCIngestor` (gRPC)

Testing gRPC clients is more involved but follows similar principles.

### 3.1 Test Case: gRPC Stream Failure and Reconnection

*   **Objective:** Verify that if the gRPC `Read()` call fails or the stream finishes unexpectedly, the `GRPCIngestor`'s exponential backoff and reconnection loop is correctly triggered.

*   **Implementation Steps:**
    1.  **Use gRPC's Mocking Tools:** gRPC provides its own testing library, which includes `grpc::testing::MockClientReader`.
    2.  **Create a Mock gRPC Client:**
        *   Define a `MockGrpcStub` class that inherits from the generated gRPC stub interface.
        *   Override the method that returns the `ClientReader` (e.g., `PrepareAsyncL4Updates`) to return an instance of `MockClientReader`.
    3.  **Configure the Mock Reader:**
        *   Set up the mock `Read()` method to return `false` after a few successful reads, simulating a stream termination.
        *   Set up the mock `Finish()` method to return a `grpc::Status` with an error code (e.g., `grpc::StatusCode::UNAVAILABLE`).
    4.  **Inject and Execute:**
        *   Inject the mock stub into the `GRPCIngestor`.
        *   Run the `StreamL4Updates` loop.
    5.  **Assert:**
        *   Check the logs for the "Stream finished with status: ... Reconnecting..." message.
        *   Verify that the `backoff_ms` increases after each failed attempt. This can be done by inspecting the class state or logging the backoff value.

By implementing these test cases, we can build a high degree of confidence in the resilience of our data ingestion pipeline, ensuring that the fixes we've implemented are effective and do not introduce new regressions.
