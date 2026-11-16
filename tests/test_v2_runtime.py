"""V2 board selection, persistent internal Flash and actual user firmware IRQs."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from simulator import Simulator, FLASH, SRAM
from fmc import BASE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP


def command_frame(command, data=b''):
    packet = bytearray.fromhex('A5 B6 00 01 01')
    packet.extend(command.to_bytes(2, 'big'))
    packet.extend((len(data), 2))
    packet.extend(data)
    crc = 0xFFFF
    for value in packet:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    packet.extend(crc.to_bytes(2, 'big'))
    packet.extend(b'\xB6\xA5')
    return packet.hex().upper().encode('ascii')


class V2RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.s = Simulator(ROOT, 'cimc-v2')
        self.s.close()

    def tearDown(self):
        self.s.close()

    def until(self, predicate, budget=5000000):
        for _ in range(budget // 100000):
            if predicate():
                return
            self.s.run_chunk(100000)
            self.assertNotEqual(self.s.status, 'faulted', self.s.diagnostics)
        self.assertTrue(predicate(), 'Actual V2 firmware did not reach the expected state')

    def send(self, data):
        self.s.command({'action': 'serial', 'channel': 'rs485',
                        'data': base64.b64encode(data).decode('ascii')})

    def test_bin_digests_and_update_header(self):
        manifest = json.loads((ROOT / 'firmware/v2-manifest.json').read_text(encoding='utf-8'))
        for item in manifest['files']:
            raw = (ROOT / 'firmware' / item['file']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), item['sha256'])
            self.assertEqual(len(raw), item['size'])
        app = (ROOT / 'firmware/v2-app.bin').read_bytes()
        update = (ROOT / 'firmware/v2-app-update.bin').read_bytes()
        self.assertEqual(update[:8], bytes.fromhex('5A A5 C3 3C 00 00 00 01'))
        self.assertEqual(update[8:], app)

    def test_selection_and_cross_board_project_are_atomic(self):
        self.s.command({'action': 'v2_demo'})
        self.s.adc.set_voltage(0.75, 11)
        project = self.s.project()
        self.s.command({'action': 'board_select', 'boardId': 'cimc-v1'})
        self.assertIsNone(self.s.uc)
        self.s.load_project(project)
        self.assertEqual(self.s.board['id'], 'cimc-v2')
        self.assertEqual(self.s.adc.current_voltage, 0.75)
        before = self.s.project()
        cpu = self.s.uc
        invalid = copy.deepcopy(project)
        invalid['adc1Voltage'] = 3.31
        with self.assertRaises(ValueError):
            self.s.load_project(invalid)
        self.assertIs(self.s.uc, cpu)
        self.assertEqual(self.s.project(), before)
        invalid = copy.deepcopy(project)
        invalid['boardId'] = 'cimc-v1'
        invalid['wires'] = [{'from': 'does-not-exist', 'to': 'PA1'}]
        with self.assertRaises(ValueError):
            self.s.load_project(invalid)
        self.assertEqual(self.s.project(), before)

    def test_cpu_flash_store_alias_export_reset_and_erase(self):
        # LDR r0, target; LDR r1, value; STR r1,[r0]; B .
        raw = struct.pack('<IIHHHHII', SRAM + 0x10000, FLASH + 9,
                          0x4801, 0x4902, 0x6001, 0xE7FE,
                          FLASH + 0x10000, 0x12345678)
        self.s.load(raw, 'flash-store.bin')
        self.s._write(BASE + 4, 0x45670123)
        self.s._write(BASE + 4, 0xCDEF89AB)
        self.s._write(BASE + 16, 0x201)
        self.s.run_chunk(10)
        self.assertNotEqual(self.s.status, 'faulted', self.s.diagnostics)
        self.assertEqual(self.s.fmc.program_count, 1)
        self.assertEqual(self.s.uc.mem_read(FLASH + 0x10000, 4), bytes.fromhex('78 56 34 12'))
        self.assertEqual(self.s.uc.mem_read(0x10000, 4), bytes.fromhex('78 56 34 12'))
        saved = self.s.project()
        self.s.reset()
        self.assertEqual(self.s.uc.mem_read(FLASH + 0x10000, 4), bytes.fromhex('78 56 34 12'))
        self.s.load_project(saved)
        self.assertEqual(self.s.uc.mem_read(FLASH + 0x10000, 4), bytes.fromhex('78 56 34 12'))
        self.s._write(BASE + 4, 0x45670123)
        self.s._write(BASE + 4, 0xCDEF89AB)
        self.s._write(BASE + 36, 0xA9B8C7D6)
        self.s._write(BASE + 32, 0x88010000)
        self.s._write(BASE + 16, 0x10002)
        self.assertEqual(self.s.uc.mem_read(FLASH + 0x10000, 4096), b'\xff' * 4096)
        self.assertEqual(self.s.uc.mem_read(FLASH, len(raw)), raw)
        self.assertEqual(self.s.fmc.erase_count, 1)

    def test_locked_and_non_erased_flash_reject_cpu_store(self):
        raw = struct.pack('<IIHHHHII', SRAM + 0x10000, FLASH + 9,
                          0x4801, 0x4902, 0x6001, 0xE7FE,
                          FLASH + 0x10000, 0xFFFFFFFF)
        self.s.load(raw, 'locked-store.bin')
        self.s.run_chunk(10)
        self.assertEqual(self.s.status, 'faulted')
        self.assertTrue(self.s.fmc.status & (1 << 4))
        self.assertEqual(self.s.uc.mem_read(FLASH + 0x10000, 4), b'\xff' * 4)
        self.s.load(raw, 'invalid-bit-transition.bin')
        self.s.fmc._store(FLASH + 0x10000, b'\x00' * 4)
        self.s._write(BASE + 4, 0x45670123)
        self.s._write(BASE + 4, 0xCDEF89AB)
        self.s._write(BASE + 16, 0x201)
        self.s.run_chunk(10)
        self.assertEqual(self.s.status, 'faulted')
        self.assertTrue(self.s.fmc.status & (1 << 7))
        self.assertEqual(self.s.uc.mem_read(FLASH + 0x10000, 4), b'\x00' * 4)

    def test_mass_erased_flash_exports_restores_and_faults_on_reset(self):
        raw=struct.pack('<IIH',SRAM+0x10000,FLASH+9,0xE7FE)
        self.s.load(raw,'erase-all.bin')
        self.s._write(BASE+4,0x45670123)
        self.s._write(BASE+4,0xCDEF89AB)
        self.s._write(BASE+16,0x10004)
        saved=self.s.project()
        self.assertEqual(base64.b64decode(saved['internalFlashData']),b'\xff'*0x80000)
        self.assertFalse(self.s.reset())
        self.assertEqual(self.s.status,'faulted')
        self.assertEqual(self.s.uc.mem_read(FLASH,64),b'\xff'*64)
        self.assertIn('系统复位失败',self.s.diagnostics[-1]['message'])
        self.s.load_project(saved)
        self.assertEqual(self.s.status,'faulted')
        self.assertEqual(self.s.project()['internalFlashData'],saved['internalFlashData'])
        self.assertEqual(self.s.uc.mem_read(0,64),b'\xff'*64)

    def test_flash_native_write_failures_roll_back_both_aliases_and_snapshot(self):
        raw=struct.pack('<IIH',SRAM+0x10000,FLASH+9,0xE7FE)
        self.s.load(raw,'rollback.bin')
        for failure_call in (1,2):
            original=self.s.uc.mem_write
            calls=0
            def failing_write(address,data):
                nonlocal calls
                calls+=1
                if calls==failure_call:raise RuntimeError('injected native write failure')
                return original(address,data)
            with patch.object(self.s.uc,'mem_write',side_effect=failing_write):
                with self.assertRaises(RuntimeError):
                    self.s.fmc._store(FLASH+0x10000,b'\x01\x02\x03\x04')
            self.assertFalse(self.s.flash_dirty)
            self.assertEqual(self.s.internal_flash[0x10000:0x10004],b'\xff'*4)
            self.assertEqual(self.s.uc.mem_read(FLASH+0x10000,4),b'\xff'*4)
            self.assertEqual(self.s.uc.mem_read(0x10000,4),b'\xff'*4)

    def test_restored_flash_uses_its_actual_reset_vectors(self):
        raw=struct.pack('<IIHHH',SRAM+0x10000,FLASH+9,0xE7FE,0xBF00,0xE7FE)
        self.s.load(raw,'old-vector.bin')
        project=self.s.project()
        snapshot=bytearray(self.s.internal_flash)
        struct.pack_into('<II',snapshot,0,SRAM+0x18000,FLASH+13)
        project['internalFlashData']=base64.b64encode(snapshot).decode('ascii')
        self.s.load_project(project)
        self.assertEqual(self.s.uc.reg_read(UC_ARM_REG_SP),SRAM+0x18000)
        self.assertEqual(self.s.uc.reg_read(UC_ARM_REG_PC),FLASH+12)
        self.assertEqual(self.s.firmware['entry'],'0x0800000D')
        self.s.run_chunk(10)
        self.assertNotEqual(self.s.status,'faulted',self.s.diagnostics)
        self.assertEqual(self.s.uc.reg_read(UC_ARM_REG_PC),FLASH+12)

    def test_serial_mode_change_clears_queued_rx_idle_and_irq(self):
        self.s.command({'action':'v2_demo'})
        self.s._write(0x4000440C,(1<<13)|(1<<2)|(1<<4)|(1<<5))
        self.s.rx['USART1'].extend(b'A')
        self.s.uart_idle['USART1']=True
        self.s.uart_status_read['USART1']=True
        self.s._refresh_uart_irq('USART1')
        self.assertTrue(self.s.uart_irqs&(1<<38))
        self.s.set_serial_mode('rs232')
        self.assertFalse(self.s.rx['USART1'])
        self.assertFalse(self.s.uart_idle['USART1'])
        self.assertFalse(self.s.uart_status_read['USART1'])
        self.assertFalse(self.s.uart_irqs&(1<<38))
        self.assertEqual(self.s._pending_irqs(),0)

    def test_real_bootloader_receives_binary_programs_resets_and_runs_app(self):
        self.s.command({'action': 'v2_demo'})
        # Every instruction and every SysTick ISR executes, including the source's
        # long software-I2C OLED delays. No firmware RAM or outputs are injected.
        self.until(lambda: self.s.uc.mem_read(SRAM + 8, 1) == b'\x01', 40000000)
        self.assertTrue(self.s.oled.on)
        self.send(command_frame(0x0502))
        self.until(lambda: self.s.uc.mem_read(SRAM + 8, 1) == b'\x02')
        update = (ROOT / 'firmware/v2-app-update.bin').read_bytes()
        self.send(update)
        self.until(lambda: self.s.uc.mem_read(SRAM + 8, 1) == b'\x03', 15000000)
        self.assertTrue(any('020502' in r['text'] for r in self.s.logs if r['direction'] == 'tx'), self.s.logs)
        self.send(command_frame(0x0503))
        self.until(lambda: self.s.program.images[0].name == 'internal-flash.bin', 15000000)
        app = (ROOT / 'firmware/v2-app.bin').read_bytes()
        self.assertEqual(self.s.uc.mem_read(0x08011000, len(app)), app)
        self.assertEqual(self.s.uc.mem_read(0x08000000, 64), (ROOT / 'firmware/v2-bootloader.bin').read_bytes()[:64])
        self.until(lambda: any('058888' in r['text'] for r in self.s.logs if r['direction'] == 'tx'), 80000000)
        self.assertEqual(self.s.regs[0xE000ED08], 0x08011000)
        self.assertTrue(self.s.oled.on)
        restored = Simulator(ROOT)
        restored.close()
        try:
            restored.load_project(self.s.project())
            self.assertEqual(restored.board['id'], 'cimc-v2')
            self.assertEqual(restored.uc.mem_read(0x08011000, len(app)), app)
        finally:
            restored.close()


if __name__ == '__main__':
    unittest.main()
