use std::fs::OpenOptions;
use std::io::{self, Write};
use std::os::unix::io::AsRawFd;
use std::ptr;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
use libc::{mmap, PROT_READ, PROT_WRITE, MAP_SHARED, MAP_FAILED};

#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct JournalEntry {
    pub timestamp_ns: u64,
    pub order_id: [u8; 64], // Fixed size for mmap
    pub token_id: [u8; 128],
    pub side: u8, // 0 for Buy, 1 for Sell
    pub size: f64,
    pub price: f64,
    pub status: u8, // 0 for Intent, 1 for Submitted, 2 for Error
}

const JOURNAL_FILE_PATH: &str = "/home/bdieu178/user/defi-agents/polymarket/data/journal.bin";
const MAX_ENTRIES: usize = 10000;
const JOURNAL_SIZE: usize = std::mem::size_of::<JournalHeader>() + (MAX_ENTRIES * std::mem::size_of::<JournalEntry>());

#[repr(C)]
pub struct JournalHeader {
    pub head: AtomicU64, // The index of the next entry to write
    pub tail: AtomicU64, // The index of the next entry to process (by the background thread)
}

pub struct JournalWriter {
    ptr: *mut u8,
}

impl JournalWriter {
    pub fn new() -> io::Result<Self> {
        let mut path = JOURNAL_FILE_PATH.to_string();
        if let Ok(home) = std::env::var("HOME") {
            let user_path = format!("{}/user/defi-agents/polymarket/data/journal.bin", home);
            if std::path::Path::new(&user_path).parent().map(|p| p.exists()).unwrap_or(false) {
                path = user_path;
            } else {
                let direct_path = format!("{}/defi-agents/polymarket/data/journal.bin", home);
                if std::path::Path::new(&direct_path).parent().map(|p| p.exists()).unwrap_or(false) {
                    path = direct_path;
                }
            }
        }

        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .open(&path)?;

        file.set_len(JOURNAL_SIZE as u64)?;

        let ptr = unsafe {
            mmap(
                ptr::null_mut(),
                JOURNAL_SIZE,
                PROT_READ | PROT_WRITE,
                MAP_SHARED,
                file.as_raw_fd(),
                0,
            )
        };

        if ptr == MAP_FAILED {
            return Err(io::Error::last_os_error());
        }

        Ok(Self { ptr: ptr as *mut u8 })
    }

    pub fn write_intent(&self, order_id: &str, token_id: &str, side: u8, size: f64, price: f64) {
        unsafe {
            let header = &*(self.ptr as *const JournalHeader);
            let head = header.head.load(Ordering::Relaxed);
            let entry_idx = (head % MAX_ENTRIES as u64) as usize;
            
            let entry_ptr = (self.ptr.add(std::mem::size_of::<JournalHeader>()) as *mut JournalEntry).add(entry_idx);
            
            let mut id_bytes = [0u8; 64];
            let id_src = order_id.as_bytes();
            let id_len = id_src.len().min(64);
            id_bytes[..id_len].copy_from_slice(&id_src[..id_len]);

            let mut token_bytes = [0u8; 128];
            let token_src = token_id.as_bytes();
            let token_len = token_src.len().min(128);
            token_bytes[..token_len].copy_from_slice(&token_src[..token_len]);

            let entry = JournalEntry {
                timestamp_ns: SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos() as u64,
                order_id: id_bytes,
                token_id: token_bytes,
                side,
                size,
                price,
                status: 0, // Intent
            };

            ptr::write_volatile(entry_ptr, entry);
            header.head.store(head + 1, Ordering::Release);
        }
    }

    pub fn get_header(&self) -> &JournalHeader {
        unsafe { &*(self.ptr as *const JournalHeader) }
    }

    pub fn get_entry(&self, index: usize) -> &JournalEntry {
        unsafe {
            let entry_ptr = (self.ptr.add(std::mem::size_of::<JournalHeader>()) as *const JournalEntry).add(index % MAX_ENTRIES);
            &*entry_ptr
        }
    }
}

unsafe impl Send for JournalWriter {}
unsafe impl Sync for JournalWriter {}
