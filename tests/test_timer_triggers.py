"""Timer events reach the modeled ADC/DAC through actual firmware time."""
from pathlib import Path
import struct
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from simulator import Simulator, FLASH, SRAM


class TimerTriggerTests(unittest.TestCase):
    def setUp(self):
        self.sim=Simulator(ROOT)
        self.sim.close()

    def tearDown(self):self.sim.close()

    def setup_adc(self,board,selection,edges=1):
        s=self.sim
        s.select_board(board)
        s.load(struct.pack('<IIH',SRAM+0x1000,FLASH+9,0xE7FE),'clock-loop.bin')
        s._write(0x40023830,1<<2)
        s._write(0x40023844,(1<<8)|1)
        s._write(0x40023840,1<<1)
        s._write(0x40020800,3)
        s._write(0x40012034,10)
        s._write(0x40012008,1|(selection<<24)|(edges<<28))

    def test_adc_timer_update_trigger_uses_selected_edge_and_clock(self):
        for board in ('cimc-v1','cimc-v2'):
            with self.subTest(board=board):
                self.setup_adc(board,8,2)  # TIMER2 TRGO, falling edge.
                s=self.sim
                ticks=s.board.get('clockTicksPerInstruction',1)
                s._write(0x40012008,0)
                s._write(0x4000042C,ticks*10-1)
                s._write(0x40000414,1)
                s._write(0x40000404,2<<4)
                s._write(0x40012008,1|(8<<24)|(2<<28))
                s._write(0x40000400,1)
                s.run_chunk(9)
                self.assertEqual(s.adc.sample_count,0)
                s.run_chunk(1)
                self.assertEqual(s.adc.sample_count,1)
                self.assertEqual(s._read(0x4001204C),2048)
                s._write(0x40023840,0)
                s.run_chunk(30)
                self.assertEqual(s.adc.sample_count,1)
                self.assertNotEqual(s.status,'faulted',s.diagnostics)

    def test_adc_compare_event_uses_correct_timer_and_channel(self):
        self.setup_adc('cimc-v1',1)  # TIMER0 CH1.
        s=self.sim
        ticks=s.board['clockTicksPerInstruction']
        s._write(0x4001002C,100*ticks-1)
        s._write(0x40010034,2*ticks)
        s._write(0x40010038,5*ticks)
        s._write(0x40010014,1)
        s._write(0x40010000,1)
        s.run_chunk(2)
        self.assertEqual(s.adc.sample_count,0)
        s.run_chunk(3)
        self.assertEqual(s.adc.sample_count,1)
        self.assertEqual(s._read(0x4001204C),2048)

    def test_basic_timer_triggers_dac_holding_value_and_ignores_software_trigger(self):
        s=self.sim
        s.select_board('cimc-v2')
        s.load(struct.pack('<IIH',SRAM+0x1000,FLASH+9,0xE7FE),'clock-loop.bin')
        s._write(0x40023830,1)
        s._write(0x40020000,3<<8)
        s._write(0x40023840,(1<<29)|(1<<4))
        s._write(0x4000102C,2399)
        s._write(0x40001014,1)
        s._write(0x40001004,2<<4)
        s._write(0x40007400,5)  # OUT0 enable, TIMER5 TRGO trigger enable.
        s._write(0x40007408,3072)
        s._write(0x40007404,1)
        self.assertEqual(s.v2_devices.dac_output,0)
        s._write(0x40001000,1)
        s.run_chunk(9)
        self.assertEqual(s.v2_devices.dac_output,0)
        s.run_chunk(1)
        self.assertEqual(s.v2_devices.dac_output,3072)
        s._write(0x40007408,2048)
        self.assertEqual(s.v2_devices.dac_output,3072)
        s.run_chunk(10)
        self.assertEqual(s.v2_devices.dac_output,2048)
        self.assertNotEqual(s.status,'faulted',s.diagnostics)


if __name__=='__main__':unittest.main()
