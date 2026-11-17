"""GD32F470 free and window watchdogs driven by emulated clock time.

The register and reset rules follow GD32F4xx User Manual Rev 3.5 chapter 16.
The functional model transfers FWDGT configuration and reload commands on the
next IRC32K edge. Its clock-domain crossing latency is not cycle accurate.
"""
from fractions import Fraction

WWDGT = 0x40002C00
FWDGT = 0x40003000
RCU_APB1RST = 0x40023820
RCU_APB1EN = 0x40023840
RCU_RSTSCK = 0x40023874
DBG_CTL1 = 0xE0042008
WWDGT_CLOCK_BIT = 1 << 11
IRC32K_HZ = 32000


def _ceil(value):
    return (value.numerator + value.denominator - 1) // value.denominator


class Watchdogs:
    def __init__(self, sim):
        self.sim = sim
        self.reset()

    def reset(self):
        self.fwdgt_enabled = False
        self.fwdgt_unlocked = False
        self.fwdgt_prescaler = 0
        self.fwdgt_reload = 0xFFF
        self.fwdgt_counter = 0xFFF
        self.fwdgt_pending_prescaler = None
        self.fwdgt_pending_reload = None
        self.fwdgt_pending_feed = False
        self.fwdgt_clock_phase = Fraction(0)
        self.fwdgt_prescale_phase = 0
        self.fwdgt_clock_cycles = 0
        self.fwdgt_last_feed = None
        self.fwdgt_reload_count = 0
        self._reset_wwdgt()
        self.reset_requested = None

    def _reset_wwdgt(self):
        self.wwdgt_enabled = False
        self.wwdgt_counter = 0x7F
        self.wwdgt_config = 0x7F
        self.wwdgt_flag = 0
        self.wwdgt_phase = Fraction(0)
        self.wwdgt_reload_count = 0

    @staticmethod
    def contains(address):
        return WWDGT <= address < FWDGT + 0x400

    def _fault(self, message):
        self.sim.diagnose('看门狗：' + message)
        return 0

    def _wwdgt_clocked(self):
        return bool(self.sim.regs.get(RCU_APB1EN, 0) & WWDGT_CLOCK_BIT) and not (
            self.sim.regs.get(RCU_APB1RST, 0) & WWDGT_CLOCK_BIT)

    def _held(self, bit):
        return bool(getattr(self.sim, 'core_halted', False) and self.sim.regs.get(DBG_CTL1, 0) & bit)

    def _fwdgt_pending(self):
        return (self.fwdgt_pending_prescaler is not None or
                self.fwdgt_pending_reload is not None or self.fwdgt_pending_feed)

    def _fwdgt_divider(self):
        return 4 << min(self.fwdgt_prescaler, 6)

    def _wwdgt_divider(self):
        return 4096 << ((self.wwdgt_config >> 7) & 3)

    def notify_rcu_write(self, address, value):
        if address == RCU_APB1RST and value & WWDGT_CLOCK_BIT:
            self._reset_wwdgt()
        if address == RCU_RSTSCK and self.fwdgt_enabled:
            # An enabled FWDGT keeps its independent oscillator running.
            self.sim.regs[RCU_RSTSCK] = self.sim.regs.get(RCU_RSTSCK, 0) | 1

    def read(self, address):
        if WWDGT <= address < FWDGT:
            offset = address - WWDGT
            if offset not in (0, 4, 8):
                return self._fault(f'未实现的 WWDGT 寄存器读取 0x{address:08X}')
            if not self._wwdgt_clocked():
                return 0
            if offset == 0:
                return self.wwdgt_counter | (0x80 if self.wwdgt_enabled else 0)
            return self.wwdgt_config if offset == 4 else self.wwdgt_flag
        offset = address - FWDGT
        if offset == 0:
            return 0  # Write-only command register.
        if offset == 4:
            return self.fwdgt_prescaler
        if offset == 8:
            return self.fwdgt_reload
        if offset == 12:
            return int(self.fwdgt_pending_prescaler is not None) | (
                int(self.fwdgt_pending_reload is not None) << 1)
        return self._fault(f'未实现的 FWDGT 寄存器读取 0x{address:08X}')

    def write(self, address, value, size=4, byte_offset=0):
        base = WWDGT if WWDGT <= address < FWDGT else FWDGT
        offsets = (0, 4, 8) if base == WWDGT else (0, 4, 8, 12)
        if address - base not in offsets:
            return self._fault(f'未实现的寄存器写入 0x{address:08X}')
        if size not in (2, 4) or byte_offset not in (0, 2) or byte_offset + size > 4:
            return self._fault('寄存器要求对齐的16位或32位访问')
        if byte_offset:
            return  # Both devices have only reserved high halfwords.
        if WWDGT <= address < FWDGT:
            return self._write_wwdgt(address - WWDGT, value)
        return self._write_fwdgt(address - FWDGT, value)

    def _write_fwdgt(self, offset, value):
        if offset == 0:
            command = value & 0xFFFF
            self.fwdgt_unlocked = command == 0x5555
            if command == 0xCCCC:
                self.fwdgt_enabled = True
                self.sim.regs[RCU_RSTSCK] = self.sim.regs.get(RCU_RSTSCK, 0) | 1
            elif command == 0xAAAA:
                clock = self.fwdgt_clock_cycles + self.fwdgt_clock_phase
                # Rev 3.5 requires >=7 IRC32K clocks between reload commands.
                # A command still crossing the clock domain is not accepted again.
                if self.fwdgt_last_feed is None or clock - self.fwdgt_last_feed >= 7:
                    self.fwdgt_pending_feed = True
                    self.fwdgt_last_feed = clock
            return
        if offset == 4:
            if self.fwdgt_unlocked and self.fwdgt_pending_prescaler is None:
                self.fwdgt_pending_prescaler = value & 7
            return
        if offset == 8:
            if self.fwdgt_unlocked and self.fwdgt_pending_reload is None:
                self.fwdgt_pending_reload = value & 0xFFF
            return
        if offset == 12:
            return  # Read-only update flags.
        return self._fault(f'未实现的 FWDGT 寄存器写入 0x{FWDGT + offset:08X}')

    def _write_wwdgt(self, offset, value):
        if offset not in (0, 4, 8):
            return self._fault(f'未实现的 WWDGT 寄存器写入 0x{WWDGT + offset:08X}')
        if not self._wwdgt_clocked():
            return
        if offset == 0:
            if self.wwdgt_enabled and self.wwdgt_counter > (self.wwdgt_config & 0x7F):
                self._request_reset('wwdgt')
                return
            self.wwdgt_counter = value & 0x7F
            self.wwdgt_enabled |= bool(value & 0x80)
            self.wwdgt_reload_count += int(self.wwdgt_enabled)
            # Refresh does not restart the free-running prescaler.
            if self.wwdgt_enabled and self.wwdgt_counter < 0x40:
                self._request_reset('wwdgt')
        elif offset == 4:
            self.wwdgt_config = (value & 0x3FF) | (self.wwdgt_config & 0x200)
        else:
            self.wwdgt_flag &= value & 1

    def _request_reset(self, reason):
        self.reset_requested = reason
        self.sim.request_system_reset(reason)

    def _fwdgt_advance(self, hclk_ticks):
        if not (self.fwdgt_enabled or self._fwdgt_pending() or self.sim.regs.get(RCU_RSTSCK, 0) & 1):
            return False
        clock = self.fwdgt_clock_phase + Fraction(hclk_ticks * IRC32K_HZ, self.sim.hclk_frequency())
        cycles = int(clock)
        self.fwdgt_clock_phase = clock - cycles
        self.fwdgt_clock_cycles += cycles
        if not cycles:
            return False
        if self.fwdgt_pending_prescaler is not None:
            self.fwdgt_prescaler = self.fwdgt_pending_prescaler
            self.fwdgt_pending_prescaler = None
            self.fwdgt_prescale_phase = 0
        if self.fwdgt_pending_reload is not None:
            self.fwdgt_reload = self.fwdgt_pending_reload
            self.fwdgt_pending_reload = None
        if self.fwdgt_pending_feed:
            self.fwdgt_counter = self.fwdgt_reload
            self.fwdgt_prescale_phase = 0
            self.fwdgt_pending_feed = False
            self.fwdgt_reload_count += 1
            cycles -= 1
        if not self.fwdgt_enabled or not cycles or self._held(1 << 12):
            return False
        divider = self._fwdgt_divider()
        until_reset = self.fwdgt_counter * divider - self.fwdgt_prescale_phase + 1
        if cycles >= until_reset:
            self.fwdgt_counter = 0
            self.fwdgt_prescale_phase = 0
            return True
        decrements, self.fwdgt_prescale_phase = divmod(self.fwdgt_prescale_phase + cycles, divider)
        self.fwdgt_counter -= decrements
        return False

    def _wwdgt_advance(self, hclk_ticks):
        if not self.wwdgt_enabled or not self._wwdgt_clocked() or self._held(1 << 11):
            return False
        numerator, denominator = self.sim.apb_clock_ratio(apb2=False)
        clock = self.wwdgt_phase + Fraction(hclk_ticks * numerator, denominator)
        divider = self._wwdgt_divider()
        decrements = int(clock // divider)
        self.wwdgt_phase = clock - decrements * divider
        previous = self.wwdgt_counter
        self.wwdgt_counter = max(0x3F, previous - decrements)
        if previous > 0x40 and self.wwdgt_counter <= 0x40:
            self.wwdgt_flag = 1
        return self.wwdgt_counter < 0x40

    def next_event_ticks(self):
        if self.reset_requested:
            return None
        deadlines = []
        if self._fwdgt_pending() or (self.fwdgt_enabled and not self._held(1 << 12)):
            cycles = 1 if self._fwdgt_pending() else (
                self.fwdgt_counter * self._fwdgt_divider() - self.fwdgt_prescale_phase + 1)
            remaining = Fraction(cycles) - self.fwdgt_clock_phase
            deadlines.append(max(1, _ceil(remaining * self.sim.hclk_frequency() / IRC32K_HZ)))
        if self.wwdgt_enabled and self._wwdgt_clocked() and not self._held(1 << 11):
            # EWIF is generated even when its interrupt is disabled.
            target = 0x40 if self.wwdgt_counter > 0x40 and not self.wwdgt_flag else 0x3F
            cycles = max(1, self.wwdgt_counter - target)
            remaining = cycles * self._wwdgt_divider() - self.wwdgt_phase
            numerator, denominator = self.sim.apb_clock_ratio(apb2=False)
            deadlines.append(max(1, _ceil(remaining * denominator / numerator)))
        return min(deadlines) if deadlines else None

    def advance(self, hclk_ticks):
        if hclk_ticks < 0:
            raise ValueError('看门狗时钟增量必须非负')
        remaining = hclk_ticks
        while remaining and not self.reset_requested:
            deadline = self.next_event_ticks()
            if deadline is None:
                self._fwdgt_advance(remaining)
                return
            elapsed = min(remaining, deadline)
            fwdgt_expired = self._fwdgt_advance(elapsed)
            wwdgt_expired = self._wwdgt_advance(elapsed)
            if fwdgt_expired:
                self._request_reset('fwdgt')
            if wwdgt_expired:
                self._request_reset('wwdgt')
            remaining -= elapsed

    def pending_irqs(self):
        return int(bool(self.wwdgt_flag and self.wwdgt_config & 0x200))

    def state(self):
        return {
            'fwdgt': {'enabled': self.fwdgt_enabled, 'clockHz': IRC32K_HZ,
                      'counter': self.fwdgt_counter, 'prescaler': self._fwdgt_divider(),
                      'reload': self.fwdgt_reload, 'updateFlags': self.read(FWDGT + 12),
                      'reloadCount': self.fwdgt_reload_count},
            'wwdgt': {'enabled': self.wwdgt_enabled, 'clockEnabled': self._wwdgt_clocked(),
                      'counter': self.wwdgt_counter, 'window': self.wwdgt_config & 0x7F,
                      'prescaler': self._wwdgt_divider(), 'earlyWakeupFlag': bool(self.wwdgt_flag),
                      'interruptEnabled': bool(self.wwdgt_config & 0x200),
                      'reloadCount': self.wwdgt_reload_count},
            'resetRequested': self.reset_requested,
        }
