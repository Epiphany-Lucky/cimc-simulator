"""GD32F470 TIMER0..13 functional register, signal and interrupt model.

Register layouts and connections follow GD32F4xx User Manual Rev3.5, chapter18.
Time is supplied as HCLK ticks by the CPU scheduler. GPIO signals and interrupt
flags are consequences of the register model and executed firmware.
"""
from collections import deque
from math import lcm

TIMER_BASES = (0x40010000, 0x40000000, 0x40000400, 0x40000800,
               0x40000C00, 0x40001000, 0x40001400, 0x40010400,
               0x40014000, 0x40014400, 0x40014800, 0x40001800,
               0x40001C00, 0x40002000)
TIMER_CHANNELS = (4, 4, 4, 4, 4, 0, 0, 4, 2, 1, 1, 2, 1, 1)
TIMER_IRQS = (25, 28, 29, 30, 50, 54, 55, 44, 24, 25, 26, 43, 44, 45)
TRIGGER_SOURCES = {0: (4, 1, 2, 3), 7: (0, 1, 3, 4),
                   1: (0, 7, 2, 3), 2: (0, 1, 4, 3),
                   3: (0, 1, 2, 7), 4: (1, 2, 3, 7),
                   8: (1, 2, 9, 10), 11: (3, 4, 12, 13)}
GPIO_BASE = {f'P{chr(65+i)}': 0x40020000+i*0x400 for i in range(9)}
FILTER_CLOCKS = ((1, 1), (1, 2), (1, 4), (1, 8), (2, 6), (2, 8),
                 (4, 6), (4, 8), (8, 6), (8, 8), (16, 5), (16, 6),
                 (16, 8), (32, 5), (32, 6), (32, 8))

# (timer, channel, complementary, AF), channel -1 is ETI, -2 is BRKIN.
PIN_FUNCTIONS = {}


def _pins(timer, af, channels):
    for channel, names in channels.items():
        complementary = isinstance(channel, str) and channel.endswith('n')
        number = int(channel[:-1]) if complementary else int(channel)
        for pin in names.split():
            PIN_FUNCTIONS.setdefault(pin, []).append((timer, number, complementary, af))


_pins(0, 1, {0: 'PA8 PE9', 1: 'PA9 PE11', 2: 'PA10 PE13', 3: 'PA11 PE14',
             '0n': 'PA7 PB13 PE8', '1n': 'PB0 PB14 PE1 PE10', '2n': 'PB1 PB15 PE12',
             -1: 'PA12 PE7', -2: 'PA6 PB12 PE15'})
_pins(1, 1, {0: 'PA0 PA5 PA15 PB8', 1: 'PA1 PB3 PB9', 2: 'PA2 PB10',
             3: 'PA3 PB2 PB11', -1: 'PA0 PA5 PA15 PB8'})
_pins(2, 2, {0: 'PA6 PB4 PC6', 1: 'PA7 PB5 PC7', 2: 'PB0 PC8', 3: 'PB1 PC9', -1: 'PD2'})
_pins(3, 2, {0: 'PB6 PD12', 1: 'PB7 PD13', 2: 'PB8 PD14', 3: 'PB9 PD15', -1: 'PE0'})
_pins(4, 2, {0: 'PA0 PH10', 1: 'PA1 PH11', 2: 'PA2 PH12', 3: 'PA3 PI0'})
_pins(7, 3, {0: 'PC6 PI5', 1: 'PC7 PI6', 2: 'PC8 PI7', 3: 'PC9 PI2',
             '0n': 'PA5 PA7 PH13', '1n': 'PB0 PB14 PH14', '2n': 'PB1 PB15 PH15',
             -1: 'PA0 PI3', -2: 'PA6 PI4'})
_pins(8, 3, {0: 'PA2 PE5', 1: 'PA3 PE6'})
_pins(9, 3, {0: 'PB8 PF6'})
_pins(10, 3, {0: 'PB9 PF7'})
_pins(11, 9, {0: 'PB14 PH6', 1: 'PB15 PH9'})
_pins(12, 9, {0: 'PA6 PF8'})
_pins(13, 9, {0: 'PA7 PF9'})


class Timer:
    def __init__(self, bank, index):
        self.bank, self.index = bank, index
        self.base = TIMER_BASES[index]
        self.channels = TIMER_CHANNELS[index]
        self.mask = 0xFFFFFFFF if index in (1, 4) else 0xFFFF
        self.advanced = index in (0, 7)
        self.level0 = index in (1, 2, 3, 4)
        self.level1 = index in (8, 11)
        self.basic = index in (5, 6)
        self.apb2 = index in (0, 7, 8, 9, 10)
        self.clock_bit = ({0: 0, 7: 1, 8: 16, 9: 17, 10: 18} if self.apb2
                          else {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 11: 6, 12: 7, 13: 8})[index]
        self.reset()

    def reset(self):
        offsets = {0, 4, 12, 16, 20, 36, 40, 44}
        if not self.basic:
            offsets |= {24, 32, 0xFC}
            offsets |= {0x34+4*i for i in range(self.channels)}
        if self.advanced or self.level0:
            offsets |= {8, 28, 0x48, 0x4C}
        if self.level1:
            offsets.add(8)
        if self.advanced:
            offsets |= {0x30, 0x44}
        if self.index in (1, 4, 10):
            offsets.add(0x50)
        self.registers = dict.fromkeys(offsets, 0)
        self.registers[44] = self.mask
        self.counter = 0
        self.psc_active = 0
        self.car_active = self.mask
        self.compare_active = [0]*self.channels
        self.controls_active = [0]*self.channels
        self.enable_active = 0
        self.lock_written = False
        self.prescaler_phase = 0
        self.clock_fraction = 0
        self.clock_denominator = 1
        self.raw_ticks = 0
        self.down = False
        self.repetition = 0
        self.reference = [False]*self.channels
        self.reference_changed = [0]*self.channels
        self.capture_dividers = [0]*self.channels
        self.input_levels = [None]*max(2, self.channels)
        self.filter_raw = [None]*max(2, self.channels)
        self.filter_since = [0]*max(2, self.channels)
        self.external_raw = self.external_level = None
        self.external_since = 0
        self.external_divider = 0
        self.trigger_level = False
        self.break_active = False
        self.status_read = 0
        self.dma_position = 0
        self.update_count = 0
        self.capture_counts = [0]*self.channels
        self.dma_requests = 0
        self.transition_count = [0]*self.channels
        self.high_ticks = [0]*self.channels

    def clocked(self):
        enable = 0x40023844 if self.apb2 else 0x40023840
        reset = 0x40023824 if self.apb2 else 0x40023820
        registers = self.bank.sim.regs
        bit = 1 << self.clock_bit
        return bool(registers.get(enable, 0) & bit) and not registers.get(reset, 0) & bit

    def fault(self, text):
        self.bank.sim.diagnose(f'TIMER{self.index}：{text}')
        return 0

    def channel_control(self, channel):
        return self.controls_active[channel]

    def counting(self):
        if not self.clocked() or not self.registers[0] & 1 or not self.car_active:
            return False
        slave = self.registers.get(8, 0) & 7
        return slave != 5 or self.trigger_level

    def internal_clock(self):
        config = self.registers.get(8, 0)
        return not config & (1 << 14) and (config & 7) not in (1, 2, 3, 7)

    def raw_deadline(self):
        if self.frozen():
            return None
        deadlines = []
        batchable = self._can_batch_counter() and (self.registers[16] & 1 or self.registers[0] & 2)
        if self.counting() and self.internal_clock() and not batchable:
            distances = [self.boundary_distance()]
            for channel in range(self.channels):
                if self.channel_control(channel) & 3:
                    continue
                compare = self.compare_active[channel]
                distance = self.counter-compare if self.down else compare-self.counter
                if distance > 0 and compare <= self.car_active:
                    distances.append(distance)
            deadlines.append(min(distances)*(self.psc_active+1)-self.prescaler_phase)
        for channel in range(self.channels):
            if self.filter_raw[channel] is not None and self.filter_raw[channel] != self.input_levels[channel]:
                deadlines.append(self.filter_delay(channel)-(self.raw_ticks-self.filter_since[channel]))
            deadtime = self.deadtime()
            if self.advanced and deadtime and self.raw_ticks-self.reference_changed[channel] < deadtime:
                deadlines.append(deadtime-(self.raw_ticks-self.reference_changed[channel]))
        if self.external_raw is not None and self.external_raw != self.external_level:
            deadlines.append(self.external_delay()-(self.raw_ticks-self.external_since))
        return max(1, min(deadlines)) if deadlines else None

    def boundary_distance(self):
        if self.registers[0] & 0x60:
            return max(1, self.counter if self.down else self.car_active-self.counter)
        if self.down:
            return self.counter+1
        top = self.car_active if self.counter <= self.car_active else self.mask
        return top-self.counter+1

    def advance_raw(self, ticks):
        if not self.clocked() or self.frozen():
            return
        self.raw_ticks += ticks
        for channel, reference in enumerate(self.reference):
            if reference:
                self.high_ticks[channel] += ticks
        if not self.counting() or not self.internal_clock():
            return
        steps, self.prescaler_phase = divmod(self.prescaler_phase+ticks, self.psc_active+1)
        self._advance_counter(steps)

    def _advance_counter(self, steps):
        if self._can_batch_counter():
            wraps, self.counter = divmod(self.counter+steps, self.car_active+1)
            if wraps and not self.registers[0] & 2:
                self.registers[16] |= 1
                self.update_count += wraps
            return
        while steps and self.counting():
            distance = self.boundary_distance()
            advance = min(steps, distance)
            previous = self.counter
            was_down = self.down
            self.counter += -advance if self.down else advance
            boundary = advance == distance
            if boundary:
                if self.registers[0] & 0x60:
                    self.counter = 0 if was_down else self.car_active
                    self.down = not was_down
                else:
                    self.counter = self.car_active if was_down else 0
                self._update('overflow')
            for channel in range(self.channels):
                if self.channel_control(channel) & 3:
                    continue
                compare = self.compare_active[channel]
                crossed = self.counter <= compare < previous if was_down else previous < compare <= self.counter
                if boundary and not self.registers[0] & 0x60:
                    crossed = crossed or compare == self.counter or compare > self.car_active
                if crossed:
                    self._compare(channel, was_down)
            self._refresh_references()
            steps -= advance

    def _can_batch_counter(self):
        # Basic timers have no channel edges. Once their level interrupt flag is
        # already set, unchanged periods can coalesce without losing observable
        # edges, shadow transfers, DMA requests, TRGO pulses or single-pulse stops.
        return (self.basic and not self.registers[0] & 8 and
                not self.registers[12] & 0x100 and self.registers[4] >> 4 & 7 in (0, 1) and
                self.psc_active == self.registers[40] and self.car_active == self.registers[44])

    def _transfer(self):
        self.psc_active = self.registers[40]
        self.car_active = self.registers[44]
        for channel in range(self.channels):
            if not self.channel_control(channel) & 3:
                self.compare_active[channel] = self.registers[0x34+4*channel]
        self.prescaler_phase = 0

    def _update(self, source):
        if source == 'overflow' and self.advanced and self.repetition:
            self.repetition -= 1
            return
        if self.registers[0] & 2:
            return
        self._transfer()
        self.repetition = self.registers.get(0x30, 0)
        self.update_count += 1
        if source == 'overflow' or not self.registers[0] & 4:
            self._event(0)
            if self.registers.get(4, 0) & 8:
                for channel in range(self.channels):
                    if self.registers[12] & (1 << (channel+9)):
                        self._dma_request(channel+1)
        if self.registers.get(4, 0) >> 4 & 7 == 2:
            self.bank.pulse(self.index)
        if self.advanced and not self.break_active and self.registers[0x44] & (1 << 14):
            self.registers[0x44] |= 1 << 15
        if self.registers[0] & 8:
            self.registers[0] &= ~1
            self._refresh_master()

    def _event(self, bit):
        self.registers[16] |= 1 << bit
        if 1 <= bit <= self.channels:
            callback = getattr(self.bank.sim, 'timer_trigger', None)
            if callback:
                callback(self.index, f'ch{bit-1}', True)
                callback(self.index, f'ch{bit-1}', False)
        enable = self.registers[12]
        update_dma = 1 <= bit <= self.channels and self.registers.get(4, 0) & 8
        if enable & (1 << (bit+8)) and not update_dma:
            self._dma_request(bit)

    def _dma_request(self, bit):
        self.dma_requests += 1
        callback = getattr(self.bank.sim, 'timer_dma_request', None)
        if callback:
            callback(self.index, bit)
        else:
            self.fault('DMA请求已产生，DMA控制器尚未连接')

    def _compare(self, channel, down=None):
        center = (self.registers[0] >> 5) & 3
        qualified = not center or center == 3 or (center == 1 and down) or (center == 2 and not down)
        if qualified:
            self._event(channel+1)
        mode = (self.channel_control(channel) >> 4) & 7
        if mode in (1, 2, 3):
            self._set_reference(channel, not self.reference[channel] if mode == 3 else mode == 1)
        if channel == 0 and self.registers.get(4, 0) >> 4 & 7 == 3:
            self.bank.pulse(self.index)

    def _set_reference(self, channel, value):
        value = bool(value)
        if value != self.reference[channel]:
            self.reference[channel] = value
            self.reference_changed[channel] = self.raw_ticks
            self.transition_count[channel] += 1
            self._refresh_master()

    def _refresh_references(self):
        for channel in range(self.channels):
            control = self.channel_control(channel)
            if control & 3:
                continue
            if control & 128 and self.external_level is not None:
                external_active = bool(self.external_level) ^ bool(self.registers.get(8, 0) & (1 << 15))
                if external_active:
                    self._set_reference(channel, False)
                    continue
            mode = (control >> 4) & 7
            if mode in (4, 5):
                self._set_reference(channel, mode == 5)
            elif mode in (6, 7):
                compare = self.compare_active[channel]
                active = self.counter <= compare if self.down else self.counter < compare
                self._set_reference(channel, active if mode == 6 else not active)

    def _refresh_master(self):
        mode = (self.registers.get(4, 0) >> 4) & 7
        if mode == 1:
            self.bank.set_trigger(self.index, self.counting())
        elif 4 <= mode < 4+self.channels:
            self.bank.set_trigger(self.index, self.reference[mode-4])

    def trigger(self, level):
        rising = level and not self.trigger_level
        changed = bool(level) != self.trigger_level
        self.trigger_level = bool(level)
        if not self.clocked():
            return
        slave = self.registers.get(8, 0) & 7
        if changed and slave == 5:
            self._event(6)
        if not rising:
            self._refresh_master()
            return
        if slave != 5:
            self._event(6)
        if slave == 4:
            self.counter = 0
            self.prescaler_phase = 0
            self._update('trigger')
            if self.registers.get(4, 0) >> 4 & 7 == 0:
                self.bank.pulse(self.index)
        elif slave == 6:
            self.registers[0] |= 1
        elif slave == 7 and self.registers[0] & 1:
            self.external_clock()
        for channel in range(self.channels):
            if self.channel_control(channel) & 3 == 3:
                self.capture(channel)
        if self.advanced and self.registers.get(4, 0) & 4:
            self.commutate()
        self._refresh_references()
        self._refresh_master()

    def external_clock(self):
        if not self.counting():
            return
        self.prescaler_phase += 1
        if self.prescaler_phase < self.psc_active+1:
            return
        self.prescaler_phase = 0
        self._advance_counter(1)

    def capture(self, channel, force=False):
        if not self.clocked() or (not force and not self.enable_active & (1 << (4*channel))):
            return
        if not force:
            self.capture_dividers[channel] += 1
            divisor = 1 << ((self.channel_control(channel) >> 2) & 3)
            if self.capture_dividers[channel] % divisor:
                return
        flag = 1 << (channel+1)
        if self.registers[16] & flag:
            self.registers[16] |= 1 << (channel+9)
        self.registers[0x34+4*channel] = self.counter
        self.capture_counts[channel] += 1
        self._event(channel+1)
        if channel == 0 and self.registers.get(4, 0) >> 4 & 7 == 3:
            self.bank.pulse(self.index)

    def filter_delay(self, channel):
        control = self.channel_control(channel)
        code = control >> 4
        if code == 0:
            return 0
        division, samples = FILTER_CLOCKS[code]
        clock_division = 1 << ((self.registers[0] >> 8) & 3) if code >= 4 else 1
        return division*samples*clock_division

    def external_delay(self):
        code = self.registers.get(8, 0) >> 8 & 15
        if code == 0:
            return 0
        division, samples = FILTER_CLOCKS[code]
        return division*samples*(1 << ((self.registers[0] >> 8) & 3) if code >= 4 else 1)

    def input_edge(self, channel, level):
        previous = self.input_levels[channel]
        self.input_levels[channel] = level
        if previous is None or previous == level:
            return
        enabled = self.enable_active
        slave = self.registers.get(8, 0) & 7
        if slave in (1, 2, 3) and channel < 2 and self.registers[0] & 1:
            if slave == 3 or (slave == 1 and channel == 1) or (slave == 2 and channel == 0):
                first = bool(self.input_levels[0]) ^ bool(enabled & 2)
                second = bool(self.input_levels[1]) ^ bool(enabled & 32)
                up = first != second if channel == 0 else first == second
                self.down = not up
                self.external_clock()
        for capture in range(self.channels):
            control = self.channel_control(capture)
            selection = control & 3
            source = capture if selection == 1 else capture ^ 1
            if selection not in (1, 2) or source != channel:
                continue
            polarity = (enabled >> (4*capture+1)) & 1
            both = enabled & (1 << (4*capture+3))
            if both or level != polarity:
                self.capture(capture)
        trigger_select = self.registers.get(8, 0) >> 4 & 7
        if trigger_select == 4 and channel == 0:
            self.trigger(True)
            self.trigger(False)
        elif trigger_select in (5, 6) and channel == trigger_select-5:
            polarity = enabled >> (4*channel+1) & 1
            self.trigger(bool(level) ^ bool(polarity))

    def commutate(self):
        for channel in range(self.channels):
            self.controls_active[channel] = (self.registers.get(24+(channel//2)*4, 0) >> (8*(channel%2))) & 255
        self.enable_active = self.registers[32]
        for channel in range(self.channels):
            if not self.enable_active & (1 << (4*channel)):
                self.capture_dividers[channel] = 0
        self._event(5)
        self._refresh_references()

    def deadtime(self):
        value = self.registers.get(0x44, 0) & 255
        if value < 128:
            ticks = value
        elif value < 192:
            ticks = (64+(value & 63))*2
        elif value < 224:
            ticks = (32+(value & 31))*8
        else:
            ticks = (32+(value & 31))*16
        return ticks*(1 << ((self.registers[0] >> 8) & 3))

    def output(self, channel, complementary=False):
        if not self.clocked() or channel >= self.channels or self.channel_control(channel) & 3:
            return None
        enable = self.enable_active >> (4*channel)
        if complementary and (not self.advanced or channel == 3):
            return None
        protection = self.registers.get(0x44, 0)
        polarity = bool(enable & (8 if complementary else 2))
        enabled = bool(enable & (4 if complementary else 1))
        if not self.advanced and not enabled:
            return None
        if self.advanced and protection & (1 << 15) and not enabled:
            return int(polarity) if protection & (1 << 11) else None
        if self.advanced and not protection & (1 << 15):
            if self.registers.get(0xFC, 0) & 1 and not protection & (1 << 10):
                return None
            if not protection & (1 << 10) and not enable & 5:
                return None
            idle_shift = 8+2*channel+int(complementary)
            return (self.registers[4] >> idle_shift) & 1
        active = not self.reference[channel] if complementary and enable & 1 else self.reference[channel]
        if self.advanced and active and self.raw_ticks-self.reference_changed[channel] < self.deadtime():
            active = False
        return int(active ^ polarity)

    def frozen(self):
        if not getattr(self.bank.sim, 'core_halted', False):
            return False
        address = 0xE004200C if self.apb2 else 0xE0042008
        return bool(self.bank.sim.regs.get(address, 0) & (1 << self.clock_bit))

    def read(self, offset):
        if offset not in self.registers:
            return self.fault(f'未实现的寄存器读取 0x{self.base+offset:08X}')
        if not self.clocked():
            return 0
        if offset == 0:
            return (self.registers[0] & ~16) | (16 if self.down else 0)
        if offset == 20:
            return 0
        if offset == 36:
            return self.counter
        if offset == 16:
            self.status_read = self.registers[16]
        if offset == 0x4C:
            return self.read(self.dma_target())
        if 0x34 <= offset < 0x34+4*self.channels:
            channel = (offset-0x34)//4
            if self.channel_control(channel) & 3:
                self.registers[16] &= ~(1 << (channel+1))
                self.status_read &= ~(1 << (channel+1))
        return self.registers[offset]

    def dma_target(self):
        config = self.registers[0x48]
        target = 4*((config & 31)+self.dma_position)
        self.dma_position = (self.dma_position+1) % ((config >> 8 & 31)+1)
        if target == 0x4C or target not in self.registers:
            self.fault('DMA突发访问指向无效寄存器')
            return 20
        return target

    def write(self, offset, value, size=4, byte_offset=0):
        if offset not in self.registers:
            return self.fault(f'未实现的寄存器写入 0x{self.base+offset:08X}')
        if size != 4 or byte_offset:
            return self.fault('寄存器要求字对齐32位访问')
        if not self.clocked():
            return
        value &= 0xFFFFFFFF
        if offset == 0x4C:
            return self.write(self.dma_target(), value)
        if offset == 16:
            self.registers[16] &= value | (128 if self.break_active else 0)
            self.status_read &= value
            return
        if offset == 20:
            if value & 1:
                self.prescaler_phase = 0
                self._update('software')
                self.counter = self.car_active if self.down else 0
                if self.registers.get(4, 0) >> 4 & 7 == 0:
                    self.bank.pulse(self.index)
            for channel in range(self.channels):
                if value & (1 << (channel+1)):
                    if self.channel_control(channel) & 3:
                        self.capture(channel, force=True)
                    else:
                        self._compare(channel, self.down)
            if self.advanced and value & (1 << 5):
                self.commutate()
            if value & (1 << 6):
                self._event(6)
            if self.advanced and value & (1 << 7):
                self.registers[0x44] &= ~(1 << 15)
                self._event(7)
            self._refresh_references()
            self._refresh_master()
            return
        if offset in (36, 44) or 0x34 <= offset < 0x34+4*self.channels:
            value &= self.mask
        elif offset == 40:
            value &= 0xFFFF
        elif offset == 0x30:
            value &= 255
        elif offset in (24, 28, 32, 0x44, 0x48, 0x50):
            value &= 0xFFFF
        if offset == 0:
            allowed = 0x8F if self.basic else (0x3FF if self.advanced or self.level0 else 0x38F)
            if not (self.advanced or self.level0 or self.level1 or self.basic):
                allowed &= ~8
            value &= allowed
            if value & 0x300 == 0x300:
                return self.fault('CKDIV=3为保留配置')
            if self.registers[0] & 1 and bool(value & 0x60) != bool(self.registers[0] & 0x60):
                return self.fault('运行中切换边沿/中心对齐模式')
            if not value & 0x60 and self.registers.get(8, 0) & 7 not in (1, 2, 3):
                self.down = bool(value & 16)
        if offset == 4:
            allowed = 0x7FFD if self.advanced else (0xF8 if self.level0 else 0x70)
            value &= allowed
            if (value >> 4 & 7) >= 4+self.channels and not self.basic:
                return self.fault('主模式选择了不存在的通道')
            if self.basic and value >> 4 & 7 > 2:
                return self.fault('基本定时器只支持复位、使能、更新TRGO源')
        if offset == 8 and self.level1:
            value &= 0xF7
        if offset == 8 and not (self.advanced or self.level0) and value & 7 in (1, 2, 3):
            return self.fault('此定时器没有正交解码模式')
        if offset == 12:
            allowed = 0x7FFF if self.advanced else (0x5F5F if self.level0 else (0x101 if self.basic else (0x47 if self.level1 else 3)))
            value &= allowed
        if offset == 32:
            allowed = sum(3 << (4*channel) for channel in range(self.channels))
            allowed |= sum(8 << (4*channel) for channel in range(min(3, self.channels)))
            if self.advanced:
                allowed |= 0x444
            value &= allowed
        if offset == 0x50:
            mask = {1: 0xC00, 4: 0xC0, 10: 3}[self.index]
            value &= mask
            if self.index == 1 and value:
                return self.fault('Ethernet PTP和USB SOF触发源尚未连接')
            if self.index == 4 and value:
                return self.fault('IRC32K、LXTAL与RTC唤醒捕获源尚未连接')
            if self.index == 10 and value == 2:
                return self.fault('HXTAL_RTC分频捕获源尚未连接')
        if offset in (24, 28):
            first = 2 if offset == 28 else 0
            for channel in range(first, min(first+2, self.channels)):
                shift = (channel%2)*8
                previous = self.registers[offset] >> shift & 3
                if self.enable_active & (1 << (4*channel)):
                    value = (value & ~(3 << shift)) | (previous << shift)
                if self.channels == 1 and value & 3 > 1:
                    return self.fault('单通道定时器只支持CI0直接输入')
        if offset == 0x44:
            previous = self.registers[offset]
            lock = previous >> 8 & 3
            locked = 0
            if lock:
                locked |= 0x73FF
            if self.lock_written:
                locked |= 0x300
            if lock >= 2:
                locked |= 0x0C00
            value = (value & ~locked) | (previous & locked)
            self.lock_written = True
        if offset in (4, 24, 28, 32) and self.advanced:
            lock = self.registers[0x44] >> 8 & 3
            if lock:
                locked = 0x7F00 if offset == 4 else 0
                if lock >= 2 and offset == 32:
                    locked |= 0x2AAA
                if lock >= 3 and offset in (24, 28):
                    locked |= 0x7878
                value = (value & ~locked) | (self.registers[offset] & locked)
        if offset == 36:
            self.counter = value
        elif offset == 44 and not self.registers[0] & 128:
            self.car_active = value
        elif 0x34 <= offset < 0x34+4*self.channels:
            channel = (offset-0x34)//4
            if self.channel_control(channel) & 3:
                return
            if self.registers.get(0xFC, 0) & 2 and value == self.registers[offset]:
                return
            if not self.channel_control(channel) & 8:
                self.compare_active[channel] = value
        self.registers[offset] = value
        if offset == 0 and not value & 128:
            self.car_active = self.registers[44]
        if offset in (4, 24, 28):
            for channel in range(self.channels):
                control = (self.registers.get(24+(channel//2)*4, 0) >> (8*(channel%2))) & 255
                if self.advanced and self.registers[4] & 1 and not control & 3:
                    control = (control & ~0x70) | (self.controls_active[channel] & 0x70)
                self.controls_active[channel] = control
                if not control & 11:
                    self.compare_active[channel] = self.registers[0x34+4*channel]
        if offset in (4, 32):
            enable = self.registers.get(32, 0)
            if self.advanced and self.registers[4] & 1:
                enable = (enable & ~0x1555) | (self.enable_active & 0x1555)
            for channel in range(self.channels):
                if not enable & (1 << (4*channel)):
                    self.capture_dividers[channel] = 0
            self.enable_active = enable
        if offset in (0, 4, 8, 24, 28, 32, 36, 44, 0x44) or 0x34 <= offset < 0x44:
            self._refresh_references()
            self._refresh_master()


class TimerBank:
    def __init__(self, sim):
        self.sim = sim
        self.timers = [Timer(self, index) for index in range(14)]
        self.reset()

    def reset(self):
        self.events = deque()
        self.trigger_levels = [False]*14
        self.processing = False
        for timer in self.timers:
            timer.reset()
        self._clock_signature = None
        self.clocked_timers = []

    def _enabled(self):
        registers = self.sim.regs
        signature = (registers.get(0x40023840, 0) & 0x1FF,
                     registers.get(0x40023844, 0) & 0x70003,
                     registers.get(0x40023820, 0) & 0x1FF,
                     registers.get(0x40023824, 0) & 0x70003)
        if signature != self._clock_signature:
            self._clock_signature = signature
            self.clocked_timers = [timer for timer in self.timers if timer.clocked()]
        return self.clocked_timers

    def contains(self, address):
        return (address & ~0x3FF) in TIMER_BASES

    def _decode(self, address):
        base = address & ~0x3FF
        return self.timers[TIMER_BASES.index(base)], address-base

    def read(self, address):
        timer, offset = self._decode(address)
        return timer.read(offset)

    def write(self, address, value, size=4, byte_offset=0):
        timer, offset = self._decode(address)
        timer.write(offset, value, size, byte_offset)
        if self.sim.status == 'faulted':
            return
        self._drain_events()
        self.sample_inputs()

    def notify_rcu_write(self, address, value):
        if address in (0x40023820, 0x40023824):
            apb2 = address == 0x40023824
            for timer in self.timers:
                if timer.apb2 == apb2 and value & (1 << timer.clock_bit):
                    timer.reset()
                    self.set_trigger(timer.index, False)
        self._drain_events()

    def _ratio(self, timer):
        callback = getattr(self.sim, 'timer_clock_ratio', None)
        return callback(timer.apb2) if callback else (1, 1)

    def next_event_ticks(self):
        deadlines = []
        for timer in self._enabled():
            deadline = timer.raw_deadline()
            if deadline is not None:
                numerator, denominator = self._ratio(timer)
                remaining = (deadline*timer.clock_denominator-timer.clock_fraction)*denominator
                divisor = numerator*timer.clock_denominator
                deadlines.append(max(1, (remaining+divisor-1)//divisor))
        return min(deadlines) if deadlines else None

    def advance(self, hclk_ticks):
        enabled = self._enabled()
        if not enabled:
            return
        remaining = int(hclk_ticks)
        while remaining > 0:
            deadline = self.next_event_ticks()
            step = remaining if deadline is None else min(remaining, deadline)
            for timer in enabled:
                numerator, denominator = self._ratio(timer)
                if timer.clock_denominator % denominator:
                    common = lcm(timer.clock_denominator, denominator)
                    timer.clock_fraction *= common//timer.clock_denominator
                    timer.clock_denominator = common
                generated = step*numerator*(timer.clock_denominator//denominator)
                ticks, timer.clock_fraction = divmod(timer.clock_fraction+generated, timer.clock_denominator)
                if ticks:
                    timer.advance_raw(ticks)
            self._drain_events()
            if self.sim.status == 'faulted':
                return
            self.sample_inputs()
            remaining -= step

    def pulse(self, index):
        self.events.extend(((index, True), (index, False)))

    def set_trigger(self, index, level):
        if bool(level) != self.trigger_levels[index]:
            self.events.append((index, bool(level)))

    def _drain_events(self):
        if self.processing:
            return
        self.processing = True
        try:
            count = 0
            while self.events:
                index, level = self.events.popleft()
                previous = self.trigger_levels[index]
                self.trigger_levels[index] = level
                if previous == level:
                    continue
                callback = getattr(self.sim, 'timer_trigger', None)
                if callback:
                    callback(index, 'trgo', level)
                for target, sources in TRIGGER_SOURCES.items():
                    timer = self.timers[target]
                    selection = timer.registers.get(8, 0) >> 4 & 7
                    if selection < 4 and sources[selection] == index:
                        if target == 1 and selection == 1 and timer.registers.get(0x50, 0) & 0xC00:
                            continue
                        timer.trigger(level)
                count += 1
                if count > 4096:
                    self.sim.diagnose('定时器内部触发形成无界反馈，请检查主从连接')
                    self.events.clear()
        finally:
            self.processing = False

    def pending_irqs(self):
        mask = 0
        for timer in self._enabled():
            active = timer.registers[16] & timer.registers[12] & 255
            if not active or not timer.clocked():
                continue
            if timer.advanced:
                start = 24 if timer.index == 0 else 43
                if active & 128:
                    mask |= 1 << start
                if active & 1:
                    mask |= 1 << (start+1)
                if active & 0x60:
                    mask |= 1 << (start+2)
                if active & 0x1E:
                    mask |= 1 << (start+3)
            else:
                mask |= 1 << TIMER_IRQS[timer.index]
        return mask

    def _pin_selected(self, pin, af):
        port, number = pin[:2], int(pin[2:])
        gpio = self.sim.gpio_state[port]
        if (gpio['mode'] >> (2*number)) & 3 != 2:
            return False
        if not self.sim.regs.get(0x40023830, 0) & (1 << (ord(port[1])-65)):
            return False
        address = GPIO_BASE[port]+(32 if number < 8 else 36)
        return (self.sim.regs.get(address, 0) >> (4*(number%8))) & 15 == af

    def pin_output(self, pin):
        for index, channel, complementary, af in PIN_FUNCTIONS.get(pin, ()):
            if channel >= 0 and self._pin_selected(pin, af):
                output = self.timers[index].output(channel, complementary)
                if output is not None:
                    return output
        return None

    def _input(self, index, channel):
        levels = []
        for pin, functions in PIN_FUNCTIONS.items():
            if any(timer == index and selected == channel and not complementary and self._pin_selected(pin, af)
                   for timer, selected, complementary, af in functions):
                level = self.sim.net_level(pin)
                if level is not None:
                    levels.append(level)
        return levels[0] if levels and len(set(levels)) == 1 else None

    def input_edge(self, index, channel, level):
        """Apply one accepted digital edge after the input filter."""
        self.timers[index].input_edge(channel, int(bool(level)))
        self._drain_events()

    def sample_inputs(self):
        for timer in self._enabled():
            config = timer.registers.get(8, 0)
            slave = config & 7
            sources = set()
            for channel in range(timer.channels):
                selection = timer.channel_control(channel) & 3
                if selection in (1, 2):
                    sources.add(channel if selection == 1 else channel ^ 1)
            if slave in (1, 2, 3):
                sources.update((0, 1))
            trigger = config >> 4 & 7
            if trigger in (4, 5, 6):
                sources.add(1 if trigger == 6 else 0)
            for channel in sources:
                level = self._input(timer.index, channel)
                if timer.registers.get(4, 0) & 128 and channel == 0:
                    hall = [self._input(timer.index, value) for value in range(3)]
                    level = None if None in hall else hall[0] ^ hall[1] ^ hall[2]
                if level is None:
                    continue
                if timer.filter_raw[channel] != level:
                    timer.filter_raw[channel] = level
                    timer.filter_since[channel] = timer.raw_ticks
                if timer.input_levels[channel] is None or timer.raw_ticks-timer.filter_since[channel] >= timer.filter_delay(channel):
                    timer.input_edge(channel, level)
            external_clear = any(timer.channel_control(channel) & 128 and not timer.channel_control(channel) & 3
                                 for channel in range(timer.channels))
            if config & 0xC000 or config >> 4 & 7 == 7 or external_clear:
                level = self._input(timer.index, -1)
                if level is not None:
                    if level != timer.external_raw:
                        timer.external_raw = level
                        timer.external_since = timer.raw_ticks
                    if timer.external_level is None or timer.raw_ticks-timer.external_since >= timer.external_delay():
                        previous = timer.external_level
                        timer.external_level = level
                        polarity = bool(config & (1 << 15))
                        active = bool(level) ^ polarity
                        if previous is not None and previous != level and active:
                            timer.external_divider += 1
                            if timer.external_divider % (1 << (config >> 12 & 3)) == 0:
                                if config & (1 << 14):
                                    timer.external_clock()
                                if config >> 4 & 7 == 7:
                                    timer.trigger(True)
                                    timer.trigger(False)
                        if external_clear:
                            timer._refresh_references()
            if timer.advanced and timer.registers[0x44] & (1 << 12):
                level = self._input(timer.index, -2)
                active = level is not None and bool(level) == bool(timer.registers[0x44] & (1 << 13))
                if active:
                    timer.registers[0x44] &= ~(1 << 15)
                    if not timer.break_active:
                        timer._event(7)
                timer.break_active = active
            elif timer.advanced:
                timer.break_active = False
        self._drain_events()

    def state(self):
        result = []
        for timer in self.timers:
            numerator, denominator = self._ratio(timer)
            frequency = getattr(self.sim, 'hclk_frequency', lambda: 16000000)()*numerator/denominator
            period = (timer.psc_active+1)*(timer.car_active+1)
            center = bool(timer.registers[0] & 0x60)
            if center:
                period = (timer.psc_active+1)*2*timer.car_active
            cycle_frequency = frequency/period if period and timer.car_active else 0
            if not timer.internal_clock():
                cycle_frequency = None
            update_frequency = 0
            if timer.counting() and not timer.registers[0] & 2:
                update_frequency = (cycle_frequency*(2 if center else 1)/(timer.registers.get(0x30, 0)+1)
                                    if cycle_frequency is not None else None)
            channels = []
            for channel in range(timer.channels):
                control = timer.channel_control(channel)
                mode = (control >> 4) & 7
                duty = None
                if not control & 3 and mode in (6, 7):
                    center = bool(timer.registers[0] & 0x60)
                    numerator = timer.compare_active[channel]+int(timer.down and not center)
                    denominator = timer.car_active if center else timer.car_active+1
                    duty = min(1.0, numerator/denominator) if denominator else 0
                    if (mode == 7) ^ bool(timer.enable_active & (2 << (4*channel))):
                        duty = 1-duty
                channels.append({'channel': channel, 'mode': 'input' if control & 3 else 'output',
                                 'outputMode': (control >> 4) & 7 if not control & 3 else None,
                                 'compare': timer.compare_active[channel],
                                 'capture': timer.registers[0x34+4*channel],
                                 'output': timer.output(channel),
                                 'complementary': timer.output(channel, True),
                                 'captures': timer.capture_counts[channel],
                                 'transitions': timer.transition_count[channel],
                                 'duty': duty})
            result.append({'index': timer.index, 'name': f'TIMER{timer.index}',
                           'address': f'0x{timer.base:08X}', 'bits': timer.mask.bit_length(),
                           'type': 'advanced' if timer.advanced else ('basic' if timer.basic else 'general'),
                           'clockEnabled': timer.clocked(), 'enabled': bool(timer.registers[0] & 1),
                           'counter': timer.counter, 'prescaler': timer.registers[40],
                           'activePrescaler': timer.psc_active, 'reload': timer.registers[44],
                           'activeReload': timer.car_active, 'flags': timer.registers[16],
                           'interruptEnable': timer.registers[12] & 255,
                           'direction': 'down' if timer.down else 'up',
                           'clockHz': frequency, 'cycleHz': cycle_frequency, 'updateHz': update_frequency,
                           'updates': timer.update_count, 'dmaRequests': timer.dma_requests,
                           'channels': channels})
        return result
