"""V2's real SPI0 Flash route and the shared-controller slave boundary."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'engine'))
from simulator import Simulator
from v2_devices import SPI0, GPIOA, RCU_AHB1EN, RCU_APB2EN, RCU_APB2RST
from spiflash import SPI1, GPIOB

class V2FlashTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulator(ROOT, 'cimc-v2')
        self.sim.close()
        self.sim.load((ROOT/'firmware/v2_spiflash_probe.bin').read_bytes(), 'v2_spiflash_probe.bin')
        self.configure()

    def tearDown(self):
        self.sim.close()

    def configure(self):
        self.sim._write(RCU_AHB1EN, 3)
        self.sim._write(RCU_APB2EN, 1 << 12)
        self.sim._write(GPIOA + 24, 1 << 15)
        self.sim._write(GPIOA, 1 << 30)
        self.sim._write(GPIOB, (2 << 6) | (2 << 8) | (2 << 10))
        self.sim._write(GPIOB + 32, 0x555000)
        self.sim._write(SPI0, 0x344)

    def select(self, active):
        self.sim._write(GPIOA + 24, 1 << (31 if active else 15))

    def byte(self, value):
        self.sim._write(SPI0 + 12, value)
        self.assertEqual(self.sim._read(SPI0 + 8) & 3, 3)
        return self.sim._read(SPI0 + 12)

    def transaction(self, values):
        self.select(True)
        received = [self.byte(value) for value in values]
        self.select(False)
        return received

    def test_single_spi0_register_bank_and_schematic_jedec_route(self):
        self.assertFalse(self.sim.flash.contains(SPI0))
        self.assertFalse(self.sim.flash.contains(SPI1))
        self.assertEqual(self.sim.v2_devices.spi[0], 0x344)
        self.assertEqual(self.sim.flash.registers[0], 0)
        self.assertEqual(self.transaction([0x9F, 0, 0, 0]), [255, 0xC8, 0x40, 0x13])
        self.assertEqual(self.sim.flash.state()['peripheral'], 'SPI0')
        self.assertEqual(self.sim.flash.state()['pins']['cs'], 'PA15')

    def test_v1_spi1_address_cannot_access_v2_flash(self):
        self.sim._write(SPI1 + 12, 0x9F)
        self.assertEqual(self.sim.status, 'faulted')
        self.assertIsNone(self.sim.flash.last_command)

    def test_wrong_gpio_af_route_does_not_clock_board_flash(self):
        self.sim._write(GPIOB, 0)
        self.sim._write(GPIOA, (1 << 30) | (2 << 10) | (2 << 12) | (2 << 14))
        self.sim._write(GPIOA + 32, 0x55500000)
        self.assertEqual(self.transaction([0x9F, 0, 0, 0]), [255] * 4)
        self.assertIsNone(self.sim.flash.last_command)
        self.configure()
        self.assertEqual(self.transaction([0x9F, 0, 0, 0])[1:], [0xC8, 0x40, 0x13])

    def test_unselected_mode_one_bus_returns_ff_without_external_device(self):
        self.sim._write(GPIOA, (1 << 30) | (2 << 10) | (2 << 12) | (2 << 14))
        self.sim._write(GPIOA + 32, 0x55500000)
        self.sim._write(SPI0, 0x37D)
        self.assertEqual([self.byte(value) for value in (0x40, 0x4B, 0, 0)], [255] * 4)
        self.assertIsNone(self.sim.flash.last_command)
        self.assertNotEqual(self.sim.status, 'faulted', self.sim.diagnostics)
        self.sim._write(SPI0, 0x344)
        self.assertEqual(self.transaction([0x9F, 0, 0, 0])[1:], [0xC8, 0x40, 0x13])

    def test_shared_spi0_overrun_reset_and_flash_chip_select(self):
        self.select(True)
        self.sim._write(SPI0 + 12, 0x9F)
        self.sim._write(SPI0 + 12, 0)
        self.assertEqual(self.sim._read(SPI0 + 8) & 64, 64)
        self.assertEqual(self.sim._read(SPI0 + 12), 255)
        self.assertEqual(self.sim._read(SPI0 + 8) & 64, 64)
        self.assertEqual(self.sim._read(SPI0 + 8) & 64, 0)
        self.select(False)
        self.select(True)
        self.byte(6)
        self.sim._write(RCU_APB2RST, 1 << 12)
        self.assertEqual(self.sim.v2_devices.spi[0], 0)
        self.assertTrue(self.sim.flash.selected)
        self.assertFalse(self.sim.flash.wel)
        self.sim._write(RCU_APB2RST, 0)
        self.select(False)
        self.assertTrue(self.sim.flash.wel)

    def test_keil_hex_and_bin_read_program_and_erase_actual_spi0(self):
        for extension in ('hex', 'bin'):
            with self.subTest(extension=extension):
                self.sim.load((ROOT/f'firmware/v2_spiflash_probe.{extension}').read_bytes(),
                              f'v2_spiflash_probe.{extension}')
                for _ in range(100):
                    self.sim.run_chunk(1000)
                    self.assertNotEqual(self.sim.status, 'faulted', self.sim.diagnostics)
                    values = struct.unpack('<5I', self.sim.uc.mem_read(0x20000000, 20))
                    if values[0]:
                        break
                self.assertEqual(values, (0x53504930, 0xC84013, 0x434D4943, 1, 255))
                self.assertEqual(self.sim.flash.memory[:10], b'CIMC FLASH')

    def test_v2_mcu_reset_retains_flash_contents_and_reconfigures_spi0(self):
        self.transaction([6])
        self.transaction([2, 0, 0, 9, 0x5A])
        self.sim.instructions += 10000
        self.assertEqual(self.sim.flash.state()['writeCount'], 1)
        self.sim.reset()
        self.configure()
        self.assertEqual(self.transaction([3, 0, 0, 9, 255])[-1], 0x5A)

if __name__ == '__main__':
    unittest.main()
