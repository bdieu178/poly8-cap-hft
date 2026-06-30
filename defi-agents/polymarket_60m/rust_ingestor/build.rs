fn main() -> Result<(), Box<dyn std::error::Error>> {
    tonic_build::configure()
        .compile(&["../src/hft_tapreader/proto/orderbook.proto"], &["../src/hft_tapreader/proto"])?;
    Ok(())
}
