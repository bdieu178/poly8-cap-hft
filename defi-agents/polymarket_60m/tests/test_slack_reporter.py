import unittest
import unittest.mock
import os
import subprocess
import re
import ctypes
import time
import json

# Add project root to path to allow imports
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from scripts import generate_live_slack_report
from utils.shm_types import L2BookStruct, AccountStateStruct

class TestSlackReporter(unittest.TestCase):
    def setUp(self):
        """Mock all external dependencies."""
        self.mock_pgrep = self.patch('subprocess.check_output')
        self.mock_shm = self.patch('scripts.generate_live_slack_report.POSIXSharedMemory')
        self.mock_read_shm = self.patch('scripts.generate_live_slack_report.read_shm_snapshot')
        self.mock_read_spsc = self.patch('scripts.generate_live_slack_report.read_spsc_ring_buffer_snapshot')
        self.mock_requests = self.patch('requests.post')

        # Mock the SHM snapshot data
        self.l2_snapshot = L2BookStruct()
        self.l2_snapshot.hl_timestamp = int(time.time() * 1000) - 1000 # 1s ago
        self.l2_snapshot.poly_up_timestamp = int(time.time() * 1000) - 2000 # 2s ago
        self.l2_snapshot.current_ofi = -123.45
        self.l2_snapshot.execution_flow_rate = 543.21

        self.acc_snapshot = AccountStateStruct()
        self.acc_snapshot.available_collateral = 1019.72
        self.acc_snapshot.up_position = 50.0
        self.acc_snapshot.down_position = 10.0

        # Set default mock return values
        self.mock_read_spsc.return_value = self.l2_snapshot
        self.mock_read_shm.return_value = self.acc_snapshot

    def patch(self, path):
        patcher = unittest.mock.patch(path)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_full_report_generation_healthy(self):
        """
        Verify a complete, healthy report is generated when all data sources are available.
        """
        # --- MOCK SETUP ---
        # 1. Mock Processes: All are running
        def pgrep_side_effect(args, **kwargs):
            cmd = args[1]
            if "unified_ingestor btc" in cmd: return b'123'
            if "historical_bulk_harvester.py --asset btc" in cmd: return b'456'
            if "rust_executor --asset btc" in cmd: return b'789'
            raise subprocess.CalledProcessError(1, cmd)
        self.mock_pgrep.side_effect = pgrep_side_effect

        # 2. Mock SHM: Return the mock snapshots
        def read_shm_side_effect(buf, struct_class):
            if struct_class == L2BookStruct: return self.l2_snapshot
            if struct_class == AccountStateStruct: return self.acc_snapshot
            return None
        self.mock_read_shm.side_effect = read_shm_side_effect

        # 3. Mock Log Files for p_theo and trade stats
        def pgrep_side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "unified_ingestor btc" in cmd: return b'123'
            if "historical_bulk_harvester.py --asset btc" in cmd: return b'456'
            if "rust_executor --asset btc" in cmd: return b'789'
            if "grep" in cmd:
                 if "+EV" in cmd: return b'[+EV Trigger]\n[+EV Trigger]\n[+EV IGNORED]'
                 if "Order" in cmd: return b'Order 123 submitted successfully\nOrder 456 failed'
                 if "P_theo_up" in cmd: return b'[SIGNAL] BTC | Mid: 80621.00 | P_theo_up: 0.5678 | P_theo_down: 0.4322'
            # Default for pgrep if no match
            if args[0] == 'pgrep':
                raise subprocess.CalledProcessError(1, args)
            return b''
        self.mock_pgrep.side_effect = pgrep_side_effect

        # --- EXECUTION ---
        generate_live_slack_report.generate_and_send_report("btc", {"SLACK_WEBHOOK_URL_PERFS": "http://fake.url"})

        # --- ASSERTIONS ---
        self.mock_requests.assert_called_once()
        kwargs = self.mock_requests.call_args.kwargs
        blocks = kwargs['json']['blocks']
        report_text = json.dumps(blocks, ensure_ascii=False)

        # Check overall status
        self.assertIn("🟢 Healthy", report_text)
        
        # Check Pipeline Status
        self.assertIn("🟢 Running", report_text)
        
        # Check Venue Heartbeat
        self.assertIn("🟢 Live", report_text)
        self.assertNotIn("Stale", report_text)

        # Check Signal Flow
        self.assertIn("-123.45", report_text) # OFI
        self.assertIn("543.21", report_text)  # Flow
        self.assertIn("0.5678", report_text)  # P(Up)
        self.assertIn("0.4322", report_text)  # P(Down)

        # Check Trade Stats
        self.assertIn("2* Triggered", report_text)
        self.assertIn("1* Ignored", report_text)
        self.assertIn("1* Succeeded", report_text)
        self.assertIn("1* Failed", report_text)
        
        # Check Portfolio
        self.assertIn("1019.72", report_text)
        self.assertIn("50.00", report_text)
        self.assertIn("10.00", report_text)

    def test_stalled_venue_heartbeat(self):
        """
        Verify report shows a stall when SHM data is old.
        """
        self.l2_snapshot.hl_timestamp = int(time.time() * 1000) - 120000 # 2 minutes ago
        self.mock_read_shm.return_value = self.l2_snapshot
        self.mock_pgrep.return_value = b'123' # Mock all other checks as passing

        generate_live_slack_report.generate_and_send_report("btc", {"SLACK_WEBHOOK_URL_PERFS": "http://fake.url"})
        
        report_text = json.dumps(self.mock_requests.call_args.kwargs['json']['blocks'], ensure_ascii=False)
        self.assertIn("🔴 Stalled", report_text)
        self.assertIn("❌ Stale", report_text)

    def test_stopped_process(self):
        """
        Verify report shows a stall when a core process is not running.
        """
        # Mock pgrep to fail for the executor
        def pgrep_side_effect(args, **kwargs):
            if "rust_executor" in " ".join(args): raise subprocess.CalledProcessError(1, args)
            return b'123'
        self.mock_pgrep.side_effect = pgrep_side_effect
        self.mock_read_shm.return_value = self.l2_snapshot

        generate_live_slack_report.generate_and_send_report("btc", {"SLACK_WEBHOOK_URL_PERFS": "http://fake.url"})

        report_text = json.dumps(self.mock_requests.call_args.kwargs['json']['blocks'], ensure_ascii=False)
        self.assertIn("🔴 Stalled", report_text)
        self.assertIn("❌ Stopped", report_text)

if __name__ == "__main__":
    unittest.main()
