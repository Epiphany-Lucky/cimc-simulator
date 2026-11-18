"""Terminal frame configuration against real firmware and USART registers."""
import base64
import copy
import json
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from simulator import FLASH, GPIO, SRAM, UART, UART_IRQ, Simulator


def frame(baud=115200, data=8, parity='none', stop=1):
    return {'baudRate': baud, 'dataBits': data, 'parity': parity, 'stopBits': stop}


class SerialSettingsTests(unittest.TestCase):
    def setUp(self):
        self.s = Simulator(ROOT)
        self.s.close()  # Advance deterministic instruction chunks in the tests.

    def configure(self, value, channel='ch340'):
        return self.s.command({'action': 'serial_settings', 'channel': channel, 'settings': value})

    def send(self, payload):
        return self.s.command({'action': 'serial', 'channel': 'ch340', 'data': base64.b64encode(payload).decode('ascii')})

    def wait_until(self, predicate, budget=1_500_000):
        for _ in range(budget//10_000):
            if predicate():
                return
            self.s.run_chunk(10_000)
            self.assertNotEqual(self.s.status, 'faulted', self.s.diagnostics)
        self.assertTrue(predicate(), 'Actual firmware did not reach the expected observable state')

    def tx(self, channel='ch340'):
        return [row['text'] for row in self.s.logs if row['direction']=='tx' and row['channel']==channel]

    def warnings(self):
        return [item for item in self.s.diagnostics if item.get('code')=='serial-config']

    def test_real_demo_blocks_mismatch_then_resumes_bidirectional_exchange(self):
        # The bundled demo programs BRR=1250 at IRC16M, which is 12800 baud.
        self.s.command({'action': 'demo'})
        self.configure(frame(9600))
        self.wait_until(lambda: self.s.oled.on)
        self.assertEqual(self.s.state()['serialParameters']['ch340'], frame(12800))
        self.assertIs(self.s.state()['serialCompatibility']['ch340'], False)
        self.assertEqual(self.tx(), [])
        self.assertTrue(self.tx('rs485'))
        self.assertEqual(len(self.warnings()), 1)
        self.send(b'L')
        self.assertFalse(self.s.rx['USART0'])
        self.assertEqual(len(self.warnings()), 1)

        # Nominal rates may differ slightly from the computed firmware rate.
        self.configure(frame(12799))
        self.assertIs(self.s.state()['serialCompatibility']['ch340'], True)
        self.send(b'L')
        self.wait_until(lambda: any('ACK L' in data for data in self.tx()))
        self.configure(None)
        self.assertEqual(self.s.state()['serialSettings'], {})
        self.assertIsNone(self.s.state()['serialCompatibility']['ch340'])

    def test_clock_dividers_and_frame_fields_use_firmware_registers(self):
        self.s._write(0x40023808, (5<<10)|(4<<13))  # APB1=4 MHz, APB2=8 MHz.
        for uart,baud,cts in (('USART0',100000,0),('USART1',50000,1),
                              ('USART2',50000,2),('USART5',100000,3)):
            with self.subTest(uart=uart):
                base=UART[uart]
                self.s._write(base+8, 0xA0)  # OVER8, divider = 10*8.
                self.s._write(base+12, (1<<15)|(1<<13)|(1<<10)|(1<<9))
                self.s._write(base+16, cts<<12)
                self.assertEqual(self.s._uart_parameters(uart), frame(baud,7,'odd',(1,.5,2,1.5)[cts]))
        base=UART['USART0']
        self.s._write(base+8, 0xA3)  # Fraction is 3 of 8.
        self.s._write(base+12, (1<<15)|(1<<13)|(1<<12)|(1<<10))
        self.assertEqual(self.s.state()['serialParameters']['ch340'], frame(96386,8,'even'))
        self.s._write(base+12, (1<<13)|(1<<12))  # OVER16, divider = 10*16+3.
        self.assertEqual(self.s.state()['serialParameters']['ch340'], frame(49080,9))
        self.s._write(base+12, 0)
        self.assertIsNone(self.s.state()['serialParameters']['ch340'])

    def test_framing_mismatch_is_checked_and_7_data_bits_are_applied(self):
        usart=UART['USART0']
        self.s._write(GPIO['PA'], (2<<18)|(2<<20))
        self.s._write(GPIO['PA']+36, (7<<4)|(7<<8))
        self.s._write(usart+8,139)
        self.s._write(usart+12,(1<<13)|(1<<10)|(1<<3)|(1<<2))  # 7E2
        self.s._write(usart+16,2<<12)
        for incorrect in (frame(),frame(data=7,parity='odd',stop=2),frame(data=7,parity='even')):
            with self.subTest(incorrect=incorrect):
                self.assertIs(self.configure(incorrect)['serialCompatibility']['ch340'], False)
                self.send(b'\xc1')
                self.s._write(usart+4,0xC1)
                self.assertFalse(self.s.rx['USART0'])
                self.assertEqual(self.tx(), [])

        self.assertIs(self.configure(frame(data=7,parity='even',stop=2))['serialCompatibility']['ch340'], True)
        self.send(b'\xc1')
        self.assertEqual(self.s._read(usart+4),0x41)
        self.s._write(usart+4,0xC1)
        self.s.state()
        self.assertEqual(self.tx(), ['A'])

    def test_unprogrammed_baud_is_unknown_and_only_automatic_accepts(self):
        usart=UART['USART0']
        self.s._write(GPIO['PA'], (2<<18)|(2<<20))
        self.s._write(GPIO['PA']+36, (7<<4)|(7<<8))
        self.s._write(usart+12,(1<<13)|(1<<3)|(1<<2))
        self.assertIsNone(self.configure(frame())['serialCompatibility']['ch340'])
        self.send(b'X')
        self.s._write(usart+4,ord('X'))
        self.assertFalse(self.s.rx['USART0'])
        self.assertEqual(self.tx(), [])
        self.assertEqual(len(self.warnings()), 1)

        self.configure(None)
        self.send(b'Y')
        self.s._write(usart+4,ord('Y'))
        self.s.state()
        self.assertEqual(self.s._read(usart+4),ord('Y'))
        self.assertEqual(self.tx(), ['Y'])

    def test_v1_rxne_and_idle_execute_real_usart_exception_handler(self):
        usart = UART['USART0']
        irq = UART_IRQ['USART0']
        image = bytearray(0x140)
        struct.pack_into('<II', image, 0, SRAM+0x10000, FLASH+0x101)
        struct.pack_into('<I', image, (16+irq)*4, FLASH+0x121)
        struct.pack_into('<H', image, 0x100, 0xE7FE)  # Idle loop: b .
        # Thumb ISR reads SR then DR, records the status and RXNE data in SRAM,
        # counts each entry, and returns via BX LR. The IDLE entry clears SR/DR
        # without overwriting the byte from the preceding RXNE entry.
        struct.pack_into('<12HII', image, 0x120, 0x4805, 0x6801, 0x6842, 0x4B05,
                         0x6019, 0x0689, 0xD500, 0x605A, 0x6899, 0x3101, 0x6099, 0x4770,
                         usart, SRAM)
        self.s.load(bytes(image),'usart-rx-irq.bin')
        self.s._write(GPIO['PA'], (2<<18)|(2<<20))
        self.s._write(GPIO['PA']+36, (7<<4)|(7<<8))
        self.s._write(usart+8,139)
        self.s._write(usart+12,(1<<13)|(1<<5)|(1<<4)|(1<<3)|(1<<2))
        self.s._write(0xE000E104,1<<(irq-32))
        self.send(b'Z')
        self.assertEqual(self.s._eligible_exception(),16+irq)
        self.s.run_chunk(100)
        status, byte, entries = struct.unpack('<III', self.s.uc.mem_read(SRAM,12))
        self.assertEqual((status&(0x20|0x10),byte,entries),(0x10,ord('Z'),2))
        self.assertFalse(self.s.uart_idle['USART0'])
        self.assertFalse(self.s.uart_irqs)
        self.assertNotEqual(self.s.status,'faulted',self.s.diagnostics)

    def test_configuration_survives_firmware_reset_and_project_roundtrip(self):
        previous=self.s.project()
        self.configure(frame())
        self.configure(frame(9600,7,'even',2),'rs485')
        different={'ch340':frame(), 'rs485':frame(9600,7,'even',2)}
        self.s.command({'action': 'demo'})
        self.s.command({'action': 'reset'})
        self.assertEqual(self.s.state()['serialSettings'],different)
        saved=json.loads(json.dumps(self.s.project()))
        self.assertEqual(saved['serialSettings'],different)

        self.s.select_board('cimc-v2')
        self.assertEqual(self.s.state()['serialSettings'],{})
        self.s.command({'action': 'project_load', 'project': saved})
        self.assertEqual(self.s.board['id'],'cimc-v1')
        self.assertEqual(self.s.state()['serialSettings'],different)
        self.s.command({'action': 'project_load', 'project': previous})
        self.assertEqual(self.s.state()['serialSettings'],{})

    def test_invalid_frames_and_project_load_are_atomic(self):
        self.s.command({'action': 'demo'})
        self.configure(frame())
        before=copy.deepcopy(self.s.project())
        bad_frames=[frame(True),frame(0),frame(12_000_001),frame(115200.0),frame(data=True),
                    frame(data=9),frame(parity='mark'),frame(stop=True),frame(stop=float('nan')),
                    {**frame(),'extra':0},{'baudRate':9600}]
        for bad in bad_frames:
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                self.configure(bad)
        for bad in ({'ch340':frame(0)}, {'invented':frame()}, {'ch340':None}, None):
            project={**before,'serialSettings':bad,'adcVoltage':0}
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                self.s.command({'action':'project_load','project':project})
        with self.assertRaises(ValueError):
            self.configure(frame(),['ch340'])
        self.assertEqual(self.s.project(),before)


if __name__ == '__main__':
    unittest.main()
