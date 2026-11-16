"""V2 schematic copper and removable reference wiring affect actual peripherals."""
import base64
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from simulator import Simulator, GPIO, UART


class V2WiringTests(unittest.TestCase):
    def setUp(self):
        self.s=Simulator(ROOT,'cimc-v2')
        self.s.close()
        self.s.command({'action':'v2_demo'})

    def tearDown(self):
        self.s.close()

    def add(self,a,b):
        self.s.command({'action':'wire_add','from':a,'to':b})

    def remove(self,a,b):
        wire=next(w for w in self.s.wires if {w['from'],w['to']}=={a,b})
        self.s.command({'action':'wire_remove','id':wire['id']})

    def uart_setup(self):
        self.s._write(GPIO['PD'],(2<<10)|(2<<12))
        self.s._write(GPIO['PD']+32,(7<<20)|(7<<24))
        self.s._write(GPIO['PE'],1<<16)
        self.s._write(UART['USART1']+12,(1<<13)|(1<<2)|(1<<3))

    def test_reference_wiring_preserves_firmware_and_custom_wires(self):
        self.add('PE7','LED2')
        self.remove('H10.2','H10.4')
        cpu=self.s.uc
        program=self.s.program
        self.s.command({'action':'v2_wiring'})
        self.assertIs(self.s.uc,cpu)
        self.assertIs(self.s.program,program)
        pairs={frozenset((w['from'],w['to'])) for w in self.s.wires}
        self.assertIn(frozenset(('PE7','LED2')),pairs)
        self.assertIn(frozenset(('H10.2','H10.4')),pairs)
        count=len(self.s.wires)
        self.s.command({'action':'v2_wiring'})
        self.assertEqual(len(self.s.wires),count)
        self.assertEqual(self.s.managed_wires(),[])

    def test_removed_rx_jumpers_stop_reception_then_reconnection_restores_it(self):
        self.uart_setup()
        self.remove('H10.2','H10.4')
        self.s.command({'action':'serial','channel':'rs485','data':base64.b64encode(b'A').decode()})
        self.assertFalse(self.s.rx['USART1'])
        self.add('H10.2','H10.4')
        self.s.command({'action':'serial','channel':'rs485','data':base64.b64encode(b'B').decode()})
        self.assertEqual(bytes(self.s.rx['USART1']),b'B')

    def test_removed_tx_jumpers_stop_transmission_then_reconnection_restores_it(self):
        self.uart_setup()
        self.s._write(GPIO['PE']+20,1<<8)
        self.remove('H10.1','H10.3')
        self.s._write(UART['USART1']+4,ord('A'))
        self.s.state()
        self.assertFalse([r for r in self.s.logs if r['direction']=='tx'])
        self.add('H10.1','H10.3')
        self.s._write(UART['USART1']+4,ord('B'))
        self.s.state()
        self.assertTrue(any(r['direction']=='tx' and r['text']=='B' for r in self.s.logs))

    def test_mode_selection_moves_removable_h10_jumpers_and_project_preserves_unplugged_state(self):
        self.add('PE7','LED2')
        self.s.command({'action':'serial_mode','mode':'rs232'})
        pairs={frozenset((w['from'],w['to'])) for w in self.s.wires}
        self.assertNotIn(frozenset(('H10.1','H10.3')),pairs)
        self.assertIn(frozenset(('H10.3','H10.5')),pairs)
        self.assertIn(frozenset(('PE7','LED2')),pairs)
        self.remove('H10.3','H10.5')
        saved=self.s.project()
        self.s.load_project(saved)
        pairs={frozenset((w['from'],w['to'])) for w in self.s.wires}
        self.assertNotIn(frozenset(('H10.3','H10.5')),pairs)
        self.s.command({'action':'serial_mode','mode':'rs485'})
        pairs={frozenset((w['from'],w['to'])) for w in self.s.wires}
        self.assertIn(frozenset(('H10.1','H10.3')),pairs)

    def test_alternate_af_cannot_bypass_board_copper_or_create_unexposed_pins(self):
        self.uart_setup()
        self.s._write(GPIO['PD'],0)
        self.s._write(GPIO['PA'],(2<<4)|(2<<6))
        self.s._write(GPIO['PA']+32,(7<<8)|(7<<12))
        self.assertFalse(self.s._uart_path('rs485','tx'))
        self.assertFalse(self.s._uart_path('rs485','rx'))
        # PA2/PA3 have USART1 AF7 in the MCU datasheet, while this board's
        # physical U2/U3 connectors expose PD5/PD6 for this route.
        with self.assertRaises(ValueError):self.add('PA2','PD5')
        with self.assertRaises(ValueError):self.add('PA3','PD6')
        self.s._write(GPIO['PD'],(2<<10)|(2<<12))
        self.assertTrue(self.s._uart_path('rs485','tx'))
        self.assertTrue(self.s._uart_path('rs485','rx'))
        self.s._write(GPIO['PD']+32,0)
        self.assertFalse(self.s._uart_path('rs485','tx'))
        self.assertFalse(self.s._uart_path('rs485','rx'))

    def test_oled_bitbang_follows_added_gpio_wires(self):
        # PB8/PB9 remain the schematic's copper endpoints. Alternate GPIO
        # sources reach those nets through ordinary removable jumper wires.
        self.s._write(GPIO['PC'],(1<<4)|(1<<6))
        self.s._write(GPIO['PC']+4,(1<<2)|(1<<3))
        self.add('PC2','PB8')
        self.add('PC3','PB9')

        def level(pin,value):
            self.s._write(GPIO['PC']+24,1<<(pin if value else pin+16))

        def packet(values):
            level(3,1)
            level(2,1)
            level(3,0)
            level(2,0)
            for value in values:
                for bit in range(7,-1,-1):
                    level(2,0)
                    level(3,(value>>bit)&1)
                    level(2,1)
                level(2,0)
                level(3,1)
                level(2,1)
                level(2,0)
            level(3,0)
            level(2,1)
            level(3,1)

        packet((0x78,0,0xAF))
        self.assertTrue(self.s.oled.on)
        packet((0x78,0x40,0xAA))
        self.assertIn(0xAA,self.s.oled.ram)
        self.remove('PC2','PB8')
        packet((0x78,0,0xAE))
        self.assertTrue(self.s.oled.on)
        self.add('PC2','PB8')
        packet((0x78,0,0xAE))
        self.assertFalse(self.s.oled.on)
        self.assertTrue(self.s._oled_powered())


if __name__=='__main__':
    unittest.main()
