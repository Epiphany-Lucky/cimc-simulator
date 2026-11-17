"""Actual ARM sleep hints preserve CPU instruction counts and wake on IRQs."""
from pathlib import Path
import struct
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from simulator import Simulator, FLASH, SRAM
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_PC, UC_ARM_REG_PRIMASK, UC_ARM_REG_BASEPRI, UC_ARM_REG_FAULTMASK


def image(instructions):
    # Independent Thumb ISR increments SRAM word0 then performs real BX LR.
    raw = bytearray(0x130)
    struct.pack_into('<II', raw, 0, SRAM + 0x10000, FLASH + 0x101)
    for number in (15, 16, 44):
        struct.pack_into('<I', raw, number * 4, FLASH + 0x121)
    struct.pack_into('<' + 'H' * len(instructions), raw, 0x100, *instructions)
    struct.pack_into('<6HI', raw, 0x120, 0x4902, 0x6808, 0x3001, 0x6008, 0x4770, 0xBF00, SRAM)
    return bytes(raw)


class SleepTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulator(ROOT)
        self.sim.close()
        self.sim.board['clockTicksPerInstruction'] = 1  # Exercise exact HCLK sleep boundaries.
        self.load()

    def tearDown(self):
        self.sim.close()

    def load(self, instructions=(0xBF30, 0x2055, 0xE7FE)):
        self.sim.load(image(instructions), 'sleep.bin')

    def count(self):
        return struct.unpack('<I', self.sim.uc.mem_read(SRAM, 4))[0]

    def pend(self, priority=0x80):
        self.sim._write(0xE000E41C, priority)
        self.sim._write(0xE000E100, 1 << 28)
        self.sim._write(0xE000E200, 1 << 28)

    def test_no_event_wait_stops_at_following_pc_without_fake_cpu_progress(self):
        self.assertEqual(self.sim.run_chunk(100), 1)
        self.assertTrue(self.sim.cpu_sleeping)
        self.assertEqual(self.sim.uc.reg_read(UC_ARM_REG_PC), FLASH + 0x102)
        self.assertEqual(self.sim.uc.reg_read(UC_ARM_REG_R0), 0)
        before = self.sim.timing_ticks
        self.assertEqual(self.sim.run_chunk(100), 0)
        self.assertEqual(self.sim.timing_ticks, before)
        self.assertEqual(self.sim.instructions, 1)
        self.assertFalse(self.sim.diagnostics)

    def test_irq_arriving_after_wfi_wakes_and_executes_real_handler(self):
        self.sim.run_chunk(100)
        self.pend()
        self.assertEqual(self.sim.run_chunk(20), 20)
        self.assertFalse(self.sim.cpu_sleeping)
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.sim.uc.reg_read(UC_ARM_REG_R0), 0x55)
        self.assertFalse(self.sim.in_exception)

    def test_primask_wakes_without_entering_until_unmasked(self):
        self.sim.uc.reg_write(UC_ARM_REG_PRIMASK, 1)
        self.sim.run_chunk(100)
        self.pend()
        self.assertEqual(self.sim.run_chunk(20), 20)
        self.assertFalse(self.sim.cpu_sleeping)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.sim.uc.reg_read(UC_ARM_REG_R0), 0x55)
        self.sim.uc.reg_write(UC_ARM_REG_PRIMASK, 0)
        self.sim.run_chunk(20)
        self.assertEqual(self.count(), 1)

    def test_basepri_and_faultmask_prevent_wake(self):
        for mask, value in ((UC_ARM_REG_BASEPRI, 0x40), (UC_ARM_REG_FAULTMASK, 1)):
            with self.subTest(mask=mask):
                self.load()
                self.sim.uc.reg_write(mask, value)
                self.sim.run_chunk(100)
                self.pend()
                self.assertEqual(self.sim.run_chunk(20), 0)
                self.assertTrue(self.sim.cpu_sleeping)
                self.assertEqual(self.count(), 0)
                self.sim.uc.reg_write(mask, 0)
                self.sim.run_chunk(20)
                self.assertEqual(self.count(), 1)

    def test_pending_primask_irq_prevents_entering_sleep(self):
        self.sim.uc.reg_write(UC_ARM_REG_PRIMASK, 1)
        self.pend()
        self.assertEqual(self.sim.run_chunk(20), 20)
        self.assertFalse(self.sim.cpu_sleeping)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.sim.uc.reg_read(UC_ARM_REG_R0), 0x55)

    def test_systick_counts_during_wfi_with_hclk_and_hclk_div8(self):
        for control in (7, 3):
            with self.subTest(clock=control):
                self.load()
                self.sim._write(0xE000E014, 99)
                self.sim._write(0xE000E018, 0)
                self.sim._write(0xE000E010, control)
                self.assertEqual(self.sim.run_chunk(20), 20)
                self.assertEqual(self.count(), 1)
                self.assertFalse(self.sim.cpu_sleeping)
                self.assertGreater(self.sim.timing_ticks, self.sim.instructions)
                self.assertEqual(self.sim.uc.reg_read(UC_ARM_REG_R0), 0x55)

    def test_timer_update_wakes_then_flag_is_serviced_by_actual_arm_handler(self):
        self.sim._write(0x40023840, 1)
        timer = 0x40000000
        for offset, value in ((44, 99), (20, 1), (16, 0), (12, 1), (0, 1)):
            self.sim._write(timer + offset, value)
        self.sim._write(0xE000E100, 1 << 28)
        # Mask source after the real first handler to avoid repeatedly servicing it.
        self.sim.run_chunk(6)
        self.assertEqual(self.count(), 1)
        self.assertGreater(self.sim.timing_ticks, self.sim.instructions)
        self.sim._write(timer + 12, 0)
        self.sim.run_chunk(20)
        self.assertFalse(self.sim.cpu_sleeping)
        self.assertEqual(self.sim.uc.reg_read(UC_ARM_REG_R0), 0x55)

    def test_conditional_wfi_and_wide_wfi_follow_actual_execution(self):
        self.load((0x2000, 0x2801, 0xBF08, 0xBF30, 0x2055, 0xE7FE))
        self.sim.run_chunk(20)
        self.assertFalse(self.sim.cpu_sleeping)
        self.assertEqual(self.sim.uc.reg_read(UC_ARM_REG_R0), 0x55)
        self.load((0x2000, 0x2800, 0xBF08, 0xBF30, 0x2055, 0xE7FE))
        self.sim.run_chunk(20)
        self.assertTrue(self.sim.cpu_sleeping)
        self.assertEqual(self.sim.uc.reg_read(UC_ARM_REG_R0), 0)
        self.load((0xF3AF, 0x8003, 0x2055, 0xE7FE))
        self.assertEqual(self.sim.run_chunk(20), 1)
        self.assertTrue(self.sim.cpu_sleeping)
        self.assertEqual(self.sim.uc.reg_read(UC_ARM_REG_PC), FLASH + 0x104)

    def test_sleep_on_exit_returns_to_sleep_after_real_interrupt_handler(self):
        self.sim._write(0xE000ED10, 2)
        self.sim._write(0xE000E014, 99)
        self.sim._write(0xE000E018, 0)
        self.sim._write(0xE000E010, 7)
        self.assertEqual(self.sim.run_chunk(6), 6)  # WFI plus five ISR instructions.
        self.assertEqual(self.count(), 1)
        self.assertTrue(self.sim.cpu_sleeping)
        self.assertEqual(self.sim.uc.reg_read(UC_ARM_REG_R0), 0)
        self.assertEqual(self.sim.run_chunk(5), 5)
        self.assertEqual(self.count(), 2)
        self.assertTrue(self.sim.cpu_sleeping)
        self.assertFalse(self.sim.in_exception)

    def test_systick_first_load_zero_reload_and_reload_change_boundaries(self):
        self.sim._write(0xE000E014, 3)
        self.sim._write(0xE000E018, 0)
        self.sim._write(0xE000E010, 7)
        self.sim._advance_systick(1)
        self.assertEqual(self.sim.systick['value'], 3)
        self.assertFalse(self.sim.systick['flag'])
        self.assertFalse(self.sim.systick['pending'])
        self.sim._advance_systick(2)
        self.assertEqual(self.sim.systick['value'], 1)
        self.assertFalse(self.sim.systick['flag'])
        self.sim._advance_systick(1)
        self.assertEqual(self.sim.systick['value'], 0)
        self.assertTrue(self.sim.systick['flag'])
        self.assertTrue(self.sim.systick['pending'])
        self.sim._read(0xE000E010)
        self.sim.systick['pending'] = False
        self.sim._advance_systick(1)
        self.assertEqual(self.sim.systick['value'], 3)
        self.assertFalse(self.sim.systick['flag'])
        self.sim._write(0xE000E014, 0)
        self.sim._advance_systick(2)
        self.assertEqual(self.sim.systick['value'], 1)
        self.sim._advance_systick(1)
        self.assertTrue(self.sim.systick['pending'])
        self.sim._read(0xE000E010)
        self.sim.systick['pending'] = False
        self.sim._advance_systick(1000000)
        self.assertEqual(self.sim.systick['value'], 0)
        self.assertFalse(self.sim.systick['flag'])
        self.assertFalse(self.sim.systick['pending'])

    def test_systick_zero_reload_has_no_wfi_deadline_or_automatic_irq(self):
        self.sim._write(0xE000E014, 0)
        self.sim._write(0xE000E010, 7)
        self.assertEqual(self.sim.run_chunk(100), 1)
        self.assertTrue(self.sim.cpu_sleeping)
        self.assertEqual(self.sim.run_chunk(100), 0)
        self.assertFalse(self.sim.systick['pending'])

    def test_systick_many_wraps_and_external_fraction_are_partition_independent(self):
        def sample(chunks):
            self.load()
            self.sim._write(0xE000E014, 5)
            self.sim._write(0xE000E010, 3)
            for ticks in chunks:
                self.sim._advance_systick(ticks)
            return dict(self.sim.systick)
        self.assertEqual(sample([10003]), sample([17] * 588 + [7]))

    def test_wfe_and_deep_sleep_diagnose_instead_of_running_past_hint(self):
        self.load((0xBF20, 0x2055, 0xE7FE))
        self.assertEqual(self.sim.run_chunk(20), 0)
        self.assertEqual(self.sim.status, 'faulted')
        self.assertIn('WFE', self.sim.diagnostics[-1]['message'])
        self.load()
        self.sim._write(0xE000ED10, 4)
        self.assertEqual(self.sim.run_chunk(20), 0)
        self.assertIn('深度休眠', self.sim.diagnostics[-1]['message'])

    def test_unhandled_timer_events_return_bounded_partial_quantum(self):
        self.sim._write(0x40023840, 1)
        for offset, value in ((44, 1), (20, 1), (16, 0), (0, 1)):
            self.sim._write(0x40000000 + offset, value)
        started = time.monotonic()
        self.assertEqual(self.sim.run_chunk(100000000), 1)
        self.assertLess(time.monotonic() - started, 1)
        self.assertTrue(self.sim.cpu_sleeping)
        before = self.sim.instructions
        self.assertEqual(self.sim.run_chunk(100000000, max_duration=0.001), 0)
        self.assertEqual(self.sim.instructions, before)
        self.assertNotEqual(self.sim.status, 'faulted')


if __name__ == '__main__':
    unittest.main()
