"""Polling GD32 SPI1 + the V1 board's GD25Q40E, a functional SPI model.

SPI bytes complete atomically. Flash WIP uses simulated instruction time (not
wall time): PP 256, sector 2048, block 4096, chip 8192 instructions. These are
deterministic test delays, NOT datasheet program/erase timing. No DMA, interrupts,
CRC, I2S, dual/quad, protection-register writes, SFDP or security-register model.
Source: GD25Q40E Rev1.1 sections 6/7; GD32F4xx UM Rev3.3 section 21.
"""
from __future__ import annotations

SPI1 = 0x40003800
GPIOB = 0x40020400
RCU_APB1EN = 0x40023840
RCU_AHB1EN = 0x40023830
CAPACITY = 512 * 1024
COMMANDS = {0x06:'WREN',0x04:'WRDI',0x05:'RDSR1',0x35:'RDSR2',
            0x03:'READ',0x0B:'FAST_READ',0x9F:'RDID',0x90:'REMS',0xAB:'RDI',
            0x02:'PP',0x20:'SE',0x52:'BE32',0xD8:'BE64',0xC7:'CE',0x60:'CE',
            0xB9:'DP',0x66:'RESET_ENABLE',0x99:'RESET'}


class SpiFlashDevice:
    def __init__(self, sim):
        self.sim = sim
        self.memory = bytearray(b'\xff' * CAPACITY)
        self.wel = False
        self.deep_power_down = False
        self.reset_enabled = False
        self.pending = None
        self.clock = 0
        self.last_instruction = getattr(sim,'instructions',0)
        self.last_command = None
        self.last_address = 0
        self.read_count = self.write_count = self.erase_count = self.programmed_bytes = 0
        self.selected = False
        self._clear_transaction()
        self.reset()

    def contains(self, address):
        return SPI1 <= address < SPI1 + 0x400

    def reset(self, controller_only=False):
        """Reset MCU SPI registers, retaining the separately powered flash.

        The board's CS pull-up terminates an in-flight command when MCU pins
        become inputs. Completed commands/pending internal writes survive.
        """
        self._advance()
        if not controller_only:
            if self.selected:
                self._finish()
            self.selected = False
            self._clear_transaction()
        self.registers = {0:0,4:0,8:2,12:0,16:7,20:0,24:0,28:0,32:2}
        self.overrun_data_read = False
        self.last_instruction = getattr(self.sim,'instructions',0)

    def _advance(self):
        current = getattr(self.sim,'instructions',0)
        self.clock += max(0, current - self.last_instruction)
        self.last_instruction = current
        if self.pending and self.clock >= self.pending['until']:
            operation = self.pending
            self.pending = None
            if operation['kind'] == 'program':
                for address, value in operation['data'].items():
                    self.memory[address] &= value
                self.write_count += 1
                self.programmed_bytes += len(operation['data'])
            else:
                start, length = operation['start'], operation['length']
                self.memory[start:start+length] = b'\xff' * length
                self.erase_count += 1

    def _clear_transaction(self):
        self.command = None
        self.index = 0
        self.address = 0
        self.page = {}
        self.ignored = False

    def _error(self, message):
        self.sim.diagnose('SPI Flash：' + message)

    def _warning(self, message):
        self.sim.diagnose('SPI Flash：' + message, 'warning')

    def _clock_enabled(self):
        return bool(self.sim.regs.get(RCU_APB1EN,0) & (1 << 14)) and not self.sim.regs.get(0x40023820,0) & (1 << 14)

    def on_gpio_changed(self, port):
        if port != 'PB':
            return
        self._advance()
        # FLASH_CS has the schematic's R8 10k pull-up. An indeterminate net is
        # not treated as a valid selection (the net resolver diagnoses shorts).
        active = self.sim.net_level('FLASH_CS') == 0
        if active != self.selected:
            if active:
                self._clear_transaction()
            else:
                self._finish()
                self._clear_transaction()
            self.selected = active

    def _bus_valid(self):
        ctl = self.registers[0]
        if not self._clock_enabled():
            self._error('SPI1 时钟未开启（RCU_APB1EN.SPI1EN）')
            return False
        if not ctl & 64:
            self._error('SPI1 未使能（SPIEN）')
            return False
        if ctl & 0xFC80 or ctl & 3 not in (0,3):
            self._error('仅支持 MSB 优先、8 位、全双工、无 CRC 的 SPI mode 0/3')
            return False
        if ctl & 0x304 != 0x304:
            self._error('仅支持主机模式及软件 NSS（MSTMOD/SWNSSEN/SWNSS）')
            return False
        if self.registers[4] & 0xF3 or self.registers[28] & 0xC00:
            self._error('SPI DMA/中断/TI/I2S 模式尚未实现')
            return False
        if not self.sim.regs.get(RCU_AHB1EN,0) & 2:
            self._error('GPIOB 时钟未开启')
            return False
        gpio = self.sim.gpio_state['PB']
        af = self.sim.regs.get(GPIOB+36,0)
        for pin, terminal in ((13,'SPI_SCK'),(14,'SPI_MISO'),(15,'SPI_MOSI')):
            if (gpio['mode'] >> (2*pin)) & 3 != 2 or (af >> (4*(pin-8))) & 15 != 5:
                self._error(f'PB{pin} 必须配置为 AF5 复用功能')
                return False
            nets = self.sim.connected(f'PB{pin}')
            if terminal not in nets or any(n in nets for n in ('DGND','AGND','GND','3V3','5V')):
                self._error(f'PB{pin} 固定网络无效或被短接')
                return False
            for net in nets:
                if len(net)>2 and net[:2] in self.sim.gpio_state and net[2:].isdigit() and net != f'PB{pin}':
                    number = int(net[2:])
                    if number < 16 and (self.sim.gpio_state[net[:2]]['mode'] >> (2*number)) & 3 == 1:
                        self._error(f'{net} 输出占用 SPI 信号线')
                        return False
        if self.selected and (gpio['mode'] >> 24) & 3 != 1:
            self._error('PB12 片选必须由 GPIO 输出驱动')
            return False
        return True

    def read(self, address):
        self._advance()
        offset = address - SPI1
        if offset not in self.registers:
            self._error(f'未实现寄存器读取 0x{address:08X}')
            return 0
        if not self._clock_enabled():
            return 0
        value = self.registers[offset]
        if offset == 12:
            self.overrun_data_read = bool(self.registers[8] & 64)
            self.registers[8] &= ~1
        elif offset == 8 and self.overrun_data_read:
            self.registers[8] &= ~64
            self.overrun_data_read = False
        return value

    def write(self, address, value, size=4, byte_offset=0):
        self._advance()
        offset = address - SPI1
        if offset not in self.registers:
            self._error(f'未实现寄存器写入 0x{address:08X}')
            return
        if not self._clock_enabled():
            self._error('SPI1 时钟未开启时写入寄存器')
            return
        mask = ((1 << (size*8))-1) << (byte_offset*8)
        merged = (self.registers[offset] & ~mask) | (value & mask)
        if offset == 12:
            if byte_offset or size not in (1,2,4):
                self._error('SPI DATA 访问须从寄存器最低字节开始')
                return
            self.on_gpio_changed('PB')
            if not self._bus_valid():
                return
            received = self._exchange(value & 255) if self.selected else 255
            if self.registers[8] & 1:
                self.registers[8] |= 64
                self.overrun_data_read = False
            else:
                self.registers[12] = received
                self.registers[8] |= 1
            return
        if offset in (8,20,24):
            # RCRC/TCRC are read-only; STAT only allows clearing CRCERR.
            if offset == 8 and not merged & 16:
                self.registers[8] &= ~16
            return
        self.registers[offset] = merged & 0xFFFF
        if offset == 4 and merged & 0xF3:
            self._error('SPI DMA/中断/TI 模式尚未实现')
        if offset == 28 and merged & 0xC00:
            self._error('SPI I2S 模式尚未实现')

    def _exchange(self, value):
        if self.command is None:
            self.command = value
            self.last_command = f'0x{value:02X} {COMMANDS.get(value,"UNSUPPORTED")}'
            if self.deep_power_down and value not in (0xAB,0x66,0x99):
                self.ignored = True
            elif self.pending and value not in (0x05,0x35,0x66,0x99):
                self.ignored = True
            elif value not in COMMANDS:
                self.ignored = True
                self._error(f'未实现 GD25Q40E 命令 0x{value:02X}')
            if value != 0x99:
                self.reset_enabled = False
            return 255
        index = self.index
        self.index += 1
        if self.ignored:
            return 255
        command = self.command
        if command == 0x05:
            return (int(self.wel) << 1) | int(self.pending is not None)
        if command == 0x35:
            return 0
        if command == 0x9F:
            return (0xC8,0x40,0x13)[index] if index < 3 else 255
        if command in (0x03,0x0B,0x02,0x20,0x52,0xD8,0x90,0xAB):
            if index < 3:
                self.address = ((self.address << 8) | value) & (CAPACITY-1)
                return 255
            if command == 0x90:
                return (0xC8,0x12)[(index-3+(self.address & 1)) % 2]
            if command == 0xAB:
                return 0x12
            if command == 0x0B and index == 3:
                return 255
            if command in (0x03,0x0B):
                result = self.memory[self.address]
                self.last_address = self.address
                self.address = (self.address+1) & (CAPACITY-1)
                self.read_count += 1
                return result
            if command == 0x02:
                # The page latch wraps, with the last byte sent to each slot
                # replacing the old latch value before the single NOR program.
                address = (self.address & ~255) | ((self.address+index-3) & 255)
                self.page[address] = value
        return 255

    def _finish(self):
        command = self.command
        if command is None or self.ignored:
            return
        if command in (0x06,0x04,0xB9,0x66,0x99,0xC7,0x60) and self.index:
            self._warning('命令长度错误，事务未执行')
            return
        if command == 0x06:
            self.wel = True
        elif command == 0x04:
            self.wel = False
        elif command == 0xB9:
            self.deep_power_down = True
        elif command == 0xAB:
            self.deep_power_down = False
        elif command == 0x66:
            self.reset_enabled = True
        elif command == 0x99:
            if self.reset_enabled:
                self.wel = self.deep_power_down = self.reset_enabled = False
                # Reset during WIP aborts this functional model's pending write;
                # real partially programmed contents are unspecified.
                self.pending = None
        elif command in (0x02,0x20,0x52,0xD8,0xC7,0x60):
            if (command == 0x02 and not self.page) or (command in (0x20,0x52,0xD8) and self.index != 3):
                self._warning('缺少地址/数据或擦除命令长度错误，事务未执行')
                return
            if not self.wel:
                self._warning('WEL=0，编程/擦除命令被器件忽略')
                return
            self.wel = False
            self.last_address = self.address
            if command == 0x02:
                self.pending = {'kind':'program','data':dict(self.page),'until':self.clock+256}
            else:
                length = {0x20:4096,0x52:32768,0xD8:65536,0xC7:CAPACITY,0x60:CAPACITY}[command]
                start = self.address & ~(length-1)
                duration = 2048 if length == 4096 else 8192 if length == CAPACITY else 4096
                self.pending = {'kind':'erase','start':start,'length':length,'until':self.clock+duration}

    def state(self):
        self._advance()
        return {'model':'GD25Q40E','capacityBytes':CAPACITY,'jedecId':'C8 40 13',
                'status':'busy' if self.pending else 'deep-power-down' if self.deep_power_down else 'ready',
                'lastCommand':self.last_command,'lastAddress':self.last_address,
                'readCount':self.read_count,'writeCount':self.write_count,'eraseCount':self.erase_count,
                'programmedBytes':self.programmed_bytes,'writeEnabled':self.wel,'selected':self.selected,
                'previewAddress':0,'preview':list(self.memory[:64]),
                'persistence':'session','timing':'instruction-based functional timing'}
