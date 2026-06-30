mod shm;
use shm::{PositionInfoStruct, ShmWriter};
use std::sync::atomic::Ordering;

fn main() {
    let name = "test_persistence";
    let shm_path = format!("/dev/shm/{}", name);
    let _ = std::fs::remove_file(&shm_path);

    println!("Step 1: Create and initialize SHM manually...");
    {
        let mut writer = ShmWriter::<PositionInfoStruct>::new(name).unwrap();
        unsafe {
            (*writer.ptr).up_position_entry_price.store(12345, Ordering::SeqCst);
            (*writer.ptr).down_position_entry_price.store(67890, Ordering::SeqCst);
        }
    }

    println!("Step 2: Re-open SHM using ShmWriter::new (which should PRESERVE state)...");
    {
        let writer = ShmWriter::<PositionInfoStruct>::new(name).unwrap();
        unsafe {
            let up = (*writer.ptr).up_position_entry_price.load(Ordering::SeqCst);
            let down = (*writer.ptr).down_position_entry_price.load(Ordering::SeqCst);
            println!("Read values: up={}, down={}", up, down);
            if up == 12345 && down == 67890 {
                println!("SUCCESS: State preserved!");
            } else {
                println!("FAILURE: State was wiped!");
                std::process::exit(1);
            }
        }
    }
}
