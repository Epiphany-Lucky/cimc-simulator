"""Real SPI register traffic and Keil HEX/BIN execution, including failure paths."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from simulator import Simulator
from spiflash import SpiFlashDevice, SPI1, GPIOB, RCU_AHB1EN, RCU_APB1EN, CAPACITY


class FlashTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulator(ROOT)
        self.sim.closed = True
        self.flash = self.sim.flash
        self.configure()

    def tearDown(self):
        self.sim.closed = True

    def configure(self):
        self.sim._write(RCU_AHB1EN,2)
        self.sim._write(RCU_APB1EN,1<<14)
        self.sim._write(GPIOB+24,1<<12)
        self.sim._write(GPIOB,(1<<24)|(2<<26)|(2<<28)|(2<<30))
        self.sim._write(GPIOB+36,0x55500000)
        self.sim._write(SPI1+4,0)
        self.sim._write(SPI1,0x344)

    def select(self, active):
        self.sim._write(GPIOB+24,1<<(28 if active else 12))

    def byte(self,value):
        self.sim._write(SPI1+12,value)
        self.assertEqual(self.sim._read(SPI1+8)&3,3)
        result = self.sim._read(SPI1+12)
        self.assertEqual(self.sim._read(SPI1+8)&1,0)
        return result

    def transaction(self,values):
        self.select(True)
        result = [self.byte(v) for v in values]
        self.select(False)
        return result

    def wait(self):
        self.sim.instructions += 10000
        self.flash.state()

    def program(self,address,data,enabled=True):
        if enabled:self.transaction([6])
        self.transaction([2,address>>16,(address>>8)&255,address&255,*data])

    def read(self,address,count,fast=False):
        prefix=[0x0B if fast else 3,address>>16,(address>>8)&255,address&255]
        if fast:prefix.append(0)
        return self.transaction(prefix+[255]*count)[len(prefix):]

    def test_jedec_ids_and_real_receive_flags(self):
        self.assertEqual(self.transaction([0x9F,0,0,0])[1:],[0xC8,0x40,0x13])
        self.assertEqual(self.transaction([0x90,0,0,0,0,0])[4:],[0xC8,0x12])
        self.assertEqual(self.transaction([0xAB,0,0,0,0])[4:], [0x12])
        self.assertEqual(self.flash.state()['capacityBytes'],CAPACITY)

    def test_write_enable_busy_and_cs_commit(self):
        self.program(0,[0],enabled=False)
        self.wait()
        self.assertEqual(self.read(0,1),[255])
        self.transaction([6])
        self.assertEqual(self.transaction([5,0])[1],2)
        self.select(True)
        for v in [2,0,0,0,0xA5]:self.byte(v)
        self.assertIsNone(self.flash.pending)
        self.select(False)
        self.assertEqual(self.transaction([5,0])[1],1)
        self.assertEqual(self.read(0,1),[255]) # READ ignored during WIP
        self.transaction([6]) # WREN ignored while busy
        self.wait()
        self.assertEqual(self.read(0,1),[0xA5])
        self.assertEqual(self.transaction([5,0])[1],0)
        self.assertEqual(self.flash.state()['writeCount'],1)

    def test_page_wrap_last_latch_and_nor_programming(self):
        self.program(254,[0xF0,0xAA,0xCC,0x55]);self.wait()
        self.assertEqual(self.read(254,4),[0xF0,0xAA,255,255])
        self.assertEqual(self.read(0,2),[0xCC,0x55])
        self.program(254,[0x0F]);self.wait()
        self.assertEqual(self.read(254,1),[0])
        self.program(0x100,[0]*256+[0xF0,0xCC]);self.wait()
        self.assertEqual(self.read(0x100,3),[0xF0,0xCC,0])

    def test_fast_read_and_end_of_array_wrap(self):
        self.program(CAPACITY-1,[0x12]);self.wait()
        self.program(0,[0x34]);self.wait()
        self.assertEqual(self.read(CAPACITY-1,2,fast=True),[0x12,0x34])

    def test_erase_sizes_alignment_and_wel(self):
        for opcode,size in ((0x20,4096),(0x52,32768),(0xD8,65536)):
            with self.subTest(opcode=opcode):
                self.flash.memory[:size*2] = b'\x00'*(size*2)
                self.transaction([opcode,0,0,123]);self.wait()
                self.assertEqual(self.flash.memory[0],0)
                self.transaction([6]);self.transaction([opcode,0,0,123])
                self.assertEqual(self.flash.state()['status'],'busy')
                self.wait()
                self.assertEqual(self.flash.memory[:size],b'\xff'*size)
                self.assertEqual(self.flash.memory[size],0)
        self.transaction([6]);self.transaction([0xC7]);self.wait()
        self.assertEqual(self.flash.memory,b'\xff'*CAPACITY)
        self.assertEqual(self.flash.erase_count,4)

    def test_mcu_reset_preserves_contents_and_pending_write(self):
        self.program(32,[0x55]);self.wait()
        self.program(33,[0xAA])
        self.sim._reset_devices()
        self.assertIs(self.sim.flash,self.flash)
        self.configure();self.wait()
        self.assertEqual(self.read(32,2),[0x55,0xAA])
        self.assertEqual(self.flash.write_count,2)

    def test_peripheral_reset_does_not_toggle_gpio_chip_select(self):
        self.select(True);self.byte(6)
        self.sim._write(0x40023820,1<<14)
        self.assertFalse(self.flash.wel)
        self.assertTrue(self.flash.selected)
        self.sim._write(0x40023820,0)
        self.assertEqual(self.sim._read(SPI1),0)
        self.select(False)
        self.assertTrue(self.flash.wel)

    def test_deep_power_down_release_and_software_reset(self):
        self.transaction([0xB9])
        self.assertEqual(self.flash.state()['status'],'deep-power-down')
        self.assertEqual(self.transaction([0x9F,0,0,0])[1:],[255]*3)
        self.transaction([0xAB]);self.transaction([6])
        self.transaction([0x66]);self.transaction([0x99])
        self.assertEqual(self.transaction([5,0])[1],0)
        self.assertEqual(self.transaction([0x9F,0,0,0])[1:],[0xC8,0x40,0x13])

    def test_cs_high_never_reaches_flash(self):
        self.assertEqual(self.byte(0x9F),255)
        self.assertIsNone(self.flash.last_command)

    def test_subword_data_access_and_malformed_erase(self):
        self.select(True)
        self.sim._write(SPI1+12,0x9F,size=1)
        self.sim._read(SPI1+12)
        self.sim._write(SPI1+12,0,size=2)
        self.assertEqual(self.sim._read(SPI1+12),0xC8)
        self.select(False)
        self.flash.memory[0]=0
        self.transaction([6]);self.transaction([0x20,0,0])
        self.wait()
        self.assertEqual(self.flash.memory[0],0)
        self.assertTrue(self.flash.wel)
        self.transaction([0x20,0,0,0,0]);self.wait()
        self.assertEqual(self.flash.memory[0],0)

    def test_overrun_requires_data_then_status_read(self):
        self.select(True)
        self.sim._write(SPI1+12,0x9F)
        self.sim._write(SPI1+12,0)
        self.assertEqual(self.sim._read(SPI1+8)&64,64)
        self.assertEqual(self.sim._read(SPI1+12),255) # unread old data retained
        self.assertEqual(self.sim._read(SPI1+8)&64,64)
        self.assertEqual(self.sim._read(SPI1+8)&64,0)
        self.select(False)

    def test_wrong_pin_clock_mode_and_unsupported_command_diagnosed(self):
        for mutation,fragment in (
            (lambda:self.sim._write(GPIOB+36,0),'AF5'),
            (lambda:self.sim._write(RCU_APB1EN,0),'时钟'),
            (lambda:self.sim._write(SPI1,0x3C4),'MSB'),
            (lambda:self.sim._write(SPI1+4,1),'DMA')):
            with self.subTest(fragment=fragment):
                self.configure();self.sim.status='paused';self.sim.diagnostics.clear()
                mutation();self.select(True);self.sim._write(SPI1+12,0x9F);self.select(False)
                self.assertEqual(self.sim.status,'faulted')
                self.assertTrue(any(fragment in d['message'] for d in self.sim.diagnostics))
        self.configure();self.sim.status='paused'
        self.transaction([0x5A])
        self.assertEqual(self.sim.status,'faulted')
        self.assertIn('0x5A',self.sim.diagnostics[-1]['message'])

    def test_keil_hex_and_bin_execute_spi_read_program_erase(self):
        for extension in ('hex','bin'):
            with self.subTest(extension=extension):
                self.sim.load((ROOT/f'firmware/spiflash_probe.{extension}').read_bytes(),f'spiflash_probe.{extension}')
                for _ in range(100):
                    self.sim.run_chunk(1000)
                    self.assertNotEqual(self.sim.status,'faulted',self.sim.diagnostics)
                    values=struct.unpack('<5I',self.sim.uc.mem_read(0x20000000,20))
                    if values[0]:break
                self.assertEqual(values[0],0x53504931)
                self.assertEqual(values[1],0xC84013)
                self.assertEqual(values[2],0x434D4943)
                self.assertEqual(values[3]&1,1)
                self.assertEqual(values[4],255)
                self.assertEqual(self.flash.memory[:10],b'CIMC FLASH')


if __name__ == '__main__':unittest.main()
