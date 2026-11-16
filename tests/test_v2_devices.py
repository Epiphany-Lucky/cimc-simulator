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
        self.wires = {('PC0', 'ADC_IN0'), ('PC1', 'ADC_IN1'), ('PA4', 'DAC_OUT0'),
                      ('PA5', 'PT100_SCK'), ('PA6', 'PT100_MISO'),
                      ('PA7', 'PT100_MOSI'), ('PB10', 'PT100_CS')}

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

    def net_level(self, terminal):
        levels = set()
        for pin in self.connected(terminal):
            if pin[:2] in self.gpio_state and pin[2:].isdigit():
                gpio = self.gpio_state[pin[:2]]
                number = int(pin[2:])
                if (gpio['mode'] >> (number * 2)) & 3 == 1:
                    levels.add((gpio['out'] >> number) & 1)
        return next(iter(levels)) if len(levels) == 1 else None


class V2AnalogTests(unittest.TestCase):
    def setUp(self):
        self.sim = AnalogBoard()
        self.devices = V2Devices(self.sim)
        self.devices.write(SPI0, 0x37D)

    def select(self, active):
        self.sim.gpio_state['PB']['out'] = 0 if active else 1 << 10
        self.devices.on_gpio_changed('PB')

    def byte(self, value):
        self.devices.write(SPI0 + 12, value)
        self.assertEqual(self.devices.read(SPI0 + 8) & 3, 3)
        result = self.devices.read(SPI0 + 12)
        self.assertEqual(self.devices.read(SPI0 + 8) & 1, 0)
        return result

    def transaction(self, values):
        self.select(True)
        result = [self.byte(value) for value in values]
        self.select(False)
        return result

    def test_spi_conversion_pipeline_config_readback_and_real_quantization(self):
        self.assertEqual(self.transaction([0x40, 0x4B]), [0, 0])
        self.assertEqual(self.devices.sample_count, 1)
        for temperature in (-50, 25, 150):
            with self.subTest(temperature=temperature):
                self.devices.set_temperature(temperature)
                high, low, cfg_high, cfg_low = self.transaction([0x40, 0x4B, 0, 0])
                raw = (high << 8) | low
                expected_resistance = 100 + .385 * temperature
                expected = int(expected_resistance * 22200 / 2200 * 32768 / 6144 + .5)
                self.assertEqual(raw, expected)
                self.assertEqual((cfg_high << 8) | cfg_low, 0x404B)
                decoded = ((raw * 6144 / 32768 * 2200 / 22200) - 100) / .385
                self.assertAlmostEqual(decoded, temperature, delta=.05)
        self.assertEqual(self.devices.sample_count, 4)
        self.assertEqual(self.sim.errors, [])

    def test_pt100_input_validation_preserves_previous_value(self):
        for value in (-51, 151, float('nan'), float('inf'), '20', True, None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.devices.set_temperature(value)
                self.assertEqual(self.devices.temperature, 25)

    def test_spi_requires_clock_pin_modes_af_and_explicit_unsupported_modes(self):
        for kind in ('clock', 'gpio_clock', 'pin_mode', 'pin_af', 'chip_select', 'phase', '16bit', 'dma'):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == 'clock':
                    self.sim.regs[RCU_APB2EN] = 0
                elif kind == 'gpio_clock':
                    self.sim.regs[RCU_AHB1EN] = 0
                elif kind == 'pin_mode':
                    self.sim.gpio_state['PA']['mode'] &= ~(3 << 10)
                elif kind == 'pin_af':
                    self.sim.regs[GPIOA + 32] = 0
                elif kind == 'chip_select':
                    self.sim.gpio_state['PB']['mode'] = 0
                elif kind == 'phase':
                    self.devices.write(SPI0, 0x37C)
                elif kind == '16bit':
                    self.devices.write(SPI0, 0x37D | (1 << 11))
                else:
                    self.devices.write(SPI0 + 4, 1)
                self.select(True)
                self.devices.write(SPI0 + 12, 0x40)
                self.assertTrue(self.sim.errors)
                self.assertEqual(self.devices.sample_count, 0)

    def test_incomplete_frame_invalid_input_and_nop_config(self):
        self.transaction([0x40])
        self.assertIn('16 或 32', self.sim.errors[-1])
        self.setUp()
        self.transaction([0x30, 0x4B])
        self.assertIn('AIN0', self.sim.errors[-1])
        self.assertEqual(self.devices.config, 0x058B)
        self.setUp()
        self.transaction([0, 0])
        self.assertEqual(self.devices.config, 0x058B)
        self.assertEqual(self.devices.sample_count, 0)

    def test_spi_overrun_sequence_reset_and_external_adc_lifetime(self):
        self.select(True)
        self.devices.write(SPI0 + 12, 0x40)
        self.devices.write(SPI0 + 12, 0x4B)
        self.assertEqual(self.devices.read(SPI0 + 8) & 64, 64)
        self.devices.read(SPI0 + 12)
        self.devices.read(SPI0 + 8)
        self.assertEqual(self.devices.read(SPI0 + 8) & 64, 0)
        self.select(False)
        old_raw = self.devices.raw
        self.devices.notify_rcu_write(RCU_APB2RST, 1 << 12)
        self.assertEqual(self.devices.spi[0], 0)
        self.assertEqual(self.devices.raw, old_raw)
        self.devices.reset()
        self.assertEqual(self.devices.raw, 0)
        self.assertEqual(self.devices.config, 0x058B)

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

    def test_dac_requires_clock_analog_pin_and_rejects_other_modes(self):
        for kind in ('clock', 'gpio_clock', 'mode', 'dma', 'trigger', 'channel'):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == 'clock':
                    self.sim.regs[RCU_APB1EN] = 0
                elif kind == 'gpio_clock':
                    self.sim.regs[RCU_AHB1EN] = 0
                elif kind == 'mode':
                    self.sim.gpio_state['PA']['mode'] = 0
                self.devices.write(DAC0, {'dma': 4097, 'trigger': 5, 'channel': 1 << 16}.get(kind, 1))
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
        with self.assertRaises(ValueError):
            self.devices.set_temperature(30)

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

    def test_dac_observation_requires_its_editable_output_wire(self):
        self.devices.write(DAC0, 1)
        self.devices.write(DAC0 + 8, 4095)
        self.assertEqual(self.devices.state()['dac']['voltage'], 3.3)
        self.sim.wires.remove(('PA4', 'DAC_OUT0'))
        self.assertIsNone(self.devices.state()['dac']['voltage'])
        self.assertFalse(self.devices.state()['dac']['connected'])
        self.devices.write(DAC0 + 8, 2048)
        self.assertEqual(self.devices.read(DAC0 + 0x2C), 2048)
        self.sim.wires.add(('PA4', 'DAC_OUT0'))
        self.assertAlmostEqual(self.devices.state()['dac']['voltage'], 2048 * 3.3 / 4095)

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

    def test_pt100_each_removed_spi_wire_blocks_sampling_and_reconnects(self):
        for wire in (('PA5', 'PT100_SCK'), ('PA6', 'PT100_MISO'),
                     ('PA7', 'PT100_MOSI'), ('PB10', 'PT100_CS')):
            with self.subTest(wire=wire):
                self.setUp()
                self.sim.wires.remove(wire)
                self.assertEqual(self.transaction([0x40, 0x4B]), [255, 255])
                self.assertEqual(self.devices.sample_count, 0)
                self.assertFalse(self.devices.state()['pt100']['connected'])
                self.assertIn('跳线', self.sim.errors[-1])
                self.sim.wires.add(wire)
                self.assertEqual(self.transaction([0x40, 0x4B]), [0, 0])
                self.assertEqual(self.devices.sample_count, 1)
                self.assertTrue(self.devices.state()['pt100']['connected'])

    def test_pt100_unplug_mid_frame_discards_partial_command(self):
        self.select(True)
        self.assertEqual(self.byte(0x40), 0)
        self.sim.wires.remove(('PA7', 'PT100_MOSI'))
        self.assertEqual(self.byte(0x4B), 255)
        self.select(False)
        self.assertEqual(self.devices.sample_count, 0)
        self.assertEqual(self.devices.config, 0x058B)
        self.sim.wires.add(('PA7', 'PT100_MOSI'))
        self.assertEqual(self.transaction([0x40, 0x4B]), [0, 0])
        self.assertEqual(self.devices.sample_count, 1)

    def test_pt100_short_to_another_output_blocks_external_sampling(self):
        self.sim.wires.add(('PT100_SCK', 'PB2'))
        self.sim.gpio_state['PB']['mode'] |= 1 << 4
        self.assertEqual(self.transaction([0x40, 0x4B]), [255, 255])
        self.assertEqual(self.devices.sample_count, 0)
        self.sim.wires.remove(('PT100_SCK', 'PB2'))
        self.assertEqual(self.transaction([0x40, 0x4B]), [0, 0])
        self.assertEqual(self.devices.sample_count, 1)


if __name__ == '__main__':
    unittest.main()
