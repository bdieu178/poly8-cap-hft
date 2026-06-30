#include <iostream>
#include <memory>
#include <string>
#include <grpcpp/grpcpp.h>
#include "orderbook.grpc.pb.h"
#include "Logger.hpp"

using grpc::Channel;
using grpc::ClientContext;
using grpc::Status;
using hyperliquid::L4BookRequest;
using hyperliquid::L4BookUpdate;
using hyperliquid::OrderBookStreaming;

int main(int argc, char** argv) {
    if (argc != 2) {
        LOG_ERR << "Usage: ./grpc_test_client <asset_name>" << std::endl;
        return 1;
    }
    std::string asset_name = argv[1];

    char* hl_target_env = std::getenv("HYPERLIQUID_GRPC_TARGET");
    std::string hl_target_str = hl_target_env ? hl_target_env : "api.hyperliquid.xyz:443";
    
    char* auth_token = std::getenv("HYPERLIQUID_AUTH_TOKEN");
    if (!auth_token) {
        LOG_ERR << "HYPERLIQUID_AUTH_TOKEN not set" << std::endl;
        return 1;
    }
    std::string token_str(auth_token);
    token_str.erase(token_str.find_last_not_of(" \n\r\t") + 1);

std::string hostname = hl_target_str;
size_t colon_pos = hostname.find(':');
if (colon_pos != std::string::npos) hostname = hostname.substr(0, colon_pos);

grpc::ChannelArguments args;
args.SetInt(GRPC_ARG_KEEPALIVE_TIME_MS, 10000);
args.SetInt(GRPC_ARG_KEEPALIVE_TIMEOUT_MS, 5000);
args.SetInt(GRPC_ARG_KEEPALIVE_PERMIT_WITHOUT_CALLS, 1);
args.SetInt(GRPC_ARG_HTTP2_MAX_PINGS_WITHOUT_DATA, 0);
args.SetString(GRPC_ARG_DEFAULT_AUTHORITY, hostname);
args.SetString(GRPC_SSL_TARGET_NAME_OVERRIDE_ARG, hostname);
args.SetMaxReceiveMessageSize(100 * 1024 * 1024);

auto channel = grpc::CreateCustomChannel(hl_target_str, grpc::SslCredentials(grpc::SslCredentialsOptions()), args);
auto stub = OrderBookStreaming::NewStub(channel);

    ClientContext context;
    context.AddMetadata("content-type", "application/grpc");
    context.AddMetadata("x-token", token_str);
    context.AddMetadata("authorization", "Bearer " + token_str);

    L4BookRequest request;
    request.set_coin(asset_name);

    auto reader = stub->StreamL4Book(&context, request);

    LOG_OUT << "Connected and streaming L4 Book for 60 seconds..." << std::endl;

    L4BookUpdate update;
    auto start_time = std::chrono::steady_clock::now();
    while (reader->Read(&update)) {
        LOG_OUT << "Received L4 update." << std::endl;
        if (std::chrono::steady_clock::now() - start_time > std::chrono::seconds(60)) {
            break;
        }    }

    Status status = reader->Finish();
    if (!status.ok()) {
        LOG_ERR << "RPC failed: " << status.error_message() << std::endl;
    } else {
        LOG_OUT << "Stream finished gracefully." << std::endl;
    }

    return 0;
}
