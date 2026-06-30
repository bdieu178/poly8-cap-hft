#include <boost/beast/core.hpp>
#include <boost/beast/websocket.hpp>
#include <boost/beast/ssl.hpp>
#include <boost/asio/connect.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/asio/ssl/stream.hpp>
#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>
#include <nlohmann/json.hpp>
#include "SharedMemoryManager.hpp"

namespace beacon = boost::beast;
namespace http = beacon::http;
namespace websocket = beacon::websocket;
namespace net = boost::asio;
namespace ssl = net::ssl;
using tcp = net::ip::tcp;
using json = nlohmann::json;

class PolyTapReader {
private:
    L2BookStruct* shared_book;
    std::string token_id;

public:
    PolyTapReader(L2BookStruct* book, std::string tid) : shared_book(book), token_id(tid) {}

    void Run() {
        std::string host = "clob.polymarket.com";
        std::string port = "443";

        net::io_context ioc;
        ssl::context ctx{ssl::context::tlsv12_client};

        tcp::resolver resolver{ioc};
        websocket::stream<beacon::ssl_stream<tcp::socket>> ws{ioc, ctx};

        auto const results = resolver.resolve(host, port);
        auto ep = net::connect(get_lowest_layer(ws), results);

        if(!SSL_set_tlsext_host_name(ws.next_layer().native_handle(), host.c_str()))
            throw beacon::system_error(beacon::error_code(static_cast<int>(::ERR_get_error()), net::error::get_ssl_category()));

        ws.next_layer().handshake(ssl::stream_base::client);
        ws.handshake(host, "/ws");

        // Subscribe to book
        json sub = {
            {"type", "subscribe"},
            {"assets_ids", {token_id}},
            {"channels", {"book"}}
        };
        ws.write(net::buffer(sub.dump()));

        std::cout << "Polymarket TapReader connected and subscribed to " << token_id << std::endl;

        for(;;) {
            beacon::flat_buffer buffer;
            ws.read(buffer);
            auto msg = beacon::buffers_to_string(buffer.data());
            ParseAndWrite(msg);
        }
    }

private:
    void ParseAndWrite(const std::string& data) {
        try {
            auto j = json::parse(data);
            if (j.contains("event_type") && j["event_type"] == "book") {
                // Seqlock Acquire (Spinlock)
                uint64_t seq = shared_book->sequence.load(std::memory_order_relaxed);
                while (true) {
                    if (seq % 2 == 1) {
                        seq = shared_book->sequence.load(std::memory_order_relaxed);
                        continue;
                    }
                    if (shared_book->sequence.compare_exchange_weak(seq, seq + 1, std::memory_order_acquire, std::memory_order_relaxed)) {
                        break;
                    }
                }

                shared_book->poly_up_timestamp = std::chrono::system_clock::now().time_since_epoch().count();
                
                // Parse Bids (Polymarket format: [[price, size], ...])
                int i = 0;
                for (auto& level : j["bids"]) {
                    if (i >= MAX_POLY_LEVELS) break;
                    shared_book->poly_up_bids[i].price = std::stod(level["price"].get<std::string>());
                    shared_book->poly_up_bids[i].size = std::stod(level["size"].get<std::string>());
                    i++;
                }

                // Parse Asks
                i = 0;
                for (auto& level : j["asks"]) {
                    if (i >= MAX_POLY_LEVELS) break;
                    shared_book->poly_up_asks[i].price = std::stod(level["price"].get<std::string>());
                    shared_book->poly_up_asks[i].size = std::stod(level["size"].get<std::string>());
                    i++;
                }

                // Seqlock Release
                shared_book->sequence.store(seq + 2, std::memory_order_release);
            }
        } catch (std::exception& e) {
            std::cerr << "JSON Error: " << e.what() << std::endl;
        }
    }
};

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "Usage: polytap <token_id>" << std::endl;
        return 1;
    }
    
    try {
        SharedMemoryManager shm("/hl_l2_book", false); // Open existing
        PolyTapReader reader(shm.get(), argv[1]);
        reader.Run();
    } catch (std::exception& e) {
        std::cerr << "Fatal Error: " << e.what() << std::endl;
        return 1;
    }
    return 0;
}
