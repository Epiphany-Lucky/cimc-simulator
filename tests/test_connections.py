"""Fixed V1 copper and serial selection are protected across API/project routes."""
import copy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from simulator import Simulator


class FixedConnectionTests(unittest.TestCase):
    def setUp(self):
        self.s=Simulator(ROOT);self.s.closed=True
        self.fixed=copy.deepcopy(self.s.board['fixedConnections'])

    def tearDown(self):self.s.closed=True

    def pair_set(self,wires):
        return {frozenset((w['from'],w['to'])) for w in wires}

    def test_oled_displayed_wires_are_already_connected_locked_copper(self):
        lines=self.s.board['fixedVisualWires']
        self.assertEqual(self.pair_set(lines),{frozenset(p) for p in
                         [('OLED.1','U2.33'),('OLED.2','U2.34'),('OLED.3','PB8'),('OLED.4','PB9')]})
        pins={p['id']:p for p in self.s.board['pins']}
        for line in lines:
            self.assertTrue(line['locked'])
            self.assertIn(self.s._pin_net(line['to']),self.s.connected(self.s._pin_net(line['from'])))
            self.assertFalse(pins[line['from']]['connectable'])
            self.assertFalse(pins[line['to']]['connectable'])
            with self.assertRaises(ValueError):self.s.command({'action':'wire_remove','id':line['id']})
        self.assertEqual(self.s.wires,[])
        self.assertEqual(self.s.net_level('OLED.1'),0)
        self.assertEqual(self.s.net_level('OLED.2'),1)

    def test_every_dedicated_endpoint_is_locked_but_led_key_wires_are_editable(self):
        locked=[p['id'] for p in self.s.board['pins'] if not p.get('connectable',True)]
        self.assertTrue({'PC0','PB8','PB9','PB12','PB13','PB14','PB15','H6.1','H7.1'}<=set(locked))
        for pin in locked:
            with self.subTest(pin=pin),self.assertRaises(ValueError):
                self.s.command({'action':'wire_add','from':pin,'to':'LED1'})
        for a,b in [('PD10','LED1'),('PE7','KEY1')]:
            self.s.command({'action':'wire_add','from':a,'to':b})
        self.assertEqual(len(self.s.wires),2)
        self.s.command({'action':'wire_remove','id':self.s.wires[0]['id']})
        self.assertEqual(len(self.s.wires),1)
        self.assertEqual(self.s.board['fixedConnections'],self.fixed)

    def test_serial_mode_only_selects_approved_h6_pairs_and_preserves_ch340(self):
        for mode in ('rs232','rs485'):
            self.s.command({'action':'serial_mode','mode':mode})
            expected={frozenset(pair) for kind in ('ch340',mode)
                      for pair in self.s.board['serialJumperPatterns'][kind]}
            self.assertEqual(self.pair_set(self.s.managed_wires()),expected)
            for w in self.s.managed_wires():
                self.assertTrue(w['locked'])
                with self.assertRaises(ValueError):self.s.command({'action':'wire_remove','id':w['id']})
            self.assertEqual(self.s.board['fixedConnections'],self.fixed)
        for invalid in ('ttl','ch340','none','both',None):
            with self.subTest(mode=invalid),self.assertRaises(ValueError):
                self.s.command({'action':'serial_mode','mode':invalid})
            self.assertEqual(self.s.serial_mode,'rs485')

    def legacy_project(self,mode='rs232'):
        p=self.s.project();p['version']=1;p.pop('serialMode');p.pop('adcVoltage')
        p['wires']=[{'from':'PD10','to':'LED1','color':'#0071e3'}]
        p['wires'] += [{'from':a,'to':b} for kind in ('ch340',mode)
                       for a,b in self.s.board['serialJumperPatterns'][kind]]
        return p

    def test_old_project_migrates_serial_pairs_without_unlocking_anything(self):
        self.s.command({'action':'adc_voltage','voltage':2.4})
        for mode in ('rs232','rs485'):
            p=self.legacy_project(mode)
            self.s.command({'action':'project_load','project':p})
            self.assertEqual(self.s.serial_mode,mode)
            self.assertEqual(self.pair_set(self.s.wires),{frozenset(('PD10','LED1'))})
            self.assertEqual(self.s.adc.voltage,2.4)
            self.assertEqual(self.s.project()['version'],2)
            self.assertEqual(self.s.board['fixedConnections'],self.fixed)

    def test_invalid_import_is_atomic_for_wires_mode_and_adc_position(self):
        self.s.command({'action':'wire_add','from':'PE7','to':'KEY1'})
        self.s.command({'action':'adc_voltage','voltage':.7})
        cases=[]
        incomplete=self.legacy_project();incomplete['wires'].pop();cases.append(incomplete)
        conflicting=self.legacy_project();conflicting['serialMode']='rs485';cases.append(conflicting)
        locked=self.s.project();locked['wires']=[{'from':'PC0','to':'LED1'}];locked['serialMode']='rs232';locked['adcVoltage']=2;cases.append(locked)
        for voltage in (-1,3.4,float('nan'),float('inf'),True,'1.2'):
            p=self.s.project();p['adcVoltage']=voltage;p['serialMode']='rs232';cases.append(p)
        for p in cases:
            before=copy.deepcopy(self.s.project())
            with self.subTest(project=p),self.assertRaises(ValueError):
                self.s.command({'action':'project_load','project':p})
            self.assertEqual(self.s.project(),before)

    def test_adc_position_roundtrips_and_survives_mcu_reset(self):
        self.s.command({'action':'adc_voltage','voltage':2.2})
        self.s.command({'action':'serial_mode','mode':'rs232'})
        self.s.command({'action':'wire_add','from':'PD10','to':'LED1'})
        saved=self.s.project()
        self.s.command({'action':'adc_voltage','voltage':0})
        self.s.command({'action':'project_load','project':saved})
        self.assertEqual(self.s.adc.voltage,2.2)
        self.assertEqual(self.s.serial_mode,'rs232')
        self.s.load((ROOT/'firmware/adc_probe.hex').read_bytes(),'adc_probe.hex')
        self.s.run_chunk(10000)
        self.assertGreater(self.s.adc.sample_count,0)
        self.s.command({'action':'reset'})
        self.assertEqual(self.s.adc.voltage,2.2)
        self.assertIsNone(self.s.adc.last_value)
        self.assertEqual(self.s.adc.sample_count,0)
        self.assertEqual(self.s.board['fixedConnections'],self.fixed)


if __name__=='__main__':unittest.main()
