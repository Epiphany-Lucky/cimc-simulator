"""Keil firmware exercises actual watchdog IRQ entry and post-reset boot paths."""
import base64
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from simulator import Simulator


class WatchdogRuntimeTests(unittest.TestCase):
    def prepare(self, board, extension='hex'):
        simulator = Simulator(ROOT, board)
        simulator.close()
        for index in range(3):
            simulator.command({'action': 'wire_add', 'from': f'PD{10 + index}', 'to': f'LED{index + 1}'})
        if board == 'cimc-v2':
            for source, target in (('H12.1', 'H12.3'), ('H12.2', 'H12.4')):
                simulator.command({'action': 'wire_add', 'from': source, 'to': target})
        filename = f'watchdog_probe.{extension}'
        simulator.load((ROOT / 'firmware' / filename).read_bytes(), filename)
        self.until(simulator, lambda: 'WDGT SELECT F W E' in self.output(simulator))
        return simulator

    @staticmethod
    def output(simulator):
        return ''.join(item['text'] for item in simulator.logs
                       if item['direction'] == 'tx' and item['channel'] == 'ch340')

    def until(self, simulator, predicate, budget=200000):
        for _ in range(budget // 1000):
            if predicate():
                return
            simulator.run_chunk(1000)
            self.assertNotEqual(simulator.status, 'faulted', simulator.diagnostics)
        self.assertTrue(predicate(), self.output(simulator))

    @staticmethod
    def send(simulator, command):
        simulator.command({'action': 'serial', 'channel': 'ch340',
                           'data': base64.b64encode(command.encode('ascii')).decode('ascii')})

    def test_actual_fwdgt_timeout_reboots_into_flag_branch_and_flags_clear(self):
        for board in ('cimc-v1', 'cimc-v2'):
            with self.subTest(board=board):
                simulator = self.prepare(board)
                try:
                    self.send(simulator, 'F')
                    self.until(simulator, lambda: 'FWDGT RESET' in self.output(simulator))
                    self.assertEqual(simulator.state()['leds'][:3], [True, False, False])
                    mailbox = struct.unpack('<4I', simulator.uc.mem_read(0x20001000, 16))
                    self.assertEqual(mailbox[0], 0x46574F4B)
                    self.assertEqual(mailbox[3] & 0xFE000000, 1 << 29)
                    self.assertEqual(simulator._read(0x40023874) & 0xFE000000, 1 << 29)
                    self.assertFalse(simulator.watchdogs.fwdgt_enabled)
                    self.send(simulator, 'C')
                    self.until(simulator, lambda: 'FLAGS CLEAR' in self.output(simulator))
                    self.assertEqual(simulator._read(0x40023874) & 0xFE000000, 0)
                finally:
                    simulator.close()

    def test_actual_wwdgt_timeout_reboots_into_flag_branch(self):
        for board in ('cimc-v1', 'cimc-v2'):
            with self.subTest(board=board):
                simulator = self.prepare(board, 'bin')
                try:
                    self.send(simulator, 'W')
                    self.until(simulator, lambda: 'WWDGT RESET' in self.output(simulator))
                    self.assertEqual(simulator.state()['leds'][:3], [False, True, False])
                    mailbox = struct.unpack('<4I', simulator.uc.mem_read(0x20001000, 16))
                    self.assertEqual(mailbox[0], 0x57574F4B)
                    self.assertEqual(mailbox[3] & 0xFE000000, 1 << 30)
                    self.assertFalse(simulator.watchdogs.wwdgt_enabled)
                finally:
                    simulator.close()

    def test_actual_wwdgt_early_interrupt_clears_flag_refreshes_and_returns(self):
        for board in ('cimc-v1', 'cimc-v2'):
            with self.subTest(board=board):
                simulator = self.prepare(board)
                try:
                    self.send(simulator, 'E')
                    self.until(simulator, lambda: 'W EWI' in self.output(simulator))
                    simulator.run_chunk(1000)
                    for _ in range(200):
                        if not simulator.in_exception:
                            break
                        simulator.run_chunk(1)
                    self.assertNotEqual(simulator.status, 'faulted', simulator.diagnostics)
                    mailbox = struct.unpack('<4I', simulator.uc.mem_read(0x20001000, 16))
                    self.assertEqual(mailbox[0], 0x57414954)
                    self.assertEqual(mailbox[1], ord('E'))
                    self.assertGreaterEqual(mailbox[2], 1)
                    self.assertEqual(simulator._read(0x40023874) & ((1 << 29) | (1 << 30)), 0)
                    self.assertEqual(simulator.state()['leds'][:3], [False, False, True])
                    self.assertTrue(simulator.watchdogs.wwdgt_enabled)
                    self.assertFalse(simulator.in_exception)
                    self.assertFalse(simulator.watchdogs.pending_irqs())
                finally:
                    simulator.close()


if __name__ == '__main__':
    unittest.main()
