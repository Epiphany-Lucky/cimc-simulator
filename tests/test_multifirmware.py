"""Multi-image transactions and real Keil Bootloader/application execution."""
import base64
import copy
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from simulator import Simulator
from firmware_images import FLASH, FLASH_SIZE, SRAM, parse_image, parse_firmware, SEGMENT_PREVIEW_LIMIT
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_MSP


def item(data, name='image.bin', address=FLASH):
    return {'filename':name,'data':base64.b64encode(data).decode('ascii'),'address':address}


def loop_image(base=FLASH, sp=SRAM+0x10000):
    # Initial SP, Thumb reset vector, then a real "b ." instruction.
    return struct.pack('<IIH',sp,base+9,0xE7FE)


def hex_image(segments):
    def record(kind, addr, data):
        raw=bytes((len(data),addr>>8,addr&255,kind))+data
        return ':'+(raw+bytes((-sum(raw)&255,))).hex().upper()
    lines=[]
    for addr,data in segments:
        lines.append(record(4,0,struct.pack('>H',addr>>16)))
        for i in range(0,len(data),16):
            lines.append(record(0,(addr+i)&65535,data[i:i+16]))
    lines.append(record(1,0,b''))
    return ('\n'.join(lines)+'\n').encode()


class MultiFirmwareTests(unittest.TestCase):
    def setUp(self):
        self.s=Simulator(ROOT)
        self.s.close()  # Deterministic tests own all native execution.

    def tearDown(self):
        self.s.close()

    def load(self,images,**selection):
        return self.s.command({'action':'load_set','images':images,**selection})

    def fixture(self,name,ext='hex',base=FLASH):
        return item((ROOT/f'firmware/{name}.{ext}').read_bytes(),name+'.'+ext,base)

    def snapshot(self):
        return (self.s.uc,self.s.program,self.s.status,self.s.instructions,
                self.s.uc.reg_read(UC_ARM_REG_PC) if self.s.uc else None,
                copy.deepcopy(self.s.logs),copy.deepcopy(self.s.diagnostics),self.s.project())

    def assert_rejected(self,command):
        before=self.snapshot()
        with self.assertRaises((ValueError,UnicodeError)):
            self.s.command(command)
        self.assertEqual(self.snapshot(),before)

    def run_until(self,predicate,chunks=200):
        for _ in range(chunks):
            if predicate():return
            self.s.run_chunk(1000)
            self.assertNotEqual(self.s.status,'faulted',self.s.diagnostics)
        self.fail('Real firmware did not reach expected state')

    def mailbox(self):
        return struct.unpack('<12I',self.s.uc.mem_read(SRAM,48))

    def test_many_images_and_data_without_vectors(self):
        images=[item(loop_image())]+[item(bytes((i,)),f'data{i}.bin',FLASH+0x100+i) for i in range(12)]
        state=self.load(images)
        self.assertEqual(len(state['firmwares']),13)
        self.assertEqual(state['firmware']['id'],state['firmwares'][0]['id'])
        for i in range(12):self.assertEqual(self.s.uc.mem_read(FLASH+0x100+i,1),bytes((i,)))
        self.s.run_chunk(20)
        self.assertEqual(self.s.uc.reg_read(UC_ARM_REG_PC),FLASH+8)

    def test_sparse_hex_holes_can_be_filled_by_another_image(self):
        sparse=hex_image([(FLASH,loop_image()),(FLASH+0x200,b'END')])
        state=self.load([item(sparse,'sparse.hex'),item(b'PAYLOAD',address=FLASH+0x100)])
        self.assertEqual(state['firmwares'][0]['writtenSize'],13)
        self.assertEqual(state['firmwares'][0]['spanSize'],0x203)
        self.assertEqual(len(state['firmwares'][0]['segments']),2)
        self.assertEqual(self.s.uc.mem_read(FLASH+0x100,7),b'PAYLOAD')
        self.assertEqual(self.s.uc.mem_read(0,FLASH_SIZE),self.s.uc.mem_read(FLASH,FLASH_SIZE))
        self.assertEqual(self.s.uc.mem_read(0x40,32),b'\xff'*32)

    def test_vectors_and_entry_can_be_in_different_data_images(self):
        self.load([item(struct.pack('<II',SRAM+0x10000,FLASH+0x101)),item(b'\xfe\xe7',address=FLASH+0x100)])
        self.s.run_chunk(10)
        self.assertEqual(self.s.uc.reg_read(UC_ARM_REG_PC),FLASH+0x100)

    def test_explicit_vector_offset_and_boot_index(self):
        images=[item(loop_image()),item(b'PREFIX!!'+b'\xff'*120+loop_image(FLASH+0x1080),address=FLASH+0x1000)]
        state=self.load(images,bootAddress='0x08001080')
        self.assertEqual(state['bootAddress'],'0x08001080')
        self.assertEqual(state['firmware']['id'],state['firmwares'][1]['id'])
        state=self.load([{'id':state['firmwares'][1]['id']},{'id':state['firmwares'][0]['id']}],bootIndex=1)
        self.assertEqual(state['bootAddress'],'0x08000000')

    def test_reference_reorder_remove_reset_and_old_load_replaces(self):
        state=self.load([item(loop_image()),item(loop_image(FLASH+0x1000),address=FLASH+0x1000)])
        ids=[im['id'] for im in state['firmwares']]
        state=self.load([{'id':ids[1]},{'id':ids[0]}],bootIndex=0)
        self.s.run_chunk(10);self.s.command({'action':'reset'})
        self.assertEqual(self.s.uc.reg_read(UC_ARM_REG_PC),FLASH+0x1008)
        self.assertEqual(self.s.uc.mem_read(FLASH,10),loop_image())
        self.load([{'id':ids[1]}])
        self.assertEqual(self.s.uc.mem_read(FLASH,10),b'\xff'*10)
        self.s.load(loop_image(),'single.bin')
        self.assertEqual(len(self.s.state()['firmwares']),1)

    def test_invalid_sets_are_atomic_while_running(self):
        state=self.load([item(loop_image())]);ident=state['firmware']['id']
        self.s.status='running';self.s.run_chunk(11)
        ref={'id':ident}
        cases=[{'images':[]},{'images':[ref,ref]},{'images':[{'id':'missing'}]},
               {'images':[ref,item(loop_image())]}, # identical bytes still overlap
               {'images':[ref,item(b'\xff',address=FLASH+8)]},
               {'images':[ref,item(b'X',address=FLASH+FLASH_SIZE)]},
               {'images':[ref,{'filename':'payload.bin','data':'WA=='}]},
               {'images':[ref,{'filename':'bad.hex','data':'not base64'}]},
               {'images':[ref,{'id':ident,**item(b'X',address=FLASH+100)}]},
               {'images':[ref],'bootAddress':FLASH,'bootIndex':0},
               {'images':[ref],'bootIndex':True},{'images':[ref],'bootIndex':-1},
               {'images':[ref],'bootAddress':False},{'images':[ref],'bootAddress':FLASH+1},
               {'images':[ref],'bootAddress':FLASH+0x100}]
        for data in cases:
            with self.subTest(data=data):self.assert_rejected({'action':'load_set',**data})
        self.s.run_chunk(10)
        self.assertEqual(self.s.status,'running')

    def test_bad_sp_thumb_and_unwritten_entry_rejected(self):
        self.load([item(loop_image())])
        vectors=[(0x20040000,FLASH+9),(SRAM+0x10000,FLASH+8),(SRAM+0x10000,FLASH+0x101)]
        for sp,entry in vectors:
            self.assert_rejected({'action':'load_set','images':[item(struct.pack('<IIH',sp,entry,0xE7FE))]})
        # The entry's second byte cannot be supplied by erased Flash.
        self.assert_rejected({'action':'load_set','images':[item(struct.pack('<II',SRAM+0x10000,FLASH+9)+b'\xfe')]})
        sparse=hex_image([(FLASH,struct.pack('<II',SRAM+0x10000,FLASH+0x101)),(FLASH+0x200,b'x')])
        with self.assertRaises(ValueError):parse_firmware(sparse,'holes.hex')

    def test_native_allocation_failure_does_not_destroy_machine(self):
        self.load([item(loop_image())]);before=self.snapshot()
        with patch.object(self.s,'_make_cpu',side_effect=RuntimeError('allocation failure')):
            with self.assertRaises(RuntimeError):self.load([item(loop_image())])
        self.assertEqual(self.snapshot(),before)

    def test_portable_set_budget_covers_all_entrypoints_and_reference_growth(self):
        state=self.load([item(loop_image())])
        saved=self.s.project()
        size=len(json.dumps(saved['firmwareSet'],ensure_ascii=True,separators=(',',':')))
        ident=state['firmware']['id']
        with patch('firmware_images.MAX_SET_EXPORT_SIZE',size):
            # Exactly the portable budget still reloads, with identical IDs/data.
            self.s.command({'action':'project_load','project':saved})
            self.assertEqual(self.s.project()['firmwareSet'],saved['firmwareSet'])
            self.assert_rejected({'action':'load_set','images':[{'id':ident},item(b'X',address=FLASH+0x100)]})
        with patch('firmware_images.MAX_SET_EXPORT_SIZE',size-1):
            for command in ({'action':'load_set','images':[{'id':ident}]},
                            {'action':'project_load','project':saved},
                            {'action':'load',**item(loop_image())}):
                self.assert_rejected(command)
        # Successful raw API accumulation is also bounded by the portable size,
        # independent of the HTTP request length (an id-only request is tiny).
        with patch('firmware_images.MAX_SET_EXPORT_SIZE',size+250):
            current=self.load([{'id':ident},item(b'X',address=FLASH+0x100)])
            refs=[{'id':im['id']} for im in current['firmwares']]
            self.assert_rejected({'action':'load_set','images':refs+[item(b'Y',address=FLASH+0x200),item(b'Z',address=FLASH+0x300)]})

    def test_segment_preview_is_bounded_without_losing_bytes(self):
        sparse=hex_image([(FLASH,loop_image())]+[(FLASH+0x100+2*i,b'X') for i in range(100)])
        state=self.load([item(sparse,'fragmented.hex')]);meta=state['firmwares'][0]
        self.assertEqual(meta['segmentCount'],101)
        self.assertTrue(meta['segmentsTruncated'])
        self.assertEqual(len(meta['segments']),SEGMENT_PREVIEW_LIMIT)
        self.assertEqual(self.s.uc.mem_read(FLASH+0x100+198,1),b'X')

    def test_project_v3_roundtrip_restores_full_set_and_settings(self):
        self.load([item(loop_image()),item(loop_image(FLASH+0x1000),address=FLASH+0x1000)],bootIndex=1)
        self.s.command({'action':'wire_add','from':'PD10','to':'LED1'})
        self.s.set_serial_mode('rs232');self.s.adc.set_voltage(2.4)
        project=json.loads(json.dumps(self.s.project()))
        self.s.load(loop_image(),'other.bin');self.s.wires=[];self.s.set_serial_mode('rs485')
        self.s.command({'action':'project_load','project':project})
        self.assertEqual(self.s.project()['firmwareSet'],project['firmwareSet'])
        self.assertEqual(self.s.serial_mode,'rs232');self.assertEqual(self.s.adc.voltage,2.4)
        self.assertEqual([(w['from'],w['to']) for w in self.s.wires],[('PD10','LED1')])
        self.assertEqual(self.s.uc.reg_read(UC_ARM_REG_PC),FLASH+0x1008)

    def test_project_invalid_firmware_or_settings_cannot_partially_apply(self):
        self.load([item(loop_image())]);self.s.status='running'
        bads=[]
        p=self.s.project();p['serialMode']='rs232';p['adcVoltage']=2;p['firmwareSet']['images'].append(item(b'X'));bads.append(p)
        p=self.s.project();p['wires']=[{'from':'unknown','to':'LED1'}];bads.append(p)
        p=self.s.project();p['firmwareSet']['bootAddress']='0x08000080';bads.append(p)
        p=self.s.project();del p['firmwareSet'];bads.append(p)
        p=self.s.project();p['adcVoltage']=float('nan');bads.append(p)
        for project in bads:self.assert_rejected({'action':'project_load','project':project})

    def test_v3_null_clears_and_legacy_preserves_loaded_machine(self):
        self.load([item(loop_image())]);before=self.s.uc
        for version in (1,2):
            p=self.s.project();p['version']=version;p.pop('firmwareSet')
            self.s.command({'action':'project_load','project':p})
            self.assertIs(self.s.uc,before)
        p=self.s.project();p['firmwareSet']=None
        self.s.command({'action':'project_load','project':p})
        self.assertIsNone(self.s.uc);self.assertEqual(self.s.status,'idle')
        self.assertEqual(self.s.state()['firmwares'],[])

    def test_icsr_pending_write_one_semantics(self):
        self.load([item(loop_image())]);s=self.s
        s._write(0xE000ED04,1<<26)
        self.assertTrue(s.systick['pending']);self.assertTrue(s._read(0xE000ED04)&(1<<26))
        s._write(0xE000ED04,0);self.assertTrue(s.systick['pending'])
        s.systick['flag']=True;s.systick['ctrl']=3
        s._write(0xE000ED04,1<<25)
        self.assertFalse(s.systick['pending']);self.assertEqual(s._read(0xE000ED04)&(3<<25),0)
        self.assertTrue(s.systick['flag']);self.assertEqual(s.systick['ctrl'],3)
        s._write(0xE000ED04,1<<28)
        self.assertEqual(s.status,'faulted')

    def test_real_keil_bootloader_jumps_to_each_app_hex_and_bin(self):
        for ext in ('hex','bin'):
            for choice,base,sp,magic,tick in ((1,FLASH+0x10000,0x20018000,0x41505041,0x54494341),
                                            (2,FLASH+0x20000,0x20020000,0x41505042,0x54494342)):
                with self.subTest(ext=ext,choice=choice):
                    self.load([self.fixture('bootloader_probe',ext),self.fixture('app_a_probe',ext,FLASH+0x10000),
                               self.fixture('app_b_probe',ext,FLASH+0x20000)])
                    self.s.wires=[]
                    for i in range(6):self.s.command({'action':'wire_add','from':f'PD{10+i}','to':f'LED{i+1}'})
                    self.run_until(lambda:any('SELECT 1 OR 2' in r['text'] for r in self.s.logs))
                    self.s.command({'action':'serial','channel':'ch340','data':base64.b64encode(str(choice).encode()).decode()})
                    self.run_until(lambda:self.mailbox()[10]==0x52454144 and self.mailbox()[7]>3)
                    m=self.mailbox()
                    self.assertEqual(m[:3],(0x424F4F54,choice,base))
                    self.assertEqual(m[4:7],(magic,sp,base))
                    self.assertEqual(m[8:10],(tick,base));self.assertEqual(m[11],0)
                    state=self.s.state()
                    self.assertEqual(state['bootAddress'],'0x08000000')
                    self.assertEqual(state['currentVectorAddress'],f'0x{base:08X}')
                    self.assertTrue(base<=self.s.uc.reg_read(UC_ARM_REG_PC)<base+0x10000)
                    self.assertTrue(any(f'APP {"A" if choice==1 else "B"} READY' in r['text'] for r in self.s.logs))
                    self.assertEqual(state['leds'],[i==choice-1 for i in range(6)])
                    self.s.command({'action':'reset'})
                    self.assertEqual(self.s.state()['currentVectorAddress'],'0x08000000')
                    self.assertEqual(self.s.uc.reg_read(UC_ARM_REG_MSP),0x20010000)
                    self.assertEqual(len(self.s.program.images),3)

    def test_two_images_missing_app_stays_in_boot_then_runs_present_app(self):
        self.load([self.fixture('bootloader_probe'),self.fixture('app_a_probe')])
        self.run_until(lambda:any('SELECT 1 OR 2' in r['text'] for r in self.s.logs))
        self.s.command({'action':'serial','channel':'ch340','data':'Mg=='})
        self.run_until(lambda:any('APP MISSING OR INVALID' in r['text'] for r in self.s.logs))
        self.assertEqual(self.mailbox()[4],0)
        self.assertEqual(self.s.state()['currentVectorAddress'],'0x08000000')
        self.s.command({'action':'serial','channel':'ch340','data':'MQ=='})
        self.run_until(lambda:self.mailbox()[10]==0x52454144)
        self.assertEqual(self.mailbox()[4],0x41505041)

    def test_direct_selected_application_starts_without_bootloader(self):
        self.load([self.fixture('bootloader_probe'),self.fixture('app_a_probe'),self.fixture('app_b_probe')],bootIndex=2)
        self.run_until(lambda:self.mailbox()[10]==0x52454144 and self.mailbox()[7]>2)
        m=self.mailbox()
        self.assertEqual(m[0],0);self.assertEqual(m[4],0x41505042)
        self.assertEqual(m[5:7],(0x20020000,FLASH+0x20000))
        self.assertFalse(any('BOOT READY' in r['text'] for r in self.s.logs))


if __name__=='__main__':unittest.main()
