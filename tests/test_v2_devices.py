"""Register-level tests for the driver-evidenced V2 analog paths."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from adc import AdcDevice, ADC_BASE, SWRCST
from v2_devices import (V2Devices, SPI0, DAC0, GPIOA, RCU_AHB1EN,
                        RCU_APB1EN, RCU_APB2EN, RCU_APB1RST, RCU_APB2RST)

class AnalogBoard:
    def __init__(self, board_id='cimc-v2'):
        self.board = {'id': board_id}
        self.regs = {RCU_AHB1EN: 7, RCU_APB1EN: 1 << 29,
                     RCU_APB2EN: (1 << 12) | (1 << 8), GPIOA + 32: 0x55500000}
        self.gpio_state = {'PA': {'mode': (3 << 8) | (2 << 10) | (2 << 12) | (2 << 14), 'out': 0},
                           'PB': {'mode': 1 << 20, 'out': 1 << 10},
                           'PC': {'mode': 15, 'out': 0}}
        self.errors = []
        self.wires = {('PC0', 'ADC_IN0'), ('PC1', 'ADC_IN1')}

    def diagnose(self, message, *args, **kwargs):
        self.errors.append(message)

    def connected(self, terminal):
        reached = {terminal}
        while True:
            previous = len(reached)
            for first, second in self.wires:
                if first in reached or second in reached:
                    reached.update((first, second))
            if len(reached) == previous:
                return reached

class V2AnalogTests(unittest.TestCase):
    def setUp(self):
        self.sim = AnalogBoard()
        self.devices = V2Devices(self.sim)
        self.devices.write(SPI0, 0x37D)

    def byte(self, value):
        self.devices.write(SPI0 + 12, value)
        self.assertEqual(self.devices.read(SPI0 + 8) & 3, 3)
        result = self.devices.read(SPI0 + 12)
        self.assertEqual(self.devices.read(SPI0 + 8) & 1, 0)
        return result

    def test_unselected_spi_bus_returns_ff_for_all_clock_modes(self):
        for mode in range(4):
            self.devices.write(SPI0, 0x344 | mode)
            self.assertEqual([self.byte(value) for value in (0x40, 0x4B, 0, 0)], [255] * 4)
        self.assertEqual(self.sim.errors, [])
        self.assertEqual(set(self.devices.state()), {'dac'})

    def test_spi_clock_and_unsupported_transfer_configuration_are_explicit(self):
        for kind in ('clock', 'lsb', '16bit', 'dma', 'i2s'):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == 'clock':
                    self.sim.regs[RCU_APB2EN] = 0
                elif kind == 'lsb':
                    self.devices.write(SPI0, 0x37D | (1 << 7))
                elif kind == '16bit':
                    self.devices.write(SPI0, 0x37D | (1 << 11))
                elif kind == 'dma':
                    self.devices.write(SPI0 + 4, 1)
                else:
                    self.devices.write(SPI0 + 28, 0xC00)
                self.devices.write(SPI0 + 12, 0)
                self.assertTrue(self.sim.errors)

    def test_spi_overrun_and_controller_reset(self):
        self.devices.write(SPI0 + 12, 0x40)
        self.devices.write(SPI0 + 12, 0x4B)
        self.assertEqual(self.devices.read(SPI0 + 8) & 64, 64)
        self.devices.read(SPI0 + 12)
        self.devices.read(SPI0 + 8)
        self.assertEqual(self.devices.read(SPI0 + 8) & 64, 0)
        self.devices.notify_rcu_write(RCU_APB2RST, 1 << 12)
        self.assertEqual(self.devices.spi[0], 0)
        self.assertEqual(self.devices.spi[8], 2)

    def test_dac_direct_software_trigger_alignment_and_output_hold(self):
        self.devices.write(DAC0, 1)
        self.devices.write(DAC0 + 8, 4095)
        self.assertEqual(self.devices.read(DAC0 + 0x2C), 4095)
        self.assertEqual(self.devices.state()['dac']['voltage'], 3.3)
        self.devices.write(DAC0 + 12, 2048 << 4)
        self.assertEqual(self.devices.dac_output, 2048)
        self.devices.write(DAC0 + 16, 255)
        self.assertEqual(self.devices.dac_output, 4080)
        self.devices.write(DAC0, 1 | 4 | (7 << 3))
        self.devices.write(DAC0 + 8, 1000)
        self.assertEqual(self.devices.dac_output, 4080)
        self.devices.write(DAC0 + 4, 1)
        self.assertEqual(self.devices.dac_output, 1000)
        self.devices.write(DAC0 + 0x2C, 4095)
        self.assertEqual(self.devices.dac_output, 1000)
        self.devices.write(DAC0, 0)
        self.assertIsNone(self.devices.state()['dac']['voltage'])
        self.assertEqual(self.sim.errors, [])

    def test_dac_pa4_output_tracks_hardware_pin_mode(self):
        self.devices.write(DAC0, 1)
        self.devices.write(DAC0 + 8, 2048)
        self.assertEqual(self.devices.state()['dac']['pin'], 'PA4')
        self.assertAlmostEqual(self.devices.state()['dac']['voltage'], 2048 * 3.3 / 4095)
        self.sim.gpio_state['PA']['mode'] &= ~(3 << 8)
        self.assertIsNone(self.devices.state()['dac']['voltage'])
        self.assertEqual(self.devices.read(DAC0 + 0x2C), 2048)
        self.sim.gpio_state['PA']['mode'] |= 3 << 8
        self.assertAlmostEqual(self.devices.state()['dac']['voltage'], 2048 * 3.3 / 4095)

    def test_dac_requires_clock_analog_pin_and_rejects_other_modes(self):
        for kind in ('clock', 'gpio_clock', 'mode', 'dma', 'waveform', 'channel'):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == 'clock':
                    self.sim.regs[RCU_APB1EN] = 0
                elif kind == 'gpio_clock':
                    self.sim.regs[RCU_AHB1EN] = 0
                elif kind == 'mode':
                    self.sim.gpio_state['PA']['mode'] = 0
                self.devices.write(DAC0, {'dma': 4097, 'waveform': 1 << 6, 'channel': 1 << 16}.get(kind, 1))
                self.assertTrue(self.sim.errors)
        self.setUp()
        self.devices.write(DAC0, 1)
        self.devices.write(DAC0 + 8, 2048)
        self.devices.notify_rcu_write(RCU_APB1RST, 1 << 29)
        self.assertEqual(self.devices.dac_output, 0)
        self.assertFalse(self.devices.state()['dac']['enabled'])

    def test_v1_cannot_claim_v2_analog_address_ranges(self):
        self.sim.board['id'] = 'cimc-v1'
        self.assertFalse(self.devices.contains(SPI0))
        self.assertFalse(self.devices.contains(DAC0))

    def test_v2_adc_pc0_pc1_independent_inputs_and_trigger_configuration(self):
        adc = AdcDevice(self.sim)
        adc.set_voltage(0, channel=10)
        adc.set_voltage(3.3, channel=11)
        self.assertIsNone(adc.state()['currentValue'])
        for channel, expected in ((10, 0), (11, 4095), (10, 0)):
            adc.write(ADC_BASE + 0x34, channel)
            adc.write(ADC_BASE + 8, 1 | (1 << 28) | SWRCST)
            self.assertEqual(adc.read(ADC_BASE + 0x4C), expected)
            self.assertEqual(adc.state()['channel'], channel)
        self.assertEqual(adc.state()['inputVoltages'], {'10': 0, '11': 3.3})
        self.assertEqual(adc.state()['channelValues'], {'10': 0, '11': 4095, '12': None})
        self.assertEqual(self.sim.errors, [])
        adc.reset()
        self.assertEqual(adc.current_voltage, 3.3)
        self.assertIsNone(adc.state()['currentValue'])
        self.sim.board['id'] = 'cimc-v1'
        with self.assertRaises(ValueError):
            adc.set_voltage(1, channel=11)
        adc.write(ADC_BASE + 0x34, 11)
        adc.write(ADC_BASE + 8, 1 | SWRCST)
        self.assertTrue(self.sim.errors)

    def test_adc_removed_wire_waits_for_reconnection_and_swapped_sources_follow_nets(self):
        adc = AdcDevice(self.sim)
        adc.set_voltage(0, 10)
        adc.set_voltage(3.3, 11)
        self.sim.wires.remove(('PC0', 'ADC_IN0'))
        adc.write(ADC_BASE + 0x34, 10)
        adc.write(ADC_BASE + 8, 1 | SWRCST)
        self.assertFalse(adc.read(ADC_BASE) & 2)
        self.assertEqual(adc.sample_count, 0)
        self.assertFalse(adc.state()['channelConnections']['10'])
        self.assertTrue(adc.state()['channelConnections']['11'])
        self.assertIn('悬空', self.sim.errors[-1])
        self.sim.wires.add(('PC0', 'ADC_IN0'))
        self.assertTrue(adc.read(ADC_BASE) & 2)
        self.assertEqual(adc.read(ADC_BASE + 0x4C), 0)
        self.assertEqual(adc.sample_count, 1)
        self.sim.wires.difference_update({('PC0', 'ADC_IN0'), ('PC1', 'ADC_IN1')})
        self.sim.wires.update({('PC0', 'ADC_IN1'), ('PC1', 'ADC_IN0')})
        for channel, expected in ((10, 4095), (11, 0)):
            adc.write(ADC_BASE + 0x34, channel)
            adc.write(ADC_BASE + 8, 1 | SWRCST)
            self.assertEqual(adc.read(ADC_BASE + 0x4C), expected)
        self.sim.wires.add(('PC0', 'ADC_IN0'))
        before = adc.sample_count
        adc.write(ADC_BASE + 0x34, 10)
        adc.write(ADC_BASE + 8, 1 | SWRCST)
        self.assertEqual(adc.sample_count, before)
        self.assertFalse(adc.state()['channelConnections']['10'])


    def test_schematic_vr1_net_is_fixed_and_pc2_reference_requires_h7_jumper(self):
        self.sim.wires.remove(('PC0', 'ADC_IN0'))
        self.sim.wires.add(('PC0', 'ADC_IN10'))
        self.sim.wires.add(('PC2', 'ADC_IN12'))
        self.sim.gpio_state['PC']['mode'] |= 3 << 4
        adc = AdcDevice(self.sim)
        adc.set_voltage(.825)
        adc.write(ADC_BASE + 0x34, 10)
        adc.write(ADC_BASE + 8, 1 | SWRCST)
        self.assertEqual(adc.read(ADC_BASE + 0x4C), 1024)
        adc.write(ADC_BASE + 0x34, 12)
        adc.write(ADC_BASE + 8, 1 | SWRCST)
        self.assertFalse(adc.read(ADC_BASE) & 2)
        self.assertFalse(adc.state()['channelConnections']['12'])
        self.sim.wires.add(('ADC_IN12', '3V3_REF'))
        self.assertTrue(adc.read(ADC_BASE) & 2)
        self.assertEqual(adc.read(ADC_BASE + 0x4C), 4095)
        self.sim.wires.remove(('ADC_IN12', '3V3_REF'))
        adc.write(ADC_BASE + 8, 1 | SWRCST)
        self.assertFalse(adc.read(ADC_BASE) & 2)

if __name__ == '__main__':
    unittest.main()
