"""CIMC Lab: real Cortex-M4 execution with an explicit GD32F470 peripheral subset.

This is a functional model, not a cycle-accurate/electrical simulation. Missing
MMIO stops execution; loading a firmware is never evidence of full compatibility.
"""
from __future__ import annotations
import base64
from collections import deque
import json
import math
from pathlib import Path
import struct
import threading
import time
import uuid

from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_INVALID, UC_HOOK_INTR, UC_PROT_READ, UC_PROT_WRITE, UC_PROT_EXEC, UC_MEM_WRITE_PROT
from unicorn.arm_const import *
from adc import AdcDevice
from spiflash import SpiFlashDevice
from app_version import VERSION
from firmware_images import parse_firmware, parse_image, assemble, prepare_set
from fmc import InternalFlash
from v2_devices import V2Devices
from timers import TimerBank
from watchdogs import Watchdogs

FLASH = 0x08000000
FLASH_SIZE = 0x80000
SRAM = 0x20000000
SRAM_SIZE = 0x30000
CCM = 0x10000000
CCM_SIZE = 0x10000
GPIO = {f'P{chr(65+i)}':0x40020000+i*0x400 for i in range(9)}
UART = {'USART0':0x40011000,'USART1':0x40004400,'USART2':0x40004800,'UART3':0x40004C00,'UART4':0x40005000,'USART5':0x40011400,'UART6':0x40007800,'UART7':0x40007C00}
UART_IRQ = dict(zip(UART, (37, 38, 39, 52, 53, 71, 82, 83)))
UART_FRAME_FIELDS = ('dataBits', 'parity', 'stopBits')
UART_STOP_BITS = (1, 0.5, 2, 1.5)  # USART_CTL1.STB / USART_CR2.STOP encoding.
CORE_REGS = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R12, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_XPSR]


def validate_serial_settings(value):
    """Validate and copy a terminal frame independently of the firmware state."""
    if not isinstance(value, dict) or value.keys() != {'baudRate', *UART_FRAME_FIELDS}:
        raise ValueError('串口参数必须包含波特率、数据位、校验位和停止位')
    baud, data_bits, parity, stop_bits = (value[key] for key in ('baudRate', *UART_FRAME_FIELDS))
    if type(baud) is not int or not 1 <= baud <= 12_000_000:
        raise ValueError('串口波特率必须为 1～12000000 的整数')
    if type(data_bits) is not int or data_bits not in (7, 8):
        raise ValueError('串口数据位只支持 7 或 8 位')
    if parity not in ('none', 'even', 'odd'):
        raise ValueError('串口校验位只支持无校验、偶校验或奇校验')
    if type(stop_bits) not in (int, float) or stop_bits not in UART_STOP_BITS:
        raise ValueError('串口停止位只支持 0.5、1、1.5 或 2 位')
    return dict(value)



class OLED:
    """SSD1306-style command/GDDRAM subset; model resolution comes from profile."""
    def __init__(self, width=128, height=32):
        self.width, self.height = width,height
        self.ram = bytearray(1024)
        self.column,self.page=0,0
        self.col_start,self.col_end=0,127
        self.page_start,self.page_end=0,height//8-1
        self.mode=2
        self.on=False
        self.inverted=False
        self.flip_x=False
        self.flip_y=False
        self.offset=0
        self.start_line=0
        self.pending=None
        self.args=[]
        self.count=0

    def command(self,b):
        if self.pending is not None:
            self.args.append(b)
            if len(self.args)<self.count:return
            cmd,args=self.pending,self.args
            if cmd==0x20:self.mode=args[0]&3
            elif cmd==0x21:self.col_start,self.col_end=args;self.column=self.col_start
            elif cmd==0x22:self.page_start,self.page_end=args;self.page=self.page_start
            elif cmd==0xD3:self.offset=args[0]&63
            self.pending=None;self.args=[]
            return
        if b in (0x20,0x81,0x8D,0xA8,0xD3,0xD5,0xD9,0xDA,0xDB):self.pending=b;self.count=1
        elif b in (0x21,0x22):self.pending=b;self.count=2
        elif 0xB0<=b<=0xB7:self.page=b&7
        elif 0<=b<=15:self.column=(self.column&0xF0)|b
        elif 0x10<=b<=0x1F:self.column=(self.column&15)|((b&15)<<4)
        elif b==0xAE:self.on=False
        elif b==0xAF:self.on=True
        elif b==0xA6:self.inverted=False
        elif b==0xA7:self.inverted=True
        elif b in (0xA0,0xA1):self.flip_x=bool(b&1)
        elif b in (0xC0,0xC8):self.flip_y=bool(b&8)
        elif 0x40<=b<=0x7F:self.start_line=b&63

    def data(self,b):
        if 0<=self.page<8 and 0<=self.column<128:self.ram[self.page*128+self.column]=b
        if self.mode==1:
            self.page+=1
            if self.page>self.page_end:self.page=self.page_start;self.column+=1
            if self.column>self.col_end:self.column=self.col_start
        else:
            self.column+=1
            if self.column>self.col_end:
                self.column=self.col_start
                if self.mode==0:
                    self.page+=1
                    if self.page>self.page_end:self.page=self.page_start

    def pixels(self):
        # Most modules are physically wired for A1/C8. The panel wiring is
        # reflected here; firmware remap commands still affect the visible image.
        result=[]
        for y in range(self.height):
            sy=(y if self.flip_y else self.height-1-y)+self.start_line+self.offset
            sy%=64
            for x in range(self.width):
                sx=x if self.flip_x else self.width-1-x
                bit=(self.ram[(sy//8)*128+sx]>>(sy%8))&1
                result.append(int(self.on and (bit^self.inverted)))
        return result


class Simulator:
    def __init__(self, root: Path, board_id='cimc-v1'):
        self.root=Path(root)
        self.lock=threading.RLock()
        self.status='idle'
        self.firmware=None
        self.uc=None
        self.image=None
        self.program=None
        self.internal_flash=bytearray()
        self.flash_dirty=False
        self._slice_deadline=None
        self._slice_timed_out=False
        self.wires=[]
        self.serial_mode='rs485'
        self.serial_settings={}
        self._connection_cache={}
        self.logs=[]
        self.diagnostics=[]
        self.sequence=0
        self.closed=False
        self.reset_flags=(1<<26)|(1<<27)
        self.board=self._load_board(board_id)
        self.keys=[False]*len(self.board.get('keyMappings',[]))
        self.adc=AdcDevice(self)
        self.flash=SpiFlashDevice(self)
        self.fmc=InternalFlash(self)
        self.v2_devices=V2Devices(self)
        self._reset_devices()
        self.worker=threading.Thread(target=self._worker,daemon=True)
        self.worker.start()

    def close(self):
        """Finish the current bounded native chunk before Python tears down callbacks."""
        self.closed=True
        # A daemon thread may otherwise still be inside Unicorn/ctypes when the
        # interpreter frees native state. No simulator lock is held while joining:
        # the worker needs that lock to finish its current 10,000-instruction chunk.
        self.worker.join()

    def _load_board(self, board_id='cimc-v1'):
        if board_id not in ('cimc-v1','cimc-v2'):
            raise ValueError('不支持的板卡版本')
        p=self.root/'web'/('board-v1.json' if board_id=='cimc-v1' else 'board-v2.json')
        if p.exists():
            board=json.loads(p.read_text(encoding='utf-8-sig'))
            board['ledMappings']=[{'net':m['terminal'],'active':0 if m.get('activeLow') else 1} for m in board.get('leds',[])]
            board['keyMappings']=[{'net':m['terminal'],'active':0 if m.get('activeLow') else 1,'idle':m.get('idle',1)} for m in board.get('keys',[])]
            board['serialMappings']={}
            for channel,uart in board.get('uart_channels',{}).items():
                if not uart:continue
                details=board.get('uart',{}).get(channel,{})
                item={'uart':uart,**details}
                if details.get('de'):item.update(dePin=details['de'],deActive=1)
                board['serialMappings'][channel]=item
            board['fixedConnections']=[]
            for net in board.get('fixedNets',[])+board.get('provisionalFixedNets',[]):
                nodes=net.get('nodes',[])
                board['fixedConnections'].extend([[nodes[0],n] for n in nodes[1:]])
            return board
        raise FileNotFoundError('Missing board profile: '+str(p))

    def select_board(self, board_id):
        board=self._load_board(board_id)
        with self.lock:
            if board['id']==self.board['id']:
                return
            self.board=board
            self.wires=[]
            self.serial_mode='rs485'
            self.serial_settings.clear()
            self._connection_cache.clear()
            self._install_program(None,None)

    def _reset_devices(self):
        if hasattr(self, 'instructions'):self.flash.state()
        self.regs={0x40023874:self.reset_flags}
        self.instructions=0
        self.timing_ticks=0
        self._peripheral_ticks=0
        self._timing_deadline=math.inf
        self._timing_scheduled=False
        self._timing_check_mask=63
        self._syncing_timing=False
        self._inside_code_hook=False
        self.core_halted=False
        self.cpu_sleeping=False
        self._sleep_hints={}
        for pattern,hint in ((b'\x30\xbf','wfi'),(b'\x20\xbf','wfe'),
                             (b'\xaf\xf3\x03\x80','wfi'),(b'\xaf\xf3\x02\x80','wfe')):
            offset=self.internal_flash.find(pattern)
            while offset>=0:
                if not offset&1:
                    self._sleep_hints[FLASH+offset]=(hint,len(pattern))
                    self._sleep_hints[offset]=(hint,len(pattern))
                offset=self.internal_flash.find(pattern,offset+1)
        self.start_time=time.monotonic()
        self.gpio_state={p:{'mode':0,'otype':0,'pull':0,'out':0,'af0':0,'af1':0} for p in GPIO}
        self.rx={p:deque() for p in UART}
        self.uart_idle={p:False for p in UART}
        self.uart_status_read={p:False for p in UART}
        self.serial_pending={channel:bytearray() for channel in self.board['serialMappings']}
        self._serial_warnings={}
        o=self.board.get('oled',{})
        self.oled=OLED(o.get('width',128),o.get('height',32))
        self.i2c={'active':False,'count':0,'value':0,'phase':'address','selected':False,'ack':False,'ack_clock':False,'control':0,'scl':1,'sda':1}
        self.systick={'ctrl':0,'reload':0,'value':0,'flag':False,'pending':False}
        self.in_exception=False
        self.exception_stack=[]
        self.exception_return=False
        self.nvic_enable=0
        self.nvic_pending=0
        self.uart_irqs=0
        self.active_exception=0
        self.pending_reset=False
        self._flash_write_pages=set()
        self._conflicts=set()
        self._floating={}
        self._warned=set()
        self.adc.reset()
        self.flash.reset()
        self.fmc.reset()
        self.v2_devices.reset()
        if hasattr(self,'timers'):self.timers.reset()
        else:self.timers=TimerBank(self)
        if hasattr(self,'watchdogs'):self.watchdogs.reset()
        else:self.watchdogs=Watchdogs(self)
        self._refresh_timing_deadline()

    def diagnose(self,message,level='error',**details):
        self.sequence+=1
        self.diagnostics.append({'id':self.sequence,'level':level,'message':message,'time':time.strftime('%H:%M:%S'),**details})
        self.diagnostics=self.diagnostics[-100:]
        if level=='error':
            self.status='faulted'
            if self.uc:self.uc.emu_stop()

    def _channel(self,uart):
        mapping=self.board.get('serialMappings',{})
        for channel,m in mapping.items():
            if m['uart']==uart and self._uart_path(channel,'tx'):return channel
        return None

    def _uart_path(self,channel,direction):
        m=self.board['serialMappings'][channel]
        pins=m.get(direction+'Pins',[m[direction]])
        return any(self._uart_pin_path(m,pin,direction) for pin in pins)

    def _uart_pin_path(self,m,pin,direction):
        terminal=m[direction+'Terminal']
        nets=self.connected(pin)
        if terminal not in nets:return False
        g=self.gpio_state[pin[:2]];n=int(pin[2:])
        if (g['mode']>>(2*n))&3!=2:return False
        af=self.regs.get(GPIO[pin[:2]]+(32 if n<8 else 36),0)
        if (af>>(4*(n%8)))&15!=m['af']:return False
        # UART bit timing is abstracted; reject forced static levels on signal nets.
        if any(net in nets for net in ('DGND','AGND','GND','3V3','5V')):return False
        for net in nets:
            if net[:2] in GPIO and net[2:].isdigit() and net!=pin:
                p=int(net[2:])
                if p<16 and (self.gpio_state[net[:2]]['mode']>>(2*p))&3==1:return False
        if direction=='rx':
            sources=[other for other,desc in self.board['serialMappings'].items() if desc['rxTerminal'] in nets]
            if len(sources)>1:return False
        return True

    def _serial_log(self,channel,direction,data):
        if not data or channel is None:return
        self.sequence+=1
        self.logs.append({'id':self.sequence,'channel':channel,'direction':direction,'text':bytes(data).decode('utf-8','replace'),'hex':' '.join(f'{b:02X}' for b in data),'time':time.strftime('%H:%M:%S')})
        self.logs=self.logs[-300:]

    def _uart_parameters(self,uart):
        base=UART[uart]
        control=self.regs.get(base+12,0)
        baud_register=self.regs.get(base+8,0)&0xFFFF
        mantissa=baud_register>>4
        if not control&(1<<13) or not mantissa:return None
        oversample=8 if control&(1<<15) else 16
        divisor=mantissa*oversample+(baud_register&(oversample-1))
        peripheral_clock=self.hclk_frequency()//self.apb_clock_ratio(uart in ('USART0','USART5'))[1]
        parity_enabled=bool(control&(1<<10))
        parity=('odd' if control&(1<<9) else 'even') if parity_enabled else 'none'
        data_bits=8+bool(control&(1<<12))-parity_enabled
        stop_bits=UART_STOP_BITS[(self.regs.get(base+16,0)>>12)&3]
        return {'baudRate':peripheral_clock/divisor,'dataBits':data_bits,'parity':parity,'stopBits':stop_bits}

    @staticmethod
    def _serial_compatible(settings,parameters):
        if settings is None or parameters is None:return None
        # Baud register rounding introduces a small mismatch even for equal
        # nominal rates. Use a functional 3% tolerance against the terminal rate.
        baud=settings['baudRate']
        return (abs(baud-parameters['baudRate'])<=baud*.03 and
                all(settings[key]==parameters[key] for key in UART_FRAME_FIELDS))

    def _serial_accepts(self,channel,uart):
        settings=self.serial_settings.get(channel)
        if settings is None:return True
        parameters=self._uart_parameters(uart)
        if self._serial_compatible(settings,parameters):
            self._serial_warnings.pop(channel,None)
            return True
        if channel not in self._serial_warnings or self._serial_warnings[channel]!=parameters:
            self._serial_warnings[channel]=parameters
            def format_frame(frame):
                return f"{frame['baudRate']:.0f} 波特，{frame['dataBits']}{frame['parity'][0].upper()}{frame['stopBits']:g}"
            actual=format_frame(parameters) if parameters else '尚未配置有效波特率'
            self.diagnose(f'{channel.upper()} 串口参数不匹配，数据未传输（终端 {format_frame(settings)}，固件 {actual}）',
                          'warning',channel=channel,code='serial-config')
        return False

    def _flush_serial_channel(self,channel):
        pending=self.serial_pending[channel]
        self._serial_log(channel,'tx',pending)
        pending.clear()

    def _flush_uart(self):
        for channel,pending in self.serial_pending.items():
            if pending:self._flush_serial_channel(channel)

    def _set_serial_settings(self,channel,value):
        if not isinstance(channel,str) or channel not in self.board['serialMappings']:
            raise ValueError('未核验的串口映射')
        settings=None if value is None else validate_serial_settings(value)
        if settings==self.serial_settings.get(channel):return
        self._flush_serial_channel(channel)
        self._serial_warnings.pop(channel,None)
        if settings is None:self.serial_settings.pop(channel,None)
        else:self.serial_settings[channel]=settings

    def load(self,raw,name,address=FLASH):
        im=parse_image(raw,name,address)
        program=assemble((im,),im.base)
        with self.lock:self._install_program(program,self._make_cpu(program))

    def load_set(self,data):
        with self.lock:
            program=prepare_set(data,self.program.images if self.program else ())
            cpu=self._make_cpu(program)
            self._install_program(program,cpu)

    def _make_cpu(self,program):
        # Allocate and configure before touching the running machine. Invalid sets
        # and native allocation failures leave the old CPU and peripherals intact.
        uc=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
        uc.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M4)
        for base in (FLASH,0):
            uc.mem_map(base,FLASH_SIZE)
            uc.mem_write(base,program.flash)
            uc.mem_protect(base,FLASH_SIZE,UC_PROT_READ|UC_PROT_EXEC)
        uc.mem_map(SRAM,SRAM_SIZE)
        uc.mem_map(CCM,CCM_SIZE,UC_PROT_READ|UC_PROT_WRITE)
        uc.mmio_map(0x40000000,0x30000,self._mmio_read,0x40000000,self._mmio_write,0x40000000)
        uc.mmio_map(0x42000000,0x2000000,self._bitband_read,None,self._bitband_write,None)
        uc.mmio_map(0xE000E000,0x2000,self._mmio_read,0xE000E000,self._mmio_write,0xE000E000)
        uc.mmio_map(0xE0042000,0x1000,self._mmio_read,0xE0042000,self._mmio_write,0xE0042000)
        uc.hook_add(UC_HOOK_MEM_INVALID,self._invalid)
        uc.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,self._bitband_access,begin=0x42000000,end=0x43FFFFFF)
        uc.hook_add(UC_HOOK_CODE,self._code_hook)
        uc.hook_add(UC_HOOK_INTR,self._interrupt)
        uc.reg_write(UC_ARM_REG_SP,program.sp)
        uc.reg_write(UC_ARM_REG_MSP,program.sp)
        uc.reg_write(UC_ARM_REG_PC,program.entry)
        uc.reg_write(UC_ARM_REG_XPSR,0x01000000)
        return uc

    def _install_program(self,program,cpu):
        self.program=program
        self.image=program.flash if program else None
        self.internal_flash=bytearray(program.flash) if program else bytearray()
        self.flash_dirty=False
        self.logs=[];self.diagnostics=[]
        if program:
            self.base=program.boot_address;self.initial_sp=program.sp;self.entry=program.entry
            boot=next(im for im in program.images if im.id==program.boot_image_id)
            self.firmware={**boot.metadata(),'entry':f'0x{program.entry:08X}'}
        else:self.firmware=None
        self._reset_devices()
        self.uc=cpu
        self.keys=[False]*len(self.board.get('keyMappings',[]))
        if program:self.regs[0xE000ED08]=program.boot_address
        self.status='ready' if program else 'idle'

    def reset(self,*,preserve_ram=False):
        with self.lock:
            if self.program is None:return False
            if not self.pending_reset:self.reset_flags|=1<<26
            try:program=self._current_program()
            except ValueError as error:
                self.pending_reset=False
                self.diagnose('系统复位失败：'+str(error))
                return False
            ram=bytes(self.uc.mem_read(SRAM,SRAM_SIZE)) if preserve_ram and self.uc else None
            ccm=bytes(self.uc.mem_read(CCM,CCM_SIZE)) if preserve_ram and self.uc else None
            cpu=self._make_cpu(program)
            if ram is not None:
                cpu.mem_write(SRAM,ram)
                cpu.mem_write(CCM,ccm)
            self.program=program
            self.image=program.flash
            self.flash_dirty=False
            boot=next(im for im in program.images if im.id==program.boot_image_id)
            self.firmware={**boot.metadata(),'entry':f'0x{program.entry:08X}'}
            self._reset_devices()
            self.keys=[False]*len(self.board.get('keyMappings',[]))
            self.uc=cpu
            self.regs[0xE000ED08]=self.program.boot_address
            self.status='ready'
            return True

    def _current_program(self):
        if not self.flash_dirty:
            return self.program
        snapshot=parse_image(bytes(self.internal_flash),'internal-flash.bin',FLASH)
        return assemble((snapshot,),self.program.boot_address)

    def hclk_frequency(self):
        configuration=self.regs.get(0x40023808,0)
        source=configuration&3
        frequency=16000000
        if source==1:frequency=25000000
        elif source==2:
            pll=self.regs.get(0x40023804,0x24003010)
            divider=pll&63
            multiplier=(pll>>6)&511
            output_divider=2*(((pll>>16)&3)+1)
            if divider and multiplier:
                input_frequency=25000000 if pll&(1<<22) else 16000000
                frequency=input_frequency*multiplier//(divider*output_divider)
        ahb_shifts=(0,0,0,0,0,0,0,0,1,2,3,4,6,7,8,9)
        return max(1,frequency>>ahb_shifts[(configuration>>4)&15])

    def apb_clock_ratio(self,apb2=False):
        shift=13 if apb2 else 10
        selection=(self.regs.get(0x40023808,0)>>shift)&7
        return 1,1<<max(0,selection-3)

    def timer_clock_ratio(self,apb2=False):
        _,divider=self.apb_clock_ratio(apb2)
        multiplier=4 if self.regs.get(0x4002388C,0)&(1<<24) else 2
        return 1,max(1,divider//multiplier)

    def _refresh_timing_deadline(self):
        self.timer_irqs=self.timers.pending_irqs()
        self.watchdog_irqs=self.watchdogs.pending_irqs()
        intervals=(self.timers.next_event_ticks(),self.watchdogs.next_event_ticks())
        available=[value for value in intervals if value is not None]
        self._timing_scheduled=bool(available)
        self._timing_deadline=self.timing_ticks+max(1,min(available)) if available else math.inf
        self._timing_check_mask=7 if available and min(available)<=self.board.get('clockTicksPerInstruction',1) else 63

    def _sync_timing(self):
        if self._syncing_timing:return
        elapsed=self.timing_ticks-self._peripheral_ticks
        if elapsed<=0:return
        self._syncing_timing=True
        try:
            self._peripheral_ticks=self.timing_ticks
            self.timers.advance(elapsed)
            self.watchdogs.advance(elapsed)
            self._refresh_timing_deadline()
        finally:self._syncing_timing=False

    def request_system_reset(self,reason='software'):
        bits={'software':28,'fwdgt':29,'wwdgt':30}
        self.reset_flags|=1<<bits[reason]
        self.pending_reset=True
        if self.uc and not self._inside_code_hook:self.uc.emu_stop()

    def timer_trigger(self,timer,event,level=True):
        self.adc.timer_trigger(timer,event,level)
        self.v2_devices.timer_trigger(timer,event,level)

    def _invalid(self,uc,access,address,size,value,user):
        if access==UC_MEM_WRITE_PROT and self.board['id']=='cimc-v2' and (0<=address<FLASH_SIZE or FLASH<=address<FLASH+FLASH_SIZE):
            if self.fmc.program(address,size,value):return True
            self.diagnose(f'FMC 拒绝 Flash 写入：0x{address:08X}，状态 0x{self.fmc.status:08X}')
            return False
        self.diagnose(f'未映射或受保护的内存访问：0x{address:08X}',address=f'0x{address:08X}',pc=f'0x{uc.reg_read(UC_ARM_REG_PC):08X}')
        return False

    def _mmio_read(self,uc,offset,size,base):
        try:
            address=base+offset
            v=self._read(address&~3)
            return (v>>((address&3)*8))&((1<<(8*size))-1)
        except Exception as e:self.diagnose('外设读取失败：'+str(e));return 0

    def _mmio_write(self,uc,offset,size,value,base):
        address=base+offset
        try:self._write(address&~3,value<<((address&3)*8),size,address&3)
        except Exception as e:self.diagnose('外设写入失败：'+str(e))

    def _bitband_target(self,offset,size):
        if size!=4 or offset&3:
            raise ValueError(f'外设位带要求字对齐32位访问：0x{0x42000000+offset:08X}')
        # ARM Cortex-M4 TRM 3.7. One alias word selects one register bit.
        return 0x40000000+(offset//128)*4,(offset//4)%32

    def _bitband_access(self,uc,access,address,size,value,user):
        # Validate the original CPU transfer before Unicorn splits unaligned MMIO.
        try:self._bitband_target(address-0x42000000,size)
        except ValueError as error:self.diagnose(str(error))

    def _bitband_read(self,uc,offset,size,user):
        if self.status=='faulted':return 0
        try:
            address,bit=self._bitband_target(offset,size)
            return (self._read(address)>>bit)&1
        except Exception as error:
            self.diagnose('外设位带读取失败：'+str(error));return 0

    def _bitband_write(self,uc,offset,size,value,user):
        if self.status=='faulted':return
        try:
            address,bit=self._bitband_target(offset,size)
            previous=self._read(address)
            if self.status=='faulted':return
            self._write(address,(previous&~(1<<bit))|((value&1)<<bit))
        except Exception as error:self.diagnose('外设位带写入失败：'+str(error))

    def _unsupported(self,a,operation):
        self.diagnose(f'尚未实现的寄存器{operation}：0x{a:08X}',address=f'0x{a:08X}',pc=f'0x{self.uc.reg_read(UC_ARM_REG_PC):08X}')
        return 0

    def _read(self,a):
        self._sync_timing()
        if self.timers.contains(a):
            value=self.timers.read(a)
            self._refresh_timing_deadline()
            return value
        if self.watchdogs.contains(a):return self.watchdogs.read(a)
        if 0xE0042004<=a<=0xE004200C:return self.regs.get(a,0)
        if self.adc.contains(a):return self.adc.read(a)
        if self.flash.contains(a):return self.flash.read(a)
        if self.fmc.contains(a):return self.fmc.read(a)
        if self.v2_devices.contains(a):return self.v2_devices.read(a)
        if 0xE000E100<=a<0xE000E120 or 0xE000E180<=a<0xE000E1A0:
            return (self.nvic_enable>>(((a&0x7F)//4)*32))&0xFFFFFFFF
        if 0xE000E200<=a<0xE000E220 or 0xE000E280<=a<0xE000E2A0:
            return (self._pending_irqs()>>(((a&0x7F)//4)*32))&0xFFFFFFFF
        if 0xE000E300<=a<0xE000E320:
            active=sum(1<<(number-16) for number in self.exception_stack+[self.active_exception] if number>=16)
            return (active>>(((a-0xE000E300)//4)*32))&0xFFFFFFFF
        if 0xE000E400<=a<0xE000E500 or 0xE000ED18<=a<=0xE000ED20:return self.regs.get(a,0)
        for port,b in GPIO.items():
            if b<=a<b+0x400:
                g=self.gpio_state[port];o=a-b
                if o==0:return g['mode']
                if o==4:return g['otype']
                if o==12:return g['pull']
                if o==16:
                    levels=[self.net_level(f'{port}{i}') for i in range(16)]
                    mask=sum((1<<i) for i,v in enumerate(levels) if v is None)
                    if mask and port not in self._floating:
                        self._floating[port]=mask
                        self.diagnose(f'{port} 输入存在悬空/不确定位 0x{mask:04X}；读取采用确定性 0，不能据此判定接线有效','warning')
                    return sum((v or 0)<<i for i,v in enumerate(levels))
                if o==20:return g['out']
                if o in (8,24,28,32,36,40):return self.regs.get(a,0)
                return self._unsupported(a,'读取')
        for uart,b in UART.items():
            if b<=a<b+0x20:
                o=a-b
                if o==0:
                    control=self.regs.get(b+12,0)
                    if not control&(1<<13):return 0
                    self.uart_status_read[uart]=True
                    return (0xC0 if control&(1<<3) else 0)|(0x20 if self.rx[uart] and control&(1<<2) else 0)|(0x10 if self.uart_idle[uart] else 0)
                if o==4:
                    if self.uart_status_read[uart]:self.uart_idle[uart]=False
                    self.uart_status_read[uart]=False
                    if not self.rx[uart]:
                        self._refresh_uart_irq(uart)
                        return 0
                    value=self.rx[uart].popleft()
                    if not self.rx[uart]:self.uart_idle[uart]=True
                    self._refresh_uart_irq(uart)
                    return value
                if o in (8,12,16,20,24):return self.regs.get(a,0)
                return self._unsupported(a,'读取')
        if 0x40023800<=a<=0x40023898:
            o=a-0x40023800;v=self.regs.get(a,0x83 if o==0 else 0)
            if o==0:
                v=(v&~0x0A020002)|((v&1)<<1)|((v&(1<<16))<<1)|((v&(1<<24))<<1)|((v&(1<<26))<<1)
            if o==8:v=(v&~12)|((v&3)<<2)
            if o==0x70:v|=(v&1)<<1
            if o==0x74:v|=(v&1)<<1
            return v
        if a==0x40023C00:return self.regs.get(a,0)
        if a==0x40007004 and self.board['id']=='cimc-v2':
            return self.regs.get(a,0)|(self.regs.get(0x40007000,0)&0x30000)
        if a in (0x40007000,0x40007004):return self.regs.get(a,0)
        if a==0xE000E010:
            v=self.systick['ctrl']|(0x10000 if self.systick['flag'] else 0);self.systick['flag']=False;return v
        if a==0xE000E014:return self.systick['reload']
        if a==0xE000E018:return self.systick['value']
        if a==0xE000E01C:return 10000
        if a==0xE000ED00:return 0x410FC241
        if a==0xE000ED0C:return 0xFA050000|self.regs.get(a,0)
        if a==0xE000ED04:
            pending=self._pending_exception()
            return ((1<<11) if len(self.exception_stack)<=1 else 0)|self.active_exception|(pending<<12)|((1<<26) if self.systick['pending'] else 0)
        if a in (0xE000ED04,0xE000ED08,0xE000ED0C,0xE000ED10,0xE000ED14,0xE000ED18,0xE000ED1C,0xE000ED20,0xE000ED24,0xE000ED28,0xE000ED2C,0xE000ED88):return self.regs.get(a,0)
        return self._unsupported(a,'读取')

    def _write(self,a,v,size=4,byte_offset=0):
        self._sync_timing()
        try:self._write_register(a,v,size,byte_offset)
        finally:
            if 0x40020000<=a<0x40022400:self.timers.sample_inputs()
            self._refresh_timing_deadline()

    def _write_register(self,a,v,size=4,byte_offset=0):
        if self.timers.contains(a):return self.timers.write(a,v,size,byte_offset)
        if self.watchdogs.contains(a):return self.watchdogs.write(a,v,size,byte_offset)
        if a==0xE000ED0C:
            if v>>16==0x5FA:
                self.regs[a]=v&0x700
                if v&4:self.request_system_reset('software')
            return
        mask=((1<<(size*8))-1)<<(byte_offset*8)
        if 0xE000E100<=a<0xE000E120:
            self.nvic_enable|=(v&mask)<<(((a-0xE000E100)//4)*32);return
        if 0xE000E180<=a<0xE000E1A0:
            self.nvic_enable&=~((v&mask)<<(((a-0xE000E180)//4)*32));return
        if 0xE000E200<=a<0xE000E220:
            self.nvic_pending|=(v&mask)<<(((a-0xE000E200)//4)*32);return
        if 0xE000E280<=a<0xE000E2A0:
            self.nvic_pending&=~((v&mask)<<(((a-0xE000E280)//4)*32));return
        if a==0xE000ED04:
            # Act only on the written bits, never replay a previous W1 command.
            command=v&mask
            if command&((1<<31)|(1<<28)):
                self.diagnose('NMI/PendSV 异常尚未实现');return
            if command&(1<<25) and command&(1<<26):
                self.diagnose('ICSR 同时设置和清除 SysTick pending 属于不可预测操作');return
            if command&(1<<25):self.systick['pending']=False
            if command&(1<<26):self.systick['pending']=True
            # PENDSVCLR clears an already-empty pending state in this subset.
            # Other bits are read-only/reserved; zero writes have no effect.
            return
        previous=self.regs.get(a,0)
        v=((previous&~mask)|(v&mask))&0xFFFFFFFF
        self.regs[a]=v
        if self.adc.contains(a):return self.adc.write(a,v,size,byte_offset)
        if self.flash.contains(a):return self.flash.write(a,v,size,byte_offset)
        if self.fmc.contains(a):return self.fmc.write(a,v,size,byte_offset)
        if self.v2_devices.contains(a):return self.v2_devices.write(a,v,size,byte_offset)
        if 0xE000E400<=a<0xE000E500:
            self.regs[a]=v&0xF0F0F0F0
            return
        if 0xE000ED18<=a<=0xE000ED20:
            self.regs[a]=v&0xF0F0F0F0
            return
        if 0xE0042004<=a<=0xE004200C:return
        for port,b in GPIO.items():
            if b<=a<b+0x400:
                g=self.gpio_state[port];o=a-b
                if o==0:g['mode']=v
                elif o==4:g['otype']=v
                elif o==12:g['pull']=v
                elif o==20:g['out']=v&0xFFFF
                elif o==24:g['out']=((g['out']|(v&65535))&~(v>>16))&65535
                elif o==40:g['out']&=~v&65535
                elif o not in (8,28,32,36):return self._unsupported(a,'写入')
                oled=self.board.get('oled',{})
                if self.board['id']=='cimc-v2' or port in (oled.get('scl','')[:2],oled.get('sda','')[:2]):self._i2c_edges()
                self.flash.on_gpio_changed(port)
                return
        for uart,b in UART.items():
            if b<=a<b+0x20:
                o=a-b
                if o==4:
                    if self.regs.get(b+12,0)&((1<<13)|(1<<3))!=((1<<13)|(1<<3)):return
                    channel=self._uart_tx_channel(uart)
                    if channel is not None:
                        pending=self.serial_pending[channel]
                        if self._serial_accepts(channel,uart):
                            bits=self.serial_settings.get(channel,{}).get('dataBits',8)
                            byte=v&((1<<bits)-1)
                            pending.append(byte)
                            if byte==10 or len(pending)>=512:self._flush_serial_channel(channel)
                        elif pending:self._flush_serial_channel(channel)
                elif o==12 and v&((1<<6)|(1<<7)):
                    self.diagnose(f'{uart} 发送中断模式尚未实现；支持 RXNE/IDLE 接收中断及轮询收发')
                elif o==20 and v&((1<<6)|(1<<7)):
                    self.diagnose(f'{uart} DMA 模式尚未实现')
                elif o not in (0,8,12,16,20,24):return self._unsupported(a,'写入')
                self._refresh_uart_irq(uart)
                return
        if 0x40023800<=a<=0x40023898:
            if a==0x40023874:
                if v&(1<<24):self.reset_flags=0
                self.regs[a]=(v&0xFFFFFF)|self.reset_flags
            self.timers.notify_rcu_write(a,self.regs[a])
            self.watchdogs.notify_rcu_write(a,self.regs[a])
            self.adc.notify_rcu_write(a,v)
            self.v2_devices.notify_rcu_write(a,v)
            if a==0x40023820 and v&(1<<14):self.flash.reset(controller_only=True)
            return
        if a in (0x40023C00,0x40007000,0x40007004):return
        if a==0xE000E010:self.systick['ctrl']=v&7;return
        if a==0xE000E014:self.systick['reload']=v&0xFFFFFF;return
        if a==0xE000E018:
            self.systick['value']=0;self.systick['flag']=False;self.systick['clockPhase']=0
            return
        if a in (0xE000ED04,0xE000ED08,0xE000ED0C,0xE000ED10,0xE000ED14,0xE000ED18,0xE000ED1C,0xE000ED20,0xE000ED24,0xE000ED28,0xE000ED2C,0xE000ED88):return
        return self._unsupported(a,'写入')

    def _uart_tx_channel(self,uart):
        channel=self._channel(uart)
        if channel is None:return None
        m=self.board['serialMappings'][channel]
        if not m.get('dePin') or self.net_level(m['dePin'])==m.get('deActive',1):return channel
        return None

    def _code_hook(self,uc,address,size,user):
        if self.pending_reset or self.cpu_sleeping:
            uc.emu_stop();return
        if self._flash_write_pages:
            for page in self._flash_write_pages:uc.mem_protect(page,4096,UC_PROT_READ|UC_PROT_EXEC)
            self._flash_write_pages.clear()
        # Bound uninterrupted native code too, without creating a native timeout
        # watchdog on each ISR restart (its shutdown adds a per-interrupt delay).
        if self._slice_deadline is not None and self.instructions&self._timing_check_mask==0:
            if time.monotonic()>=self._slice_deadline:
                self._slice_timed_out=True
                uc.emu_stop();return
        # This callback precedes execution. Deliver an already-pending exception
        # without counting or ticking the thread instruction we are about to stop.
        # Most instructions have no pending exception. Keep that path free of
        # native register reads and priority selection calls.
        pending=self.systick['pending'] or (self.nvic_enable and
            (self.nvic_pending|self.uart_irqs|self.timer_irqs|self.watchdog_irqs)&self.nvic_enable)
        if pending and self._eligible_exception():
            uc.emu_stop();return
        hint=None
        if self.flash_dirty or address>=FLASH+FLASH_SIZE:
            hint=self._sleep_hint(uc,address,size)
        elif self._sleep_hints:
            cached=self._sleep_hints.get(address)
            if cached and cached[1]==size:hint=cached[0]
        if hint=='wfe':
            self.diagnose('WFE 事件等待尚未实现')
            return
        if hint=='wfi' and self.regs.get(0xE000ED10,0)&4:
            self.diagnose('WFI 深度休眠的时钟和电源域尚未实现')
            return
        self.instructions+=1
        ticks=self.board.get('clockTicksPerInstruction',1)
        self.timing_ticks+=ticks
        if self._timing_scheduled and self.timing_ticks>=self._timing_deadline:
            self._inside_code_hook=True
            try:self._sync_timing()
            finally:self._inside_code_hook=False
        st=self.systick
        if st['ctrl']&1:
            # The linear HCLK path cannot set flags. Reload, zero transitions and
            # the divided clock retain the shared event implementation below.
            if st['ctrl']&4 and ticks<st['value']:
                st['value']-=ticks
            else:self._advance_systick(ticks)
        if hint=='wfi':self.cpu_sleeping=not bool(self._eligible_exception(ignore_primask=True))
        # A newly pending exception is delivered at the next instruction boundary.

    def _sleep_hint(self,uc,address,size):
        if not self.flash_dirty and address<FLASH+FLASH_SIZE:
            cached=self._sleep_hints.get(address)
            return cached[0] if cached and cached[1]==size else None
        offset=address-FLASH if address>=FLASH else address
        raw=(self.internal_flash[offset:offset+size] if 0<=offset<len(self.internal_flash)
             else uc.mem_read(address,size))
        if raw in (b'\x30\xbf',b'\xaf\xf3\x03\x80'):return 'wfi'
        if raw in (b'\x20\xbf',b'\xaf\xf3\x02\x80'):return 'wfe'
        return None

    def _advance_systick(self,ticks):
        st=self.systick
        if not st['ctrl']&1:return
        if not st['ctrl']&4:
            ticks,st['clockPhase']=divmod(st.get('clockPhase',0)+ticks,8)
        if not ticks:return
        wrapped=False
        if st['value']:
            if ticks<st['value']:
                st['value']-=ticks
                return
            ticks-=st['value']
            st['value']=0
            wrapped=True
        if st['reload'] and ticks:
            periods,phase=divmod(ticks,st['reload']+1)
            wrapped|=bool(periods)
            st['value']=st['reload']+1-phase if phase else 0
        if wrapped:
            st['flag']=True
            if st['ctrl']&2:st['pending']=True

    def _advance_sleep_clock(self):
        self._sync_timing()
        deadlines=[]
        if math.isfinite(self._timing_deadline):
            deadlines.append(max(1,self._timing_deadline-self.timing_ticks))
        st=self.systick
        if st['ctrl']&1 and (st['value'] or st['reload']):
            divider=1 if st['ctrl']&4 else 8
            phase=st.get('clockPhase',0) if divider==8 else 0
            remaining=st['value'] if st['value'] else st['reload']+1
            deadlines.append(max(1,remaining*divider-phase))
        if not deadlines:return False
        ticks=min(deadlines)
        self.timing_ticks+=ticks
        self._advance_systick(ticks)
        self._sync_timing()
        return True

    def _complete_pending_reset(self):
        was_running=self.status=='running'
        executed=self.instructions
        try:reset_ok=self.reset(preserve_ram=True)
        except ValueError as error:
            self.pending_reset=False
            self.diagnose('系统复位失败：'+str(error))
            return False
        if not reset_ok:return False
        self.instructions=executed
        if was_running:self.status='running'
        return True

    def _interrupt(self,uc,intno,user):
        if intno==8 and self.in_exception:self.exception_return=True;uc.emu_stop()
        else:self.diagnose(f'尚未实现的 CPU 异常：{intno}',pc=f'0x{uc.reg_read(UC_ARM_REG_PC):08X}')

    def _enter_systick(self):
        self._enter_exception(15)

    def _pending_irqs(self):
        return self.nvic_pending|self.uart_irqs|self.timer_irqs|self.watchdog_irqs

    def _refresh_uart_irq(self, uart):
        bit=1<<UART_IRQ[uart]
        control=self.regs.get(UART[uart]+12,0)
        active=control&(1<<13) and ((self.rx[uart] and control&(1<<5) and control&(1<<2)) or (self.uart_idle[uart] and control&(1<<4)))
        if active:self.uart_irqs|=bit
        else:self.uart_irqs&=~bit

    def _exception_priority(self,number):
        if number==15:return (self.regs.get(0xE000ED20,0)>>24)&0xF0
        index=number-16
        return (self.regs.get(0xE000E400+(index//4)*4,0)>>((index%4)*8))&0xF0

    def _pending_exception(self):
        candidates=[15] if self.systick['pending'] else []
        pending=self._pending_irqs()&self.nvic_enable
        while pending:
            bit=pending&-pending
            candidates.append(bit.bit_length()+15)
            pending^=bit
        return min(candidates,key=lambda number:(self._exception_priority(number),number)) if candidates else 0

    def _eligible_exception(self,*,ignore_primask=False):
        if not (self.systick['pending'] or (self.nvic_enable and
            (self.nvic_pending|self.uart_irqs|self.timer_irqs|self.watchdog_irqs)&self.nvic_enable)):return 0
        if not self.uc or (not ignore_primask and self.uc.reg_read(UC_ARM_REG_PRIMASK)) or self.uc.reg_read(UC_ARM_REG_FAULTMASK):return 0
        candidate=self._pending_exception()
        if not candidate:return 0
        priority=self._exception_priority(candidate)
        threshold=self.uc.reg_read(UC_ARM_REG_BASEPRI)&0xF0
        grouping=(self.regs.get(0xE000ED0C,0)>>8)&7
        subpriority_bits=max(0,grouping-3)
        if threshold and (priority>>(4+subpriority_bits))>=(threshold>>(4+subpriority_bits)):return 0
        if self.in_exception:
            current=self._exception_priority(self.active_exception)
            if (priority>>(4+subpriority_bits))>=(current>>(4+subpriority_bits)):return 0
        return candidate

    def _enter_exception(self, number):
        u=self.uc
        vector=self.regs.get(0xE000ED08,self.base)
        handler=int.from_bytes(u.mem_read(vector+number*4,4),'little')
        if not handler&1 or not FLASH <= (handler&~1)<FLASH+FLASH_SIZE:
            self.diagnose('SysTick 中断向量无效' if number==15 else f'异常 {number} 中断向量无效')
            return
        sp=u.reg_read(UC_ARM_REG_SP)-32
        frame=[u.reg_read(r) for r in CORE_REGS]
        u.mem_write(sp,struct.pack('<8I',*frame))
        u.reg_write(UC_ARM_REG_SP,sp)
        u.reg_write(UC_ARM_REG_LR,0xFFFFFFF1 if self.in_exception else 0xFFFFFFF9)
        u.reg_write(UC_ARM_REG_XPSR,(frame[-1]&0xF0000000)|0x01000000|number)
        u.reg_write(UC_ARM_REG_PC,handler)
        self.exception_stack.append(self.active_exception)
        self.in_exception=True;self.active_exception=number
        if number==15:self.systick['pending']=False
        else:self.nvic_pending&=~(1<<(number-16))

    def _return_exception(self):
        u=self.uc;sp=u.reg_read(UC_ARM_REG_SP)
        values=struct.unpack('<8I',u.mem_read(sp,32))
        for r,v in zip(CORE_REGS,values):u.reg_write(r,v)
        u.reg_write(UC_ARM_REG_SP,sp+32)
        self.active_exception=self.exception_stack.pop() if self.exception_stack else 0
        self.in_exception=bool(self.active_exception);self.exception_return=False
        u.reg_write(UC_ARM_REG_FAULTMASK,0)
        if not self.in_exception and self.regs.get(0xE000ED10,0)&2:
            self.cpu_sleeping=True

    def run_chunk(self,count=10000,*,max_duration=None):
        """Consume an instruction budget across exception boundaries.

        Manual calls are deterministic and remain usable after close() stops the
        worker. The optional wall-time ceiling is only a host responsiveness limit;
        it does not change the instruction-driven peripheral clock model.
        """
        if isinstance(count,bool) or not isinstance(count,int) or count<=0:
            raise ValueError('指令预算必须为正整数')
        if max_duration is not None and (isinstance(max_duration,bool) or
                not isinstance(max_duration,(int,float)) or not math.isfinite(max_duration) or max_duration<=0):
            raise ValueError('执行时间上限必须为有限正数')
        if not self.uc or self.status=='faulted':return 0
        started=self.instructions
        deadline=time.monotonic()+max_duration if max_duration is not None else None
        self._slice_deadline=deadline
        self._slice_timed_out=False
        try:
            while self.instructions-started<count and self.status!='faulted':
                if self.exception_return:self._return_exception()
                if deadline is not None and time.monotonic()>=deadline:break
                if self.cpu_sleeping:
                    if not self._eligible_exception(ignore_primask=True):
                        if not self._advance_sleep_clock():break
                        if self.pending_reset:
                            if not self._complete_pending_reset():break
                            continue
                        if not self._eligible_exception(ignore_primask=True):break
                    self.cpu_sleeping=False
                exception=self._eligible_exception()
                if exception:self._enter_exception(exception)
                if self.status=='faulted':break
                remaining=count-(self.instructions-started)
                before=self.instructions
                self.uc.emu_start(self.uc.reg_read(UC_ARM_REG_PC)|1,0,count=remaining)
                if self.pending_reset:
                    if not self._complete_pending_reset():break
                    continue
                returning=self.exception_return
                if returning:self._return_exception()
                if self.status=='faulted':break
                if deadline is not None and (self._slice_timed_out or time.monotonic()>=deadline):break
                eligible=self._eligible_exception()
                if self.instructions==before and not returning and not eligible and not self.cpu_sleeping:
                    self.diagnose('固件执行没有取得进展，也没有可处理的异常边界',pc=f'0x{self.uc.reg_read(UC_ARM_REG_PC):08X}')
                    break
        except UcError as e:
            if self.status!='faulted':self.diagnose(f'固件停止：{e}',pc=f'0x{self.uc.reg_read(UC_ARM_REG_PC):08X}')
        finally:
            self._slice_deadline=None
            self._slice_timed_out=False
        self._flush_uart()
        return self.instructions-started

    def _worker(self):
        while not self.closed:
            started=time.monotonic()
            with self.lock:
                if self.status=='running':self.run_chunk(max_duration=0.012)
            # Exception entry/return do not each incur a host sleep. Only the
            # unused part of the overall service period is idle; sleep(0) still
            # yields after an overrun so UI requests can acquire the lock.
            time.sleep(max(0,0.012-(time.monotonic()-started)))

    def _pin_net(self,pin):
        for p in self.board.get('pins',[]):
            if p['id']==pin:return p.get('net',p['id'])
        return pin

    def connected(self,net):
        if net in self._connection_cache:return self._connection_cache[net]
        reached={net}
        edges=[(self._pin_net(w['from']),self._pin_net(w['to'])) for w in self.wires]
        edges.extend((self._pin_net(w['from']),self._pin_net(w['to'])) for w in self.managed_wires())
        for edge in self.board.get('fixedConnections',[]):
            if isinstance(edge,dict):
                a,b=edge.get('from',edge.get('a')),edge.get('to',edge.get('b'))
                if a and b:edges.append((self._pin_net(a),self._pin_net(b)))
            else:edges.append((self._pin_net(edge[0]),self._pin_net(edge[1])))
        while True:
            n=len(reached)
            for a,b in edges:
                if a in reached or b in reached:reached.add(a);reached.add(b)
            if n==len(reached):
                for item in reached:self._connection_cache[item]=reached
                return reached

    def net_level(self,net,include_device=True,include_timers=True):
        nets=self.connected(self._pin_net(net));strong=[];weak=[]
        for n in nets:
            if n in ('GND','DGND','0V'):strong.append(0)
            if n in ('3V3','3.3V','VCC','5V'):strong.append(1)
            if len(n)>=3 and n[:2] in GPIO and n[2:].isdigit():
                pin=int(n[2:]);g=self.gpio_state[n[:2]]
                if pin>15:continue
                mode=(g['mode']>>(pin*2))&3;out=(g['out']>>pin)&1
                if mode==1 and not ((g['otype']>>pin)&1 and out):strong.append(out)
                if mode==2 and include_timers:
                    output=self.timers.pin_output(n)
                    if output is not None and not ((g['otype']>>pin)&1 and output):strong.append(output)
                pull=(g['pull']>>(pin*2))&3
                if pull in (1,2):weak.append(1 if pull==1 else 0)
        for i,k in enumerate(self.board.get('keyMappings',[])):
            if k.get('net',k.get('pin')) in nets:
                if i<len(self.keys) and self.keys[i]:strong.append(k.get('active',0))
                elif 'idle' in k:weak.append(k['idle'])
        o=self.board.get('oled',{})
        for pull in self.board.get('fixedPulls',[]):
            if pull['net'] in nets:weak.append(pull['level'])
        if include_device and self.i2c['ack'] and self.i2c.get('ack_drive') and o.get('sda') in nets:strong.append(0)
        if o.get('sda') in nets or o.get('scl') in nets:weak.append(1)
        if 0 in strong and 1 in strong:
            identity=tuple(sorted(nets))
            if identity not in self._conflicts:self._conflicts.add(identity);self.diagnose('线路输出冲突：'+' ↔ '.join(identity))
            return None
        if strong:return strong[0]
        if weak:return weak[0] if len(set(weak))==1 else None
        return None

    def _i2c_edges(self):
        o=self.board.get('oled',{})
        if not o.get('scl') or not o.get('sda'):return
        if not self._oled_powered():
            self.i2c.update(active=False,selected=False,ack=False,ack_drive=False)
            return
        scl=self.net_level(o['scl']);sda=self.net_level(o['sda'],include_device=False)
        scl=1 if scl is None else scl;sda=1 if sda is None else sda
        st=self.i2c;oldc,oldd=st['scl'],st['sda']
        # START/STOP can only occur while SCL stays high, not on its rising edge.
        if oldc==1 and scl==1 and oldd!=sda:
            if sda==0:st.update(active=True,count=0,value=0,phase='address',selected=False,ack=False,ack_clock=False,ack_drive=False)
            else:st.update(active=False,ack=False,ack_drive=False)
        elif st['active'] and oldc==0 and scl==1:
            if st['count']==8:st['ack_clock']=True
            else:
                st['value']=(st['value']<<1)|sda;st['count']+=1
                if st['count']==8:
                    b=st['value']
                    if st['phase']=='address':st['selected']=(b>>1)==o.get('address',60) and not b&1;st['phase']='control'
                    elif st['selected'] and st['phase']=='control':st['control']=b;st['phase']='data'
                    elif st['selected']:
                        if st['control']&0x40:self.oled.data(b)
                        else:self.oled.command(b)
                        if st['control']&0x80:st['phase']='control'
                    st['ack']=st['selected']
        elif st['active'] and oldc==1 and scl==0:
            if st['ack_clock']:
                st['count']=0;st['value']=0;st['ack']=False;st['ack_clock']=False;st['ack_drive']=False
            elif st['count']==8:st['ack_drive']=True
        st['scl'],st['sda']=scl,sda

    def _oled_powered(self):
        if self.board['id']!='cimc-v2':return True
        oled=self.board.get('oled',{})
        return self.net_level(oled.get('vccTerminal','OLED_3V3'))==1 and self.net_level(oled.get('gndTerminal','OLED_GND'))==0

    def apply_reference_wiring(self):
        if self.board['id']!='cimc-v2':raise ValueError('参考接线适用于 V2 板卡')
        staged=list(self.wires)
        pairs={frozenset((self._pin_net(w['from']),self._pin_net(w['to']))) for w in staged}
        for wire in self.board.get('defaultAddedWires',[]):
            pair=frozenset((self._pin_net(wire['a']),self._pin_net(wire['b'])))
            if pair in pairs:continue
            staged.append(self.validate_wire({'from':wire['a'],'to':wire['b']},staged))
            pairs.add(pair)
        self.wires=staged
        self._on_wiring_changed()

    def _on_wiring_changed(self):
        self._connection_cache.clear()
        if self.board['id']=='cimc-v2':
            self._i2c_edges()
            self.flash.on_gpio_changed('PA')
        self.timers.sample_inputs()
        self._refresh_timing_deadline()

    def command(self,data):
        action=data.get('action','')
        if action=='load':
            raw=base64.b64decode(data.get('data',data.get('dataBase64','')),validate=True)
            if len(raw)>4*1024*1024:raise ValueError('固件文件超过 4 MiB')
            a=data.get('address',FLASH);a=int(a,0) if isinstance(a,str) else int(a)
            self.load(raw,data.get('filename','firmware.bin'),a)
        elif action=='load_set':self.load_set(data)
        elif action=='board_select':self.select_board(data.get('boardId'))
        elif action=='v2_demo':
            images=[]
            for filename,address in (('v2-bootloader.bin',FLASH),('v2-app.bin',0x08011000)):
                path=self.root/'firmware'/filename
                images.append(parse_image(path.read_bytes(),filename,address))
            program=assemble(tuple(images),FLASH)
            cpu=self._make_cpu(program)
            board=self._load_board('cimc-v2')
            with self.lock:
                if board['id']!=self.board['id']:self.serial_settings.clear()
                self.board=board
                self.wires=[];self.serial_mode='rs485';self._connection_cache.clear()
                self._install_program(program,cpu)
                self.apply_reference_wiring()
        elif action=='timer_demo':
            p=self.root/'firmware'/'timer_probe.hex'
            self.load(p.read_bytes(),'GD32F470 · TIMER0–13.hex')
            with self.lock:
                self.wires=[]
                self._connection_cache.clear()
                pairs=[(f'PD{8+i}',f'LED{i+1}') for i in range(6)]
                if self.board['id']=='cimc-v2':
                    pairs.extend((wire['a'],wire['b']) for wire in self.board['defaultAddedWires']
                                 if wire['a'].startswith('H12.') and wire['b'].startswith('H12.'))
                for a,b in pairs:self.wires.append(self.validate_wire({'from':a,'to':b},self.wires))
                self._on_wiring_changed()
        elif action=='demo':
            p=self.root/'firmware'/'demo.hex';self.load(p.read_bytes(),'CIMC Lab · Keil demo.hex')
            self.serial_mode='rs485'
            self._connection_cache.clear()
            self.wires=[]
            for w in self.board.get('defaultAddedWires',[]):
                self.command({'action':'wire_add','from':w['a'],'to':w['b'],'color':'#0071e3' if 'led' in w['id'] else '#a855f7'})
            self.diagnose(f"已载入真实 Keil 示例固件与 {len(self.wires)} 条可删除示例跳线；原板固定网络未改变",'info')
        else:
            with self.lock:
                self._sync_timing()
                if action=='adc_voltage':self.adc.set_voltage(data.get('voltage'),data.get('channel',10))
                elif action=='v2_wiring':self.apply_reference_wiring()
                elif action=='serial_mode':self.set_serial_mode(data.get('mode'))
                elif action=='serial_settings':
                    if 'settings' not in data:raise ValueError('缺少串口参数')
                    self._set_serial_settings(data.get('channel'),data['settings'])
                elif action=='run':
                    if not self.uc:raise ValueError('请先载入固件')
                    if self.status=='faulted':raise ValueError('请先复位或载入其他固件')
                    self.status='running'
                elif action=='pause':
                    if self.status=='running':self.status='paused'
                elif action=='reset':self.reset()
                elif action=='step':
                    if not self.uc:raise ValueError('请先载入固件')
                    self.status='paused';self.run_chunk(1)
                elif action=='key':
                    i=int(data['index'])
                    if not 0<=i<len(self.keys):raise ValueError('无效的按键编号')
                    self.keys[i]=bool(data['pressed'])
                    self.timers.sample_inputs()
                    self._refresh_timing_deadline()
                elif action=='serial':
                    channel=data.get('channel','ch340');mapping=self.board.get('serialMappings',{}).get(channel)
                    if mapping is None:raise ValueError('未核验的串口映射')
                    uart=mapping['uart'] if isinstance(mapping,dict) else mapping
                    raw=base64.b64decode(data.get('data',''),validate=True)
                    limit=128*1024 if self.board['id']=='cimc-v2' else 4096
                    if len(raw)>limit:raise ValueError(f'单次最多发送 {limit} 字节')
                    if len(self.rx[uart])+len(raw)>limit:raise ValueError('串口接收队列已满，请等待 MCU 处理')
                    self._serial_log(channel,'rx',raw)
                    if not self._uart_path(channel,'rx'):
                        self.diagnose('串口接收线路未接通、被短接或 GPIO 复用未配置；请检查 '+', '.join(mapping.get('jumpers',[])),'warning')
                    elif isinstance(mapping,dict) and mapping.get('dePin') and self.net_level(mapping['dePin'])==mapping.get('deActive',1):
                        self.diagnose('RS485 处于发送状态，本次接收未送入 MCU','warning')
                    elif self.board['id']=='cimc-v2' and mapping.get('dePin') and self.net_level(mapping['dePin'])!=1-mapping.get('deActive',1):
                        self.diagnose('RS485 方向端子未连接或未配置接收电平，本次接收未送入 MCU','warning')
                    elif self.regs.get(UART[uart]+12,0)&((1<<13)|(1<<2))!=((1<<13)|(1<<2)):
                        self.diagnose(f'{uart} 尚未启用接收，本次输入未送入 MCU','warning')
                    elif raw and self._serial_accepts(channel,uart):
                        bits=self.serial_settings.get(channel,{}).get('dataBits',8)
                        self.rx[uart].extend((byte&0x7F for byte in raw) if bits==7 else raw)
                        self.uart_idle[uart]=False
                        self._refresh_uart_irq(uart)
                elif action=='wire_add':
                    wire=self.validate_wire(data,self.wires)
                    self.wires.append(wire)
                    self._on_wiring_changed()
                    self.net_level(wire['from'])
                elif action=='wire_remove':
                    if not any(w['id']==data.get('id') for w in self.wires):raise ValueError('只能删除用户添加的跳线，固定连线不可删除')
                    self.wires=[w for w in self.wires if w['id']!=data.get('id')]
                    self._on_wiring_changed()
                elif action=='project_load':
                    self.load_project(data.get('project',data))
                elif action=='clear_log':self.logs=[]
                else:raise ValueError('未知操作：'+action)
        return self.state()

    def managed_wires(self):
        if self.board['id']=='cimc-v2':return []
        patterns=self.board['serialJumperPatterns']
        return [{'id':f'fixed-{kind}-{i}','from':a,'to':b,'color':'#8094ad','locked':True}
                for kind in ('ch340',self.serial_mode) for i,(a,b) in enumerate(patterns[kind])]

    def set_serial_mode(self,mode,*,update_wires=True):
        if mode not in ('rs485','rs232'):raise ValueError('串口模式只允许 RS485 或 RS232')
        staged=None
        if self.board['id']=='cimc-v2' and update_wires:
            patterns=self.board['serialJumperPatterns']
            pairs={frozenset(pair) for key in ('rs485','rs232') for pair in patterns[key]}
            staged=[w for w in self.wires if frozenset((w['from'],w['to'])) not in pairs]
            for a,b in patterns[mode]:staged.append(self.validate_wire({'from':a,'to':b},staged))
        if mode!=self.serial_mode:
            self._flush_uart()
            self.serial_mode=mode
            self.rx['USART1'].clear()
            self.uart_idle['USART1']=False
            self.uart_status_read['USART1']=False
            self._refresh_uart_irq('USART1')
            self._connection_cache.clear()
        if staged is not None:
            self.wires=staged
            self._on_wiring_changed()

    def validate_wire(self,data,wires,board=None):
        board=self.board if board is None else board
        ids={p['id'] for p in board['pins'] if p.get('connectable',True)}
        a,b=data.get('from'),data.get('to')
        if a not in ids or b not in ids or a==b:raise ValueError('固定外设引脚不可改接；请选择空闲 GPIO 或 LED/KEY 排针')
        if len(wires)>=200:raise ValueError('用户跳线最多 200 条')
        if any({w['from'],w['to']}=={a,b} for w in wires):raise ValueError('这两个端点已经有用户跳线')
        nets={p['id']:p.get('net',p['id']) for p in board['pins']}
        if nets[a]==nets[b]:raise ValueError('两个端点本来就属于同一固定网络')
        pins={p['id']:p for p in board['pins']}
        va,vb=pins[a].get('powerVoltage'),pins[b].get('powerVoltage')
        if va is not None and vb is not None and va!=vb:raise ValueError('电源端子电位不一致，不能直接连接')
        return {'id':str(uuid.uuid4())[:8],'from':a,'to':b,'color':str(data.get('color','#0071e3'))}

    def load_project(self,project):
        if not isinstance(project,dict) or project.get('format')!='cimc-lab-project' or project.get('version') not in (1,2,3):raise ValueError('不支持的工程格式或版本')
        board=self._load_board(project.get('boardId'))
        if project['version']!=3 and board['id']!=self.board['id']:raise ValueError('工程板卡版本与当前板卡不一致')
        raw=project.get('wires')
        if not isinstance(raw,list) or len(raw)>200 or any(not isinstance(w,dict) for w in raw):raise ValueError('工程跳线列表无效')
        mode=project.get('serialMode','rs485')
        if mode not in ('rs485','rs232'):raise ValueError('无效的串口模式')
        settings=project.get('serialSettings',{}) if project['version']==3 else {}
        if not isinstance(settings,dict) or not settings.keys()<=board['serialMappings'].keys():
            raise ValueError('工程串口参数列表无效')
        settings={channel:validate_serial_settings(frame) for channel,frame in settings.items()}
        voltage=project.get('adcVoltage',self.adc.voltage)
        if isinstance(voltage,bool) or not isinstance(voltage,(int,float)) or not math.isfinite(voltage) or not 0<=voltage<=3.3:raise ValueError('工程 ADC 电压无效')
        adc1=project.get('adc1Voltage',1.65)
        if board['id']=='cimc-v2':
            if isinstance(adc1,bool) or not isinstance(adc1,(int,float)) or not math.isfinite(adc1) or not 0<=adc1<=3.3:raise ValueError('工程 PC1 电压无效')
        if project['version']==1:
            patterns={k:{frozenset(pair) for pair in v} for k,v in board['serialJumperPatterns'].items()}
            seen=set();remaining=[]
            for w in raw:
                pair=frozenset((w.get('from'),w.get('to')))
                if pair in patterns['ch340']:continue
                if pair in patterns['rs485'] or pair in patterns['rs232']:seen.add(pair)
                else:remaining.append(w)
            if seen:
                inferred=next((k for k in ('rs485','rs232') if seen==patterns[k]),None)
                if inferred is None:raise ValueError('旧工程的 H6 跳线不属于完整的 RS232/RS485 组合')
                if 'serialMode' in project and mode!=inferred:raise ValueError('旧工程串口模式与跳线矛盾')
                mode=inferred
            raw=remaining
        staged=[]
        for w in raw:staged.append(self.validate_wire(w,staged,board))
        # A v3 restore is self-contained. Legacy projects intentionally only
        # restore wiring/settings and retain the machine already loaded.
        program=cpu=None
        flash_data=None
        snapshot_error=None
        if project['version']==3:
            if 'firmwareSet' not in project:raise ValueError('v3 工程缺少 firmwareSet')
            saved=project['firmwareSet']
            if saved is not None:
                program=prepare_set(saved,allow_references=False)
                cpu=self._make_cpu(program)
            if 'internalFlashData' in project:
                encoded=project['internalFlashData']
                if program is None or board['id']!='cimc-v2' or not isinstance(encoded,str) or len(encoded)>700000:
                    raise ValueError('工程内部 Flash 快照无效')
                try:flash_data=base64.b64decode(encoded,validate=True)
                except (ValueError,TypeError):raise ValueError('工程内部 Flash 快照编码无效') from None
                if len(flash_data)!=FLASH_SIZE:raise ValueError('工程内部 Flash 快照长度无效')
                cpu.mem_write(FLASH,flash_data)
                cpu.mem_write(0,flash_data)
                try:snapshot_program=assemble((parse_image(flash_data,'internal-flash.bin',FLASH),),program.boot_address)
                except ValueError as error:snapshot_error=str(error)
                else:
                    cpu=self._make_cpu(snapshot_program)
                    program=snapshot_program
        if project['version']==3:
            self.board=board
            self._connection_cache.clear()
            self._install_program(program,cpu)
            if flash_data is not None:
                self.internal_flash=bytearray(flash_data)
                self.image=flash_data
                self.flash_dirty=bool(snapshot_error)
                if snapshot_error:self.diagnose('Flash 快照无法启动：'+snapshot_error)
        self.serial_settings=settings
        self._serial_warnings.clear()
        self.set_serial_mode(mode,update_wires=False)
        self.adc.set_voltage(voltage)
        if board['id']=='cimc-v2':
            self.adc.set_voltage(adc1,11)
        self.wires=staged
        self._on_wiring_changed()

    def project(self):
        with self.lock:
            return {'format':'cimc-lab-project','version':3,'boardId':self.board.get('id'),
                    'wires':list(self.wires),'firmware':self.firmware,
                    'firmwareSet':self.program.exported() if self.program else None,
                    **({'internalFlashData':base64.b64encode(self.internal_flash).decode('ascii')} if self.flash_dirty else {}),
                    **({'serialSettings':{channel:dict(frame) for channel,frame in self.serial_settings.items()}} if self.serial_settings else {}),
                    'serialMode':self.serial_mode,'adcVoltage':self.adc.voltage,
                    **({'adc1Voltage':self.adc.current_voltage} if self.board['id']=='cimc-v2' else {})}

    def state(self):
        with self.lock:
            self._sync_timing()
            for wire in self.wires:self.net_level(wire['from'])
            self._flush_uart()
            leds=[self.net_level(m.get('net',m.get('pin')))==m.get('active',1) for m in self.board.get('ledMappings',[])]
            pc=self.uc.reg_read(UC_ARM_REG_PC) if self.uc else 0
            sp=self.uc.reg_read(UC_ARM_REG_SP) if self.uc else 0
            oled_visible=self.oled.on and self._oled_powered()
            serial_parameters={channel:self._uart_parameters(mapping['uart'])
                               for channel,mapping in self.board['serialMappings'].items()}
            serial_state={
                'serialSettings':{channel:dict(frame) for channel,frame in self.serial_settings.items()},
                'serialParameters':{channel:{**frame,'baudRate':round(frame['baudRate'])} if frame else None
                                    for channel,frame in serial_parameters.items()},
                'serialCompatibility':{channel:self._serial_compatible(self.serial_settings.get(channel),frame)
                                       for channel,frame in serial_parameters.items()},
            }
            return {'status':self.status,'firmware':self.firmware,'firmwares':[im.metadata() for im in self.program.images] if self.program else [],'bootAddress':f'0x{self.program.boot_address:08X}' if self.program else None,'currentVectorAddress':f"0x{self.regs.get(0xE000ED08,0):08X}" if self.uc else None,'cpu':{'pc':f'0x{pc:08X}','sp':f'0x{sp:08X}','instructions':self.instructions,'model':'Cortex-M4 / Unicorn 2.1.4'},'board':self.board,'leds':leds,'keys':list(self.keys),'oled':{'width':self.oled.width,'height':self.oled.height,'pixels':self.oled.pixels() if oled_visible else [0]*(self.oled.width*self.oled.height),'on':oled_visible},'wires':list(self.wires),'managedWires':self.managed_wires(),'serialMode':self.serial_mode,**serial_state,'adc':self.adc.state(),'flash':self.flash.state(),'internalFlash':self.fmc.state(),'analog':self.v2_devices.state(),'timers':self.timers.state(),'watchdogs':self.watchdogs.state(),'systick':{**self.systick,'inputClockHz':self.hclk_frequency()//(1 if self.systick['ctrl']&4 else 8)},'clock':{'hclkHz':self.hclk_frequency(),'apb1Hz':self.hclk_frequency()//self.apb_clock_ratio()[1],'apb2Hz':self.hclk_frequency()//self.apb_clock_ratio(True)[1],'ticks':self.timing_ticks,'crystalHz':25000000},'serial':list(self.logs),'diagnostics':list(self.diagnostics),'engine':{'version':VERSION,'mode':'functional','cycleAccurate':False,'clockTicksPerInstruction':self.board.get('clockTicksPerInstruction',1),'supported':('TIMER0–13, FWDGT/WWDGT, GPIO, USART RX/IDLE IRQ, GPIO I2C OLED, SysTick, internal Flash, ADC PC0/PC1/PC2, DAC PA4, SPI0 GD25Q40E' if self.board['id']=='cimc-v2' else 'TIMER0–13, FWDGT/WWDGT, GPIO, USART RX/IDLE IRQ, GPIO I2C OLED, basic SysTick, software ADC, SPI1 GD25Q40E')}}
