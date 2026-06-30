use rust_ingestor::{Args, run};
use clap::Parser;
use futures::future::pending;

#[tokio::main]
async fn main() -> Result<(), String> {
    let args = Args::parse();
    run(args, pending()).await
}
