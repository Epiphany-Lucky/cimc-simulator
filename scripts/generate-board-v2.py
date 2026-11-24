"""V2 connection diagram transcribed from the provided five-page schematic."""
from html import escape
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'web/board-v2.json'
board = json.loads(path.read_text(encoding='utf-8'))
old_pins = {pin['id']: pin for pin in board['pins']}
u2_left = 'PE2 PE4 PE6 PC0 PC2 PA0 PA4 PA6 PC4 PB0 PE7 PE9 PE11 PE13 PE15 PB11 NC DGND DGND DGND'.split()
u2_right = 'PE3 PE5 PC13 PC1 PC3 PA1 PA5 PA7 PC5 PB1 PE8 PE10 PE12 PE14 PB10 NC NC 3V3 3V3 3V3'.split()
u3_left = 'PB12 PB14 PD8 PD10 PD12 PD14 PC6 PC8 PA8 PA12 PC10 PC12 PD1 PD3 PD5 PD7 PB4 PB6 PB8 PE0'.split()
u3_right = 'PB13 PB15 PD9 PD11 PD13 PD15 PC7 PC9 PA11 PA15 PC11 PD0 PD2 PD4 PD6 PB3 PB5 PB7 PB9 PE1'.split()
old_power_ids = {32: 'U2_R05_L', 33: 'U2_R04_R', 34: 'U2_R04_L',
                 35: 'U2_R03_R', 36: 'U2_R03_L', 37: 'U2_R02_R',
                 38: 'U2_R02_L', 39: 'U2_R01_R', 40: 'U2_R01_L'}
header_pins = []
for group, left, right in (('U2', u2_left, u2_right), ('U3', u3_left, u3_right)):
    for row, pair in enumerate(zip(left, right), 1):
        for column, net in enumerate(pair):
            number = (row - 1) * 2 + column + 1
            endpoint = net if net.startswith('P') else f'{group}.{number}'
            previous = old_pins.get(endpoint, old_pins.get(old_power_ids.get(number, ''), {}))
            pin = {**previous, 'id': endpoint, 'net': net, 'group': group,
                   'rowFromTop': row, 'column': 'left' if column == 0 else 'right',
                   'number': number, 'connectable': net != 'NC',
                   'kind': 'gpio' if net.startswith('P') else 'nc' if net == 'NC' else 'power',
                   'verified': True, 'evidence': f'V2 schematic physical page 1, {group} pin {number}'}
            header_pins.append(pin)
board['pins'] = header_pins + [pin for pin in board['pins']
                              if pin['group'] not in ('U2', 'U3') and not pin['id'].startswith('PT100_')]
board.update(evidenceStatus='v2-schematic-verified-scope',
             clockTicksPerInstruction=240, referenceImage='assets/board-v2.jpg',
             image='assets/board-v2.svg', viewBox=[0, 0, 1000, 650],
             coordinates='Connection diagram. Connector numbers and fixed copper networks follow the five-page V2.0 schematic provided on 2026-11-16.')
board['notes'] = [
    'V2 使用原理图接线视图。U2/U3 及 OLED、LED、KEY、通信跳帽的脚号按 V2.0 五页原图核对。',
    '板内固定铜线保存在 fixedNets，固件代码的外接线作为可删除示例保存。',
    'OLED 的 PB8/PB9 和供电、PC0 的板载 VR1、USART 固定引出与 RS485 方向线按原图保持。',
    '原图暴露的 GPIO 排针允许新增跳线，新增线与原有固定网络共同参与电平解析。',
    'PA5/PA7 等与 DAC/Ethernet 共享的原网络按原图保持。',
    '用户于 2026-11-16 提供的 27_0_BootLoader 作为 V2 软件行为和示例接线依据。'
]
board['uart_channels'] = {'rs485': 'USART1', 'rs232': 'USART1', 'ch340': 'USART0', 'ttl': 'USART2'}
board['uart'] = {'rs485': {'uart': 'USART1', 'tx': 'PD5', 'rx': 'PD6', 'af': 7,
                          'txPins': ['PD5', 'PA2'], 'rxPins': ['PD6', 'PA3'],
                          'txTerminal': '485_RX', 'rxTerminal': '485_TX',
                          'de': '485_DE', 'deExamplePin': 'PE8', 'deTerminal': '485_DE', 'jumpers': [],
                          'evidence': '27_0_BootLoader/Driver/USART/usart.c',
                          'mappingSource': 'removable-driver-example'}}
board['uart'].update(
    rs232={'uart': 'USART1', 'tx': 'PD5', 'rx': 'PD6', 'af': 7, 'txPins': ['PD5', 'PA2'], 'rxPins': ['PD6', 'PA3'], 'txTerminal': '232_RX', 'rxTerminal': '232_TX', 'jumpers': ['H10.3 ↔ H10.5', 'H10.4 ↔ H10.6']},
    ch340={'uart': 'USART0', 'tx': 'PA9', 'rx': 'PA10', 'af': 7, 'txPins': ['PA9'], 'rxPins': ['PA10'], 'txTerminal': 'USB_RX', 'rxTerminal': 'USB_TX', 'jumpers': ['H12.1 ↔ H12.3', 'H12.2 ↔ H12.4']},
    ttl={'uart': 'USART2', 'tx': 'PD8', 'rx': 'PD9', 'af': 7, 'txPins': ['PD8'], 'rxPins': ['PD9'], 'txTerminal': 'TTL_OUT_RX', 'rxTerminal': 'TTL_OUT_TX', 'jumpers': ['H11.1 ↔ H11.3', 'H11.2 ↔ H11.4']})
board['uart']['rs485']['jumpers'] = ['H10.1 ↔ H10.3', 'H10.2 ↔ H10.4']
board['serialJumperPatterns'] = {'ch340': [],
                                 'rs485': [['H10.1', 'H10.3'], ['H10.2', 'H10.4']],
                                 'rs232': [['H10.3', 'H10.5'], ['H10.4', 'H10.6']]}
board['memory'] = {'flash': {'base': '0x08000000', 'bytes': 524288},
                   'sram': {'base': '0x20000000', 'bytes': 196608},
                   'tcm': {'base': '0x10000000', 'bytes': 65536, 'executable': False}}
board['adc'] = {'pin': 'PC0', 'channel': 10, 'pins': ['PC0', 'PC1', 'PC2'],
                'terminals': ['ADC_IN10', 'ADC_IN1', 'ADC_IN12'], 'referenceVoltage': 3.3, 'locked': False}
board['dac'] = {'pin': 'PA4', 'channel': 0, 'signalNet': 'DAC0_OUT', 'locked': False}
board.pop('pt100', None)
board['oled'].update(scl='OLED_SCL', sda='OLED_SDA', sclTerminal='OLED_SCL', sdaTerminal='OLED_SDA',
                     vccTerminal='OLED_3V3', gndTerminal='OLED_GND',
                     powerTerminal='OLED_3V3', groundTerminal='OLED_GND', locked=False)
# Transcribe the schematic's copper nets while retaining exposed pin access.
board['fixedNets'] = [{'id': 'header_' + pin['id'], 'nodes': ['MCU.' + pin['id'], pin['id']],
                      'locked': True, 'verified': True, 'evidence': f'V2 schematic p1 {pin["group"]} pin {pin["number"]}'}
                     for pin in header_pins if pin['kind'] == 'gpio']
fixed = {
    'OLED_CLK': ['PB8', 'OLED_CLK', 'OLED_SCL', 'E_SCL'],
    'OLED_DAT': ['PB9', 'OLED_DAT', 'OLED_SDA', 'E_SDA'],
    'OLED_POWER': ['3V3', 'OLED_3V3'], 'OLED_GROUND': ['DGND', 'GND', 'AGND', 'OLED_GND'],
    'ADC_IN10': ['PC0', 'ADC_IN10'], 'ADC_IN12': ['PC2', 'ADC_IN12'],
    'USART1_TX': ['PD5', 'USART1_TX'], 'USART1_RX': ['PD6', 'USART1_RX'],
    'USART0_TX': ['PA9', 'USART0_TX'], 'USART0_RX': ['PA10', 'USART0_RX'],
    'USART2_TX': ['PD8', 'USART2_TX'], 'USART2_RX': ['PD9', 'USART2_RX'],
    '485_CS': ['PE8', '485_CS', '485_DE'],
    'FLASH_CS': ['PA15', 'FLASH_CS'], 'SPI_SCK': ['PB3', 'SPI_SCK'],
    'SPI_MISO': ['PB4', 'SPI_MISO'], 'SPI_MOSI': ['PB5', 'SPI_MOSI'],
    'SPI3_SCK': ['PE12', 'SPI3_SCK', 'S_SCK', 'W_SPI_SCK'],
    'SPI3_MISO': ['PE13', 'SPI3_MISO', 'S_MISO', 'W_SPI_MISO'],
    'SPI3_MOSI': ['PE14', 'SPI3_MOSI', 'S_MOSI', 'W_SPI_MOSI'],
    'S_SPI_CS': ['PE10', 'S_SPI_CS', 'S_CS'], 'W_SPI_CS': ['PE9', 'W_SPI_CS'],
    'USART5_TX': ['PC6', 'USART5_TX', 'S_UARTRX'], 'USART5_RX': ['PC7', 'USART5_RX', 'S_UARTTX'],
    'SD_CD': ['PE2', 'SD_CD'], 'SD_DAT0': ['PC8', 'SD_DAT0'], 'SD_DAT1': ['PC9', 'SD_DAT1'],
    'SD_DAT2': ['PC10', 'SD_DAT2'], 'SD_DAT3': ['PC11', 'SD_DAT3'],
    'SD_CLK': ['PC12', 'SD_CLK'], 'SD_CMD': ['PD2', 'SD_CMD'],
    'WK_UP': ['PA0', 'WK_UP'], 'W_RST': ['PA3', 'W_RST', 'W_GPIO7'],
    'PHY_RST': ['PD3', 'PHY_RST'], 'DAC0_OUT': ['PA4', 'DAC0_OUT'], 'DAC1_OUT': ['PA5', 'DAC1_OUT'],
    'ETH_MDC': ['PC1', 'ETH_MDC'], 'ETH_MDIO': ['PA2', 'ETH_MDIO'],
    'ETH_REF_CLK': ['PA1', 'ETH_REF_CLK'], 'ETH_CRS_DV': ['PA7', 'ETH_CRS_DV'],
    'ETH_RXD0': ['PC4', 'ETH_RXD0'], 'ETH_RXD1': ['PC5', 'ETH_RXD1'],
    'ETH_TX_EN': ['PB11', 'ETH_TX_EN'], 'ETH_TXD0': ['PB12', 'ETH_TXD0'], 'ETH_TXD1': ['PB13', 'ETH_TXD1'],
}
board['fixedNets'] += [{'id': 'schematic_' + name, 'nodes': nodes, 'locked': True, 'verified': True,
                       'evidence': 'V2 schematic p1 MCU net labels and p2/p4 peripheral terminals'}
                      for name, nodes in fixed.items()]
board['fixedPulls'] = [
    {'net': net, 'level': 1, 'resistanceOhms': 10000, 'component': component,
     'evidence': f'V2 schematic p2 {component}, 10k to 3V3'}
    for component, net in (('R26', 'FLASH_CS'), ('R27', 'E_SCL'), ('R28', 'E_SDA'),
                           ('R9', 'SD_DAT0'), ('R16', 'SD_DAT1'), ('R18', 'SD_DAT2'),
                           ('R19', 'SD_DAT3'), ('R20', 'SD_CMD'), ('R21', 'SD_CD'))
]
board['provisionalFixedNets'] = []
board['fixedVisualWires'] = []
examples = [('H10.1', 'H10.3'), ('H10.2', 'H10.4'),
            ('H12.1', 'H12.3'), ('H12.2', 'H12.4'),
            ('H11.1', 'H11.3'), ('H11.2', 'H11.4'),
            ('PC1', 'ADC_IN1'), ('PE6', 'LED1')]
board['defaultAddedWires'] = [{'id': f'v2-example-{destination.lower()}',
                               'a': source, 'b': destination,
                               'evidence': 'User V2 driver example, 2026-11-16',
                               'verified': False, 'editable': True}
                              for source, destination in examples]
svg = [
    '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="650" viewBox="0 0 1000 650">',
    '<defs><linearGradient id="pcb" x2="0" y2="1"><stop stop-color="#172b48"/><stop offset="1" stop-color="#0c182a"/></linearGradient></defs>',
    '<rect x="10" y="10" width="980" height="630" rx="28" fill="url(#pcb)" stroke="#364d6c"/>',
    '<g fill="#5d7391">' + ''.join(f'<circle cx="{x}" cy="{y}" r="8"/>'
                                    for x, y in ((32, 32), (968, 32), (32, 618), (968, 618))) + '</g>'
]


def text(x, y, value, size=12, fill='#9eb3cf', anchor='middle'):
    svg.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="Segoe UI,Arial,sans-serif" '
               f'font-size="{size}" fill="{fill}">{escape(str(value))}</text>')


def rectangle(x, y, width, height):
    svg.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="8" '
               'fill="#080f1b" stroke="#38506d"/>')


def place(pin, x, y):
    if pin.get('x') is not None and 'photoPosition' not in pin:
        pin['photoPosition'] = {'x': pin['x'], 'y': pin['y'], 'viewBox': [0, 0, 1000, 650]}
    pin['x'], pin['y'] = x, y
    pin.pop('lockedReason', None)
    pin['connectable'] = pin.get('kind') != 'nc'
    if pin.get('kind') == 'power':
        pin['powerVoltage'] = 3.3 if pin['net'] in ('3V3', 'OLED_3V3') else 0
        pin['powerRole'] = 'input' if pin['id'].startswith('OLED_') else 'supply'
    color = '#6f7c90' if pin.get('kind') == 'nc' else '#cba462'
    svg.append(f'<rect x="{x - 5}" y="{y - 5}" width="10" height="10" rx="2" fill="{color}"/>')


text(500, 38, 'CIMC · V2.0', 19, '#eff6ff')
text(500, 619, 'V2 SCHEMATIC · FIXED COPPER + EDITABLE JUMPERS', 11)
text(500, 638, 'CONNECTOR PIN NUMBERS VERIFIED FROM ORIGINAL SCHEMATIC', 9, '#8094ad')
for group, center in (('U3', 300), ('U2', 700)):
    rectangle(center - 34, 142, 68, 410)
    text(center, 123, group + ' · 2 × 20', 14, '#d7e6f8')
    for pin in (pin for pin in board['pins'] if pin['group'] == group):
        row = pin['rowFromTop']
        left = pin['column'] == 'left'
        net = pin.get('net') or 'NC'
        suffix = 'L' if left else 'R'
        pin['label'] = f'{group}.{pin["number"]} · {net}'
        x, y = center + (-15 if left else 15), 160 + (row - 1) * 20
        place(pin, x, y)
        text(center - 43 if left else center + 43, y + 4,
             f'{pin["number"]} {net}', 10, anchor='end' if left else 'start')
rectangle(425, 286, 150, 126)
text(500, 324, 'GD32F470', 20, '#e8f2ff')
text(500, 350, 'VET6 · Cortex-M4', 11)
text(500, 382, 'MCU BREAKOUT', 10)
text(90, 144, 'H4 · LED', 13, '#f0c67b')
text(910, 144, 'H3 · KEY', 13, '#f0c67b')
for index in range(6):
    y = 175 + index * 26
    for prefix, x, label_x, anchor in (('LED', 120, 103, 'end'), ('KEY', 880, 897, 'start')):
        pin = next(pin for pin in board['pins'] if pin['id'] == f'{prefix}{index + 1}')
        pin['number'] = 6 - index
        pin['label'] = f'{pin["group"]}.{pin["number"]} · {pin["id"]}'
        pin['evidence'] = f'V2 schematic p2 {pin["group"]} pin {pin["number"]}'
        pin['net'] = pin['id'] if prefix == 'LED' else f'FUN_KEY{index + 1}'
        place(pin, x, y)
        text(label_x, y + 4, pin['id'], 12, anchor=anchor)
text(90, 380, 'OLED', 13, '#d7e6f8')
for index, endpoint in enumerate(('OLED_SDA', 'OLED_SCL', 'OLED_3V3', 'OLED_GND')):
    pin = next(pin for pin in board['pins'] if pin['id'] == endpoint)
    pin['label'] = f'OLED · {endpoint.removeprefix("OLED_")}'
    pin['number'] = 4 - index
    pin['evidence'] = f'V2 schematic p2 OLED1 pin {pin["number"]}'
    pin['net'] = {'OLED_SDA': 'OLED_DAT', 'OLED_SCL': 'OLED_CLK',
                  'OLED_3V3': '3V3', 'OLED_GND': 'DGND'}[endpoint]
    place(pin, 120, 405 + index * 25)
    text(105, 409 + index * 25, endpoint.removeprefix('OLED_'), 11, anchor='end')
# Functional terminals have no claimed physical connector number.
new_terminals = {
    '485_DE': ('RS485', 120, 530, '485 DIR'),
    'ADC_IN10': ('ANALOG', 450, 471, 'VR1 / PC0'), 'ADC_IN1': ('ANALOG', 450, 497, 'EXT ADC'),
    'S_ADC': ('SENSOR', 450, 195, 'H6.5 S_ADC'),
    'S_DAC': ('SENSOR', 450, 221, 'H6.6 S_DAC'),
    'ADC_IN12': ('H7', 840, 535, 'H7.1 ADC12'), '3V3_REF': ('H7', 840, 560, 'H7.2 REF'),
}
board['pins'] = [pin for pin in board['pins'] if pin['id'] not in new_terminals and pin['id'] not in ('ADC_IN0', '485_RX', '485_TX', 'DAC_OUT0') and pin['group'] not in ('H10','H11','H12')]
for x, y, width, height, label, label_y in ((425, 451, 150, 64, 'ADC', 443),
                                          (425, 177, 150, 60, 'H6 · SENSOR', 169)):
    rectangle(x, y, width, height)
    text(500, label_y, label, 12, '#d7e6f8')
for endpoint, (group, x, y, label) in new_terminals.items():
    pin = {'id': endpoint, 'net': endpoint, 'label': endpoint, 'group': group,
           'kind': 'signal', 'verified': False, 'physicalPinVerified': False,
           'evidence': 'Functional endpoint from user V2 driver; physical connector number pending schematic'}
    place(pin, x, y)
    if endpoint in ('ADC_IN10', 'ADC_IN12', '3V3_REF', '485_DE'):
        pin.update(verified=True, evidence='V2 schematic p1/p2/p3/p4 fixed peripheral net')
    if endpoint == 'ADC_IN12':
        pin.update(number=1, physicalPinVerified=True, evidence='V2 schematic p3 H7 pin 1')
    if endpoint == '3V3_REF':
        pin.update(number=2, physicalPinVerified=True, kind='power', powerVoltage=3.3,
                   powerRole='supply', evidence='V2 schematic p3 H7 pin 2 3.3VREF')
    if endpoint in ('S_ADC', 'S_DAC'):
        pin.update(number=5 if endpoint == 'S_ADC' else 6, physicalPinVerified=True,
                   verified=True, evidence=f'V2 schematic p2 H6 pin {5 if endpoint == "S_ADC" else 6}')
    board['pins'].append(pin)
    text(x + 14, y + 4, label, 11, anchor='start')
for group, rows, center, top in (
        ('H10', [('485_RX','485_TX'),('USART1_TX','USART1_RX'),('232_RX','232_TX')], 500, 80),
        ('H12', [('USB_RX','USB_TX'),('USART0_TX','USART0_RX')], 500, 566),
        ('H11', [('TTL_OUT_RX','TTL_OUT_TX'),('USART2_TX','USART2_RX'),('ESP_RX','ESP_TX')], 895, 400)):
    text(center, top - 18, group, 12, '#d7e6f8')
    for row, pair in enumerate(rows):
        for column, net in enumerate(pair):
            number = row * 2 + column + 1
            x, y = center - 30 + column * 60, top + row * 24
            pin = {'id': f'{group}.{number}', 'net': net, 'label': f'{group}.{number} · {net}',
                   'group': group, 'number': number, 'kind': 'signal', 'verified': True,
                   'evidence': f'V2 schematic p4 {group} pin {number}'}
            place(pin, x, y)
            board['pins'].append(pin)
            text(x - 13 if column == 0 else x + 13, y + 4, net, 9,
                 anchor='end' if column == 0 else 'start')
if not any(source['id'] == 'S8' for source in board['sources']):
    board['sources'].append({'id': 'S8', 'title': 'User supplied V2 Bootloader and App driver example',
                              'local': '../27_0_BootLoader', 'date': '2026-11-16'})
for led in board['leds']:
    led.update(activeLow=False, polarityVerified=True, resistorOhms=2000,
               polarityEvidence='V2 schematic p2 LED series resistor and cathode-to-DGND')
for index, key in enumerate(board['keys'], 1):
    key.update(terminal=f'FUN_KEY{index}', activeLow=True, idle=1, polarityVerified=True,
               pullUpOhms=10000, polarityEvidence='V2 schematic p2 10k pull-up, switch-to-DGND')
source_pdf = Path('D:/Edge_Download/GD32F470+Development+Kit+V2.0+原理图.pdf')
if source_pdf.exists():
    board['sources'] = [source for source in board['sources'] if source['id'] != 'S9']
    board['sources'].append({'id': 'S9', 'title': 'GD32F470 Development Kit V2.0 five-page schematic',
                              'local': str(source_pdf), 'sha256': hashlib.sha256(source_pdf.read_bytes()).hexdigest(),
                              'packaged': 'assets/schematics/GD32F470-V2.0-schematic.pdf',
                              'date': '2026-11-16'})
# Display paths illustrate copper already represented by fixedNets.
board['fixedVisualWires'] = [
    {'id': 'fixed-v2-oled-sda', 'from': 'OLED_SDA', 'to': 'PB9', 'color': '#cab1ed',
     'label': 'OLED SDA · V2 原理图固定铜线', 'locked': True,
     'points': [[120,405],[180,405],[180,565],[340,565],[340,520],[315,520]]},
    {'id': 'fixed-v2-oled-scl', 'from': 'OLED_SCL', 'to': 'PB8', 'color': '#63d6c7',
     'label': 'OLED SCL · V2 原理图固定铜线', 'locked': True,
     'points': [[120,430],[205,430],[205,520],[285,520]]},
    {'id': 'fixed-v2-oled-vcc', 'from': 'OLED_3V3', 'to': 'U2.36', 'color': '#e99291',
     'label': 'OLED 3V3 · V2 原理图固定铜线', 'locked': True,
     'points': [[120,455],[160,455],[160,600],[775,600],[775,500],[715,500]]},
    {'id': 'fixed-v2-oled-gnd', 'from': 'OLED_GND', 'to': 'U2.35', 'color': '#a5b5c9',
     'label': 'OLED GND · V2 原理图固定铜线', 'locked': True,
     'points': [[120,480],[140,480],[140,585],[650,585],[650,500],[685,500]]},
]
svg.append('</svg>')
path.write_text(json.dumps(board, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(ROOT / 'web/assets/board-v2.svg').write_text('\n'.join(svg) + '\n', encoding='utf-8')
print(f'V2 connection diagram: {len(board["pins"])} endpoints, {len(examples)} editable example wires')
