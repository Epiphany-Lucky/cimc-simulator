"""GD32F470 software single-conversion ADC for board-profile analog inputs.

Sources: GD32F4xx User Manual Rev3.4, pp293-302; V1 schematic pp1-2.
Conversions and calibration complete immediately (functional, not cycle timed).
V2 uses the schematic's VR1/ADC_IN10 -> PC0 and H7/ADC_IN12 -> PC2.
PC1/channel 11 is an editable external input from the supplied driver. Software
starts and timer-selected trigger edges drive conversions. Continuous, scan,
analog-watchdog, DMA and ADC interrupt modes require separate modeling.
"""
import math

ADC_BASE = 0x40012000
RCU_AHB1EN = 0x40023830
RCU_APB2EN = 0x40023844
RCU_APB2RST = 0x40023824
EOC = 1 << 1
STRC = 1 << 4
ROVF = 1 << 5
ADCON = 1
SWRCST = 1 << 30


class AdcDevice:
    def __init__(self, sim):
        self.sim = sim
        self.voltage = 1.65
        self.current_voltage = 1.65
        self.reference_voltage = 3.3
        self.reset()

    @staticmethod
    def contains(address):
        return ADC_BASE <= address < ADC_BASE + 0x400

    def reset(self):
        self.registers = [{0x24: 0xFFF} for _ in range(3)]
        self.common = 0
        self.last_value = None
        self.bits = 12
        self.sample_count = 0
        self.last_adc = None
        self.last_channel = 10
        self.channel_values = {10: None, 11: None, 12: None}
        self.channel_bits = {10: 12, 11: 12, 12: 12}
        self.pending_conversions = set()
        self.wiring_warnings = set()

    def notify_rcu_write(self, address, value):
        if address == RCU_APB2RST and value & (1 << 8):
            self.reset()

    def is_v2(self):
        return getattr(self.sim, 'board', {}).get('id') == 'cimc-v2'

    def set_voltage(self, voltage, channel=10):
        if isinstance(channel, bool) or channel not in (10, 11):
            raise ValueError('ADC 输入只允许通道 10 或 11')
        if channel == 11 and not self.is_v2():
            raise ValueError('PC1 / ADC 通道 11 只在 V2 配置中可用')
        if isinstance(voltage, bool) or not isinstance(voltage, (int, float)):
            raise ValueError('ADC 电压必须是 0–3.3 V 的数字')
        if not math.isfinite(voltage) or not 0 <= voltage <= self.reference_voltage:
            raise ValueError('ADC 电压必须在 0–3.3 V 范围内')
        if channel == 10:
            self.voltage = float(voltage)
        else:
            self.current_voltage = float(voltage)

    def state(self):
        return {'voltage': self.voltage, 'referenceVoltage': self.reference_voltage,
                'value': self.last_value, 'bits': self.bits, 'channel': self.last_channel,
                'pin': f'PC{self.last_channel - 10}',
                'sampleCount': self.sample_count, 'peripheral': self.last_adc,
                'idealValue': self._quantize(12),
                'currentVoltage': self.current_voltage if self.is_v2() else None,
                'currentValue': self.channel_values[11] if self.is_v2() else None,
                'inputVoltages': {'10': self.voltage, **({'11': self.current_voltage} if self.is_v2() else {})},
                'channelValues': {str(channel): value for channel, value in self.channel_values.items()
                                  if channel == 10 or self.is_v2()},
                'channelBits': {str(channel): bits for channel, bits in self.channel_bits.items()
                                if channel == 10 or self.is_v2()},
                'channelConnections': {str(channel): self._input_voltage(channel) is not None
                                       for channel in (10, 11, 12)} if self.is_v2() else {'10': True}}

    def _input_voltage(self, channel):
        if not self.is_v2():
            return self.voltage
        nets = self.sim.connected(f'PC{channel - 10}')
        sources = []
        if nets & {'ADC_IN0', 'ADC_IN10'}:
            sources.append(self.voltage)
        if 'ADC_IN1' in nets:
            sources.append(self.current_voltage)
        grounded = bool(nets & {'GND', 'DGND', 'AGND', '0V'})
        powered = bool(nets & {'3V3', '3.3V', 'VCC', '3.3VREF', '3V3_REF'})
        if len(sources) == 1 and not grounded and not powered:
            return sources[0]
        if not sources and grounded != powered:
            return self.reference_voltage if powered else 0.0
        return None

    def _quantize(self, bits, channel=10):
        voltage = self._input_voltage(channel)
        if voltage is None:
            return None
        return min((1 << bits)-1, int(voltage / self.reference_voltage * ((1 << bits)-1) + .5))

    def _fault(self, message):
        self.sim.diagnose('ADC：' + message)
        return 0

    def _clocked(self, index):
        return bool(self.sim.regs.get(RCU_APB2EN, 0) & (1 << (8 + index))) and not self.sim.regs.get(RCU_APB2RST, 0) & (1 << 8)

    def read(self, address):
        offset = address - ADC_BASE
        if offset == 0x300:
            return sum((r.get(0, 0) & 0x33) << (i*8) for i, r in enumerate(self.registers))
        if offset == 0x304:
            return self.common
        if offset == 0x308:
            return self._fault('多 ADC 同步数据尚未实现')
        index, off = divmod(offset, 0x100)
        if index >= 3 or off not in set(range(0, 0x50, 4)) | {0x80}:
            return self._fault(f'未实现的寄存器读取 0x{address:08X}')
        if not self._clocked(index):
            return 0
        r = self.registers[index]
        if index in self.pending_conversions:
            self._convert(index)
        result = r.get(off, 0)
        if off == 0x4C:
            r[0] = r.get(0, 0) & ~EOC
        return result

    def write(self, address, value, size=4, byte_offset=0):
        if size != 4 or byte_offset:
            return self._fault('寄存器要求 32 位对齐访问')
        value &= 0xFFFFFFFF
        offset = address - ADC_BASE
        if offset == 0x304:
            # Independent mode only. Prescaler field is retained; no clock-time model.
            if value & ~0x70000:
                return self._fault('同步、多 ADC、内部参考或同步 DMA 模式尚未实现')
            self.common = value
            return
        index, off = divmod(offset, 0x100)
        if index >= 3 or off not in set(range(0, 0x50, 4)) | {0x80}:
            return self._fault(f'未实现的寄存器写入 0x{address:08X}')
        if not self._clocked(index):
            if off == 8 and value & SWRCST:
                return self._fault(f'ADC{index} 时钟未开启或仍处于复位，不能转换')
            return  # Disabled peripheral clock: writes do not change its registers.
        r = self.registers[index]
        if off == 0:
            r[0] = r.get(0, 0) & value & 0x33  # rc_w0 flags cannot be set by software.
        elif off == 4:
            if value & ~0x0300001F:
                return self._fault('扫描、间断、模拟看门狗或 ADC 中断尚未实现')
            r[off] = value
        elif off == 8:
            # Firmware can select a timer edge or explicitly start with SWRCST.
            trigger_edges = 3 << 28
            if value & ~(ADCON | 0xC | (1 << 10) | (1 << 11) | (15 << 24) | trigger_edges | SWRCST):
                return self._fault('ADC 支持软件或定时器触发的单次转换，请检查连续转换、DMA及其他触发配置')
            r[off] = value & ~(0xC | SWRCST)  # Immediate functional calibration / start.
            if value & SWRCST:
                self._convert(index)
        elif off in (0x0C, 0x10, 0x24, 0x28, 0x2C, 0x30, 0x34):
            r[off] = value
        elif off == 0x4C:
            return  # Read-only routine conversion data.
        elif value:
            return self._fault('插入转换或过采样模式尚未实现')

    def _convert(self, index):
        r = self.registers[index]
        if not r.get(8, 0) & ADCON:
            return self._fault(f'ADC{index} 未开启 ADCON，不能转换')
        if not self.sim.regs.get(RCU_AHB1EN, 0) & (1 << 2):
            return self._fault('GPIOC 时钟未开启')
        if (r.get(0x2C, 0) >> 20) & 15:
            return self._fault('仅支持长度为 1 的常规转换序列')
        channel = r.get(0x34, 0) & 31
        if channel != 10 and not (self.is_v2() and channel in (11, 12)):
            return self._fault('本版旋钮固定为 PC0 / ADC 通道 10，不支持改到其他通道')
        pin = channel - 10
        if (self.sim.gpio_state['PC']['mode'] >> (2 * pin)) & 3 != 3:
            return self._fault(f'PC{pin} 必须配置为模拟输入')
        bits = 12 - 2*((r.get(4, 0) >> 24) & 3)
        raw = self._quantize(bits, channel)
        if raw is None:
            self.pending_conversions.add(index)
            if channel not in self.wiring_warnings:
                self.sim.diagnose(f'ADC：PC{pin} 模拟输入悬空或多个源短接，请检查模拟输入端与跳线', 'warning')
                self.wiring_warnings.add(channel)
            return
        self.pending_conversions.discard(index)
        self.wiring_warnings.discard(channel)
        self.sample_count += 1
        if r.get(0, 0) & EOC and r.get(8, 0) & (1 << 10):
            # Per manual: when overflow detection is enabled, the new result is lost.
            r[0] |= ROVF | STRC
            return
        r[0x4C] = raw << (16-bits) if r.get(8, 0) & (1 << 11) else raw
        r[0] = r.get(0, 0) | EOC | STRC
        self.last_value, self.bits, self.last_adc = raw, bits, f'ADC{index}'
        self.last_channel = channel
        self.channel_values[channel] = raw
        self.channel_bits[channel] = bits

    def timer_trigger(self,timer,event,level=True):
        sources=((0,'ch0'),(0,'ch1'),(0,'ch2'),(1,'ch1'),(1,'ch2'),(1,'ch3'),
                 (1,'trgo'),(2,'ch0'),(2,'trgo'),(3,'ch3'),(4,'ch0'),(4,'ch1'),
                 (4,'ch2'),(7,'ch0'),(7,'trgo'))
        for index,registers in enumerate(self.registers):
            control=registers.get(8,0)
            edges=(control>>28)&3
            selection=(control>>24)&15
            edge=1 if level else 2
            if (control&ADCON and self._clocked(index) and edges&edge and
                    selection<len(sources) and sources[selection]==(timer,event)):
                self._convert(index)
