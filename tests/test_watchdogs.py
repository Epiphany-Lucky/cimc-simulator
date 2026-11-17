"""Deterministic GD32 watchdog register, clock-domain and reset boundary tests."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from watchdogs import Watchdogs, WWDGT, FWDGT, RCU_APB1EN, RCU_APB1RST, RCU_RSTSCK, DBG_CTL1


class WatchdogBoard:
    def __init__(self):
        self.regs = {RCU_APB1EN: 1 << 11}
        self.frequency = 32000000
        self.apb_divider = 4
        self.core_halted = False
        self.errors = []
        self.resets = []

    def diagnose(self, message):
        self.errors.append(message)

    def request_system_reset(self, reason):
        self.resets.append(reason)

    def hclk_frequency(self):
        return self.frequency

    def apb_clock_ratio(self, apb2=False):
        return 1, self.apb_divider


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.sim = WatchdogBoard()
        self.device = Watchdogs(self.sim)

    def configure_fwdgt(self, reload, prescaler=0):
        self.device.write(FWDGT, 0x5555)
        self.device.write(FWDGT + 4, prescaler)
        self.device.write(FWDGT + 8, reload)
        self.device.write(FWDGT, 0xAAAA)
        self.device.advance(1000)  # One functional IRC32K latch edge at32MHz.

    def test_reset_registers_and_write_protection(self):
        self.assertEqual(self.device.read(FWDGT), 0)
        self.assertEqual(self.device.read(FWDGT + 4), 0)
        self.assertEqual(self.device.read(FWDGT + 8), 0xFFF)
        self.assertEqual(self.device.read(FWDGT + 12), 0)
        self.assertEqual(self.device.read(WWDGT), 0x7F)
        self.assertEqual(self.device.read(WWDGT + 4), 0x7F)
        self.device.write(FWDGT + 8, 3)
        self.device.advance(10000)
        self.assertEqual(self.device.read(FWDGT + 8), 0xFFF)
        self.device.write(FWDGT, 0x5555)
        self.device.write(FWDGT + 8, 7)
        self.device.write(FWDGT, 0)
        self.device.advance(1000)
        self.device.write(FWDGT + 8, 8)
        self.assertEqual(self.device.read(FWDGT + 8), 7)

    def test_configuration_latches_on_clock_edge_and_feed_uses_new_reload(self):
        self.device.write(FWDGT, 0x5555)
        self.device.write(FWDGT + 4, 2)
        self.device.write(FWDGT + 8, 31)
        self.assertEqual(self.device.read(FWDGT + 12), 3)
        self.device.write(FWDGT, 0xAAAA)
        self.device.advance(999)
        self.assertEqual(self.device.read(FWDGT + 12), 3)
        self.device.advance(1)
        self.assertEqual(self.device.read(FWDGT + 12), 0)
        self.assertEqual(self.device.read(FWDGT + 4), 2)
        self.assertEqual(self.device.fwdgt_counter, 31)
        self.assertEqual(self.device.fwdgt_reload_count, 1)
        self.assertFalse(self.sim.resets)

    def test_fwdgt_timeout_matches_gd32_table_for_every_prescaler(self):
        for encoded in range(8):
            for reload in (0, 1, 7, 0xFFF):
                with self.subTest(prescaler=encoded, reload=reload):
                    self.setUp()
                    self.configure_fwdgt(reload, encoded)
                    self.device.write(FWDGT, 0xCCCC)
                    divisor = 4 << min(encoded, 6)
                    hclk_ticks = (reload * divisor + 1) * 1000
                    self.assertEqual(self.device.next_event_ticks(), hclk_ticks)
                    self.device.advance(hclk_ticks - 1)
                    self.assertFalse(self.sim.resets)
                    self.device.advance(1)
                    self.assertEqual(self.sim.resets, ['fwdgt'])

    def test_enable_sticky_independent_clock_reload_spacing_and_debug_hold(self):
        self.configure_fwdgt(20)
        self.device.write(FWDGT, 0xCCCC)
        self.assertTrue(self.sim.regs[RCU_RSTSCK] & 1)
        self.sim.regs[RCU_RSTSCK] = 0
        self.device.notify_rcu_write(RCU_RSTSCK, 0)
        self.assertTrue(self.sim.regs[RCU_RSTSCK] & 1)
        self.device.write(FWDGT, 0)
        self.assertTrue(self.device.fwdgt_enabled)
        self.device.advance(6000)
        self.device.write(FWDGT, 0xAAAA)  # 7clocks since accepted reload.
        self.device.advance(1000)
        self.assertEqual(self.device.fwdgt_reload_count, 2)
        self.device.write(FWDGT, 0xAAAA)  # Too soon to cross the domain again.
        self.device.advance(1000)
        self.assertEqual(self.device.fwdgt_reload_count, 2)
        self.sim.core_halted = True
        self.sim.regs[DBG_CTL1] = 1 << 12
        count = self.device.fwdgt_counter
        self.device.advance(1000000)
        self.assertEqual(self.device.fwdgt_counter, count)
        self.assertFalse(self.sim.resets)
        self.sim.core_halted = False
        self.device.advance(self.device.next_event_ticks())
        self.assertEqual(self.sim.resets, ['fwdgt'])

    def test_wwdgt_ewi_flag_interrupt_and_reset_boundaries_for_all_prescalers(self):
        for encoded in range(4):
            with self.subTest(prescaler=encoded):
                self.setUp()
                self.device.write(WWDGT + 4, 0x7F | (encoded << 7))
                self.device.write(WWDGT, 0xC2)
                ticks = 4096 * (1 << encoded) * self.sim.apb_divider
                self.device.advance(ticks * 2 - 1)
                self.assertEqual(self.device.wwdgt_counter, 0x41)
                self.assertEqual(self.device.read(WWDGT + 8), 0)
                self.device.advance(1)
                self.assertEqual(self.device.read(WWDGT + 8), 1)
                self.assertEqual(self.device.pending_irqs(), 0)
                self.device.write(WWDGT + 4, self.device.wwdgt_config | 0x200)
                self.assertEqual(self.device.pending_irqs(), 1)
                self.device.write(WWDGT + 8, 1)
                self.assertEqual(self.device.pending_irqs(), 1)
                self.device.write(WWDGT + 8, 0)
                self.assertEqual(self.device.pending_irqs(), 0)
                self.device.advance(ticks - 1)
                self.assertFalse(self.sim.resets)
                self.device.advance(1)
                self.assertEqual(self.sim.resets, ['wwdgt'])

    def test_wwdgt_window_refresh_equal_allowed_greater_resets_and_enables_sticky(self):
        self.device.write(WWDGT + 4, 0x41 | 0x200)
        self.device.write(WWDGT, 0xC2)
        self.device.advance(4096 * 4)
        self.device.write(WWDGT, 0x42)  # CNT==WIN allowed, WDGTEN remains set.
        self.assertTrue(self.device.wwdgt_enabled)
        self.assertFalse(self.sim.resets)
        self.device.write(WWDGT + 4, 0x41)
        self.assertTrue(self.device.wwdgt_config & 0x200)
        self.device.write(WWDGT, 0xC2)  # CNT>WIN.
        self.assertEqual(self.sim.resets, ['wwdgt'])

    def test_wwdgt_clock_gate_peripheral_reset_and_counter_below_window(self):
        self.device.write(WWDGT, 0xC1)
        self.device.advance(100)
        self.sim.regs[RCU_APB1EN] = 0
        self.device.advance(1000000)
        self.assertEqual(self.device.wwdgt_counter, 0x41)
        self.assertEqual(self.device.read(WWDGT), 0)
        self.device.write(WWDGT, 0)
        self.assertFalse(self.sim.resets)
        self.sim.regs[RCU_APB1EN] = 1 << 11
        self.device.advance(4096 * 4 - 100)
        self.assertEqual(self.device.wwdgt_counter, 0x40)
        self.device.notify_rcu_write(RCU_APB1RST, 1 << 11)
        self.assertEqual(self.device.wwdgt_counter, 0x7F)
        self.assertFalse(self.device.wwdgt_enabled)
        self.assertEqual(self.device.wwdgt_config, 0x7F)
        self.device.write(WWDGT, 0xBF)
        self.assertEqual(self.sim.resets, ['wwdgt'])

    def test_clock_changes_and_chunking_produce_identical_watchdog_state(self):
        def prepare():
            board = WatchdogBoard()
            device = Watchdogs(board)
            device.write(WWDGT, 0xF0)
            device.write(FWDGT, 0x5555)
            device.write(FWDGT + 8, 2000)
            device.write(FWDGT, 0xAAAA)
            device.write(FWDGT, 0xCCCC)
            return board, device
        board_a, a = prepare()
        board_b, b = prepare()
        a.advance(12345)
        for ticks in (7, 38, 7000, 5300):
            b.advance(ticks)
        board_a.frequency = board_b.frequency = 168000000
        board_a.apb_divider = board_b.apb_divider = 2
        a.advance(25000)
        for _ in range(100):
            b.advance(250)
        self.assertEqual(a.state(), b.state())
        self.assertEqual(a.fwdgt_clock_phase, b.fwdgt_clock_phase)
        self.assertEqual(a.wwdgt_phase, b.wwdgt_phase)
        self.assertFalse(board_a.resets)
        self.assertFalse(board_b.resets)

    def test_unknown_offsets_and_unsupported_writes_are_diagnosed(self):
        for address in (WWDGT + 12, FWDGT + 16):
            with self.subTest(address=hex(address)):
                self.device.write(address, 0, size=2, byte_offset=2)
                self.assertIn(f'0x{address:08X}', self.sim.errors[-1])
        self.device.write(FWDGT, 0x55, size=1)
        self.assertIn('16位或32位', self.sim.errors[-1])
        self.device.write(FWDGT, 0x5555, size=2)
        self.assertTrue(self.device.fwdgt_unlocked)
        self.device.write(FWDGT, 0, size=2, byte_offset=2)
        self.assertTrue(self.device.fwdgt_unlocked)


if __name__ == '__main__':
    unittest.main()
