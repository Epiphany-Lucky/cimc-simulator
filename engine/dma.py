"""GD32F470 DMA registers and direct USART receive transfers to SRAM."""

from dataclasses import dataclass
from itertools import islice


DMA_BASE = 0x40026000
DMA_STRIDE = 0x400
RCU_AHBRST = 0x40023810
RCU_AHBEN = 0x40023830
EN, CIRC, MINC = 1, 1 << 8, 1 << 10
DMAR = 1 << 6
FE, DME, TE, HT, TC = (1 << bit for bit in (0, 2, 3, 4, 5))
IRQ_NUMBERS = ((11, 12, 13, 14, 15, 16, 17, 47), (56, 57, 58, 59, 60, 68, 69, 70))
FLAG_SHIFTS = (0, 6, 16, 22)
# Physical controller/stream/request numbers. STM32 calls USART0 "USART1"
# and the controller at 0x40026400 "DMA2".
RX_ROUTES = {
    'USART0': ((1, 2, 4), (1, 5, 4)),
    'USART1': ((0, 5, 4),),
    'USART2': ((0, 1, 4),),
    'UART3': ((0, 2, 4),),
    'UART4': ((0, 0, 4),),
    'USART5': ((1, 1, 5), (1, 2, 5)),
    'UART6': ((0, 3, 5),),
    'UART7': ((0, 6, 5),),
}
ROUTE_UART = {route: uart for uart, routes in RX_ROUTES.items() for route in routes}


@dataclass
class Stream:
    control: int = 0
    remaining: int = 0
    peripheral: int = 0
    memory: int = 0
    second_memory: int = 0
    fifo: int = 0x21
    flags: int = 0
    count: int = 0
    width: int = 1


class DmaBank:
    def __init__(self, sim, uart, sram_start, sram_size):
        self.sim = sim
        self.uart = uart
        self.sram_start = sram_start
        self.sram_end = sram_start + sram_size
        self.reset()

    def reset(self):
        self.streams = [[Stream() for _ in range(8)] for _ in range(2)]
        self.irqs = 0

    @staticmethod
    def contains(address):
        return (DMA_BASE <= address < DMA_BASE + 0xD0 or
                DMA_BASE + DMA_STRIDE <= address < DMA_BASE + DMA_STRIDE + 0xD0)

    def _clocked(self, controller):
        return bool(self.sim.regs.get(RCU_AHBEN, 0) & (1 << (21 + controller)) and
                    not self.sim.regs.get(RCU_AHBRST, 0) & (1 << (21 + controller)))

    def _refresh_irq(self, controller, index):
        stream = self.streams[controller][index]
        enabled = (stream.control & 0x1E) << 1 | ((stream.fifo >> 7) & FE)
        irq = 1 << IRQ_NUMBERS[controller][index]
        if self._clocked(controller) and stream.flags & enabled:
            self.irqs |= irq
        else:
            self.irqs &= ~irq

    def notify_rcu_write(self, address, value):
        if address not in (RCU_AHBEN, RCU_AHBRST):
            return
        for controller, streams in enumerate(self.streams):
            if address == RCU_AHBRST and value & (1 << (21 + controller)):
                streams[:] = [Stream() for _ in streams]
            for index in range(len(streams)):
                self._refresh_irq(controller, index)
        # A buffered USART request can become serviceable after enabling a DMA clock.
        for uart in RX_ROUTES:
            self.service_rx(uart)

    def read(self, address):
        controller, offset = divmod(address - DMA_BASE, DMA_STRIDE)
        if not self._clocked(controller):
            return 0
        if offset < 0x10:
            if offset >= 8:
                return 0  # Write-only flag clear registers.
            first = offset
            return sum(self.streams[controller][first + i].flags << shift
                       for i, shift in enumerate(FLAG_SHIFTS))
        index, register = divmod(offset - 0x10, 0x18)
        stream = self.streams[controller][index]
        return (stream.control, stream.remaining, stream.peripheral, stream.memory,
                stream.second_memory, stream.fifo)[register // 4]

    def write(self, address, value, size, byte_offset):
        controller, offset = divmod(address - DMA_BASE, DMA_STRIDE)
        if not self._clocked(controller):
            return
        mask = ((1 << (size * 8)) - 1) << (byte_offset * 8)
        if offset < 0x10:
            if offset >= 8:
                first = offset - 8
                for i, shift in enumerate(FLAG_SHIFTS):
                    self.streams[controller][first + i].flags &= ~((value & mask) >> shift)
                    self._refresh_irq(controller, first + i)
            return
        index, register = divmod(offset - 0x10, 0x18)
        stream = self.streams[controller][index]
        merged = (self.read(address) & ~mask) | (value & mask)
        if register == 0:
            self._write_control(controller, index, stream, merged)
        elif register == 0x14:
            writable = 0x80 if stream.control & EN else 0x87
            stream.fifo = 0x20 | (stream.fifo & ~writable) | (merged & writable)
        elif not stream.control & EN:
            if register == 4:
                stream.remaining = merged & 0xFFFF
                stream.count = stream.remaining
            elif register == 8:
                stream.peripheral = merged
            elif register == 0xC:
                stream.memory = merged
            elif register == 0x10:
                stream.second_memory = merged
        self._refresh_irq(controller, index)

    def _write_control(self, controller, index, stream, value):
        if stream.control & EN:
            stream.control = (stream.control & ~0x1F) | (value & 0x1F)
            if not stream.control & EN:
                stream.flags |= TC
            return
        stream.control = value & 0x0FEFFFFF
        if not value & EN:
            return
        if stream.flags & TC:
            stream.control &= ~EN
            return
        request = (value >> 25) & 7
        uart = ROUTE_UART.get((controller, index, request))
        forbidden = (3 << 23) | (3 << 21) | (3 << 18) | (1 << 15) | (1 << 9) | (3 << 6) | (1 << 5)
        peripheral_size = (value >> 11) & 3
        memory_size = (value >> 13) & 3
        if (uart is None or stream.peripheral != self.uart[uart] + 4 or
                value & forbidden or stream.fifo & 4 or peripheral_size != memory_size or peripheral_size == 3):
            stream.control &= ~EN
            self.sim.diagnose(f'DMA{controller} CH{index} 请求 {request} 的配置尚未实现，支持 USART 直接接收至 SRAM')
            return
        stream.remaining = stream.count
        stream.width = 1 << peripheral_size
        if not stream.count:
            stream.control &= ~EN
            return
        for other_controller, other_index, other_request in RX_ROUTES[uart]:
            other = self.streams[other_controller][other_index]
            if other is not stream and other.control & EN and (other.control >> 25) & 7 == other_request:
                stream.control &= ~EN
                self.sim.diagnose(f'{uart} DMA 接收请求同时启用了两个通道')
                return
        self.service_rx(uart)

    def service_rx(self, uart):
        base = self.uart[uart]
        queue = self.sim.rx[uart]
        rx_enabled = (1 << 13) | (1 << 2)
        if (not queue or not self.sim.uc or not self.sim.regs.get(base + 20, 0) & DMAR or
                self.sim.regs.get(base + 12, 0) & rx_enabled != rx_enabled):
            return
        for controller, index, request in RX_ROUTES[uart]:
            if not self._clocked(controller):
                continue
            stream = self.streams[controller][index]
            if not stream.control & EN or (stream.control >> 25) & 7 != request:
                continue
            self._transfer_rx(controller, index, stream, queue)
            if not queue:
                self.sim.uart_idle[uart] = True
                break
        self.sim._refresh_uart_irq(uart)

    def _transfer_rx(self, controller, index, stream, queue):
        width = stream.width
        increment = bool(stream.control & MINC)
        buffer_end = stream.memory + width * (stream.count if increment else 1)
        if stream.memory % width or not self.sram_start <= stream.memory < buffer_end <= self.sram_end:
            stream.flags |= TE
            stream.control &= ~EN
            self._refresh_irq(controller, index)
            self.sim.diagnose(f'DMA{controller} CH{index} 接收缓冲区越界或地址未对齐：0x{stream.memory:08X}', 'warning')
            return

        # A terminal send supplies a batch of bytes. Transfers are atomic with
        # respect to CPU execution and use the same SRAM as firmware loads.
        while queue and stream.control & EN:
            before = stream.remaining
            length = min(before, len(queue))
            offset = (stream.count - before) * width if increment else 0
            values = bytes(islice(queue, length))
            if not increment:
                payload = values[-1].to_bytes(width, 'little')
            elif width == 1:
                payload = values
            else:
                expanded = bytearray(length * width)
                expanded[::width] = values
                payload = bytes(expanded)
            self.sim.uc.mem_write(stream.memory + offset, payload)
            for _ in range(length):
                queue.popleft()
            stream.remaining -= length
            if stream.count > 1 and stream.remaining <= stream.count // 2 < before:
                stream.flags |= HT
            if not stream.remaining:
                stream.flags |= TC
                if stream.control & CIRC:
                    stream.remaining = stream.count
                else:
                    stream.control &= ~EN
        self._refresh_irq(controller, index)
