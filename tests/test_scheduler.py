"""Instruction quantum regressions with checked-in Keil SysTick machine code.

These test functional instruction scheduling, not cycle-accurate timing.
"""
import json
from pathlib import Path
import struct
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from simulator import Simulator, FLASH, SRAM, CORE_REGS
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_PRIMASK

CTRL, LOAD, VALUE, ICSR, VTOR = 0xE000E010, 0xE000E014, 0xE000E018, 0xE000ED04, 0xE000ED08


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.s = Simulator(ROOT)
        self.s.close()  # Join the worker; manual run_chunk remains supported.
        self.raw = (ROOT / 'firmware/systick.hex').read_bytes()
        self.load()

    def tearDown(self):
        self.s.close()

    def load(self):
        self.s.load(self.raw, 'systick.hex')

    def ticks(self):
        return struct.unpack('<I', self.s.uc.mem_read(SRAM, 4))[0]

    def execute(self, count):
        before = self.s.instructions
        executed = self.s.run_chunk(count)
        self.assertEqual(executed, count)
        self.assertEqual(self.s.instructions - before, count)
        self.assertNotEqual(self.s.status, 'faulted', self.s.diagnostics)

    def initialize_timer(self):
        for _ in range(100):
            if self.s.systick['ctrl'] == 7:
                return
            self.execute(1)
        self.fail('Real SysTick fixture did not initialize the timer')

    def snapshot(self):
        return (self.s.instructions, self.ticks(),
                tuple(self.s.uc.reg_read(register) for register in CORE_REGS),
                self.s.uc.reg_read(UC_ARM_REG_SP), self.s.uc.reg_read(UC_ARM_REG_PRIMASK),
                dict(self.s.systick), self.s.in_exception, self.s.exception_return,
                bytes(self.s.uc.mem_read(0x2000FF80, 128)))

    def test_one_quantum_crosses_multiple_real_interrupts(self):
        self.assertTrue(self.s.closed)
        self.execute(10000)
        self.assertGreaterEqual(self.ticks(), 8)
        self.assertLessEqual(self.ticks(), 11)

    def test_partition_does_not_change_instructions_or_machine_state(self):
        # Include a non-round endpoint, which may legitimately be inside an ISR.
        baseline = None
        for chunks in ([10037], [1000] * 10 + [37], [1] * 10037):
            self.load()
            for count in chunks:
                self.execute(count)
            if baseline is None:
                baseline = self.snapshot()
            else:
                self.assertEqual(self.snapshot(), baseline)

    def test_continuous_pending_does_not_double_count_stopped_hook(self):
        baseline = None
        for chunks in ([128], [7] * 18 + [2], [1] * 128):
            self.load()
            self.initialize_timer()
            self.s._write(LOAD, 0)
            self.s._write(VALUE, 0)
            self.s._write(ICSR, 1 << 26)
            before = self.s.instructions
            for count in chunks:
                self.execute(count)
            self.assertEqual(self.s.instructions - before, 128)
            self.assertGreater(self.ticks(), 1)
            if baseline is None:
                baseline = self.snapshot()
            else:
                self.assertEqual(self.snapshot(), baseline)

    def test_existing_pending_enters_and_returns_within_same_quantum(self):
        self.initialize_timer()
        self.s._write(CTRL, 0)
        sp = self.s.uc.reg_read(UC_ARM_REG_SP)
        self.s._write(ICSR, 1 << 26)
        self.execute(80)
        self.assertEqual(self.ticks(), 1)
        self.assertFalse(self.s.in_exception)
        self.assertFalse(self.s.systick['pending'])
        self.assertEqual(self.s.uc.reg_read(UC_ARM_REG_SP), sp)

    def test_single_step_exception_return_restores_frame_without_extra_instruction(self):
        self.initialize_timer()
        self.s._write(CTRL, 0)
        frame = tuple(self.s.uc.reg_read(register) for register in CORE_REGS)
        sp = self.s.uc.reg_read(UC_ARM_REG_SP)
        self.s._write(ICSR, 1 << 26)
        self.execute(1)  # Host exception entry does not consume this instruction.
        self.assertTrue(self.s.in_exception)
        self.assertEqual(self.s.uc.reg_read(UC_ARM_REG_SP), sp - 32)
        # The checked-in leaf Tick_Handler ends in Thumb BX LR (0x4770).
        for _ in range(32):
            pc = self.s.uc.reg_read(UC_ARM_REG_PC)
            if bytes(self.s.uc.mem_read(pc, 2)) == b'\x70\x47':
                break
            self.execute(1)
            self.assertTrue(self.s.in_exception)
        else:
            self.fail('Real SysTick handler did not reach BX LR')
        self.execute(1)
        self.assertFalse(self.s.in_exception)
        self.assertFalse(self.s.exception_return)
        self.assertEqual(self.ticks(), 1)
        self.assertEqual(self.s.uc.reg_read(UC_ARM_REG_SP), sp)
        self.assertEqual(tuple(self.s.uc.reg_read(register) for register in CORE_REGS), frame)
        self.execute(80)
        self.assertEqual(self.ticks(), 1)

    def test_masked_pending_coalesces_then_runs_after_unmask(self):
        self.initialize_timer()
        self.s.uc.reg_write(UC_ARM_REG_PRIMASK, 1)
        self.execute(5000)
        self.assertEqual(self.ticks(), 0)
        self.assertTrue(self.s.systick['pending'])
        self.assertTrue(self.s.systick['flag'])
        self.s._write(CTRL, 0)  # Stop new ticks; keep the latched pending event.
        self.s.uc.reg_write(UC_ARM_REG_PRIMASK, 0)
        self.execute(1000)
        self.assertEqual(self.ticks(), 1)
        self.assertFalse(self.s.in_exception)
        self.assertFalse(self.s.systick['pending'])

    def test_pending_during_isr_waits_for_return_without_nested_stack(self):
        self.initialize_timer()
        self.s._write(CTRL, 0)
        sp = self.s.uc.reg_read(UC_ARM_REG_SP)
        self.s._write(ICSR, 1 << 26)
        self.execute(1)
        self.assertTrue(self.s.in_exception)
        self.s._write(ICSR, 1 << 26)
        self.s._write(ICSR, 1 << 26)  # Pending is a latch, not an event queue.
        self.execute(1)
        self.assertTrue(self.s.in_exception)
        self.assertEqual(self.s.uc.reg_read(UC_ARM_REG_SP), sp - 32)
        self.execute(80)
        self.assertEqual(self.ticks(), 2)
        self.assertFalse(self.s.in_exception)
        self.assertFalse(self.s.systick['pending'])
        self.assertEqual(self.s.uc.reg_read(UC_ARM_REG_SP), sp)

    def test_fault_aborts_budget_instead_of_fabricating_progress(self):
        self.initialize_timer()
        self.s._write(CTRL, 0)
        self.s._write(VTOR, FLASH + 0x1000)  # Erased vector location.
        self.s._write(ICSR, 1 << 26)
        before = self.s.instructions
        self.assertEqual(self.s.run_chunk(10000), 0)
        self.assertEqual(self.s.instructions, before)
        self.assertEqual(self.s.status, 'faulted')
        self.assertTrue(any('SysTick' in item['message'] for item in self.s.diagnostics))
        self.assertEqual(self.s.run_chunk(1), 0)
        self.assertEqual(self.s.instructions, before)

    def test_invalid_budget_or_duration_does_not_advance(self):
        before = self.snapshot()
        for count in (0, -1, True, False, 1.5, None):
            with self.subTest(count=count):
                with self.assertRaises((TypeError, ValueError)):
                    self.s.run_chunk(count)
                self.assertEqual(self.snapshot(), before)
        for duration in (0, -1, True, False, float('nan'), float('inf')):
            with self.subTest(duration=duration):
                with self.assertRaises((TypeError, ValueError)):
                    self.s.run_chunk(100, max_duration=duration)
                self.assertEqual(self.snapshot(), before)

    def test_time_limit_does_not_leak_into_later_manual_budget(self):
        count = self.s.run_chunk(1000000, max_duration=0.001)
        self.assertGreaterEqual(count, 0)
        self.assertLess(count, 1000000)
        self.assertIsNone(self.s._slice_deadline)
        self.execute(10000)

    def test_zero_native_progress_faults_without_retrying_forever(self):
        # A second native call raises immediately so a missing no-progress guard
        # fails the test instead of hanging the test process indefinitely.
        with patch.object(self.s.uc, 'emu_start', side_effect=[None, AssertionError('Repeated zero-progress native call')]) as native:
            self.assertEqual(self.s.run_chunk(100), 0)
            self.assertEqual(native.call_count, 1)
        self.assertEqual(self.s.instructions, 0)
        self.assertEqual(self.s.status, 'faulted')
        self.assertTrue(any('没有取得进展' in item['message'] for item in self.s.diagnostics))
        self.assertIsNone(self.s._slice_deadline)

    def test_wall_cap_and_live_worker_pause_resume_close_are_bounded(self):
        # Isolate native-loop regressions so a broken pause/close cannot hang CI.
        script = textwrap.dedent('''
            import json, sys, time
            from pathlib import Path
            root = Path(sys.argv[1])
            sys.path.insert(0, str(root / 'engine'))
            from simulator import Simulator
            raw = (root / 'firmware/systick.hex').read_bytes()
            manual = Simulator(root)
            manual.close()
            manual.load(raw, 'systick.hex')
            before = manual.instructions
            start = time.monotonic()
            count = manual.run_chunk(100000000, max_duration=0.005)
            assert 0 <= count < 100000000
            assert manual.instructions - before == count
            assert time.monotonic() - start < 2
            assert manual.status != 'faulted', manual.diagnostics
            manual._write(0xE000E010, 0)
            manual._write(0xE000ED04, 1 << 25)
            before = manual.instructions
            start = time.monotonic()
            quiet_count = manual.run_chunk(100000000, max_duration=0.005)
            assert 0 <= quiet_count < 100000000
            assert manual.instructions - before == quiet_count
            assert time.monotonic() - start < 2
            live = Simulator(root)
            live.load(raw, 'systick.hex')
            live.command({'action':'run'})
            deadline = time.monotonic() + 2
            while live.instructions < 500 and time.monotonic() < deadline:
                time.sleep(0.005)
            assert live.instructions >= 500
            with live.lock:
                live._write(0xE000E014, 0)  # Dense, continuously re-pending SysTick.
                live._write(0xE000E018, 0)
                dense_start = live.instructions
                dense_ticks = int.from_bytes(live.uc.mem_read(0x20000000, 4), 'little')
            deadline = time.monotonic() + 2
            while live.instructions < dense_start + 1000 and time.monotonic() < deadline:
                time.sleep(0.005)
            assert live.instructions >= dense_start + 1000, (dense_start, live.instructions, live.status, live.diagnostics)
            start = time.monotonic()
            live.command({'action':'pause'})
            pause_ms = (time.monotonic() - start) * 1000
            assert pause_ms < 2000
            assert live.status == 'paused'
            assert int.from_bytes(live.uc.mem_read(0x20000000, 4), 'little') > dense_ticks
            paused = live.instructions
            time.sleep(0.05)
            assert live.instructions == paused
            live.command({'action':'run'})
            deadline = time.monotonic() + 2
            while live.instructions == paused and time.monotonic() < deadline:
                time.sleep(0.005)
            assert live.instructions > paused
            assert live.status != 'faulted', live.diagnostics
            live.close()
            assert not live.worker.is_alive()
            print(json.dumps({'capInstructions':count,'quietCapInstructions':quiet_count,'pauseMs':pause_ms,'resumed':True}))
        ''')
        result = subprocess.run([sys.executable, '-c', script, str(ROOT)],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)['resumed'])


if __name__ == '__main__':
    unittest.main()
