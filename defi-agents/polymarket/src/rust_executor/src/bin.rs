use alloy::providers::ProviderBuilder;

fn main() {
    let rpc_url = "http://localhost:8545".parse().unwrap();
    let provider = ProviderBuilder::new().on_http(rpc_url);
}