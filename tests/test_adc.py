"""ADC acceptance includes actual Keil code reading the fixed PC0 input."""
from pathlib import Path
import struct
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from adc import AdcDevice, ADC_BASE, EOC, ROVF, SWRCST, RCU_AHB1EN, RCU_APB2EN, RCU_APB2RST
from simulator import Simulator


class FakeBoard:
    def __init__(self):
        self.regs={RCU_AHB1EN:1<<2,RCU_APB2EN:7<<8}
        self.gpio_state={'PC':{'mode':3}}
        self.errors=[]
    def diagnose(self,message,*args,**kwargs):self.errors.append(message)


class AdcRegisterTests(unittest.TestCase):
    def setUp(self):
        self.sim=FakeBoard();self.adc=AdcDevice(self.sim)
        for i in range(3):
            self.adc.write(ADC_BASE+i*0x100+0x34,10)
            self.adc.write(ADC_BASE+i*0x100+8,1)

    def sample(self,voltage,index=0):
        self.adc.set_voltage(voltage)
        base=ADC_BASE+index*0x100
        control=self.adc.read(base+8)
        self.adc.write(base+8,control|SWRCST)
        self.assertTrue(self.adc.read(base)&EOC,self.sim.errors)
        result=self.adc.read(base+0x4C)
        self.assertFalse(self.adc.read(base)&EOC)
        return result

    def test_endpoints_midpoint_and_sample_hold(self):
        self.assertIsNone(self.adc.state()['value'])
        self.assertEqual(self.sample(0),0)
        self.adc.set_voltage(1.65)
        self.assertEqual(self.adc.state()['value'],0)
        self.assertEqual(self.sample(1.65),2048)
        self.assertEqual(self.sample(3.3),4095)
        self.assertEqual(self.adc.state()['sampleCount'],3)

    def test_instances_resolution_and_left_alignment(self):
        for index in range(3):
            for encoding,bits in enumerate((12,10,8,6)):
                for left in (False,True):
                    with self.subTest(index=index,bits=bits,left=left):
                        self.adc.write(ADC_BASE+index*0x100+4,encoding<<24)
                        self.adc.write(ADC_BASE+index*0x100+8,1|((1<<11) if left else 0))
                        fullscale=(1<<bits)-1
                        self.assertEqual(self.sample(3.3,index),fullscale<<(16-bits) if left else fullscale)
                        self.assertEqual(self.adc.state()['value'],fullscale)
                        self.assertEqual(self.adc.state()['bits'],bits)

    def test_invalid_ui_voltage_is_atomic(self):
        for value in (-.1,3.31,float('nan'),float('inf'),True,'2.0',None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):self.adc.set_voltage(value)
                self.assertEqual(self.adc.voltage,1.65)

    def test_calibration_reset_and_input_position_preserved(self):
        self.adc.write(ADC_BASE+8,1|12)
        self.assertEqual(self.adc.read(ADC_BASE+8),1)
        self.sample(2.4)
        self.adc.notify_rcu_write(RCU_APB2RST,1<<8)
        self.assertIsNone(self.adc.state()['value'])
        self.assertEqual(self.adc.state()['voltage'],2.4)
        self.assertEqual(self.adc.state()['sampleCount'],0)
        self.assertEqual(self.adc.read(ADC_BASE+8),0)

    def test_clock_analog_mode_and_channel_are_required(self):
        for kind in ['clock','gpio_clock','analog','channel']:
            with self.subTest(kind=kind):
                self.setUp()
                if kind=='clock':self.sim.regs[RCU_APB2EN]=0
                if kind=='gpio_clock':self.sim.regs[RCU_AHB1EN]=0
                if kind=='analog':self.sim.gpio_state['PC']['mode']=0
                if kind=='channel':self.adc.write(ADC_BASE+0x34,11)
                self.adc.write(ADC_BASE+8,1|SWRCST)
                self.assertTrue(self.sim.errors)
                self.assertIsNone(self.adc.state()['value'])

    def test_overrun_preserves_old_result_and_flags_clear(self):
        self.adc.write(ADC_BASE+8,1|(1<<10))
        self.adc.set_voltage(0);self.adc.write(ADC_BASE+8,1|(1<<10)|SWRCST)
        self.adc.set_voltage(3.3);self.adc.write(ADC_BASE+8,1|(1<<10)|SWRCST)
        self.assertTrue(self.adc.read(ADC_BASE)&ROVF)
        self.assertEqual(self.adc.read(ADC_BASE+0x4C),0)
        self.adc.write(ADC_BASE,~ROVF)
        self.assertFalse(self.adc.read(ADC_BASE)&ROVF)

    def test_unsupported_modes_fail_explicitly(self):
        for off,value in [(4,1<<5),(4,1<<8),(8,1|(1<<8)),(8,3),(8,1|(1<<28)),(0x304,6),(0x80,1),(0x38,1)]:
            with self.subTest(off=off,value=value):
                self.setUp();self.adc.write(ADC_BASE+off,value)
                self.assertTrue(self.sim.errors)


class AdcFirmwareTests(unittest.TestCase):
    def test_demo_machine_code_updates_oled_and_uart_after_sampling(self):
        s=Simulator(ROOT);s.closed=True
        def until(predicate):
            for _ in range(200):
                if predicate():return
                s.run_chunk(10000)
                self.assertNotEqual(s.status,'faulted',s.diagnostics)
            self.fail('Demo did not reach its firmware sampling or serial output')
        try:
            s.command({'action':'demo'})
            until(lambda:s.adc.sample_count>1)
            self.assertTrue(any('FLASH JEDEC C84013' in r['text'] for r in s.state()['serial']))
            # Independently known 5x7 decimal glyphs, each followed by a blank column.
            digits={'0':'3e5149453e00','2':'426151494600','4':'1814127f1000',
                    '5':'274545453900','8':'364949493600','9':'064949291e00'}
            for volts,expected in [(0,0),(3.3,4095),(1.65,2048)]:
                old_count=s.adc.sample_count
                s.command({'action':'adc_voltage','voltage':volts})
                until(lambda:s.adc.sample_count>old_count+1)
                self.assertEqual(s.adc.last_value,expected)
                glyphs=bytes.fromhex(''.join(digits[d] for d in f'{expected:04d}'))
                self.assertEqual(bytes(s.oled.ram[152:176]),glyphs)
                s.logs=[]
                s.command({'action':'serial','channel':'ch340','data':'QQ=='})
                until(lambda:any(f'ADC {expected:04d} PC0' in r['text'] for r in s.state()['serial']))
            self.assertEqual(s.flash.state()['writeCount'],0)
            self.assertEqual(s.flash.state()['eraseCount'],0)
        finally:s.closed=True

    def test_keil_machine_code_reads_knob_into_sram(self):
        s=Simulator(ROOT);s.closed=True
        try:
            s.load((ROOT/'firmware/adc_probe.hex').read_bytes(),'adc_probe.hex')
            for voltage,expected in [(0,0),(1.65,2048),(3.3,4095)]:
                s.command({'action':'adc_voltage','voltage':voltage})
                for _ in range(5):s.run_chunk(10000)
                self.assertNotEqual(s.status,'faulted',s.diagnostics)
                value,count=struct.unpack('<II',s.uc.mem_read(0x20000000,8))
                self.assertEqual(value,expected)
                self.assertGreater(count,0)
                self.assertEqual(s.state()['adc']['value'],expected)
        finally:s.closed=True


if __name__=='__main__':unittest.main()
