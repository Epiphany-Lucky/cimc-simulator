"""V1.0 schematic transcription. Coordinates describe a diagram, never PCB geometry."""
import json
from pathlib import Path
from html import escape

ROOT=Path(__file__).resolve().parents[1]
board={'schemaVersion':1,'id':'cimc-v1','name':'CIMC GD32F470VET6 V1.0','verified':False,
 'evidenceStatus':'schematic-verified-scope','viewBox':[0,0,1000,650],'image':'assets/board-v1.svg',
 'coordinates':'Schematic connection diagram; not a photograph or PCB placement. Header numbers follow the V1.0 PDF.',
 'notes':['V1.0 原理图四页已取得；本版显示原理图接线视图，不用 V2 照片代替 V1。',
 '已核对 U2/U3、H2/H3、OLED1、H6/H7 的脚序及网络；完整芯片外设和模拟电路未仿真。',
 'H6 通过跳帽选择 USART1 的 RS485 或 RS232；H7 通过跳帽连接 CH340。跳帽也是新增导线，不是固定铜线。'],
 'pins':[],'leds':[],'keys':[],'fixedNets':[],'defaultAddedWires':[],
 'oled':{'width':128,'height':32,'address':60,'scl':'PB8','sda':'PB9','controller':'SSD1306-compatible command subset','evidence':'V1 p1/p2 pins; resolution/address from local driver'},
 'uart_channels':{'ch340':'USART0','rs485':'USART1','rs232':'USART1','ttl':'USART2'},
 'uart':{
 'ch340':{'uart':'USART0','tx':'PA9','rx':'PA10','af':7,'txTerminal':'USB_RX','rxTerminal':'USB_TX','jumpers':['H7.1 ↔ H7.3','H7.2 ↔ H7.4']},
 'rs485':{'uart':'USART1','tx':'PA2','rx':'PA3','af':7,'txTerminal':'485_RX','rxTerminal':'485_TX','de':'PA1','jumpers':['H6.1 ↔ H6.3','H6.2 ↔ H6.4']},
 'rs232':{'uart':'USART1','tx':'PA2','rx':'PA3','af':7,'txTerminal':'232_RX','rxTerminal':'232_TX','jumpers':['H6.3 ↔ H6.5','H6.4 ↔ H6.6']},
 'ttl':{'uart':'USART2','tx':'PB10','rx':'PB11','af':7,'txTerminal':'USART2_TX','rxTerminal':'USART2_RX','jumpers':[]}},
 'memory':{'flash':{'base':'0x08000000','bytes':524288},'sram':{'base':'0x20000000','bytes':196608},'tcm':{'base':'0x10000000','bytes':65536,'executable':False}}}

svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="650" viewBox="0 0 1000 650">',
 '<defs><linearGradient id="pcb" x2="0" y2="1"><stop stop-color="#172b48"/><stop offset="1" stop-color="#0c182a"/></linearGradient></defs>',
 '<rect x="10" y="10" width="980" height="630" rx="28" fill="url(#pcb)" stroke="#364d6c"/>',
 '<g fill="#5d7391">'+''.join(f'<circle cx="{x}" cy="{y}" r="8"/>' for x,y in [(32,32),(968,32),(32,618),(968,618)])+'</g>']
def text(x,y,t,size=12,fill='#9eb3cf',anchor='middle'):
 svg.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="Segoe UI,Arial,sans-serif" font-size="{size}" fill="{fill}">{escape(t)}</text>')
def pin(id,net,label,group,num,x,y,page,kind='signal'):
 board['pins'].append({'id':id,'net':net,'label':label,'group':group,'number':num,'x':x,'y':y,'connectable':net!='NC','kind':kind,'verified':True,'evidence':f'V1.0 schematic page {page}, {group} pin {num}'})
 svg.append(f'<rect x="{x-5}" y="{y-5}" width="10" height="10" rx="2" fill="#cba462"/>')
def fixed(name,*nodes,page=1):board['fixedNets'].append({'name':name,'nodes':list(nodes),'locked':True,'evidence':f'V1 schematic p{page}'})
u2l='PE2 PE4 PE6 PC0 PC2 PA0 PA4 PA6 PC4 PB0 PE7 PE9 PE11 PE13 PE15 PB11 DGND DGND DGND NC'.split()
u2r='PE3 PE5 PC13 PC1 PC3 PA1 PA5 PA7 PC5 PB1 PE8 PE10 PE12 PE14 PB10 NC 3V3 3V3 3V3 NC'.split()
u3l='PB12 PB14 PD8 PD10 PD12 PD14 PC6 PC8 PA8 PA12 PC10 PC12 PD1 PD3 PD5 PD7 PB4 PB6 PB8 PE0'.split()
u3r='PB13 PB15 PD9 PD11 PD13 PD15 PC7 PC9 PA11 PA15 PC11 PD0 PD2 PD4 PD6 PB3 PB5 PB7 PB9 PE1'.split()
for group,left,right,cx in [('U3',u3l,u3r,300),('U2',u2l,u2r,700)]:
 svg.append(f'<rect x="{cx-34}" y="142" width="68" height="410" rx="8" fill="#080f1b" stroke="#38506d"/>')
 text(cx,128,group+' · 2 × 20',14,'#d7e6f8')
 for row,(a,b) in enumerate(zip(left,right)):
  y=160+row*20
  for j,net in enumerate((a,b)):
   number=row*2+j+1;x=cx-15+j*30
   id=net if net.startswith('P') else f'{group}.{number}'
   pin(id,net,f'{number} · {net}',group,number,x,y,1,'gpio' if net.startswith('P') else 'power' if net!='NC' else 'nc')
   text(cx-43 if j==0 else cx+43,y+4,f'{number} {net}',11,anchor='end' if j==0 else 'start')
text(500,38,'CIMC · V1.0',19,'#eff6ff')
text(500,620,'SCHEMATIC CONNECTION VIEW  ·  FIXED NETS LOCKED',11)
svg.append('<rect x="420" y="278" width="160" height="150" rx="12" fill="#080f1b" stroke="#5b7393"/>')
text(500,332,'GD32F470',22,'#e8f2ff');text(500,358,'VET6 · Cortex-M4',12);text(500,390,'U1',11)
for i in range(6):
 y=175+i*26
 pin(f'LED{i+1}',f'LED{i+1}',f'{6-i} · LED{i+1}','H2',6-i,120,y,2)
 text(103,y+4,f'LED{i+1}',12,anchor='end')
 board['leds'].append({'id':f'led{i+1}','terminal':f'LED{i+1}','activeLow':False,'polarityVerified':True,'resistorOhms':2000})
 pin(f'KEY{i+1}',f'FUN_KEY{i+1}',f'{6-i} · KEY{i+1}','H3',6-i,880,y,2)
 text(897,y+4,f'KEY{i+1}',12,anchor='start')
 board['keys'].append({'id':f'key{i+1}','terminal':f'FUN_KEY{i+1}','activeLow':True,'idle':1,'polarityVerified':True,'pullUpOhms':10000})
 board['defaultAddedWires'] += [{'id':f'led{i+1}','a':f'PD{10+i}','b':f'LED{i+1}'},{'id':f'key{i+1}','a':f'PE{7+i}','b':f'KEY{i+1}'}]
text(90,144,'H2 · LED',13,'#f0c67b');text(910,144,'H3 · KEY',13,'#f0c67b')
for group,rows,cy in [('H6',[('485_RX','485_TX'),('USART1_TX','USART1_RX'),('232_RX','232_TX')],80),('H7',[('USB_RX','USB_TX'),('USART0_TX','USART0_RX')],510)]:
 for row,pair in enumerate(rows):
  y=cy+row*26
  for j,net in enumerate(pair):
   n=row*2+j+1;x=470+j*60
   pin(f'{group}.{n}',net,f'{n} · {net}',group,n,x,y,4)
   text(x-13 if j==0 else x+13,y+4,f'{n} {net}',10,anchor='end' if j==0 else 'start')
 text(500,cy-18,group+(' · RS485 / RS232' if group=='H6' else ' · USB CH340'),12,'#d7e6f8')
for n,net in enumerate(['DGND','3V3','OLED_CLK','OLED_DAT'],1):
 pin(f'OLED.{n}',net,f'{n} · {net}','OLED1',n,120,405+(n-1)*25,2)
 text(105,409+(n-1)*25,['GND','VCC','SCL','SDA'][n-1],11,anchor='end')
text(90,380,'OLED1',13,'#d7e6f8')
for n,net in enumerate(['DGND','USART2_TX','USART2_RX'],1):
 pin(f'CN1.{n}',net,f'{n} · {net}','CN1',n,880,420+(n-1)*25,4)
 text(897,424+(n-1)*25,['GND','TX','RX'][n-1],11,anchor='start')
text(910,395,'TTL · CN1',13,'#d7e6f8')
for name,nodes in {'OLED_CLK':['PB8','OLED_CLK'],'OLED_DAT':['PB9','OLED_DAT'],'USART0_TX':['PA9','USART0_TX'],'USART0_RX':['PA10','USART0_RX'],'USART1_TX':['PA2','USART1_TX'],'USART1_RX':['PA3','USART1_RX'],'USART2_TX':['PB10','USART2_TX'],'USART2_RX':['PB11','USART2_RX'],'485_CS':['PA1','485_CS'],'ground':['DGND','AGND','GND']}.items():fixed(name,*nodes)
board['preservedUnimplementedFixedNets']=[{'nodes':n,'simulated':False,'locked':True} for n in [
 ['PE2','SD_CD'],['PC8','SD_DAT0'],['PC9','SD_DAT1'],['PC10','SD_DAT2'],['PC11','SD_DAT3'],['PC12','SD_CLK'],['PD2','SD_CMD'],
 ['PB12','FLASH_CS'],['PB13','SPI_SCK'],['PB14','SPI_MISO'],['PB15','SPI_MOSI'],['PC0','ADC'],['PA0','WK_UP'],['PA13','SWDIO'],['PA14','SWCLK'],['PB2','BOOT1']]]
for item in board['preservedUnimplementedFixedNets']:fixed(item['nodes'][1],*item['nodes'])
board['defaultAddedWires'] += [{'id':'usb-tx','a':'H7.1','b':'H7.3'},{'id':'usb-rx','a':'H7.2','b':'H7.4'}, {'id':'rs485-tx','a':'H6.1','b':'H6.3'},{'id':'rs485-rx','a':'H6.2','b':'H6.4'}]
svg.append('</svg>')
(ROOT/'web/board-v1.json').write_text(json.dumps(board,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(ROOT/'web/assets/board-v1.svg').write_text('\n'.join(svg),encoding='utf-8')
print('V1 profile:',len(board['pins']),'endpoints')
