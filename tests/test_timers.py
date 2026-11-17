"""GD32F470 timer boundaries and independent Keil machine-code acceptance."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from simulator import GPIO, SRAM, Simulator

BASES = (0x40010000, 0x40000000, 0x40000400, 0x40000800,
         0x40000C00, 0x40001000, 0x40001400, 0x40010400,
         0x40014000, 0x40014400, 0x40014800, 0x40001800,
         0x40001C00, 0x40002000)
CHANNELS = (4, 4, 4, 4, 4, 0, 0, 4, 2, 1, 1, 2, 1, 1)
IRQS = (25, 28, 29, 30, 50, 54, 55, 44, 24, 25, 26, 43, 44, 45)
CLOCK_BITS = (0, 0, 1, 2, 3, 4, 5, 1, 16, 17, 18, 6, 7, 8)
PASS = 0x54494D52


class TimerTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulator(ROOT)
        self.sim.close()
        self.bank = self.sim.timers

    def tearDown(self):
        self.sim.close()

    def clock_register(self, index):
        return 0x40023844 if index in (0, 7, 8, 9, 10) else 0x40023840

    def enable(self, index):
        address = self.clock_register(index)
        self.sim._write(address, self.sim.regs.get(address, 0) | (1 << CLOCK_BITS[index]))

    def write(self, index, offset, value):
        self.bank.write(BASES[index] + offset, value)
        self.assertNotEqual(self.sim.status, 'faulted', self.sim.diagnostics)

    def read(self, index, offset):
        result = self.bank.read(BASES[index] + offset)
        self.assertNotEqual(self.sim.status, 'faulted', self.sim.diagnostics)
        return result

    def start(self, index, reload=9, prescaler=0, control=1):
        self.enable(index)
        self.write(index, 0x28, prescaler)
        self.write(index, 0x2C, reload)
        self.write(index, 0x14, 1)
        self.write(index, 0x10, 0)
        self.write(index, 0, control)

    def wire(self, source, target):
        if not any({wire['from'], wire['to']} == {source, target} for wire in self.sim.wires):
            self.sim.command({'action': 'wire_add', 'from': source, 'to': target})

    def gpio(self, pin, mode=1, af=0):
        base = GPIO[pin[:2]]
        number = int(pin[2:])
        current = self.sim.gpio_state[pin[:2]]['mode']
        self.sim._write(base, (current & ~(3 << (number * 2))) | (mode << (number * 2)))
        if mode == 2:
            address = base + (32 if number < 8 else 36)
            shift = (number % 8) * 4
            self.sim._write(address, (self.sim.regs.get(address, 0) & ~(15 << shift)) | (af << shift))

    def drive(self, pin, value, settle=1):
        number = int(pin[2:])
        self.sim._write(GPIO[pin[:2]] + 24, 1 << (number if value else number + 16))
        self.bank.sample_inputs()
        if settle:
            self.bank.advance(settle)

    def capture_input(self):
        self.sim._write(0x40023830, 9)
        self.gpio('PD8')
        self.drive('PD8', 0)
        self.gpio('PA5', 2, 1)
        self.wire('PD8', 'PA5')
        self.enable(1)
        self.write(1, 0x18, 1)
        self.write(1, 0x20, 1)
        self.start(1, reload=0xFFFFFFFF)
        self.bank.sample_inputs()

    def test_all_instances_classes_widths_and_independent_registers(self):
        state = self.bank.state()
        self.assertEqual(len(state), 14)
        for index, timer in enumerate(state):
            with self.subTest(timer=index):
                self.assertEqual(timer['index'], index)
                self.assertEqual(timer['address'], f'0x{BASES[index]:08X}')
                self.assertEqual(timer['bits'], 32 if index in (1, 4) else 16)
                self.assertEqual(len(timer['channels']), CHANNELS[index])
                self.enable(index)
                self.write(index, 0x24, 0x89ABC000 + index)
                mask = 0xFFFFFFFF if index in (1, 4) else 0xFFFF
                self.assertEqual(self.read(index, 0x24), (0x89ABC000 + index) & mask)
        self.assertFalse(self.bank.contains(0x40002400))

    def test_clock_gating_and_reset_on_every_timer(self):
        for index in range(14):
            with self.subTest(timer=index):
                self.write(index, 0, 1)
                self.assertEqual(self.read(index, 0), 0)
                self.start(index, reload=99)
                self.bank.advance(7)
                self.assertEqual(self.read(index, 0x24), 7)
                enable = self.clock_register(index)
                self.sim._write(enable, self.sim.regs[enable] & ~(1 << CLOCK_BITS[index]))
                self.bank.advance(100)
                self.enable(index)
                self.assertEqual(self.read(index, 0x24), 7)
                reset = enable - 32
                self.sim._write(reset, 1 << CLOCK_BITS[index])
                self.write(index, 0, 1)
                self.sim._write(reset, 0)
                self.assertEqual(self.read(index, 0), 0)
                self.assertEqual(self.read(index, 0x24), 0)

    def test_prescaler_shadow_applies_at_update(self):
        self.enable(2)
        self.write(2, 0x2C, 99)
        self.write(2, 0x28, 3)
        self.write(2, 0, 1)
        self.bank.advance(8)
        self.assertEqual(self.read(2, 0x24), 8)
        self.write(2, 0x14, 1)
        self.bank.advance(11)
        self.assertEqual(self.read(2, 0x24), 2)
        self.bank.advance(1)
        self.assertEqual(self.read(2, 0x24), 3)
        self.write(2, 0x28, 1)
        self.bank.advance(8)
        self.assertEqual(self.read(2, 0x24), 5)
        self.write(2, 0x14, 1)
        self.bank.advance(4)
        self.assertEqual(self.read(2, 0x24), 2)

    def test_reload_and_compare_preloads_transfer_at_overflow(self):
        self.enable(3)
        self.write(3, 0, 128)
        self.write(3, 0x18, (6 << 4) | 8)
        self.write(3, 0x2C, 9)
        self.write(3, 0x34, 2)
        self.write(3, 0x14, 1)
        self.write(3, 0, 129)
        self.write(3, 0x2C, 4)
        self.write(3, 0x34, 3)
        self.bank.advance(9)
        self.assertEqual(self.read(3, 0x24), 9)
        self.assertEqual(self.bank.timers[3].car_active, 9)
        self.assertEqual(self.bank.timers[3].compare_active[0], 2)
        self.bank.advance(1)
        self.assertEqual(self.read(3, 0x24), 0)
        self.assertEqual(self.bank.timers[3].car_active, 4)
        self.assertEqual(self.bank.timers[3].compare_active[0], 3)

    def test_down_and_center_aligned_counter_sequences(self):
        self.start(2, reload=4, control=17)
        self.write(2, 0x24, 4)
        self.bank.advance(4)
        self.assertEqual(self.read(2, 0x24), 0)
        self.bank.advance(1)
        self.assertEqual(self.read(2, 0x24), 4)
        self.write(2, 0, 0)
        self.start(2, reload=3, control=33)
        sequence = []
        for _ in range(7):
            self.bank.advance(1)
            sequence.append(self.read(2, 0x24))
        self.assertEqual(sequence, [1, 2, 3, 2, 1, 0, 1])

    def test_single_pulse_classes_and_level2_reserved_bit(self):
        for index in range(14):
            with self.subTest(timer=index):
                self.start(index, reload=4, control=9)
                self.bank.advance(5)
                if index in (9, 10, 12, 13):
                    self.assertTrue(self.read(index, 0) & 1)
                    self.assertFalse(self.read(index, 0) & 8)
                    self.write(index, 0, 0)
                else:
                    self.assertFalse(self.read(index, 0) & 1)
                self.assertTrue(self.read(index, 0x10) & 1)

    def test_update_source_disable_and_rc_w0_flags(self):
        self.start(2)
        self.write(2, 0x10, 0)
        self.write(2, 0, 5)
        self.write(2, 0x14, 1)
        self.assertFalse(self.read(2, 0x10) & 1)
        self.bank.advance(10)
        self.assertTrue(self.read(2, 0x10) & 1)
        self.write(2, 0x10, 0)
        self.write(2, 0, 3)
        self.bank.advance(10)
        self.assertFalse(self.read(2, 0x10) & 1)
        self.write(2, 0x24, 5)
        self.write(2, 0x14, 1)
        self.assertEqual(self.read(2, 0x24), 0)
        self.assertFalse(self.read(2, 0x10) & 1)
        self.write(2, 0, 1)
        self.write(2, 0x14, 3)
        self.assertEqual(self.read(2, 0x10) & 3, 3)
        self.write(2, 0x10, 0xFFFFFFFE)
        self.assertEqual(self.read(2, 0x10) & 3, 2)
        self.write(2, 0x10, 0)
        self.write(2, 0x10, 0xFFFFFFFF)
        self.assertEqual(self.read(2, 0x10), 0)

    def test_shared_and_split_interrupt_vectors_keep_other_sources(self):
        for index in (0, 8, 9):
            self.enable(index)
            self.write(index, 0x0C, 1)
            self.write(index, 0x14, 1)
        self.assertEqual(self.bank.pending_irqs(), (1 << 24) | (1 << 25))
        self.write(0, 0x10, 0)
        self.assertTrue(self.bank.pending_irqs() & (1 << 25))
        self.write(9, 0x10, 0)
        self.assertFalse(self.bank.pending_irqs() & (1 << 25))
        self.write(0, 0x0C, 0xE2)
        self.write(0, 0x14, 0xE2)
        self.assertEqual(self.bank.pending_irqs(), (1 << 24) | (1 << 26) | (1 << 27))

    def test_external_gpio_capture_overcapture_and_read_clear(self):
        self.capture_input()
        self.bank.advance(123)
        self.drive('PD8', 1)
        self.assertTrue(self.read(1, 0x10) & 2)
        self.drive('PD8', 0)
        self.bank.advance(37)
        self.drive('PD8', 1)
        self.assertTrue(self.read(1, 0x10) & (1 << 9))
        self.assertEqual(self.read(1, 0x34), 162)
        self.assertFalse(self.read(1, 0x10) & 2)
        self.assertTrue(self.read(1, 0x10) & (1 << 9))

    def test_capture_filter_rejects_short_pulse_and_input_prescaler(self):
        self.capture_input()
        self.write(1, 0x18, 1 | (1 << 4))
        self.drive('PD8', 1, settle=0)
        self.bank.advance(1)
        self.drive('PD8', 0, settle=0)
        self.bank.advance(4)
        self.assertFalse(self.read(1, 0x10) & 2)
        self.drive('PD8', 1)
        self.bank.advance(4)
        self.assertTrue(self.read(1, 0x10) & 2)
        self.read(1, 0x34)
        self.write(1, 0x20, 0)
        self.write(1, 0x18, 1 | (1 << 2))
        self.write(1, 0x20, 1)
        self.drive('PD8', 0)
        self.drive('PD8', 1)
        self.assertFalse(self.read(1, 0x10) & 2)
        self.drive('PD8', 0)
        self.drive('PD8', 1)
        self.assertTrue(self.read(1, 0x10) & 2)

    def test_external_clock_does_not_use_internal_ticks(self):
        self.capture_input()
        self.write(1, 8, (5 << 4) | 7)
        self.bank.advance(1000)
        self.assertEqual(self.read(1, 0x24), 0)
        for _ in range(3):
            self.drive('PD8', 1)
            self.drive('PD8', 0)
        self.assertEqual(self.read(1, 0x24), 3)

    def test_quadrature_decoder_counts_forward_and_reverse_gpio_edges(self):
        self.sim._write(0x40023830, 9)
        for source, target in (('PD8', 'PA6'), ('PD9', 'PA7')):
            self.gpio(source)
            self.drive(source, 0)
            self.gpio(target, 2, 2)
            self.wire(source, target)
        self.enable(2)
        self.write(2, 0x18, 0x101)
        self.write(2, 0x20, 0x11)
        self.write(2, 8, 3)
        self.start(2, reload=0xFFFF)
        self.bank.sample_inputs()
        for _ in range(4):
            for pin, level in (('PD8', 1), ('PD9', 1), ('PD8', 0), ('PD9', 0)):
                self.drive(pin, level)
        self.assertEqual(self.read(2, 0x24), 16)
        self.bank.advance(1000)
        self.assertEqual(self.read(2, 0x24), 16)
        for _ in range(4):
            for pin, level in (('PD9', 1), ('PD8', 1), ('PD9', 0), ('PD8', 0)):
                self.drive(pin, level)
        self.assertEqual(self.read(2, 0x24), 0)
        self.assertTrue(self.read(2, 0) & 16)

    def test_master_update_counts_slave_external_clock(self):
        self.enable(1)
        self.enable(2)
        self.write(2, 8, (1 << 4) | 7)
        self.start(2, reload=0xFFFF)
        self.write(1, 4, 2 << 4)
        self.start(1, reload=3)
        self.bank.advance(12)
        self.assertEqual(self.read(1, 0x24), 0)
        self.assertEqual(self.read(2, 0x24), 4)  # UG plus three real overflows.

    def test_complementary_pwm_deadtime_break_and_lock(self):
        self.sim._write(0x40023830, 1)
        self.gpio('PA8', 2, 1)
        self.gpio('PA7', 2, 1)
        self.enable(0)
        self.write(0, 0x18, 6 << 4)
        self.write(0, 0x20, 5)
        self.write(0, 0x34, 5)
        self.write(0, 0x44, (1 << 15) | 2)
        self.start(0, reload=9)
        observed = []
        for _ in range(40):
            self.bank.advance(1)
            pair = (self.bank.pin_output('PA8'), self.bank.pin_output('PA7'))
            self.assertNotEqual(pair, (1, 1))
            observed.append(pair)
        self.assertIn((1, 0), observed)
        self.assertIn((0, 1), observed)
        self.assertIn((0, 0), observed)
        self.write(0, 0x0C, 1 << 7)
        self.write(0, 0x14, 1 << 7)
        self.assertFalse(self.read(0, 0x44) & (1 << 15))
        self.assertTrue(self.read(0, 0x10) & (1 << 7))
        self.assertTrue(self.bank.pending_irqs() & (1 << 24))
        self.sim._write(0x40023824, 1)
        self.sim._write(0x40023824, 0)
        self.write(0, 0x44, (1 << 8) | 2)
        self.write(0, 0x44, 0)
        self.assertEqual(self.read(0, 0x44) & 0x3FF, (1 << 8) | 2)

    def test_repetition_counter_delays_update_interrupt(self):
        self.enable(0)
        self.write(0, 0x30, 2)
        self.start(0, reload=3)
        self.bank.advance(8)
        self.assertFalse(self.read(0, 0x10) & 1)
        self.bank.advance(4)
        self.assertTrue(self.read(0, 0x10) & 1)

    def test_large_advance_matches_many_small_ones(self):
        self.start(3, reload=37, prescaler=4, control=33)
        self.write(3, 0x18, 6 << 4)
        self.write(3, 0x34, 11)
        self.bank.advance(10000)
        expected = [self.read(3, offset) for offset in (0, 0x10, 0x24, 0x28, 0x2C, 0x34)]
        self.sim._write(0x40023820, 1 << 2)
        self.sim._write(0x40023820, 0)
        self.start(3, reload=37, prescaler=4, control=33)
        self.write(3, 0x18, 6 << 4)
        self.write(3, 0x34, 11)
        for _ in range(10000):
            self.bank.advance(1)
        self.assertEqual([self.read(3, offset) for offset in (0, 0x10, 0x24, 0x28, 0x2C, 0x34)], expected)

    def test_apb_prescalers_and_timer_clock_selection(self):
        self.sim._write(0x40023808, (5 << 10) | (6 << 13))
        self.assertEqual(self.sim.timer_clock_ratio(False), (1, 2))
        self.assertEqual(self.sim.timer_clock_ratio(True), (1, 4))
        self.start(0, reload=999)
        self.start(1, reload=999)
        self.bank.advance(8)
        self.assertEqual((self.read(0, 0x24), self.read(1, 0x24)), (2, 4))
        self.sim._write(0x4002388C, 1 << 24)
        self.assertEqual(self.sim.timer_clock_ratio(False), (1, 1))
        self.assertEqual(self.sim.timer_clock_ratio(True), (1, 2))
        self.bank.advance(8)
        self.assertEqual((self.read(0, 0x24), self.read(1, 0x24)), (6, 12))

    def test_clock_fraction_survives_apb_prescaler_change(self):
        self.sim._write(0x40023808, 7 << 10)
        self.start(5, reload=999)
        self.bank.advance(7)
        self.assertEqual(self.read(5, 0x24), 0)
        self.sim._write(0x40023808, 0)
        self.bank.advance(1)
        self.assertEqual(self.read(5, 0x24), 1)
        self.bank.advance(1)
        self.assertEqual(self.read(5, 0x24), 2)

    def test_32bit_overflow_preserves_high_counter_bits(self):
        for index in (1, 4):
            with self.subTest(timer=index):
                self.start(index, reload=0xFFFFFFFF)
                self.write(index, 0x24, 0xFFFFFFFE)
                self.bank.advance(1)
                self.assertEqual(self.read(index, 0x24), 0xFFFFFFFF)
                self.assertFalse(self.read(index, 0x10) & 1)
                self.bank.advance(1)
                self.assertEqual(self.read(index, 0x24), 0)
                self.assertTrue(self.read(index, 0x10) & 1)
                self.write(index, 0, 0)

    def test_all_output_compare_and_pwm_modes_drive_real_af_pin(self):
        self.sim._write(0x40023830, 1 << 3)
        self.gpio('PD12', 2, 2)
        for mode in range(8):
            with self.subTest(mode=mode):
                self.sim._write(0x40023820, 1 << 2)
                self.sim._write(0x40023820, 0)
                self.enable(3)
                if mode == 2:
                    self.write(3, 0x18, 5 << 4)
                self.write(3, 0x18, mode << 4)
                self.write(3, 0x34, 3)
                self.write(3, 0x20, 1)
                self.start(3, reload=9)
                initial = self.bank.pin_output('PD12')
                self.bank.advance(3)
                matched = self.bank.pin_output('PD12')
                self.assertTrue(self.read(3, 0x10) & 2)
                expected = {0: (0, 0), 1: (0, 1), 2: (1, 0), 3: (0, 1),
                            4: (0, 0), 5: (1, 1), 6: (1, 0), 7: (0, 1)}
                self.assertEqual((initial, matched), expected[mode])
                self.bank.advance(10)
                if mode == 3:
                    self.assertEqual(self.bank.pin_output('PD12'), 0)

    def test_external_break_pin_clears_primary_output_enable(self):
        self.sim._write(0x40023830, 9)
        self.gpio('PD8')
        self.drive('PD8', 0)
        self.gpio('PA6', 2, 1)
        self.wire('PD8', 'PA6')
        self.enable(0)
        self.write(0, 0x44, (1 << 15) | (1 << 13) | (1 << 12))
        self.bank.sample_inputs()
        self.assertTrue(self.read(0, 0x44) & (1 << 15))
        self.drive('PD8', 1)
        self.assertFalse(self.read(0, 0x44) & (1 << 15))
        self.assertTrue(self.read(0, 0x10) & (1 << 7))

    def test_advanced_commutation_transfers_mode_and_enable_shadow(self):
        self.sim._write(0x40023830, 1)
        self.gpio('PA8', 2, 1)
        self.enable(0)
        self.write(0, 0x44, 1 << 15)
        self.write(0, 0x18, 4 << 4)
        self.write(0, 0x20, 1)
        self.write(0, 4, 1)
        self.write(0, 0x18, 5 << 4)
        self.assertEqual(self.bank.pin_output('PA8'), 0)
        self.write(0, 0x14, 1 << 5)
        self.assertEqual(self.bank.pin_output('PA8'), 1)
        self.write(0, 0x20, 0)
        self.assertEqual(self.bank.pin_output('PA8'), 1)
        self.write(0, 0x14, 1 << 5)
        self.assertIsNone(self.bank.pin_output('PA8'))

    def test_software_input_capture_bypasses_channel_enable_and_prescaler(self):
        self.enable(1)
        self.write(1, 0x18, 1 | (3 << 2))
        self.write(1, 0x24, 0x1234)
        self.write(1, 0x14, 2)
        self.assertTrue(self.read(1, 0x10) & 2)
        self.assertEqual(self.read(1, 0x34), 0x1234)
        self.assertFalse(self.read(1, 0x10) & 2)
        self.write(1, 0x24, 0x5678)
        self.write(1, 0x14, 2)
        self.assertEqual(self.read(1, 0x34), 0x5678)

    def test_debug_freeze_only_holds_selected_timers_when_core_halted(self):
        self.start(1, reload=999)
        self.start(2, reload=999)
        self.sim._write(0xE0042008, 1)
        self.bank.advance(7)
        self.assertEqual((self.read(1, 0x24), self.read(2, 0x24)), (7, 7))
        self.sim.core_halted = True
        self.bank.advance(11)
        self.assertEqual((self.read(1, 0x24), self.read(2, 0x24)), (7, 18))
        self.sim.core_halted = False
        self.bank.advance(3)
        self.assertEqual((self.read(1, 0x24), self.read(2, 0x24)), (10, 21))

    def test_unimplemented_usb_eth_trigger_remaps_produce_diagnostic(self):
        self.enable(1)
        self.bank.write(BASES[1] + 0x50, 1 << 10)
        self.assertEqual(self.sim.status, 'faulted')
        self.assertTrue(self.sim.diagnostics)

    def test_pwm1_and_polarity_report_correct_configured_duty(self):
        self.enable(3)
        self.write(3, 0x18, 7 << 4)
        self.write(3, 0x34, 3)
        self.write(3, 0x20, 1)
        self.start(3, reload=9)
        self.assertAlmostEqual(self.bank.state()[3]['channels'][0]['duty'], .7)
        self.write(3, 0x20, 3)
        self.assertAlmostEqual(self.bank.state()[3]['channels'][0]['duty'], .3)

    def test_advanced_complementary_only_output_follows_reference(self):
        self.sim._write(0x40023830, 1)
        self.gpio('PA8', 2, 1)
        self.gpio('PA7', 2, 1)
        self.enable(0)
        self.write(0, 0x18, 6 << 4)
        self.write(0, 0x20, 4)
        self.write(0, 0x34, 5)
        self.write(0, 0x44, 1 << 15)
        self.start(0, reload=9)
        self.assertEqual(self.bank.pin_output('PA7'), 1)
        self.assertIsNone(self.bank.pin_output('PA8'))
        self.bank.advance(5)
        self.assertEqual(self.bank.pin_output('PA7'), 0)

    def test_cycle_and_update_frequency_handle_center_repetition_and_external_clock(self):
        self.start(0, reload=4, control=33)
        state = self.bank.state()[0]
        self.assertEqual(state['cycleHz'], 2000000)
        self.assertEqual(state['updateHz'], 4000000)
        self.write(0, 0x30, 3)
        self.assertEqual(self.bank.state()[0]['updateHz'], 1000000)
        self.write(0, 0, 35)
        self.assertEqual(self.bank.state()[0]['updateHz'], 0)
        self.write(0, 0, 32)
        self.assertEqual(self.bank.state()[0]['updateHz'], 0)
        self.write(0, 8, (5 << 4) | 7)
        self.write(0, 0, 33)
        self.assertIsNone(self.bank.state()[0]['cycleHz'])
        self.assertIsNone(self.bank.state()[0]['updateHz'])

    def test_single_pulse_stops_at_software_update(self):
        self.start(2, reload=99, control=9)
        self.bank.advance(7)
        self.assertTrue(self.read(2, 0) & 1)
        self.write(2, 0x14, 1)
        self.assertFalse(self.read(2, 0) & 1)

    def fixture(self, mode=0, board='cimc-v1', extension='hex'):
        self.sim.select_board(board)
        self.bank = self.sim.timers
        self.sim.load((ROOT / f'firmware/timer_probe.{extension}').read_bytes(), f'timer_probe.{extension}')
        self.sim.uc.mem_write(SRAM + 124, struct.pack('<I', mode))
        if mode == 1:
            self.wire('PD12', 'PA5')
        elif mode == 2:
            self.wire('PD8', 'PA6')
            self.wire('PD9', 'PA7')
        else:
            for index in range(6):
                self.wire(f'PD{8 + index}', f'LED{index + 1}')
        for _ in range(100):
            self.sim.run_chunk(10000)
            self.assertNotEqual(self.sim.status, 'faulted', self.sim.diagnostics)
            result = struct.unpack('<32I', self.sim.uc.mem_read(SRAM, 128))
            if result[0]:
                self.assertEqual(result[0], PASS, result)
                return result
        self.fail('Actual timer firmware did not complete its requested mode')

    def test_real_all14_interrupt_vectors_and_32bit_counters(self):
        for board in ('cimc-v1', 'cimc-v2'):
            for extension in ('hex', 'bin'):
                with self.subTest(board=board, format=extension):
                    result = self.fixture(board=board, extension=extension)
                    self.assertEqual(result[1:15], (1,) * 14)
                    expected_mask = sum(1 << irq for irq in set(IRQS))
                    actual_mask = result[16] | (result[17] << 32) | (result[18] << 64)
                    self.assertEqual(actual_mask, expected_mask)
                    self.assertEqual(result[21:23], (0x89ABCDEF, 0xFEDCBA98))
                    self.assertEqual(self.sim.state()['leds'], [True, False, True, False, True, True])

    def test_real_pwm_loopback_capture_interrupt(self):
        for board in ('cimc-v1', 'cimc-v2'):
            with self.subTest(board=board):
                result = self.fixture(1, board)
                self.assertGreaterEqual(result[24], 3)
                self.assertEqual(result[27], 60000)
                self.assertEqual(result[28], 0)

    def test_real_cpu_driven_encoder_edges(self):
        for board in ('cimc-v1', 'cimc-v2'):
            with self.subTest(board=board):
                self.assertEqual(self.fixture(2, board)[26], 16)

    def test_real_timer_master_slave_trigger(self):
        for board in ('cimc-v1', 'cimc-v2'):
            with self.subTest(board=board):
                self.assertGreater(self.fixture(3, board)[26], 0)

    def test_real_nested_timer_priorities_and_basepri_mask(self):
        for board in ('cimc-v1', 'cimc-v2'):
            with self.subTest(board=board):
                result = self.fixture(4, board)
                self.assertEqual(result[28], 1)
                self.assertEqual(result[29], 0x123)
                self.assertEqual(result[30], 1)

    def test_real_advanced_timer_four_interrupt_vectors(self):
        for board in ('cimc-v1', 'cimc-v2'):
            with self.subTest(board=board):
                result = self.fixture(5, board)
                self.assertEqual(result[1:6], (1, 1, 1, 1, 1))
                self.assertEqual(result[16] & (15 << 24), 15 << 24)


if __name__ == '__main__':
    unittest.main()
