"""Functional regression tests execute the checked-in Keil-produced machine code."""
import base64
import copy
import json
from pathlib import Path
import struct
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from simulator import Simulator, parse_firmware, FLASH, FLASH_SIZE, SRAM, SRAM_SIZE, CCM, CCM_SIZE, GPIO, UART


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.s=Simulator(ROOT)
        self.s.closed=True

    def tearDown(self):self.s.closed=True

    def advance(self,instructions=200000):
        for _ in range(instructions//10000):
            self.s.run_chunk(10000)
            self.assertNotEqual(self.s.status,'faulted',self.s.diagnostics)

    def demo(self):
        self.s.command({'action':'demo'})
        self.until(lambda:any('OLED READY' in r['text'] for r in self.s.logs))

    def until(self,predicate):
        for _ in range(150):
            if predicate():return
            self.advance(10000)
        self.fail('Firmware did not reach expected observable state')

    def test_keil_hex_and_bin_equal_machine_image(self):
        a=parse_firmware((ROOT/'firmware/demo.hex').read_bytes(),'demo.hex')
        b=parse_firmware((ROOT/'firmware/demo.bin').read_bytes(),'demo.bin')
        self.assertEqual(a[:4],b[:4])
        self.assertIn('Keil',(ROOT/'firmware/compiler.txt').read_text(encoding='utf-8-sig'))
        self.s.command({'action':'demo'})
        for ext in ('hex','bin'):
            self.s.load((ROOT/f'firmware/demo.{ext}').read_bytes(),f'demo.{ext}')
            self.until(lambda:any('OLED READY' in r['text'] for r in self.s.logs))
            state=self.s.state()
            self.assertGreater(sum(state['oled']['pixels']),300)
            self.assertTrue(any('ARM firmware ready' in r['text'] for r in state['serial']))

    def test_bad_hex_checksum_rejected(self):
        raw=(ROOT/'firmware/demo.hex').read_text()
        lines=raw.splitlines();lines[0]=lines[0][:-2]+'00'
        with self.assertRaises(ValueError):parse_firmware('\n'.join(lines).encode(),'bad.hex')

    def test_capacity_and_vectors(self):
        self.assertEqual(FLASH_SIZE,512*1024)
        self.assertEqual(SRAM_SIZE,192*1024)
        self.assertEqual(CCM_SIZE,64*1024)
        with self.assertRaises(ValueError):parse_firmware(struct.pack('<II',0x20070000,FLASH+9)+b'\xfe\xe7','bad.bin')
        with self.assertRaises(ValueError):parse_firmware((ROOT/'firmware/demo.bin').read_bytes(),'bad.bin',FLASH+FLASH_SIZE)

    def test_real_key_and_removable_jumper(self):
        self.demo()
        fixed=copy.deepcopy(self.s.board.get('fixedNets'))
        self.assertEqual(self.s.state()['leds'],[True,False,False,False,False,False])
        self.s.command({'action':'key','index':1,'pressed':True})
        self.until(lambda:self.s.state()['leds']==[False,True,False,False,False,False])
        self.assertEqual(self.s.state()['leds'],[False,True,False,False,False,False])
        self.assertTrue(any('KEY pressed' in r['text'] for r in self.s.logs))
        wire=next(w for w in self.s.wires if w['to']=='LED2')
        self.s.command({'action':'wire_remove','id':wire['id']})
        self.assertFalse(self.s.state()['leds'][1])
        self.assertEqual(fixed,self.s.board.get('fixedNets'))

    def test_serial_response_from_firmware(self):
        self.demo()
        for channel in ('ch340','rs485','ttl'):
            self.s.command({'action':'serial','channel':channel,'data':base64.b64encode(b'L').decode()})
            self.until(lambda:any(r['channel']==channel and r['direction']=='tx' and 'ACK L' in r['text'] for r in self.s.logs))
            self.assertTrue(any(r['channel']==channel and r['direction']=='tx' and 'ACK L' in r['text'] for r in self.s.logs))
        self.s.command({'action':'serial_mode','mode':'rs232'})
        self.s.command({'action':'serial','channel':'rs232','data':'TA=='})
        self.until(lambda:any(r['channel']=='rs232' and r['direction']=='tx' and 'ACK L' in r['text'] for r in self.s.logs))

    def test_disabled_uart_does_not_receive(self):
        self.s.command({'action':'demo'})
        self.s.command({'action':'serial','channel':'ch340','data':'TA=='})
        self.assertFalse(self.s.rx['USART0'])
        self.assertEqual(self.s._read(UART['USART0']),0)

    def test_inactive_serial_mode_blocks_data(self):
        self.demo()
        self.s.command({'action':'serial','channel':'rs232','data':'TA=='})
        self.assertFalse(self.s.rx['USART1'])
        self.assertTrue(any('线路未接通' in d['message'] for d in self.s.diagnostics))

    def test_v1_connector_and_copper_mapping(self):
        pins={p['id']:p for p in self.s.board['pins']}
        self.assertEqual(pins['LED1']['group'],'H2')
        self.assertEqual(pins['LED1']['number'],6)
        self.assertEqual(pins['KEY6']['number'],1)
        self.assertEqual(pins['PB10']['number'],30)
        self.assertEqual(self.s.board['serialMappings']['ttl']['tx'],'PB10')
        self.assertIn('PB8',self.s.connected('OLED_CLK'))
        self.assertNotIn('PD10',self.s.connected('LED1'))

    def test_dynamic_conflict_after_key_press_stops(self):
        self.s._write(GPIO['PE']+20,1<<13)
        self.s._write(GPIO['PE'],1<<26)
        self.s.command({'action':'wire_add','from':'PE13','to':'KEY1'})
        self.assertNotEqual(self.s.status,'faulted')
        self.s.command({'action':'key','index':0,'pressed':True})
        self.assertEqual(self.s.status,'faulted')

    def test_unknown_mmio_stops(self):
        self.s.command({'action':'demo'})
        self.s._read(0x40026000)
        self.assertEqual(self.s.status,'faulted')
        self.assertIn('0x40026000',self.s.diagnostics[-1]['message'])

    def test_systick_executes_real_exception_handler(self):
        self.s.load((ROOT/'firmware/systick.hex').read_bytes(),'systick.hex')
        for _ in range(100):self.s.run_chunk(1000)
        ticks=struct.unpack('<I',self.s.uc.mem_read(SRAM,4))[0]
        self.assertGreater(ticks,10)
        self.assertLess(ticks,100)
        self.assertNotEqual(self.s.status,'faulted',self.s.diagnostics)
        self.assertFalse(self.s.in_exception)

    def test_uart_interrupt_enable_stops_instead_of_fake_progress(self):
        self.s.command({'action':'demo'})
        self.s._write(UART['USART0']+12,(1<<13)|(1<<5))
        self.assertEqual(self.s.status,'faulted')
        self.assertIn('中断模式尚未实现',self.s.diagnostics[-1]['message'])

    def test_project_roundtrip_and_atomic_rejection(self):
        self.s.command({'action':'demo'})
        project=json.loads(json.dumps(self.s.project()))
        fixed=copy.deepcopy(self.s.board.get('fixedNets'))
        self.s.command({'action':'project_load','project':project})
        expected=[(w['from'],w['to']) for w in self.s.wires]
        bad=copy.deepcopy(project);bad['wires'].append({'from':'invented','to':'KEY1'})
        with self.assertRaises(ValueError):self.s.command({'action':'project_load','project':bad})
        self.assertEqual(expected,[(w['from'],w['to']) for w in self.s.wires])
        bad=copy.deepcopy(project);bad['boardId']='another'
        with self.assertRaises(ValueError):self.s.command({'action':'project_load','project':bad})
        self.assertEqual(fixed,self.s.board.get('fixedNets'))

    def test_nc_rejected_and_conflict_diagnosed(self):
        nc=next(p for p in self.s.board['pins'] if not p.get('connectable',True))
        with self.assertRaises(ValueError):self.s.command({'action':'wire_add','from':nc['id'],'to':'KEY1'})
        power=next(p for p in self.s.board['pins'] if p['net']=='3V3')
        ground=next(p for p in self.s.board['pins'] if p['net'] in ('GND','DGND'))
        with self.assertRaises(ValueError):self.s.command({'action':'wire_add','from':power['id'],'to':ground['id']})
        self.s._write(GPIO['PE']+20,1<<13)
        self.s._write(GPIO['PE'],(1<<26)|(1<<28))
        self.s.command({'action':'wire_add','from':'PE13','to':'PE14'})
        self.assertTrue(any('冲突' in d['message'] for d in self.s.diagnostics))

    def test_i2c_ack_is_driven_on_ninth_clock(self):
        s=self.s;s.command({'action':'demo'})
        b=GPIO['PB'];s._write(b,(1<<16)|(1<<18));s._write(b+4,(1<<8)|(1<<9));s._write(b+12,(1<<16)|(1<<18))
        def pin(n,v):s._write(b+24,1<<n if v else 1<<(n+16))
        pin(8,0);pin(9,1);pin(8,1);pin(9,0);pin(8,0)
        for bit in range(7,-1,-1):pin(9,(0x78>>bit)&1);pin(8,1);pin(8,0)
        pin(9,1);pin(8,1)
        self.assertEqual((s._read(b+16)>>9)&1,0)
        pin(8,0)
        self.assertEqual((s._read(b+16)>>9)&1,1)


if __name__=='__main__':unittest.main()
