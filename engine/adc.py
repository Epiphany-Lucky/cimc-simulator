"""GD32F470 ADC routine single-conversion subset for V1's fixed VR1 -> PC0.

Sources: GD32F4xx User Manual Rev3.4, pp293-302; V1 schematic pp1-2.
Conversions and calibration complete immediately (functional, not cycle timed).
Continuous/scan, watchdog, DMA, interrupts and external triggers are explicit errors.
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

    def notify_rcu_write(self, address, value):
        if address == RCU_APB2RST and value & (1 << 8):
            self.reset()

    def set_voltage(self, voltage):
        if isinstance(voltage, bool) or not isinstance(voltage, (int, float)):
            raise ValueError('ADC 电压必须是 0–3.3 V 的数字')
        if not math.isfinite(voltage) or not 0 <= voltage <= self.reference_voltage:
            raise ValueError('ADC 电压必须在 0–3.3 V 范围内')
        self.voltage = float(voltage)

    def state(self):
        return {'voltage': self.voltage, 'referenceVoltage': self.reference_voltage,
                'value': self.last_value, 'bits': self.bits, 'channel': 10, 'pin': 'PC0',
                'sampleCount': self.sample_count, 'peripheral': self.last_adc,
                'idealValue': self._quantize(12)}

    def _quantize(self, bits):
        return min((1 << bits)-1, int(self.voltage / self.reference_voltage * ((1 << bits)-1) + .5))

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
            if value & ~(ADCON | 0xC | (1 << 10) | (1 << 11) | (15 << 24) | SWRCST):
                return self._fault('仅支持软件触发单次转换；连续、DMA、外部触发尚未实现')
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
        if self.sim.gpio_state['PC']['mode'] & 3 != 3:
            return self._fault('PC0 必须配置为模拟输入，原板 VR1 固定连接不变')
        if (r.get(0x2C, 0) >> 20) & 15:
            return self._fault('仅支持长度为 1 的常规转换序列')
        if r.get(0x34, 0) & 31 != 10:
            return self._fault('本版旋钮固定为 PC0 / ADC 通道 10，不支持改到其他通道')
        bits = 12 - 2*((r.get(4, 0) >> 24) & 3)
        self.sample_count += 1
        if r.get(0, 0) & EOC and r.get(8, 0) & (1 << 10):
            # Per manual: when overflow detection is enabled, the new result is lost.
            r[0] |= ROVF | STRC
            return
        raw = self._quantize(bits)
        r[0x4C] = raw << (16-bits) if r.get(8, 0) & (1 << 11) else raw
        r[0] = r.get(0, 0) | EOC | STRC
        self.last_value, self.bits, self.last_adc = raw, bits, f'ADC{index}'
