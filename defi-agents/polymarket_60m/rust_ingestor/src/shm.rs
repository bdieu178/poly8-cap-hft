use std::ffi::CString;
use std::ptr;
use std::sync::atomic::{AtomicU64, Ordering, AtomicU32};
use libc::{shm_open, mmap, O_RDWR, O_CREAT, ftruncate, PROT_READ, PROT_WRITE, MAP_SHARED};

pub const MAX_LEVELS: usize = 10;
pub const MAX_POLY_LEVELS: usize = 5;

#[repr(C)]
#[derive(Debug, Clone, Copy, Default)]
pub struct PriceLevel {
    pub price: f64,
    pub size: f64,
}

/// A plain-data version of L2BookStruct for safe copying.
/// Matches C++ layout exactly.
#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct L2BookSnapshot {
    pub hl_sequence: u64,
    pub poly_sequence: u64,
    pub hl_timestamp: u64,
    pub hl_bids: [PriceLevel; MAX_LEVELS],
    pub hl_asks: [PriceLevel; MAX_LEVELS],
    pub poly_up_timestamp: u64,
    pub poly_up_bids: [PriceLevel; MAX_POLY_LEVELS],
    pub poly_up_asks: [PriceLevel; MAX_POLY_LEVELS],
    pub poly_down_timestamp: u64,
    pub poly_down_bids: [PriceLevel; MAX_POLY_LEVELS],
    pub poly_down_asks: [PriceLevel; MAX_POLY_LEVELS],
    pub strike_price: f64,
    pub rotation_ts: u64,
    pub poly_up_id: [u8; 128],
    pub poly_down_id: [u8; 128],
    pub current_ofi: f64,
    pub execution_flow_rate: f64,
    pub p_max_i: f64,
    pub signed_flow_rate: f64,
    pub event_flags: u32,
    pub padding0: u32,
    pub last_event_ts: u64,
    pub regime_multiplier: f64,
    pub regime_state_enum: u32,
    pub padding1: u32,
    pub last_update_local_ns: u64,
    pub hot_path_latency_ns: u64,
    pub hl_l4_height: u64,
    pub bid_order_count: u32,
    pub ask_order_count: u32,
    pub whale_bid_size: f64,
    pub whale_ask_size: f64,
    pub bid_concentration: f64,
    pub ask_concentration: f64,
}

impl Default for L2BookSnapshot {
    fn default() -> Self {
        unsafe { std::mem::zeroed() }
    }
}

#[repr(C)]
#[derive(Debug)]
pub struct L2BookStruct {
    pub hl_sequence: AtomicU64,
    pub poly_sequence: AtomicU64,
    pub hl_timestamp: u64,
    pub hl_bids: [PriceLevel; MAX_LEVELS],
    pub hl_asks: [PriceLevel; MAX_LEVELS],
    pub poly_up_timestamp: u64,
    pub poly_up_bids: [PriceLevel; MAX_POLY_LEVELS],
    pub poly_up_asks: [PriceLevel; MAX_POLY_LEVELS],
    pub poly_down_timestamp: u64,
    pub poly_down_bids: [PriceLevel; MAX_POLY_LEVELS],
    pub poly_down_asks: [PriceLevel; MAX_POLY_LEVELS],
    pub strike_price: f64,
    pub rotation_ts: u64,
    pub poly_up_id: [u8; 128],
    pub poly_down_id: [u8; 128],
    pub current_ofi: f64,
    pub execution_flow_rate: f64,
    pub p_max_i: f64,
    pub signed_flow_rate: f64,
    pub event_flags: AtomicU32,
    pub padding0: u32,
    pub last_event_ts: u64,
    pub regime_multiplier: f64,
    pub regime_state_enum: u32,
    pub padding1: u32,
    pub last_update_local_ns: u64,
    pub hot_path_latency_ns: u64,
    pub hl_l4_height: u64,
    pub bid_order_count: u32,
    pub ask_order_count: u32,
    pub whale_bid_size: f64,
    pub whale_ask_size: f64,
    pub bid_concentration: f64,
    pub ask_concentration: f64,
    pub padding_final: [u8; 72],
}

impl L2BookStruct {
    pub fn copy_to_snapshot(&self) -> L2BookSnapshot {
        L2BookSnapshot {
            hl_sequence: self.hl_sequence.load(Ordering::Acquire),
            poly_sequence: self.poly_sequence.load(Ordering::Acquire),
            hl_timestamp: self.hl_timestamp,
            hl_bids: self.hl_bids,
            hl_asks: self.hl_asks,
            poly_up_timestamp: self.poly_up_timestamp,
            poly_up_bids: self.poly_up_bids,
            poly_up_asks: self.poly_up_asks,
            poly_down_timestamp: self.poly_down_timestamp,
            poly_down_bids: self.poly_down_bids,
            poly_down_asks: self.poly_down_asks,
            strike_price: self.strike_price,
            rotation_ts: self.rotation_ts,
            poly_up_id: self.poly_up_id,
            poly_down_id: self.poly_down_id,
            current_ofi: self.current_ofi,
            execution_flow_rate: self.execution_flow_rate,
            p_max_i: self.p_max_i,
            signed_flow_rate: self.signed_flow_rate,
            event_flags: self.event_flags.load(Ordering::Acquire),
            padding0: self.padding0,
            last_event_ts: self.last_event_ts,
            regime_multiplier: self.regime_multiplier,
            regime_state_enum: self.regime_state_enum,
            padding1: self.padding1,
            last_update_local_ns: self.last_update_local_ns,
            hot_path_latency_ns: self.hot_path_latency_ns,
            hl_l4_height: self.hl_l4_height,
            bid_order_count: self.bid_order_count,
            ask_order_count: self.ask_order_count,
            whale_bid_size: self.whale_bid_size,
            whale_ask_size: self.whale_ask_size,
            bid_concentration: self.bid_concentration,
            ask_concentration: self.ask_concentration,
        }
    }
}

impl Default for L2BookStruct {
    fn default() -> Self {
        unsafe {
            let mut s: Self = std::mem::zeroed();
            s.regime_multiplier = 1.0;
            s
        }
    }
}

#[repr(C)]
#[derive(Debug)]
pub struct AccountStateStruct {
    pub sequence: AtomicU64,
    pub available_collateral: f64,
    pub total_equity: f64,
    pub total_maint_margin: f64,
    pub up_position: f64,
    pub down_position: f64,
    pub next_nonce: AtomicU64,
    pub last_update_ts: u64,
}

impl Default for AccountStateStruct {
    fn default() -> Self {
        Self {
            sequence: AtomicU64::new(0),
            available_collateral: 0.0,
            total_equity: 0.0,
            total_maint_margin: 0.0,
            up_position: 0.0,
            down_position: 0.0,
            next_nonce: AtomicU64::new(1),
            last_update_ts: 0,
        }
    }
}

#[repr(C)]
#[derive(Debug)]
pub struct PositionInfoStruct {
    pub up_position_entry_price: AtomicU64,
    pub down_position_entry_price: AtomicU64,
    pub realized_pnl: AtomicU64,
    pub cumulative_fees: AtomicU64,
    pub is_exiting_up: AtomicU64,   // 1 if exit in progress
    pub is_exiting_down: AtomicU64, // 1 if exit in progress
}

impl Default for PositionInfoStruct {
    fn default() -> Self {
        Self {
            up_position_entry_price: AtomicU64::new(0),
            down_position_entry_price: AtomicU64::new(0),
            realized_pnl: AtomicU64::new(0),
            cumulative_fees: AtomicU64::new(0),
            is_exiting_up: AtomicU64::new(0),
            is_exiting_down: AtomicU64::new(0),
        }
    }
}

#[repr(C)]
#[derive(Debug)]
pub struct GlobalRiskStruct {
    pub sequence: AtomicU64,
    pub global_gross_exposure: AtomicU64, // Notional USD (bits)
    pub global_net_pnl: AtomicU64,        // Realized PnL - Fees (bits)
    pub daily_stop_loss_triggered: AtomicU64, // 1 if triggered
    pub last_update_ts: AtomicU64,
}

impl Default for GlobalRiskStruct {
    fn default() -> Self {
        Self {
            sequence: AtomicU64::new(0),
            global_gross_exposure: AtomicU64::new(0),
            global_net_pnl: AtomicU64::new(0),
            daily_stop_loss_triggered: AtomicU64::new(0),
            last_update_ts: AtomicU64::new(0),
        }
    }
}

#[repr(C)]
pub struct CognitionStateStruct {
    pub sequence: AtomicU64,
    pub regime_multiplier: f64,
    pub regime_state_enum: u32,
}

pub struct ShmReader<T> {
    pub ptr: *const T,
}

unsafe impl<T> Send for ShmReader<T> {}
unsafe impl<T> Sync for ShmReader<T> {}

impl<T> ShmReader<T> {
    pub fn new(name: &str) -> Result<Self, String> {
        unsafe {
            let c_name = CString::new(name).unwrap();
            let fd = shm_open(c_name.as_ptr(), O_RDWR, 0o666);
            if fd < 0 {
                return Err(format!("Failed to open SHM segment {}: {}", name, fd));
            }
            let ptr = mmap(
                ptr::null_mut(),
                std::mem::size_of::<T>(),
                PROT_READ | PROT_WRITE,
                MAP_SHARED,
                fd,
                0,
            );
            if ptr == libc::MAP_FAILED {
                return Err(format!("Failed to mmap SHM segment {}", name));
            }
            Ok(Self { ptr: ptr as *const T })
        }
    }
}

pub struct ShmWriter<T> {
    pub ptr: *mut T,
}

unsafe impl<T> Send for ShmWriter<T> {}
unsafe impl<T> Sync for ShmWriter<T> {}

impl<T> ShmWriter<T> {
    pub fn new(name: &str) -> Result<Self, String> {
        unsafe {
            let c_name = CString::new(name).unwrap();
            let fd = shm_open(c_name.as_ptr(), O_RDWR | O_CREAT, 0o666);
            if fd < 0 {
                return Err(format!("Failed to create/open SHM segment {}: {}", name, fd));
            }
            
            let mut stat: libc::stat = std::mem::zeroed();
            if libc::fstat(fd, &mut stat) == -1 {
                return Err(format!("Failed to fstat SHM segment {}", name));
            }
            let is_new = stat.st_size == 0;

            if ftruncate(fd, std::mem::size_of::<T>() as libc::off_t) == -1 {
                return Err(format!("Failed to ftruncate SHM segment {}", name));
            }
            let ptr = mmap(
                ptr::null_mut(),
                std::mem::size_of::<T>(),
                PROT_READ | PROT_WRITE,
                MAP_SHARED,
                fd,
                0,
            );
            if ptr == libc::MAP_FAILED {
                return Err(format!("Failed to mmap SHM segment {}", name));
            }
            
            if is_new {
                ptr::write_bytes(ptr, 0, std::mem::size_of::<T>());
            }
            Ok(Self { ptr: ptr as *mut T })
        }
    }
}


#[cfg(test)]
mod tests {
    use super::*;
    use std::mem::{size_of, offset_of};

    #[test]
    fn test_struct_sizes() {
        assert_eq!(size_of::<L2BookStruct>(), 912);
        assert_eq!(size_of::<AccountStateStruct>(), 64);
        assert_eq!(size_of::<PositionInfoStruct>(), 16);
        assert_eq!(size_of::<CognitionStateStruct>(), 24);
    }

    #[test]
    fn test_l2_book_offsets() {
        assert_eq!(offset_of!(L2BookStruct, sequence), 0);
        assert_eq!(offset_of!(L2BookStruct, hl_timestamp), 8);
        assert_eq!(offset_of!(L2BookStruct, hl_bids), 16);
        assert_eq!(offset_of!(L2BookStruct, hl_asks), 176);
        assert_eq!(offset_of!(L2BookStruct, poly_up_timestamp), 336);
        assert_eq!(offset_of!(L2BookStruct, poly_down_timestamp), 504);
        assert_eq!(offset_of!(L2BookStruct, current_ofi), 672);
        assert_eq!(offset_of!(L2BookStruct, event_flags), 696);
        assert_eq!(offset_of!(L2BookStruct, regime_multiplier), 712);
        assert_eq!(offset_of!(L2BookStruct, last_update_local_ns), 728);
        assert_eq!(offset_of!(L2BookStruct, hl_l4_height), 744);
        assert_eq!(offset_of!(L2BookStruct, bid_order_count), 752);
        assert_eq!(offset_of!(L2BookStruct, whale_bid_size), 760);
        assert_eq!(offset_of!(L2BookStruct, padding_final), 792);
    }

    #[test]
    fn test_account_state_offsets() {
        assert_eq!(offset_of!(AccountStateStruct, sequence), 0);
        assert_eq!(offset_of!(AccountStateStruct, available_collateral), 8);
        assert_eq!(offset_of!(AccountStateStruct, up_position), 32);
        assert_eq!(offset_of!(AccountStateStruct, down_position), 40);
        assert_eq!(offset_of!(AccountStateStruct, next_nonce), 48);
        assert_eq!(offset_of!(AccountStateStruct, last_update_ts), 56);
    }

    #[test]
    fn test_position_info_offsets() {
        assert_eq!(offset_of!(PositionInfoStruct, up_position_entry_price), 0);
        assert_eq!(offset_of!(PositionInfoStruct, down_position_entry_price), 8);
    }
}