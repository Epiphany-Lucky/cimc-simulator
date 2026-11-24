"""GD32F470 polling SDIO and a removable, byte-addressed SDSC image.

The CPU moves 32-bit words through the FIFO. Successful writes commit one
sector at a time. Controller resets and power changes leave the image intact.
"""

from dataclasses import dataclass, field


BASE = 0x40012C00
APB2_RESET = 0x40023824
APB2_ENABLE = 0x40023844
SDIO_CLOCK_BIT = 1 << 11
MAX_SD_IMAGE_BYTES = 128 * 1024 * 1024
SECTOR_SIZE = 512

POWER, CLOCK, ARGUMENT, COMMAND = 0x00, 0x04, 0x08, 0x0C
RESPONSE_COMMAND, RESPONSE0 = 0x10, 0x14
DATA_TIMEOUT, DATA_LENGTH, DATA_CONTROL, DATA_COUNT = 0x24, 0x28, 0x2C, 0x30
STATUS, CLEAR, INTERRUPT_ENABLE, FIFO_COUNT, FIFO = 0x34, 0x38, 0x3C, 0x48, 0x80
SDIO_FIFO_ADDRESS = BASE + FIFO

COMMAND_CRC_ERROR = 1 << 0
DATA_CRC_ERROR = 1 << 1
COMMAND_TIMEOUT = 1 << 2
DATA_TIMED_OUT = 1 << 3
COMMAND_RECEIVED = 1 << 6
COMMAND_SENT = 1 << 7
DATA_END = 1 << 8
DATA_BLOCK_END = 1 << 10
TX_RUNNING, RX_RUNNING = 1 << 12, 1 << 13
TX_HALF_EMPTY, RX_HALF_FULL = 1 << 14, 1 << 15
RX_FULL = 1 << 17
TX_EMPTY, RX_EMPTY = 1 << 18, 1 << 19
RX_AVAILABLE = 1 << 21
STICKY_FLAGS = 0x7FF | (3 << 22)

DATA_ENABLE, FROM_CARD, STREAM_MODE, DMA_ENABLE = (1 << bit for bit in range(4))
COMMAND_ENABLE = 1 << 10
R1_OUT_OF_RANGE, R1_ADDRESS_ERROR, R1_BLOCK_LENGTH_ERROR = (1 << bit for bit in (31, 30, 29))
R1_WRITE_PROTECT, R1_ILLEGAL_COMMAND = 1 << 26, 1 << 22

IDLE, READY, IDENTIFICATION, STANDBY, TRANSFER, SENDING, RECEIVING = range(7)
RCA = 1
OCR = 0x80FF8000  # Ready, standard capacity, 2.7–3.6 V.
CID = int.from_bytes(b'\x03CMSTUDI\x10\x10\x00\x00\x01\x01\xA1\x01', 'big')
SCR = b'\x02\x05\x00\x00\x00\x00\x00\x00'  # SD 2.0, 1-bit and 4-bit.


def is_sdio_fifo(address):
    return SDIO_FIFO_ADDRESS <= address < BASE + 0x100 and address % 4 == 0


@dataclass
class DataTransfer:
    receive: bool
    start: int = 0
    multiple: bool = False
    metadata: bytes = b''
    length: int = 0
    position: int = 0
    expires: int | None = None
    write_buffer: bytearray = field(default_factory=bytearray)

    @property
    def block_size(self):
        return len(self.metadata) or SECTOR_SIZE

    @property
    def remaining(self):
        return self.length - self.position


class SdioDevice:
    def __init__(self, sim):
        self.sim = sim
        self.image = None
        self.name = None
        self.read_only = False
        self.csd = 0
        self.sectors_read = self.sectors_written = 0
        self.reset()

    @staticmethod
    def contains(address):
        return BASE <= address < BASE + 0x100

    @property
    def inserted(self):
        return self.image is not None

    @property
    def card_detect_level(self):
        return int(not self.inserted)

    @staticmethod
    def _image_csd(size, read_only):
        sectors = size // SECTOR_SIZE
        for multiplier in range(8):
            groups, remainder = divmod(sectors, 1 << (multiplier + 2))
            if 1 <= groups <= 4096 and not remainder:
                break
        else:
            raise ValueError('镜像容量无法用 SDSC 的 512 字节扇区容量编码表示')

        # CSD v1.0. C_SIZE and C_SIZE_MULT describe the exact image length.
        return (0x0E << 112 | 0x32 << 96 | 0x5B5 << 84 | 9 << 80 | 1 << 79 |
                (groups - 1) << 62 | multiplier << 47 | 1 << 46 | 127 << 39 |
                2 << 26 | 9 << 22 | int(read_only) << 12 | 1)

    def mount(self, raw, name='sd-card.img', read_only=False):
        if not isinstance(raw, (bytes, bytearray)):
            raise ValueError('SD 卡镜像必须是原始字节')
        if not raw or len(raw) % SECTOR_SIZE or len(raw) > MAX_SD_IMAGE_BYTES:
            raise ValueError('SD 卡镜像必须由 512 字节扇区组成，大小不超过 128 MiB')
        csd = self._image_csd(len(raw), read_only)
        image = bytearray(raw)
        self.eject()
        self.image = image
        self.name = name
        self.read_only = bool(read_only)
        self.csd = csd

    def eject(self):
        if self.transfer is not None:
            self.data_failure |= DATA_TIMED_OUT
        self._reset_card()
        self.image = None
        self.name = None
        self.read_only = False
        self.csd = 0
        self.sectors_read = self.sectors_written = 0

    def export(self):
        if not self.inserted:
            raise ValueError('没有可导出的 SD 卡镜像')
        return bytes(self.image)

    def state(self):
        return {
            'inserted': self.inserted,
            'readOnly': self.read_only,
            'capacityBytes': len(self.image) if self.inserted else 0,
            'sectorsRead': self.sectors_read,
            'sectorsWritten': self.sectors_written,
            'name': self.name,
        }

    def _reset_card(self):
        self.card_state = IDLE
        self.application_command = False
        self.card_width = 1
        self.block_length = SECTOR_SIZE
        self.transfer = None
        self.stop_state = None

    def _reset_controller(self):
        self.registers = {offset: 0 for offset in (
            POWER, CLOCK, ARGUMENT, COMMAND, DATA_TIMEOUT, DATA_LENGTH, DATA_CONTROL, INTERRUPT_ENABLE)}
        self.flags = 0
        self.data_failure = 0
        self.command_status_pending = False
        self.response_command = 0
        self.response = (0, 0, 0, 0)
        self.transfer = None
        self.stop_state = None

    def reset(self):
        self._reset_controller()
        self._reset_card()

    def notify_rcu_write(self, address, value):
        if address == APB2_RESET and value & SDIO_CLOCK_BIT:
            self._reset_controller()

    def _clocked(self):
        return bool(self.sim.regs.get(APB2_ENABLE, 0) & SDIO_CLOCK_BIT and
                    not self.sim.regs.get(APB2_RESET, 0) & SDIO_CLOCK_BIT)

    def _host_width(self):
        return (1, 4, 8, 0)[self.registers[CLOCK] >> 11 & 3]

    def _signal_path(self, width):
        return width in (1, 4) and self.sim._sdio_path(wide=width == 4)

    def _abort_transfer(self, error=0):
        self.transfer = None
        self.stop_state = None
        self.data_failure |= error

    def _refresh_transfer(self):
        transfer = self.transfer
        if transfer and transfer.length:
            if (self.sim.timing_ticks >= transfer.expires or not self.registers[CLOCK] & (1 << 8) or
                    not self._signal_path(self._host_width())):
                self._abort_transfer(DATA_TIMED_OUT)

    def _data_status(self):
        status = TX_EMPTY | RX_EMPTY
        transfer = self.transfer
        if transfer is None or not transfer.length:
            return status
        if not transfer.receive:
            return status | TX_RUNNING | TX_HALF_EMPTY
        words = min(32, (transfer.remaining + 3) // 4)
        status = TX_EMPTY | RX_RUNNING | RX_AVAILABLE
        if words >= 8:
            status |= RX_HALF_FULL
        if words == 32:
            status |= RX_FULL
        return status

    def read(self, address):
        if not self._clocked():
            return 0
        self._refresh_transfer()
        offset = address - BASE
        if offset in self.registers:
            return self.registers[offset]
        if offset == STATUS:
            if not self.command_status_pending:
                self.flags |= self.data_failure
                self.data_failure = 0
            self.command_status_pending = False
            return self.flags | self._data_status()
        if offset == RESPONSE_COMMAND:
            return self.response_command
        if RESPONSE0 <= offset <= RESPONSE0 + 12:
            return self.response[(offset - RESPONSE0) // 4]
        if offset == DATA_COUNT:
            return self.transfer.remaining if self.transfer else 0
        if offset == FIFO_COUNT:
            return (self.transfer.remaining + 3) // 4 if self.transfer else 0
        if is_sdio_fifo(address):
            return self._read_fifo()
        if offset == CLEAR:
            return 0
        return self.sim._unsupported(address, '读取')

    def write(self, address, value, size=4, byte_offset=0):
        if not self._clocked():
            return
        self._refresh_transfer()
        offset = address - BASE
        mask = ((1 << (size * 8)) - 1) << (byte_offset * 8)
        if offset == CLEAR:
            self.flags &= ~(value & mask & STICKY_FLAGS)
            return
        if is_sdio_fifo(address):
            if size == 4:
                self._write_fifo(value & 0xFFFFFFFF)
            else:
                self.sim.diagnose('SDIO FIFO 需要 32 位访问')
            return
        if offset not in self.registers:
            if offset not in (RESPONSE_COMMAND, DATA_COUNT, STATUS, FIFO_COUNT) and not RESPONSE0 <= offset <= RESPONSE0 + 12:
                self.sim._unsupported(address, '写入')
            return
        merged = (self.registers[offset] & ~mask) | (value & mask)
        if offset == POWER:
            self.registers[offset] = merged & 3
            if self.registers[offset] != 3:
                self._reset_card()
        elif offset == COMMAND:
            self.registers[offset] = merged & (0x7FFF ^ COMMAND_ENABLE)
            if merged & COMMAND_ENABLE:
                self._execute_command(merged & 63, (merged >> 6) & 3)
        elif offset == DATA_CONTROL:
            was_enabled = self.registers[offset] & DATA_ENABLE
            self.registers[offset] = merged & 0xFFF
            if not merged & DATA_ENABLE:
                if was_enabled:
                    self._abort_transfer()
                    self.data_failure = 0
            elif merged & DMA_ENABLE:
                self._abort_transfer(DATA_TIMED_OUT)
                self.sim.diagnose('SDIO DMA 传输尚未实现')
            else:
                self._start_transfer()
        elif offset == INTERRUPT_ENABLE:
            self.registers[offset] = merged & 0xFFFFFF
            if self.registers[offset]:
                self.sim.diagnose('SDIO 中断传输尚未实现')
        else:
            self.registers[offset] = merged & (0x1FFFFFF if offset == DATA_LENGTH else 0xFFFFFFFF)

    def _r1(self, error=0):
        card_state = self.card_state if self.stop_state is None else self.stop_state
        if self.transfer and self.transfer.length:
            card_state = SENDING if self.transfer.receive else RECEIVING
        ready = 1 << 8 if card_state in (STANDBY, TRANSFER) else 0
        return (card_state << 9) | ready | error

    def _execute_command(self, command, response_type):
        argument = self.registers[ARGUMENT]
        is_application = self.application_command and command != 55
        self.application_command = False
        self.response = (0, 0, 0, 0)
        self.response_command = 0
        self.command_status_pending = False
        powered = self.registers[POWER] == 3 and self.registers[CLOCK] & (1 << 8)
        available = powered and self.inserted and self._signal_path(1)
        if not response_type:
            if command == 0 and available:
                self._reset_card()
            self.flags |= COMMAND_SENT
            return
        if not available:
            self.flags |= COMMAND_TIMEOUT
            if self.transfer is not None:
                self._abort_transfer(DATA_TIMED_OUT)
            return

        # HOST observes the command response before a following data failure.
        # The firmware can W1C the command flags between its two polling loops.
        self.command_status_pending = True
        response, flag = self._card_command(command, argument, is_application)
        self.flags |= flag
        if flag == COMMAND_TIMEOUT:
            return
        self.response_command = 63 if command in (2, 9, 10) or (is_application and command == 41) else command
        if response_type == 3:
            self.response = tuple(response >> shift & 0xFFFFFFFF for shift in (96, 64, 32, 0))
        else:
            self.response = (response & 0xFFFFFFFF, 0, 0, 0)

    def _card_command(self, command, argument, is_application):
        state = self.card_state
        if is_application:
            return self._application_command(command, argument)
        if command == 55:
            if argument >> 16 != (RCA if state >= STANDBY else 0):
                return 0, COMMAND_TIMEOUT
            self.application_command = True
            return self._r1(1 << 5), COMMAND_RECEIVED
        if command == 8:
            return (argument & 0xFFF, COMMAND_RECEIVED) if state == IDLE and argument & 0xF00 == 0x100 else (0, COMMAND_TIMEOUT)
        if command == 2 and state == READY:
            self.card_state = IDENTIFICATION
            return CID, COMMAND_RECEIVED
        if command == 3 and state in (IDENTIFICATION, STANDBY):
            self.card_state = STANDBY
            return (RCA << 16) | self._r1(), COMMAND_RECEIVED
        if command in (9, 10, 13) and argument >> 16 == RCA and state >= STANDBY:
            response = {9: self.csd, 10: CID, 13: self._r1()}[command]
            return response, COMMAND_RECEIVED
        if command == 7:
            if argument >> 16 == RCA and state in (STANDBY, TRANSFER):
                self.card_state = TRANSFER
                return self._r1(), COMMAND_RECEIVED
            if argument >> 16 == 0 and state == TRANSFER:
                self._abort_transfer()
                self.card_state = STANDBY
            return 0, COMMAND_TIMEOUT
        if command == 12 and state == TRANSFER:
            self._abort_transfer()
            return self._r1(), COMMAND_RECEIVED
        if state == TRANSFER and self.stop_state is None:
            if command == 16:
                if 1 <= argument <= SECTOR_SIZE and argument & (argument - 1) == 0:
                    self.block_length = argument
                    return self._r1(), COMMAND_RECEIVED
                return self._r1(R1_BLOCK_LENGTH_ERROR), COMMAND_RECEIVED
            if command in (17, 18, 24, 25):
                return self._storage_command(command, argument), COMMAND_RECEIVED
        return self._r1(R1_ILLEGAL_COMMAND), COMMAND_RECEIVED

    def _application_command(self, command, argument):
        if command == 41 and self.card_state in (IDLE, READY):
            ready = bool(argument & (OCR & 0xFFFFFF))
            if ready:
                self.card_state = READY
            # R3/OCR contains no CRC. This controller reports CCRCERR on R3.
            return (OCR if ready else OCR & 0x7FFFFFFF), COMMAND_CRC_ERROR
        if self.card_state == TRANSFER and self.stop_state is None:
            if command == 6 and argument in (0, 2):
                self.card_width = 4 if argument == 2 else 1
                return self._r1(), COMMAND_RECEIVED
            if command in (13, 51):
                status = bytes([0x80 if self.card_width == 4 else 0]) + bytes(63)
                self.transfer = DataTransfer(receive=True, metadata=SCR if command == 51 else status)
                self._start_transfer()
                return self._r1(), COMMAND_RECEIVED
        return self._r1(R1_ILLEGAL_COMMAND), COMMAND_RECEIVED

    def _storage_command(self, command, offset):
        receive = command in (17, 18)
        if offset >= len(self.image):
            return self._r1(R1_OUT_OF_RANGE)
        if offset % SECTOR_SIZE:
            return self._r1(R1_ADDRESS_ERROR)
        if self.block_length != SECTOR_SIZE:
            return self._r1(R1_BLOCK_LENGTH_ERROR)
        if not receive and self.read_only:
            return self._r1(R1_WRITE_PROTECT)
        self.transfer = DataTransfer(receive, start=offset, multiple=command in (18, 25))
        self._start_transfer()
        return self._r1()

    def _start_transfer(self):
        transfer = self.transfer
        control = self.registers[DATA_CONTROL]
        if (transfer is None or transfer.length or not control & DATA_ENABLE or
                bool(control & FROM_CARD) != transfer.receive):
            return
        width = self._host_width()
        timeout = self.registers[DATA_TIMEOUT]
        length = self.registers[DATA_LENGTH]
        block_size = 1 << (control >> 4 & 15)
        if not timeout or width != self.card_width or not self._signal_path(width):
            self._abort_transfer(DATA_TIMED_OUT)
            return
        if (control & STREAM_MODE or block_size != transfer.block_size or not length or
                length % block_size or (not transfer.multiple and length != block_size) or
                (not transfer.metadata and transfer.start + length > len(self.image))):
            self._abort_transfer(DATA_CRC_ERROR)
            return
        # The functional board model uses a nominal 48 MHz SDIO kernel clock.
        clock = self.registers[CLOCK]
        divider = 1 if clock & (1 << 10) else ((clock & 255) | ((clock >> 23) & 256)) + 2
        hclk_ticks = (timeout * divider * self.sim.hclk_frequency() + 47999999) // 48000000
        transfer.length = length
        transfer.expires = self.sim.timing_ticks + max(1, hclk_ticks)

    def _complete_word(self, transfer):
        transfer.position += 4
        if transfer.position % transfer.block_size == 0:
            self.flags |= DATA_BLOCK_END
        if not transfer.remaining:
            self.flags |= DATA_END
            if transfer.multiple:
                self.stop_state = SENDING if transfer.receive else RECEIVING
            self.transfer = None

    def _read_fifo(self):
        transfer = self.transfer
        if transfer is None or not transfer.receive or not transfer.length:
            return 0
        if transfer.metadata:
            value = transfer.metadata[transfer.position:transfer.position + 4]
        else:
            start = transfer.start + transfer.position
            value = self.image[start:start + 4]
            if (transfer.position + 4) % SECTOR_SIZE == 0:
                self.sectors_read += 1
        self._complete_word(transfer)
        return int.from_bytes(value, 'little')

    def _write_fifo(self, value):
        transfer = self.transfer
        if transfer is None or transfer.receive or not transfer.length:
            return
        transfer.write_buffer.extend(value.to_bytes(4, 'little'))
        if len(transfer.write_buffer) == SECTOR_SIZE:
            end = transfer.start + transfer.position + 4
            self.image[end - SECTOR_SIZE:end] = transfer.write_buffer
            transfer.write_buffer.clear()
            self.sectors_written += 1
        self._complete_word(transfer)
