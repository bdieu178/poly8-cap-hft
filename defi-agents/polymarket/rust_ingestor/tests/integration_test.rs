use std::env;
use std::time::Duration;
use tokio::time::{timeout, sleep};
use tokio::sync::oneshot;
use mockito;

use rust_ingestor::{run, Args};
use rust_ingestor::shm;

#[tokio::test]
async fn test_ingestor_smoke_test() {
    let asset = "test_asset";
    let l2_shm_name = format!("/hl_l2_book_{}", asset);
    let acc_shm_name = format!("/poly_account_{}", asset);

    // --- Mock Gamma API Server ---
    let mock_market_response = r#"
    [
        {
            "id": "0x123",
            "clobTokenIds": ["1111111111111111111111111111111111111111111111111111111111111111111", "2222222222222222222222222222222222222222222222222222222222222222222"],
            "outcomes": ["Up", "Down"]
        }
    ]
    "#;
    let _m = mockito::mock("GET", mockito::Matcher::Any)
        .with_status(200)
        .with_header("content-type", "application/json")
        .with_body(mock_market_response)
        .create();

    // --- 1. Setup Environment Variables for Test ---
    env::set_var("GAMMA_API_URL", &mockito::server_url());
    env::set_var("TEST_DISABLE_HL", "true");
    env::set_var("TEST_DISABLE_WEB3", "true");

    // --- 2. Clean up any old SHM segments ---
    println!("Cleaning up old SHM segments: {} and {}", l2_shm_name, acc_shm_name);
    let _ = std::process::Command::new("rm")
        .args(&["-f", &format!("/dev/shm{}", l2_shm_name), &format!("/dev/shm{}", acc_shm_name)])
        .status();

    // --- 3. Prepare for graceful shutdown ---
    let (shutdown_tx, shutdown_rx) = oneshot::channel();
    let args = Args { asset: asset.to_string() };

    // --- 4. Spawn the ingestor and let it run for a short period ---
    println!("Spawning ingestor for {} seconds...", 5);
    let ingestor_handle = tokio::spawn(async move {
        rust_ingestor::run_test(args, async move { let _ = shutdown_rx.await; }).await
    });

    // Let the ingestor run for a short time
    sleep(Duration::from_secs(5)).await;
    println!("Ingestor run time elapsed. Sending shutdown signal.");

    // --- 5. Send shutdown signal ---
    let _ = shutdown_tx.send(());

    // Wait for the ingestor to shut down
    let shutdown_timeout = Duration::from_secs(5);
    let run_result = timeout(shutdown_timeout, ingestor_handle).await
        .expect("Ingestor should shut down gracefully")
        .expect("Tokio task join should succeed");
    
    assert!(run_result.is_ok(), "Ingestor run should complete without error. Error: {:?}", run_result.err());
    println!("Ingestor shut down successfully.");

    // --- 6. Assert SHM state ---
    println!("Asserting SHM states...");
    let l2_reader = shm::ShmReader::<shm::L2BookStruct>::new(&l2_shm_name)
        .expect("Failed to create L2 SHM reader");

    unsafe {
        let l2_seq = (*l2_reader.ptr).sequence.load(std::sync::atomic::Ordering::Acquire);
        println!("L2 SHM Sequence: {}", l2_seq);
        
        // Assert that the L2 book sequence number has incremented.
        assert!(l2_seq > 0, "L2 SHM sequence should be greater than 0");
    }
    println!("SHM assertions passed.");

    // --- 7. Cleanup SHM segments ---
    println!("Final cleanup of SHM segments.");
    let _ = std::process::Command::new("rm")
        .args(&["-f", &format!("/dev/shm{}", l2_shm_name)])
        .status();
}
