"""V2 driver-evidenced SPI0 PT100 ADC and DAC0/PA4 functional subset.

GD30AD3344 Rev1.1 sections 7.5/7.6 define the SPI conversion/config frames.
The user's Function.c supplies the PT100 analog transfer function. SPI mode 1,
16/32-bit transactions, AIN0-to-GND and PGA scaling are modeled. A completed
valid conversion request advances one ideal sample atomically. Data rate,
analog filtering, noise, settling and electrical timing are outside this model.
GD30AD3340 is an I2C part and is not the SPI device represented here.
"""
import math

SPI0 = 0x40013000
DAC0 = 0x40007400
GPIOA = 0x40020000
RCU_AHB1EN = 0x40023830
RCU_APB1EN = 0x40023840
RCU_APB2EN = 0x40023844
RCU_APB1RST = 0x40023820
RCU_APB2RST = 0x40023824
FULL_SCALE = (6.144, 4.096, 2.048, 1.024, .512, .256, .064, .064)


class V2Devices:
    def __init__(self, sim):
        self.sim = sim
        self.temperature = 25.0
        self.reset()

    def active(self):
        return getattr(self.sim, 'board', {}).get('id') == 'cimc-v2'

    def contains(self, address):
        return self.active() and (SPI0 <= address < SPI0 + 0x400 or
                                  DAC0 <= address < DAC0 + 0x400)

    def reset(self):
        self._reset_spi()
        self._reset_dac()
        self.config = 0x058B
        self.raw = 0
        self.sample_count = 0
        self.last_sample_temperature = None
        self.wiring_warning = False

    def _reset_spi(self):
        self.spi = {0: 0, 4: 0, 8: 2, 12: 0, 16: 7, 20: 0, 24: 0, 28: 0, 32: 2}
        self.selected = False
        self.frame = bytearray()
        self.shift_result = 0
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

    def set_temperature(self, temperature):
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            raise ValueError('PT100 温度必须是 -50–150 °C 的数字')
        if not math.isfinite(temperature) or not -50 <= temperature <= 150:
            raise ValueError('PT100 温度必须在 -50–150 °C 范围内')
        if not self.active():
            raise ValueError('PT100 输入只在 V2 配置中可用')
        self.temperature = float(temperature)

    def _error(self, message):
        self.sim.diagnose('V2 模拟外设：' + message)
        return 0

    def _clocked(self, kind):
        enable, reset, bit = ((RCU_APB2EN, RCU_APB2RST, 12) if kind == 'spi'
                              else (RCU_APB1EN, RCU_APB1RST, 29))
        return bool(self.sim.regs.get(enable, 0) & (1 << bit)) and not self.sim.regs.get(reset, 0) & (1 << bit)

    def on_gpio_changed(self, port):
        if not self.active():
            return
        connected = self._bus_connected()
        active = connected and self.sim.net_level('PT100_CS') == 0
        if active == self.selected:
            return
        if active:
            # A continuous-mode sample becomes visible at a fresh SPI frame.
            # The first frame after reset still shifts the reset conversion 0.
            if not self.config & (1 << 8):
                self._sample()
            self.frame.clear()
            self.shift_result = self.raw & 0xFFFF
        elif connected and len(self.frame) not in (0, 2, 4):
            self._error('PT100 SPI 传输需在完整 16 或 32 位后释放 PB10 片选')
        if not active:
            self.frame.clear()
        self.selected = active

    def _connected_signal(self, terminal, pin):
        nets = self.sim.connected(terminal)
        other_signals = {'PT100_SCK', 'PT100_MISO', 'PT100_MOSI', 'PT100_CS',
                         'GND', 'DGND', 'AGND', '0V', '3V3', '3.3V', 'VCC', '5V'} - {terminal}
        if pin not in nets or nets & other_signals:
            return False
        for net in nets:
            if net != pin and net[:2] in self.sim.gpio_state and net[2:].isdigit():
                number = int(net[2:])
                if number < 16 and (self.sim.gpio_state[net[:2]]['mode'] >> (number * 2)) & 3 == 1:
                    return False
        return True

    def _bus_connected(self):
        return all(self._connected_signal(terminal, pin) for terminal, pin in
                   (('PT100_SCK', 'PA5'), ('PT100_MISO', 'PA6'),
                    ('PT100_MOSI', 'PA7'), ('PT100_CS', 'PB10')))

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

    def _pt100_pins_valid(self):
        if self.spi[0] & 3 != 1:
            self._error('PT100 需要 SPI0 mode 1')
            return False
        if self.sim.regs.get(RCU_AHB1EN, 0) & 3 != 3:
            self._error('PT100 需要 GPIOA/GPIOB 时钟')
            return False
        gpio = self.sim.gpio_state['PA']
        af = self.sim.regs.get(GPIOA + 32, 0)
        for pin in (5, 6, 7):
            if (gpio['mode'] >> (2 * pin)) & 3 != 2 or (af >> (4 * pin)) & 15 != 5:
                self._error(f'PT100 的 PA{pin} 必须配置为 AF5')
                return False
        if (self.sim.gpio_state['PB']['mode'] >> 20) & 3 != 1:
            self._error('PT100 的 PB10 片选必须配置为输出')
            return False
        return True

    def _sample(self):
        resistance = 100 + .385 * self.temperature
        millivolts = resistance * 22200 / 2200
        scale = FULL_SCALE[(self.config >> 9) & 7] * 1000
        self.raw = min(32767, max(-32768, int(millivolts * 32768 / scale + .5)))
        self.sample_count += 1
        self.last_sample_temperature = self.temperature

    def _config(self, value):
        if (value >> 1) & 3 != 1:
            return
        if (value >> 12) & 7 != 4:
            self._error('PT100 SPI 子集仅实现 AIN0 对 GND 输入')
            return
        if (value >> 9) & 7 == 7:
            self._error('PT100 ADC 的 PGA=7 为保留配置')
            return
        was_single = bool(self.config & (1 << 8))
        self.config = (value & 0x7FEF) | 1
        if ((was_single and not value & (1 << 8)) or
                (value & (1 << 8) and value & (1 << 15))):
            self._sample()

    def _exchange(self, value):
        index = len(self.frame)
        if index >= 4:
            return self._error('PT100 SPI 子集每个片选只允许 16 或 32 位传输')
        result = ((self.shift_result if index < 2 else self.config) >> (8 if index % 2 == 0 else 0)) & 255
        self.frame.append(value)
        if index == 1:
            self._config((self.frame[0] << 8) | value)
        # The second half of a 32-bit cycle only returns the configuration.
        # The device accepts the first configuration word once per cycle.
        return result

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
            self.on_gpio_changed('PB')
            if not self._spi_valid():
                return
            connected = self._bus_connected()
            flash = getattr(self.sim, 'flash', None)
            flash_response = flash.exchange_shared(value & 255, self.spi) if flash else None
            pt100_active = self.selected or (self.spi[0] & 3 == 1 and flash_response is None)
            if pt100_active and not self._pt100_pins_valid():
                return
            if flash_response is not None and self.selected:
                return self._error('SPI0 的 Flash 与 PT100 同时选中，MISO 输出冲突')
            if pt100_active and not connected and not self.wiring_warning:
                self.sim.diagnose('PT100 SPI 示例跳线未接通或被短接，请检查 SCK / MISO / MOSI / CS', 'warning')
                self.wiring_warning = True
            elif connected:
                self.wiring_warning = False
            received = flash_response if flash_response is not None else (
                self._exchange(value & 255) if connected and self.selected else 255)
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
            if merged & ~0x3F or (merged & 4 and (merged >> 3) & 7 != 7):
                return self._error('DAC0 子集仅实现 OUT0 直写与软件触发，无波形、DMA或中断')
            self.dac[0] = merged
            self._update_dac()
        elif offset == 4:
            if merged & ~1:
                return self._error('DAC0 OUT1 软件触发尚未实现')
            if merged & 1:
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

    def state(self):
        enabled = self.active() and self._clocked('dac') and bool(self.dac[0] & 1)
        dac_nets = self.sim.connected('DAC_OUT0') if self.active() else set()
        dac_connected = 'PA4' in dac_nets and not dac_nets & {'GND', 'DGND', '3V3', '5V'}
        return {'pt100': {'temperature': self.temperature,
                          'resistance': 100 + .385 * self.temperature,
                          'raw': self.raw, 'sampleCount': self.sample_count,
                          'sampleTemperature': self.last_sample_temperature,
                          'config': f'0x{self.config:04X}', 'enabled': self.active(),
                          'connected': self.active() and self._bus_connected()},
                'dac': {'value': self.dac_output, 'voltage': self.dac_output * 3.3 / 4095 if enabled and dac_connected else None,
                        'holdingValue': self.dac_holding, 'enabled': enabled,
                        'connected': dac_connected, 'pin': 'PA4'}}
