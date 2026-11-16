"""Run the distributed native engine, catching failures invisible in source tests."""
import base64
import json
from pathlib import Path
import socket
import statistics
import struct
import subprocess
import sys
import time
from urllib.request import Request,urlopen

package=Path(sys.argv[1]).resolve()
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
url=f'http://127.0.0.1:{port}'
process=subprocess.Popen([str(package/('CIMC-Engine.exe' if sys.platform=='win32' else 'CIMC-Engine')),'--port',str(port)],cwd=package,
                         stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
def state():
    with urlopen(url+'/api/state',timeout=10) as r:return json.load(r)
def command(action,**fields):
    with urlopen(Request(url+'/api/command',data=json.dumps({'action':action,**fields}).encode(),headers={'Content-Type':'application/json'}),timeout=5) as r:return json.load(r)

def project():
    with urlopen(url+'/api/project',timeout=5) as r:return json.load(r)

def wait_for(predicate,description):
    for _ in range(150):
        current=state()
        assert current['status']!='faulted',current['diagnostics']
        if predicate(current):return current
        time.sleep(.05)
    fail('Packaged engine timeout: '+description,current)

def has_tx(current,text,channel='ch340'):
    # A wall-time slice or UI poll can flush part of a UART line. Reconstruct
    # only the real TX bytes for this channel; RX input cannot satisfy a reply.
    stream=b''.join(bytes.fromhex(log['hex']) for log in current['serial']
                    if log['channel']==channel and log['direction']=='tx')
    return text.encode('utf-8') in stream

def fail(description,current):
    evidence={key:current.get(key) for key in ('status','cpu','serial','diagnostics','serialMode','wires')}
    raise RuntimeError(description+'; state='+json.dumps(evidence,ensure_ascii=False))

def verify_application(letter,base,led):
    current=wait_for(lambda s:has_tx(s,f'APP {letter} READY') and s['currentVectorAddress']==base
                     and s['leds']==[i==led for i in range(6)],f'APP {letter} UART/VTOR/LED')
    assert int(base,16)<=int(current['cpu']['pc'],16)<int(base,16)+0x10000,current['cpu']
    command('pause')
    return current

def boot_select(choice):
    command('run')
    wait_for(lambda s:has_tx(s,'SELECT 1 OR 2'),'Bootloader serial selection prompt')
    command('serial',channel='ch340',data=base64.b64encode(str(choice).encode()).decode())
    result=verify_application('A' if choice==1 else 'B',f'0x080{choice}0000',choice-1)
    assert result['bootAddress']=='0x08000000',result['bootAddress']
    return result

def scheduler_sample(name,raw):
    command('load',filename=name,data=base64.b64encode(raw).decode())
    command('run')
    time.sleep(.15)  # Exclude loading, native translation and timer setup.
    first=state();begin=time.monotonic()
    time.sleep(.6)
    last=state();elapsed=time.monotonic()-begin
    command('pause')
    assert last['status']=='running',last['diagnostics']
    delta=last['cpu']['instructions']-first['cpu']['instructions']
    assert delta>0,(name,first['cpu'],last['cpu'])
    return delta/elapsed
try:
    for _ in range(120):
        if process.poll() is not None:raise RuntimeError('Packaged engine exited during startup: '+process.stderr.read().decode(errors='replace'))
        try:state();break
        except OSError:time.sleep(.25)
    else:raise RuntimeError('Packaged engine startup timeout')
    assert command('demo')['board']['id']=='cimc-v1'
    command('run')
    for _ in range(200):
        s=state()
        assert s['status']!='faulted',s['diagnostics']
        if has_tx(s,'OLED READY'):break
        time.sleep(.1)
    else:fail('No OLED startup output from packaged engine',s)
    assert sum(s['oled']['pixels'])>300
    command('serial',channel='ch340',data='TA==')
    for _ in range(100):
        s=state()
        assert s['status']!='faulted',s['diagnostics']
        if has_tx(s,'ACK L'):break
        time.sleep(.1)
    else:fail('Packaged engine did not execute UART reply',s)
    command('pause')
    assert s['adc']['sampleCount']>0 and s['adc']['value']==2048,s['adc']
    assert s['flash']['lastCommand'] is not None,s['flash']
    command('adc_voltage',voltage=3.3)
    command('run')
    for _ in range(100):
        s=state()
        assert s['status']!='faulted',s['diagnostics']
        if s['adc']['value']==4095:break
        time.sleep(.1)
    else:raise RuntimeError('Packaged ADC did not sample the changed voltage')
    command('serial_mode',mode='rs232')
    command('serial',channel='rs232',data='TA==')
    for _ in range(100):
        s=state()
        assert s['status']!='faulted',s['diagnostics']
        if has_tx(s,'ACK L','rs232'):break
        time.sleep(.1)
    else:fail('Packaged H6 mode switch did not route firmware output',s)
    command('pause')
    for ext in ('hex','bin'):
        before=state()['flash']
        firmware=package/'firmware'/f'spiflash_probe.{ext}'
        command('load',filename=firmware.name,data=base64.b64encode(firmware.read_bytes()).decode())
        command('run')
        for _ in range(100):
            s=state()
            assert s['status']!='faulted',s['diagnostics']
            if s['flash']['writeCount']>=before['writeCount']+2 and s['flash']['eraseCount']>=before['eraseCount']+2:break
            time.sleep(.1)
        else:raise RuntimeError('Packaged SPI Flash probe did not program and erase')
        command('pause')
    # These are three independently linked Keil programs. No RAM inspection or
    # special debug endpoint is used: only the same HTTP contract as the GUI.
    for ext in ('hex','bin'):
        images=[]
        for name,address in (('bootloader_probe','0x08000000'),('app_a_probe','0x08010000'),('app_b_probe','0x08020000')):
            path=package/'firmware'/f'{name}.{ext}'
            images.append({'filename':path.name,'data':base64.b64encode(path.read_bytes()).decode(),'address':address})
        loaded=command('load_set',images=images,bootIndex=0)
        assert len(loaded['firmwares'])==3,loaded['firmwares']
        assert loaded['cpu']['sp']=='0x20010000',loaded['cpu']
        ids=[im['id'] for im in loaded['firmwares']]
        for pin,terminal in (('PD10','LED1'),('PD11','LED2')):
            if not any({w['from'],w['to']}=={pin,terminal} for w in loaded['wires']):
                command('wire_add',**{'from':pin,'to':terminal})
        saved=project()
        assert saved['version']==3 and len(saved['firmwareSet']['images'])==3,saved['version']
        assert [base64.b64decode(im['data']) for im in saved['firmwareSet']['images']]==[
            base64.b64decode(im['data']) for im in images]
        boot_select(1)
        reset=command('reset')
        assert reset['currentVectorAddress']=='0x08000000' and len(reset['firmwares'])==3,reset['bootAddress']
        # Reset preserves log history, so clear it to require new firmware output.
        command('clear_log')
        boot_select(2)
        direct=command('load_set',images=[{'id':ident} for ident in ids],bootIndex=2)
        assert direct['firmware']['id']==ids[2] and direct['cpu']['sp']=='0x20020000',direct['firmware']
        command('run')
        direct=verify_application('B','0x08020000',1)
        assert direct['bootAddress']=='0x08020000',direct['bootAddress']
        assert not has_tx(direct,'BOOT READY'),direct['serial']
        restored=command('project_load',project=json.loads(json.dumps(saved)))
        assert [im['id'] for im in restored['firmwares']]==ids,restored['firmwares']
        assert restored['bootAddress']=='0x08000000' and restored['status']=='ready',restored['status']
        assert project()['firmwareSet']==saved['firmwareSet']
        boot_select(1)
    # Relative throughput catches the old per-interrupt 12 ms sleep in the
    # actual frozen worker. Interleave paired trials to reduce host-load drift;
    # this is a broad regression threshold, not a real-time MCU speed promise.
    noirq=struct.pack('<IIHH',0x20010000,0x08000009,0xBF00,0xE7FD)
    tick=(package/'firmware/systick.hex').read_bytes()
    rates={'systick':[],'noirq':[]}
    for order in (('systick','noirq'),('noirq','systick'),('systick','noirq')):
        for name in order:
            rates[name].append(scheduler_sample('systick.hex' if name=='systick' else 'noirq.bin',
                                                tick if name=='systick' else noirq))
    ratio=statistics.median(rates['systick'])/statistics.median(rates['noirq'])
    print('Frozen scheduler paired samples: '+json.dumps({'instructionsPerSecond':rates,'systickToNoIrq':ratio}),flush=True)
    assert ratio>=.25,'SysTick worker loses too much throughput at interrupt boundaries: '+str(ratio)
    command('board_select',boardId='cimc-v2')
    for extension in ('hex','bin'):
        probe=package/'firmware'/f'v2_spiflash_probe.{extension}'
        before=state()['flash']
        command('load',filename=probe.name,data=base64.b64encode(probe.read_bytes()).decode())
        command('run')
        current=wait_for(lambda snapshot:snapshot['flash']['writeCount']>=before['writeCount']+2
                         and snapshot['flash']['eraseCount']>=before['eraseCount']+2,'V2 SPI0 program/erase')
        assert bytes(current['flash']['preview'][:10])==b'CIMC FLASH',current['flash']
        assert current['flash']['peripheral']=='SPI0',current['flash']
        command('pause')
    loaded=command('v2_demo')
    assert len(loaded['firmwares'])==2
    assert any({w['from'],w['to']}=={'PE6','LED1'} for w in loaded['wires'])
    command('run')
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        current=state()
        assert current['status']!='faulted',current['diagnostics']
        if has_tx(current,'A5B60001058888000263A1B6A5','rs485'):break
        time.sleep(.2)
    else:fail('V2 real Bootloader/App startup timeout',current)
    assert current['currentVectorAddress']=='0x08011000'
    assert current['analog']['dac']['enabled']
    frame=bytearray.fromhex('A5B600010101040002')
    crc=0xFFFF
    for byte in frame:
        crc^=byte
        for _ in range(8):crc=(crc>>1)^0xA001 if crc&1 else crc>>1
    frame+=crc.to_bytes(2,'big')+b'\xb6\xa5'
    command('serial',channel='rs485',data=base64.b64encode(frame.hex().upper().encode()).decode())
    wait_for(lambda snapshot:has_tx(snapshot,'A5B60001020104040202000100','rs485'),'V2 real version response')
    command('pause')
    saved=project()
    assert saved['boardId']=='cimc-v2' and saved['adc1Voltage']==1.65
    print('PASS: packaged V2 real Bootloader/App + USART IRQ/CRC version + ADC/DAC/SPI initialization + project export',flush=True)
    print('PASS: packaged engine + Keil HEX/BIN + OLED + UART + ADC + H6 switch + SPI Flash program/erase + '
          '3-image Bootloader to A/B + direct B + project v3 restore (real UART/VTOR/LED) + SysTick scheduler')
finally:
    if process.poll() is None:
        if sys.platform=='win32':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        else:process.terminate()
    process.wait(timeout=10)
    process.stdout.close();process.stderr.close()
