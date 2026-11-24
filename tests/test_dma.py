"""Exercise DMA registers, USART requests, SRAM and the shared NVIC model."""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from simulator import Simulator, UART, SRAM, SRAM_SIZE


DMA0, DMA1 = 0x40026000, 0x40026400
AHB_ENABLE, AHB_RESET = 0x40023830, 0x40023810
CH2 = DMA1 + 0x40
TC, HT, TE = 1 << 21, 1 << 20, 1 << 19
IRQ58 = 1 << 58


class DmaTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulator(ROOT)
        self.sim.close()
        self.sim.command({'action': 'demo'})

    def configure(self, base=CH2, uart='USART0', request=4, count=8, destination=SRAM + 0x100,
                  extra=1 << 10, enable_clock=True):
        sim = self.sim
        address = UART[uart]
        if enable_clock:
            sim._write(AHB_ENABLE, (1 << 21) | (1 << 22))
        sim._write(address + 12, (1 << 13) | (1 << 4) | (1 << 2))
        sim._write(base + 4, count)
        sim._write(base + 8, address + 4)
        sim._write(base + 12, destination)
        sim._write(base, request << 25 | extra | 0x15)
        sim._write(address + 20, 1 << 6)

    def receive(self, payload, uart='USART0'):
        self.sim.uart_idle[uart] = False
        self.sim.rx[uart].extend(payload)
        self.sim.dma.service_rx(uart)

    def test_partial_full_stop_and_flag_clear(self):
        sim = self.sim
        self.configure()
        self.receive(b'\x00abc')
        self.assertEqual(sim.uc.mem_read(SRAM + 0x100, 4), b'\x00abc')
        self.assertEqual(sim._read(CH2 + 4), 4)
        self.assertEqual(sim._read(DMA1), HT)
        self.assertFalse(sim._pending_irqs() & IRQ58)  # HT flag exists with HTIE masked.
        uart = UART['USART0']
        self.assertEqual(sim._read(uart) & 0x30, 0x10)
        sim._read(uart + 4)
        self.assertFalse(sim._read(uart) & 0x10)
        sim._write(CH2 + 4, 100)  # Counter and address are read-only while enabled.
        self.assertEqual(sim._read(CH2 + 4), 4)
        self.receive(b'\xFFdef')
        self.assertEqual(sim.uc.mem_read(SRAM + 0x100, 8), b'\x00abc\xFFdef')
        self.assertEqual(sim._read(CH2 + 4), 0)
        self.assertEqual(sim._read(CH2) & 1, 0)
        self.assertEqual(sim._read(DMA1), HT | TC)
        self.assertTrue(sim._pending_irqs() & IRQ58)
        sim._write(DMA1 + 8, TC)
        self.assertEqual(sim._read(DMA1), HT)
        self.assertFalse(sim._pending_irqs() & IRQ58)

    def test_all_uart_receive_routes_and_high_bank_flags(self):
        routes = (
            (DMA1, 2, 4, 'USART0', 58), (DMA1, 5, 4, 'USART0', 68),
            (DMA0, 5, 4, 'USART1', 16), (DMA0, 1, 4, 'USART2', 12),
            (DMA0, 2, 4, 'UART3', 13), (DMA0, 0, 4, 'UART4', 11),
            (DMA1, 1, 5, 'USART5', 57), (DMA1, 2, 5, 'USART5', 58),
            (DMA0, 3, 5, 'UART6', 14), (DMA0, 6, 5, 'UART7', 17),
        )
        for controller, index, request, uart, irq in routes:
            with self.subTest(uart=uart, stream=index):
                self.sim.reset()
                base = controller + 0x10 + index * 0x18
                self.configure(base, uart, request, count=3)
                self.receive(b'\xC0\x00\xFF', uart)
                self.assertEqual(self.sim.uc.mem_read(SRAM + 0x100, 3), b'\xC0\x00\xFF')
                shift = (0, 6, 16, 22)[index % 4]
                bank = controller + (4 if index >= 4 else 0)
                self.assertEqual(self.sim._read(bank), 0x30 << shift)
                self.assertTrue(self.sim._pending_irqs() & (1 << irq))
                self.sim._write(bank + 8, 0x30 << shift)
                self.assertFalse(self.sim._pending_irqs() & (1 << irq))

    def test_circular_wrap_and_halfword_memory(self):
        sim = self.sim
        self.configure(count=3, extra=(1 << 10) | (1 << 8) | (1 << 11) | (1 << 13))
        self.receive(b'abcdefg')
        self.assertEqual(sim.uc.mem_read(SRAM + 0x100, 6), b'g\x00e\x00f\x00')
        self.assertEqual(sim._read(CH2 + 4), 2)
        self.assertTrue(sim._read(CH2) & 1)
        self.assertEqual(sim._read(DMA1), TC | HT)

    def test_deferred_request_clock_gating_abort_and_reset(self):
        sim = self.sim
        sim._write(AHB_ENABLE, 1 << 22)
        self.configure(enable_clock=False)
        sim._write(AHB_ENABLE, 0)
        self.receive(b'XYZ')
        self.assertEqual(sim._read(CH2 + 4), 0)
        self.assertEqual(sim.uc.mem_read(SRAM + 0x100, 3), bytes(3))
        sim._write(AHB_ENABLE, 1 << 22)
        self.assertEqual(sim._read(CH2 + 4), 5)
        self.assertEqual(sim.uc.mem_read(SRAM + 0x100, 3), b'XYZ')
        sim._write(CH2, sim._read(CH2) & ~1)
        self.assertEqual(sim._read(CH2 + 4), 5)
        self.assertEqual(sim._read(DMA1), TC)
        config = sim._read(CH2)
        sim._write(CH2, config | 1)
        self.assertEqual(sim._read(CH2) & 1, 0)
        sim._write(DMA1 + 8, TC)
        sim._write(CH2, config | 1)
        self.assertEqual(sim._read(CH2) & 1, 1)
        self.assertEqual(sim._read(CH2 + 4), 8)
        sim._write(AHB_RESET, 1 << 22)
        self.assertFalse(sim._pending_irqs() & IRQ58)
        sim._write(AHB_RESET, 0)
        self.assertEqual(sim._read(CH2), 0)
        self.assertEqual(sim._read(CH2 + 20), 0x21)

    def test_invalid_destination_sets_transfer_error_without_consuming_rx(self):
        sim = self.sim
        self.configure(destination=SRAM + SRAM_SIZE - 1)
        self.receive(b'ab')
        self.assertEqual(sim._read(DMA1), TE)
        self.assertTrue(sim._pending_irqs() & IRQ58)
        self.assertFalse(sim._read(CH2) & 1)
        self.assertEqual(sim._read(CH2 + 4), 8)
        self.assertEqual(bytes(sim.rx['USART0']), b'ab')
        self.assertEqual(sim.uc.mem_read(SRAM + SRAM_SIZE - 1, 1), b'\x00')


if __name__ == '__main__':
    unittest.main()
