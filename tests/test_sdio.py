"""Regression tests for SDIO routing and virtual media lifetime."""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from simulator import GPIO, SDIO_PINS, Simulator
from sdio import (
    APB2_ENABLE, APB2_RESET, ARGUMENT, BASE, CLEAR, CLOCK, COMMAND, COMMAND_ENABLE,
    COMMAND_RECEIVED, COMMAND_TIMEOUT, DATA_BLOCK_END, DATA_CONTROL, DATA_LENGTH,
    DATA_TIMEOUT, FROM_CARD, POWER, RESPONSE0, SDIO_CLOCK_BIT, SDIO_FIFO_ADDRESS,
    STATUS,
)


class SdioTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulator(ROOT)
        self.addCleanup(self.sim.close)
        self.image = bytes(range(256)) * 8

    def configure(self):
        for pin, _ in SDIO_PINS:
            port, number = pin[:2], int(pin[2:])
            base = GPIO[port]
            self.sim._write(base, self.sim._read(base) | 2 << (number * 2))
            af = base + (32 if number < 8 else 36)
            self.sim._write(af, self.sim._read(af) | 12 << (number % 8 * 4))
        self.sim._write(APB2_ENABLE, SDIO_CLOCK_BIT)
        self.sim._write(BASE + POWER, 3)
        self.sim._write(BASE + CLOCK, 1 << 8)

    def send(self, command, argument=0, response=1):
        self.sim._write(BASE + CLEAR, 0x7FF)
        self.sim._write(BASE + ARGUMENT, argument)
        self.sim._write(BASE + COMMAND, COMMAND_ENABLE | response << 6 | command)
        return self.sim._read(BASE + RESPONSE0)

    def test_card_switch_and_clock_reset_on_both_boards(self):
        for board in ('cimc-v1', 'cimc-v2'):
            with self.subTest(board=board):
                self.sim.select_board(board)
                self.assertEqual(self.sim.net_level('PE2'), 1)
                self.assertEqual(self.sim.net_level('PC8'), 1)
                self.configure()
                self.send(8, 0x1AA)
                self.assertTrue(self.sim._read(BASE + STATUS) & COMMAND_TIMEOUT)
                mounted = self.sim.mount_sd(self.image, 'fixture.img', False)
                self.assertTrue(mounted['sdCard']['inserted'])
                self.assertEqual(self.sim.net_level('PE2'), 0)
                self.assertEqual(self.send(8, 0x1AA), 0x1AA)
                self.assertTrue(self.sim._read(BASE + STATUS) & COMMAND_RECEIVED)
                self.sim._write(APB2_RESET, SDIO_CLOCK_BIT)
                self.sim._write(APB2_RESET, 0)
                self.assertEqual(self.sim._read(BASE + POWER), 0)
                self.assertEqual(self.sim.export_sd(), self.image)
                self.assertFalse(self.sim.command({'action': 'sd_eject'})['sdCard']['inserted'])
                self.assertEqual(self.sim.net_level('PE2'), 1)
                with self.assertRaises(ValueError):
                    self.sim.export_sd()

    def test_invalid_replacement_keeps_mounted_image(self):
        self.sim.mount_sd(self.image, 'original.img', True)
        with self.assertRaises(ValueError):
            self.sim.mount_sd(bytes(513), 'bad.img', False)
        with self.assertRaises(ValueError):
            self.sim.mount_sd(bytes(512), 'unrepresentable.img', False)
        self.assertEqual(self.sim.export_sd(), self.image)
        self.assertTrue(self.sim.state()['sdCard']['readOnly'])

    def test_polling_fifo_completion_and_write_cancel(self):
        self.sim.mount_sd(self.image, 'fixture.img', False)
        self.configure()
        self.send(0, response=0)
        self.send(8, 0x1AA)
        self.send(55)
        self.send(41, 0x00FF8000)
        self.send(2, response=3)
        rca = self.send(3) & 0xFFFF0000
        self.send(7, rca)
        self.send(55, rca)
        self.send(6, 2)
        self.sim._write(BASE + CLOCK, 1 << 8 | 1 << 11)
        self.sim._write(BASE + DATA_TIMEOUT, 0xFFFFFFFF)
        self.sim._write(BASE + DATA_LENGTH, 512)
        self.sim._write(BASE + DATA_CONTROL, 9 << 4 | FROM_CARD | 1)
        self.send(17, 512)
        sector = bytearray()
        for _ in range(128):
            self.assertFalse(self.sim._read(BASE + STATUS) & DATA_BLOCK_END)
            sector += self.sim._read(SDIO_FIFO_ADDRESS).to_bytes(4, 'little')
        self.assertEqual(sector, self.image[512:1024])
        self.assertTrue(self.sim._read(BASE + STATUS) & DATA_BLOCK_END)
        self.assertEqual(self.sim.state()['sdCard']['sectorsRead'], 1)

        self.sim._write(BASE + DATA_CONTROL, 0)
        self.send(24, 0)
        self.sim._write(BASE + DATA_CONTROL, 9 << 4 | 1)
        self.sim._write(SDIO_FIFO_ADDRESS, 0x12345678)
        self.sim._write(APB2_RESET, SDIO_CLOCK_BIT)
        self.assertEqual(self.sim.export_sd(), self.image)
        self.assertEqual(self.sim.state()['sdCard']['sectorsWritten'], 0)


if __name__ == '__main__':
    unittest.main()
