"""GD32F470 internal Flash programming used by the supplied V2 driver.

Operations complete synchronously in this functional model. Unlock sequences,
program widths, one-way bit transitions and 4 KiB page boundaries are enforced.
"""
from unicorn import UC_PROT_READ, UC_PROT_WRITE, UC_PROT_EXEC

FLASH = 0x08000000
SIZE = 0x80000
BASE = 0x40023C00


class InternalFlash:
    def __init__(self, sim):
        self.sim = sim
        self.reset()

    def reset(self):
        self.control = 1 << 31
        self.status = 0
        self.page_config = 0
        self.page_unlocked = False
        self.key_stage = 0
        self.erase_count = 0
        self.program_count = 0

    def contains(self, address):
        return self.sim.board['id'] == 'cimc-v2' and BASE <= address <= BASE + 0x100

    def read(self, address):
        offset = address - BASE
        if offset == 12:
            return self.status
        if offset == 16:
            return self.control
        if offset == 32:
            return self.page_config
        if offset in (0, 4, 36, 252, 256):
            return self.sim.regs.get(address, 0)
        return self.sim._unsupported(address, '读取')

    def write(self, address, value, size=4, byte_offset=0):
        offset = address - BASE
        if offset == 4:
            if self.key_stage == 1 and value == 0xCDEF89AB:
                self.control &= ~(1 << 31)
                self.key_stage = 0
            else:
                self.key_stage = int(value == 0x45670123)
        elif offset == 12:
            self.status &= ~(value & (((1 << (size * 8)) - 1) << (byte_offset * 8)))
        elif offset == 36:
            self.page_unlocked = value == 0xA9B8C7D6
        elif offset == 32:
            if self.page_unlocked:
                self.page_config = value
            else:
                self.status |= 1 << 4
        elif offset == 16:
            if self.control & (1 << 31):
                return
            self.control = value
            if value & ((1 << 24) | (1 << 25)):
                self.sim.diagnose('FMC 中断模式尚未实现')
                return
            if value & (1 << 16):
                self._erase()
                self.control &= ~(1 << 16)
        elif offset not in (0, 252):
            self.sim._unsupported(address, '写入')

    def _erase(self):
        if self.control & (1 << 31):
            self.status |= 1 << 4
            return
        if self.control & 4:
            start, length = FLASH, SIZE
        elif self.control & 2 and self.page_config & (1 << 31):
            start = self.page_config & 0x1FFFFFFF
            length = 4096
            if not self.page_unlocked or start % length:
                self.status |= 1 << 7
                return
        elif self.control & 2:
            sector = (self.control >> 3) & 31
            boundaries = (0, 0x4000, 0x8000, 0xC000, 0x10000, 0x20000, 0x40000, 0x60000, SIZE)
            if sector >= len(boundaries) - 1:
                self.status |= 1 << 7
                return
            start = FLASH + boundaries[sector]
            length = boundaries[sector + 1] - boundaries[sector]
        else:
            self.status |= 1 << 7
            return
        if not FLASH <= start < start + length <= FLASH + SIZE:
            self.status |= 1 << 7
            return
        self._store(start, b'\xff' * length)
        self.erase_count += 1
        self.status |= 1

    def program(self, address, size, value):
        canonical = address if address >= FLASH else address + FLASH
        if self.control & (1 << 31) or not self.control & 1:
            self.status |= 1 << 4
            return False
        expected = 1 << ((self.control >> 8) & 3)
        if size != expected or size not in (1, 2, 4) or canonical % size:
            self.status |= 1 << 6
            return False
        if not FLASH <= canonical < canonical + size <= FLASH + SIZE:
            self.status |= 1 << 7
            return False
        data = value.to_bytes(size, 'little')
        offset = canonical - FLASH
        old = self.sim.internal_flash[offset:offset + size]
        if any((before & after) != after for before, after in zip(old, data)):
            self.status |= 1 << 7
            return False
        self._store(canonical, data)
        # Unicorn retries a protected CPU store after its fault callback returns.
        # Restore protection at the following instruction boundary.
        page = address & ~4095
        self.sim.uc.mem_protect(page, 4096, UC_PROT_READ | UC_PROT_WRITE | UC_PROT_EXEC)
        self.sim._flash_write_pages.add(page)
        self.program_count += 1
        self.status |= 1
        return True

    def _store(self, address, data):
        offset = address - FLASH
        previous = bytes(self.sim.internal_flash[offset:offset + len(data)])
        try:
            self.sim.uc.mem_write(address, data)
            self.sim.uc.mem_write(offset, data)
            self.sim.uc.ctl_remove_cache(address, address + len(data))
            self.sim.uc.ctl_remove_cache(offset, offset + len(data))
        except Exception:
            try:
                self.sim.uc.mem_write(address, previous)
                self.sim.uc.mem_write(offset, previous)
                self.sim.uc.ctl_remove_cache(address, address + len(data))
                self.sim.uc.ctl_remove_cache(offset, offset + len(data))
            except Exception as rollback_error:
                self.sim.diagnose('Flash 映射恢复失败：' + str(rollback_error))
            raise
        self.sim.internal_flash[offset:offset + len(data)] = data
        self.sim.flash_dirty = True

    def state(self):
        return {'locked': bool(self.control & (1 << 31)), 'status': self.status,
                'eraseCount': self.erase_count, 'programCount': self.program_count,
                'modified': getattr(self.sim, 'flash_dirty', False), 'pageSize': 4096}
