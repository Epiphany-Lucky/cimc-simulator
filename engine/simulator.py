"""CIMC Lab: real Cortex-M4 execution with an explicit GD32F470 peripheral subset.

This is a functional model, not a cycle-accurate/electrical simulation. Missing
MMIO stops execution; loading a firmware is never evidence of full compatibility.
"""
from __future__ import annotations
import base64
from collections import deque
import hashlib
import json
from pathlib import Path
import struct
import threading
import time
import uuid

from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_INVALID, UC_HOOK_INTR, UC_PROT_READ, UC_PROT_WRITE, UC_PROT_EXEC
from unicorn.arm_const import *

FLASH = 0x08000000
FLASH_SIZE = 0x80000
SRAM = 0x20000000
SRAM_SIZE = 0x30000
CCM = 0x10000000
CCM_SIZE = 0x10000
GPIO = {f'P{chr(65+i)}':0x40020000+i*0x400 for i in range(9)}
UART = {'USART0':0x40011000,'USART1':0x40004400,'USART2':0x40004800,'UART3':0x40004C00,'UART4':0x40005000,'USART5':0x40011400,'UART6':0x40007800,'UART7':0x40007C00}
CORE_REGS = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R12, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_XPSR]


def parse_firmware(data: bytes, filename: str, address: int=FLASH):
    """Validate Intel HEX (including checksum and address records), or raw BIN."""
    is_hex = filename.lower().endswith('.hex')
    cells = {}
    if is_hex:
        upper = 0
        eof = False
        for line_no, line in enumerate(data.decode('ascii').splitlines(), 1):
            line = line.strip()
            if not line: continue
            if eof: raise ValueError(f'HEX 第 {line_no} 行：EOF 后仍有记录')
            if not line.startswith(':'): raise ValueError(f'HEX 第 {line_no} 行缺少冒号')
            try: record = bytes.fromhex(line[1:])
            except ValueError: raise ValueError(f'HEX 第 {line_no} 行包含非法十六进制')
            if len(record) < 5 or len(record) != record[0]+5 or sum(record)&255:
                raise ValueError(f'HEX 第 {line_no} 行长度或校验和错误')
            length, offset, kind = record[0], int.from_bytes(record[1:3], 'big'), record[3]
            payload = record[4:-1]
            if kind == 0:
                for i,b in enumerate(payload):
                    a = upper+offset+i
                    if a in cells and cells[a] != b: raise ValueError('HEX 记录地址重叠且内容不一致')
                    cells[a] = b
            elif kind == 1:
                if length or offset: raise ValueError('HEX EOF 记录无效')
                eof = True
            elif kind in (2,4):
                if length != 2 or offset: raise ValueError('HEX 扩展地址记录无效')
                upper = int.from_bytes(payload, 'big') << (4 if kind == 2 else 16)
            elif kind in (3,5):
                if length != 4: raise ValueError('HEX 起始地址记录无效')
            else: raise ValueError(f'HEX 不支持记录类型 {kind}')
        if not eof: raise ValueError('HEX 缺少 EOF 结束记录')
        if not cells: raise ValueError('HEX 没有程序数据')
        base = min(cells)
        end = max(cells)+1
        if base < FLASH or end > FLASH+FLASH_SIZE: raise ValueError('HEX 数据超出本版本模型的 Flash 地址范围')
        image = bytearray(b'\xff'*(end-base))
        for a,b in cells.items(): image[a-base] = b
        image = bytes(image)
    else:
        base = address
        image = data
        if not image or base < FLASH or base+len(image)>FLASH+FLASH_SIZE: raise ValueError('BIN 装载地址或大小超出 Flash 范围')
    if base % 128: raise ValueError('向量表地址必须至少按 128 字节对齐')
    if len(image)<8: raise ValueError('固件缺少初始栈指针和复位向量')
    sp, entry = struct.unpack_from('<II',image)
    if sp%4 or not (SRAM < sp <= SRAM+SRAM_SIZE or CCM < sp <= CCM+CCM_SIZE): raise ValueError(f'初始 SP 0x{sp:08X} 不在 SRAM 范围内')
    if not entry&1 or not base <= (entry&~1) < base+len(image): raise ValueError(f'复位向量 0x{entry:08X} 无效或不在固件内')
    return image, base, sp, entry, 'HEX' if is_hex else 'BIN'


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
    def __init__(self, root: Path):
        self.root=Path(root)
        self.lock=threading.RLock()
        self.status='idle'
        self.firmware=None
        self.uc=None
        self.image=None
        self.wires=[]
        self._connection_cache={}
        self.logs=[]
        self.diagnostics=[]
        self.sequence=0
        self.closed=False
        self.board=self._load_board()
        self.keys=[False]*len(self.board.get('keyMappings',[]))
        self._reset_devices()
        self.worker=threading.Thread(target=self._worker,daemon=True)
        self.worker.start()

    def _load_board(self):
        p=self.root/'web'/'board-v1.json'
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
        raise FileNotFoundError('Missing verified V1 board profile: '+str(p))

    def _reset_devices(self):
        self.regs={}
        self.instructions=0
        self.start_time=time.monotonic()
        self.gpio_state={p:{'mode':0,'otype':0,'pull':0,'out':0,'af0':0,'af1':0} for p in GPIO}
        self.rx={p:deque() for p in UART}
        self.uart_pending={p:bytearray() for p in UART}
        o=self.board.get('oled',{})
        self.oled=OLED(o.get('width',128),o.get('height',32))
        self.i2c={'active':False,'count':0,'value':0,'phase':'address','selected':False,'ack':False,'ack_clock':False,'control':0,'scl':1,'sda':1}
        self.systick={'ctrl':0,'reload':0,'value':0,'flag':False,'pending':False}
        self.in_exception=False
        self.exception_return=False
        self.nvic_enable=0
        self._conflicts=set()
        self._floating={}
        self._warned=set()

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
        pin=m[direction];terminal=m[direction+'Terminal']
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

    def _flush_uart(self):
        for uart,b in self.uart_pending.items():
            if b:self._serial_log(self._channel(uart),'tx',b);b.clear()

    def load(self,raw,name,address=FLASH):
        image,base,sp,entry,fmt=parse_firmware(raw,name,address)
        with self.lock:
            self.image=image;self.base=base;self.initial_sp=sp;self.entry=entry
            self.firmware={'name':name,'size':len(raw),'imageSize':len(image),'format':fmt,'sha256':hashlib.sha256(raw).hexdigest(),'entry':f'0x{entry:08X}','address':f'0x{base:08X}'}
            self.logs=[];self.diagnostics=[]
            self.reset()

    def reset(self):
        with self.lock:
            if self.image is None:return
            self._reset_devices()
            self.keys=[False]*len(self.board.get('keyMappings',[]))
            self.uc=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
            self.uc.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M4)
            self.uc.mem_map(FLASH,FLASH_SIZE)
            self.uc.mem_write(FLASH,b'\xff'*FLASH_SIZE)
            self.uc.mem_write(self.base,self.image)
            self.uc.mem_protect(FLASH,FLASH_SIZE,UC_PROT_READ|UC_PROT_EXEC)
            self.uc.mem_map(0,FLASH_SIZE)
            self.uc.mem_write(self.base-FLASH,self.image)
            self.uc.mem_protect(0,FLASH_SIZE,UC_PROT_READ|UC_PROT_EXEC)
            self.uc.mem_map(SRAM,SRAM_SIZE)
            self.uc.mem_map(CCM,CCM_SIZE,UC_PROT_READ|UC_PROT_WRITE)
            # Dedicated MMIO callbacks avoid modifying translated memory from a read hook.
            self.uc.mmio_map(0x40000000,0x30000,self._mmio_read,0x40000000,self._mmio_write,0x40000000)
            self.uc.mmio_map(0xE000E000,0x2000,self._mmio_read,0xE000E000,self._mmio_write,0xE000E000)
            self.uc.hook_add(UC_HOOK_MEM_INVALID,self._invalid)
            self.uc.hook_add(UC_HOOK_CODE,self._code_hook)
            self.uc.hook_add(UC_HOOK_INTR,self._interrupt)
            self.uc.reg_write(UC_ARM_REG_SP,self.initial_sp)
            self.uc.reg_write(UC_ARM_REG_MSP,self.initial_sp)
            self.uc.reg_write(UC_ARM_REG_PC,self.entry)
            self.uc.reg_write(UC_ARM_REG_XPSR,0x01000000)
            self.regs[0xE000ED08]=self.base
            self.status='ready'

    def _invalid(self,uc,access,address,size,value,user):
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

    def _unsupported(self,a,operation):
        self.diagnose(f'尚未实现的寄存器{operation}：0x{a:08X}',address=f'0x{a:08X}',pc=f'0x{self.uc.reg_read(UC_ARM_REG_PC):08X}')
        return 0

    def _read(self,a):
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
                    return (0xC0 if control&(1<<3) else 0)|(0x20 if self.rx[uart] and control&(1<<2) else 0)
                if o==4:return self.rx[uart].popleft() if self.rx[uart] else 0
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
        if a in (0x40007000,0x40007004):return self.regs.get(a,0)
        if a==0xE000E010:
            v=self.systick['ctrl']|(0x10000 if self.systick['flag'] else 0);self.systick['flag']=False;return v
        if a==0xE000E014:return self.systick['reload']
        if a==0xE000E018:return self.systick['value']
        if a==0xE000E01C:return 10000
        if a==0xE000ED00:return 0x410FC241
        if a in (0xE000ED04,0xE000ED08,0xE000ED0C,0xE000ED10,0xE000ED14,0xE000ED18,0xE000ED1C,0xE000ED20,0xE000ED24,0xE000ED28,0xE000ED2C,0xE000ED88):return self.regs.get(a,0)
        return self._unsupported(a,'读取')

    def _write(self,a,v,size=4,byte_offset=0):
        mask=((1<<(size*8))-1)<<(byte_offset*8)
        previous=self.regs.get(a,0)
        v=((previous&~mask)|(v&mask))&0xFFFFFFFF
        self.regs[a]=v
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
                if port in (oled.get('scl','')[:2],oled.get('sda','')[:2]):self._i2c_edges()
                return
        for uart,b in UART.items():
            if b<=a<b+0x20:
                o=a-b
                if o==4:
                    if self.regs.get(b+12,0)&((1<<13)|(1<<3))!=((1<<13)|(1<<3)):return
                    if self._uart_transmit_enabled(uart):
                        self.uart_pending[uart].append(v&255)
                        if v&255==10 or len(self.uart_pending[uart])>=512:self._serial_log(self._channel(uart),'tx',self.uart_pending[uart]);self.uart_pending[uart].clear()
                elif o==12 and v&((1<<5)|(1<<6)|(1<<7)):
                    self.diagnose(f'{uart} 中断模式尚未实现；本版本支持轮询收发')
                elif o==20 and v&((1<<6)|(1<<7)):
                    self.diagnose(f'{uart} DMA 模式尚未实现')
                elif o not in (0,8,12,16,20,24):return self._unsupported(a,'写入')
                return
        if 0x40023800<=a<=0x40023898:return
        if a in (0x40023C00,0x40007000,0x40007004):return
        if a==0xE000E010:self.systick['ctrl']=v&7;return
        if a==0xE000E014:self.systick['reload']=v&0xFFFFFF;return
        if a==0xE000E018:self.systick['value']=0;self.systick['flag']=False;return
        if a in (0xE000ED04,0xE000ED08,0xE000ED0C,0xE000ED10,0xE000ED14,0xE000ED18,0xE000ED1C,0xE000ED20,0xE000ED24,0xE000ED28,0xE000ED2C,0xE000ED88):return
        return self._unsupported(a,'写入')

    def _uart_transmit_enabled(self,uart):
        channel=self._channel(uart)
        if channel is None:return False
        m=self.board['serialMappings'][channel]
        return not m.get('dePin') or self.net_level(m['dePin'])==m.get('deActive',1)

    def _code_hook(self,uc,address,size,user):
        self.instructions+=1
        st=self.systick
        if st['ctrl']&1:
            if st['value']==0:
                st['value']=st['reload'];st['flag']=True
                if st['ctrl']&2:st['pending']=True
            else:st['value']-=1
        if st['pending'] and not self.in_exception and not uc.reg_read(UC_ARM_REG_PRIMASK):uc.emu_stop()

    def _interrupt(self,uc,intno,user):
        if intno==8 and self.in_exception:self.exception_return=True;uc.emu_stop()
        else:self.diagnose(f'尚未实现的 CPU 异常：{intno}',pc=f'0x{uc.reg_read(UC_ARM_REG_PC):08X}')

    def _enter_systick(self):
        u=self.uc
        vector=self.regs.get(0xE000ED08,self.base)
        handler=int.from_bytes(u.mem_read(vector+60,4),'little')
        if not handler&1 or not FLASH <= (handler&~1)<FLASH+FLASH_SIZE:self.diagnose('SysTick 中断向量无效');return
        sp=u.reg_read(UC_ARM_REG_SP)-32
        frame=[u.reg_read(r) for r in CORE_REGS]
        u.mem_write(sp,struct.pack('<8I',*frame))
        u.reg_write(UC_ARM_REG_SP,sp)
        u.reg_write(UC_ARM_REG_LR,0xFFFFFFF9)
        u.reg_write(UC_ARM_REG_XPSR,(frame[-1]&0xF0000000)|0x0100000F)
        u.reg_write(UC_ARM_REG_PC,handler)
        self.in_exception=True;self.systick['pending']=False

    def _return_exception(self):
        u=self.uc;sp=u.reg_read(UC_ARM_REG_SP)
        values=struct.unpack('<8I',u.mem_read(sp,32))
        for r,v in zip(CORE_REGS,values):u.reg_write(r,v)
        u.reg_write(UC_ARM_REG_SP,sp+32)
        self.in_exception=False;self.exception_return=False

    def run_chunk(self,count=10000):
        if not self.uc:return
        try:
            if self.exception_return:self._return_exception()
            if self.systick['pending'] and not self.in_exception and not self.uc.reg_read(UC_ARM_REG_PRIMASK):self._enter_systick()
            if self.status=='faulted':return
            self.uc.emu_start(self.uc.reg_read(UC_ARM_REG_PC)|1,0,count=count)
            if self.exception_return:self._return_exception()
        except UcError as e:
            if self.status!='faulted':self.diagnose(f'固件停止：{e}',pc=f'0x{self.uc.reg_read(UC_ARM_REG_PC):08X}')
        self._flush_uart()

    def _worker(self):
        while not self.closed:
            with self.lock:
                if self.status=='running':self.run_chunk()
            time.sleep(0.012)

    def _pin_net(self,pin):
        for p in self.board.get('pins',[]):
            if p['id']==pin:return p.get('net',p['id'])
        return pin

    def connected(self,net):
        if net in self._connection_cache:return self._connection_cache[net]
        reached={net}
        edges=[(self._pin_net(w['from']),self._pin_net(w['to'])) for w in self.wires]
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

    def net_level(self,net,include_device=True):
        nets=self.connected(self._pin_net(net));strong=[];weak=[]
        for n in nets:
            if n in ('GND','DGND','0V'):strong.append(0)
            if n in ('3V3','3.3V','VCC','5V'):strong.append(1)
            if len(n)>=3 and n[:2] in GPIO and n[2:].isdigit():
                pin=int(n[2:]);g=self.gpio_state[n[:2]]
                if pin>15:continue
                mode=(g['mode']>>(pin*2))&3;out=(g['out']>>pin)&1
                if mode==1 and not ((g['otype']>>pin)&1 and out):strong.append(out)
                pull=(g['pull']>>(pin*2))&3
                if pull in (1,2):weak.append(1 if pull==1 else 0)
        for i,k in enumerate(self.board.get('keyMappings',[])):
            if k.get('net',k.get('pin')) in nets:
                if i<len(self.keys) and self.keys[i]:strong.append(k.get('active',0))
                elif 'idle' in k:weak.append(k['idle'])
        o=self.board.get('oled',{})
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

    def command(self,data):
        action=data.get('action','')
        if action=='load':
            raw=base64.b64decode(data.get('data',data.get('dataBase64','')),validate=True)
            if len(raw)>4*1024*1024:raise ValueError('固件文件超过 4 MiB')
            a=data.get('address',FLASH);a=int(a,0) if isinstance(a,str) else int(a)
            self.load(raw,data.get('filename','firmware.bin'),a)
        elif action=='demo':
            p=self.root/'firmware'/'demo.hex';self.load(p.read_bytes(),'CIMC Lab · Keil demo.hex')
            self.wires=[]
            for w in self.board.get('defaultAddedWires',[]):
                self.command({'action':'wire_add','from':w['a'],'to':w['b'],'color':'#0071e3' if 'led' in w['id'] else '#a855f7'})
            self.diagnose(f"已载入真实 Keil 示例固件与 {len(self.wires)} 条可删除示例跳线；原板固定网络未改变",'info')
        else:
            with self.lock:
                if action=='run':
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
                elif action=='serial':
                    channel=data.get('channel','ch340');mapping=self.board.get('serialMappings',{}).get(channel)
                    if mapping is None:raise ValueError('未核验的串口映射')
                    uart=mapping['uart'] if isinstance(mapping,dict) else mapping
                    raw=base64.b64decode(data.get('data',''),validate=True)
                    if len(raw)>4096:raise ValueError('单次最多发送 4096 字节')
                    self._serial_log(channel,'rx',raw)
                    if not self._uart_path(channel,'rx'):
                        self.diagnose('串口接收线路未接通、被短接或 GPIO 复用未配置；请检查 '+', '.join(mapping.get('jumpers',[])),'warning')
                    elif isinstance(mapping,dict) and mapping.get('dePin') and self.net_level(mapping['dePin'])==mapping.get('deActive',1):
                        self.diagnose('RS485 处于发送状态，本次接收未送入 MCU','warning')
                    elif self.regs.get(UART[uart]+12,0)&((1<<13)|(1<<2))!=((1<<13)|(1<<2)):
                        self.diagnose(f'{uart} 尚未启用接收，本次输入未送入 MCU','warning')
                    else:self.rx[uart].extend(raw)
                elif action=='wire_add':
                    ids={p['id'] for p in self.board.get('pins',[]) if p.get('connectable',True)}
                    a,b=data.get('from'),data.get('to')
                    if a not in ids or b not in ids or a==b:raise ValueError('只能连接两个实际存在的排针端点')
                    if any({w['from'],w['to']}=={a,b} for w in self.wires):raise ValueError('这两个端点已经有用户跳线')
                    if self._pin_net(a)==self._pin_net(b):raise ValueError('两个端点本来就属于同一固定网络')
                    self.wires.append({'id':str(uuid.uuid4())[:8],'from':a,'to':b,'color':data.get('color','#0071e3')})
                    self._connection_cache.clear()
                    self.net_level(a)
                elif action=='wire_remove':self.wires=[w for w in self.wires if w['id']!=data.get('id')];self._connection_cache.clear()
                elif action=='project_load':
                    project=data.get('project',data)
                    if project.get('format')!='cimc-lab-project' or project.get('version')!=1:raise ValueError('不支持的工程格式或版本')
                    if project.get('boardId')!=self.board.get('id'):raise ValueError('工程板卡版本与当前板卡不一致')
                    if not isinstance(project.get('wires'),list) or len(project['wires'])>200:raise ValueError('工程跳线列表无效')
                    old=self.wires;self.wires=[]
                    self._connection_cache.clear()
                    try:
                        for w in project['wires']:self.command({'action':'wire_add','from':w.get('from'),'to':w.get('to'),'color':w.get('color','#0071e3')})
                    except Exception:self.wires=old;self._connection_cache.clear();raise
                elif action=='clear_log':self.logs=[]
                else:raise ValueError('未知操作：'+action)
        return self.state()

    def project(self):return {'format':'cimc-lab-project','version':1,'boardId':self.board.get('id'),'wires':list(self.wires),'firmware':self.firmware}

    def state(self):
        with self.lock:
            for wire in self.wires:self.net_level(wire['from'])
            self._flush_uart()
            leds=[self.net_level(m.get('net',m.get('pin')))==m.get('active',1) for m in self.board.get('ledMappings',[])]
            pc=self.uc.reg_read(UC_ARM_REG_PC) if self.uc else 0
            sp=self.uc.reg_read(UC_ARM_REG_SP) if self.uc else 0
            return {'status':self.status,'firmware':self.firmware,'cpu':{'pc':f'0x{pc:08X}','sp':f'0x{sp:08X}','instructions':self.instructions,'model':'Cortex-M4 / Unicorn 2.1.4'},'board':self.board,'leds':leds,'keys':list(self.keys),'oled':{'width':self.oled.width,'height':self.oled.height,'pixels':self.oled.pixels(),'on':self.oled.on},'wires':list(self.wires),'serial':list(self.logs),'diagnostics':list(self.diagnostics),'engine':{'version':'0.1.0','mode':'functional','cycleAccurate':False,'supported':'GPIO, polling USART, GPIO I2C OLED, basic SysTick'}}
