"""Actual Cortex-M4 alias LDR/STR regressions using an independent Keil fixture."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from simulator import Simulator, SRAM


class PeripheralBitbandTests(unittest.TestCase):
    def setUp(self):
        self.simulator = Simulator(ROOT)
        self.simulator.close()

    def tearDown(self):
        self.simulator.close()

    def run_fixture(self, mode=0, board_id='cimc-v1'):
        self.simulator.select_board(board_id)
        self.simulator.load((ROOT / 'firmware/bitband_probe.hex').read_bytes(), 'bitband_probe.hex')
        self.simulator.uc.mem_write(SRAM + 60, struct.pack('<I', mode))
        self.simulator.run_chunk(1000)
        return struct.unpack('<12I', self.simulator.uc.mem_read(SRAM, 48))

    def test_real_alias_reads_writes_lsb_and_current_gpio_state_on_both_boards(self):
        for board_id in ('cimc-v1', 'cimc-v2'):
            with self.subTest(board=board_id):
                result = self.run_fixture(board_id=board_id)
                self.assertNotEqual(self.simulator.status, 'faulted', self.simulator.diagnostics)
                self.assertEqual(result[:3], (0x42424F4B, 0, 1))
                self.assertEqual(result[3], 0x03030003)  # Enabled oscillators and their ready flags.
                self.assertEqual(result[4:9], (0xA5C5, 0xA7C5, 0xA6C5, 1, 0))
                self.assertEqual(result[9:11], (0x8055A5A5, 0x0055A5A5))
                self.assertEqual(self.simulator.gpio_state['PD']['out'], 0xA6C5)

    def test_unknown_backing_register_faults_without_fake_success(self):
        for mode in (1, 2):
            with self.subTest(mode=mode):
                result = self.run_fixture(mode)
                self.assertEqual(self.simulator.status, 'faulted')
                self.assertEqual(result[0], 0)
                self.assertIn('0x400260D0', self.simulator.diagnostics[-1]['message'])
                self.assertNotIn(0x400260D0, self.simulator.regs)

    def test_model_diagnoses_unaligned_or_narrow_alias_accesses(self):
        for mode in (3, 4, 5, 6):
            with self.subTest(mode=mode):
                result = self.run_fixture(mode)
                self.assertEqual(self.simulator.status, 'faulted', self.simulator.diagnostics)
                self.assertEqual(result[0], 0)
                self.assertIn('32位', self.simulator.diagnostics[-1]['message'])
                self.assertEqual(self.simulator.regs.get(0x40023800, 0), 0)

    def test_mapping_includes_all_bytes_and_high_bits_of_a_register(self):
        for bit in range(32):
            alias_offset = (0x40023800 - 0x40000000) * 32 + bit * 4
            self.assertEqual(self.simulator._bitband_target(alias_offset, 4), (0x40023800, bit))

    def test_power_ready_bits_follow_overdrive_control_on_both_boards(self):
        control, status = 0x40007000, 0x40007004
        for board_id in ('cimc-v1', 'cimc-v2'):
            with self.subTest(board=board_id):
                self.simulator.select_board(board_id)
                self.assertEqual(self.simulator._read(status), 0)
                self.simulator._write(status, 0x100)  # Preserve the wake-up pin configuration.
                self.simulator._write(control, 0xC000)
                self.assertEqual(self.simulator._read(status), 0x100)
                self.simulator._write(control, 0x1C000)  # Enable high-drive mode.
                self.assertEqual(self.simulator._read(status), 0x10100)
                self.simulator._write(control, 0x3C000)  # Switch the regulator to high-drive mode.
                self.assertEqual(self.simulator._read(status), 0x30100)
                self.simulator._write(control, 0xC000)
                self.assertEqual(self.simulator._read(status), 0x100)


if __name__ == '__main__':
    unittest.main()
