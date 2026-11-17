"""V2 DAC0/PA4 and the shared polling SPI0 controller."""

SPI0 = 0x40013000
DAC0 = 0x40007400
GPIOA = 0x40020000
RCU_AHB1EN = 0x40023830
RCU_APB1EN = 0x40023840
RCU_APB2EN = 0x40023844
RCU_APB1RST = 0x40023820
RCU_APB2RST = 0x40023824

class V2Devices:
    def __init__(self, sim):
        self.sim = sim
        self.reset()

    def active(self):
        return getattr(self.sim, 'board', {}).get('id') == 'cimc-v2'

    def contains(self, address):
        return self.active() and (SPI0 <= address < SPI0 + 0x400 or
                                  DAC0 <= address < DAC0 + 0x400)

    def reset(self):
        self._reset_spi()
        self._reset_dac()

    def _reset_spi(self):
        self.spi = {0: 0, 4: 0, 8: 2, 12: 0, 16: 7, 20: 0, 24: 0, 28: 0, 32: 2}
        self.overrun_data_read = False

    def _reset_dac(self):
        self.dac = {offset: 0 for offset in range(0, 0x38, 4)}
        self.dac_holding = 0
        self.dac_output = 0

    def notify_rcu_write(self, address, value):
        if address == RCU_APB2RST and value & (1 << 12):
            self._reset_spi()
            if getattr(self.sim, 'flash', None):
                self.sim.flash.reset(controller_only=True)
        if address == RCU_APB1RST and value & (1 << 29):
            self._reset_dac()

    def _error(self, message):
        self.sim.diagnose('V2 模拟外设：' + message)
        return 0

    def _clocked(self, kind):
        enable, reset, bit = ((RCU_APB2EN, RCU_APB2RST, 12) if kind == 'spi'
                              else (RCU_APB1EN, RCU_APB1RST, 29))
        return bool(self.sim.regs.get(enable, 0) & (1 << bit)) and not self.sim.regs.get(reset, 0) & (1 << bit)

    def _spi_valid(self):
        control = self.spi[0]
        if not self._clocked('spi'):
            self._error('SPI0 时钟未开启或仍处于复位')
            return False
        if control & 0xFC80 or control & 0x344 != 0x344:
            self._error('SPI0 子集需要主机、软件 NSS、8 位 MSB')
            return False
        if self.spi[4] & 0xF3 or self.spi[28] & 0xC00:
            self._error('SPI0 DMA、中断、TI 与 I2S 模式尚未实现')
            return False
        return True

    def _dac_valid(self):
        if not self._clocked('dac'):
            self._error('DAC0 时钟未开启或仍处于复位')
            return False
        if not self.sim.regs.get(RCU_AHB1EN, 0) & 1:
            self._error('DAC0 需要 GPIOA 时钟')
            return False
        if (self.sim.gpio_state['PA']['mode'] >> 8) & 3 != 3:
            self._error('DAC0 OUT0 的 PA4 必须配置为模拟模式')
            return False
        return True

    def _update_dac(self, triggered=False):
        control = self.dac[0]
        if not control & 1:
            return
        if control & 4 and not triggered:
            return
        if self._dac_valid():
            self.dac_output = self.dac_holding
            self.dac[0x2C] = self.dac_output

    def read(self, address):
        if SPI0 <= address < SPI0 + 0x400:
            offset = address - SPI0
            if offset not in self.spi:
                return self._error(f'未实现的 SPI0 寄存器读取 0x{address:08X}')
            if not self._clocked('spi'):
                return 0
            value = self.spi[offset]
            if offset == 12:
                self.overrun_data_read = bool(self.spi[8] & 64)
                self.spi[8] &= ~1
            elif offset == 8 and self.overrun_data_read:
                self.spi[8] &= ~64
                self.overrun_data_read = False
            return value
        offset = address - DAC0
        if offset not in self.dac:
            return self._error(f'未实现的 DAC0 寄存器读取 0x{address:08X}')
        return self.dac[offset] if self._clocked('dac') else 0

    def write(self, address, value, size=4, byte_offset=0):
        if SPI0 <= address < SPI0 + 0x400:
            return self._write_spi(address - SPI0, value, size, byte_offset)
        return self._write_dac(address - DAC0, value, size, byte_offset)

    def _write_spi(self, offset, value, size, byte_offset):
        if offset not in self.spi:
            return self._error(f'未实现的 SPI0 寄存器写入 0x{SPI0 + offset:08X}')
        if not self._clocked('spi'):
            return self._error('SPI0 时钟未开启时写入寄存器')
        mask = ((1 << (size * 8)) - 1) << (byte_offset * 8)
        merged = (self.spi[offset] & ~mask) | (value & mask)
        if offset == 12:
            if byte_offset or size not in (1, 2, 4):
                return self._error('SPI0 DATA 访问须从最低字节开始')
            if not self._spi_valid():
                return
            flash = getattr(self.sim, 'flash', None)
            response = flash.exchange_shared(value & 255, self.spi) if flash else None
            received = response if response is not None else 255
            if self.spi[8] & 1:
                self.spi[8] |= 64
                self.overrun_data_read = False
            else:
                self.spi[12] = received
                self.spi[8] |= 1
            return
        if offset in (8, 20, 24):
            if offset == 8 and not merged & 16:
                self.spi[8] &= ~16
            return
        self.spi[offset] = merged & 0xFFFF
        if (offset == 4 and merged & 0xF3) or (offset == 28 and merged & 0xC00):
            self._error('SPI0 DMA、中断、TI 与 I2S 模式尚未实现')

    def _write_dac(self, offset, value, size, byte_offset):
        if offset not in self.dac:
            return self._error(f'未实现的 DAC0 寄存器写入 0x{DAC0 + offset:08X}')
        if size not in (1, 2, 4) or byte_offset + size > 4:
            return self._error('DAC0 寄存器访问大小或对齐无效')
        if not self._clocked('dac'):
            return self._error('DAC0 时钟未开启时写入寄存器')
        mask = ((1 << (size * 8)) - 1) << (byte_offset * 8)
        merged = (self.dac[offset] & ~mask) | (value & mask)
        if offset in (0x2C, 0x30):
            return
        if offset == 0:
            if merged & ~0x3F:
                return self._error('DAC0 OUT0 波形、DMA和中断尚未实现')
            self.dac[0] = merged
            self._update_dac()
        elif offset == 4:
            if merged & ~1:
                return self._error('DAC0 OUT1 软件触发尚未实现')
            if merged & 1 and (self.dac[0]>>3)&7==7:
                self._update_dac(triggered=True)
        elif offset in (8, 12, 16):
            self.dac[offset] = merged
            if offset == 8:
                self.dac_holding = merged & 4095
            elif offset == 12:
                self.dac_holding = (merged >> 4) & 4095
            else:
                self.dac_holding = (merged & 255) << 4
            self._update_dac()
        elif merged:
            return self._error('DAC0 OUT1、双通道与DMA状态尚未实现')

    def timer_trigger(self,timer,event,level=True):
        if not self.active() or not level or event!='trgo':return
        control=self.dac[0]
        sources=(5,7,6,4,1,3)
        selection=(control>>3)&7
        if control&4 and selection<len(sources) and sources[selection]==timer:
            self._update_dac(triggered=True)

    def state(self):
        enabled = self.active() and self._clocked('dac') and bool(self.dac[0] & 1)
        analog_pin = (self.sim.gpio_state['PA']['mode'] >> 8) & 3 == 3
        output_active = enabled and analog_pin and bool(self.sim.regs.get(RCU_AHB1EN, 0) & 1)
        return {'dac': {'value': self.dac_output,
                        'voltage': self.dac_output * 3.3 / 4095 if output_active else None,
                        'holdingValue': self.dac_holding, 'enabled': enabled,
                        'pin': 'PA4'}}
