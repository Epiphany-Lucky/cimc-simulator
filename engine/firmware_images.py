"""Validated, immutable sparse firmware images and atomic internal Flash layouts."""
from dataclasses import dataclass
import base64
import hashlib
import json
import struct
import uuid

FLASH = 0x08000000
FLASH_SIZE = 0x80000
SRAM = 0x20000000
SRAM_SIZE = 0x30000
CCM = 0x10000000
CCM_SIZE = 0x10000
MAX_FILE_SIZE = 4 * 1024 * 1024
MAX_SET_EXPORT_SIZE = 8 * 1024 * 1024
SEGMENT_PREVIEW_LIMIT = 64


def address_value(value, label='地址'):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(label + '必须为整数或十六进制地址')
    try:
        return int(value, 0) if isinstance(value, str) else value
    except ValueError:
        raise ValueError(label + '无效') from None


def valid_sp(sp):
    return sp % 4 == 0 and (SRAM < sp <= SRAM + SRAM_SIZE or CCM < sp <= CCM + CCM_SIZE)


@dataclass(frozen=True)
class FirmwareImage:
    id: str
    name: str
    raw: bytes
    format: str
    segments: tuple

    @property
    def base(self):
        return self.segments[0][0]

    @property
    def end(self):
        a, data = self.segments[-1]
        return a + len(data)

    def metadata(self):
        spans = [{'address': f'0x{a:08X}', 'size': len(b)} for a, b in self.segments[:SEGMENT_PREVIEW_LIMIT]]
        return {'id': self.id, 'name': self.name, 'format': self.format,
                'size': len(self.raw), 'imageSize': self.end - self.base,
                'address': f'0x{self.base:08X}', 'endAddress': f'0x{self.end:08X}',
                'writtenSize': sum(len(b) for _, b in self.segments),
                'spanSize': self.end - self.base, 'segments': spans,
                'segmentCount': len(self.segments), 'segmentsTruncated': len(self.segments) > len(spans),
                'sha256': hashlib.sha256(self.raw).hexdigest()}

    def exported(self):
        return {'id': self.id, 'filename': self.name, 'data': base64.b64encode(self.raw).decode('ascii'),
                'address': f'0x{self.base:08X}'}


def parse_image(raw, filename, address=FLASH, image_id=None):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_FILE_SIZE:
        raise ValueError('固件为空或超过 4 MiB')
    if not isinstance(filename, str) or not filename or len(filename) > 512:
        raise ValueError('固件文件名无效')
    if image_id is None:
        image_id = str(uuid.uuid4())
    if not isinstance(image_id, str) or not image_id or len(image_id) > 128:
        raise ValueError('固件 id 无效')
    if not filename.lower().endswith('.hex'):
        base = address_value(address)
        if base < FLASH or base + len(raw) > FLASH + FLASH_SIZE:
            raise ValueError('BIN 装载地址或大小超出 Flash 范围')
        return FirmwareImage(image_id, filename, raw, 'BIN', ((base, raw),))
    cells = {}
    upper = 0
    eof = False
    for line_no, line in enumerate(raw.decode('ascii').splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if eof:
            raise ValueError(f'HEX 第 {line_no} 行：EOF 后仍有记录')
        if not line.startswith(':'):
            raise ValueError(f'HEX 第 {line_no} 行缺少冒号')
        try:
            record = bytes.fromhex(line[1:])
        except ValueError:
            raise ValueError(f'HEX 第 {line_no} 行包含非法十六进制') from None
        if len(record) < 5 or len(record) != record[0] + 5 or sum(record) & 255:
            raise ValueError(f'HEX 第 {line_no} 行长度或校验和错误')
        length, offset, kind = record[0], int.from_bytes(record[1:3], 'big'), record[3]
        payload = record[4:-1]
        if kind == 0:
            start = upper + offset
            if start < FLASH or start + length > FLASH + FLASH_SIZE:
                raise ValueError('HEX 数据超出 Flash 地址范围')
            for i, b in enumerate(payload):
                a = start + i
                if a in cells and cells[a] != b:
                    raise ValueError('HEX 记录地址重叠且内容不一致')
                cells[a] = b
        elif kind == 1:
            if length or offset:
                raise ValueError('HEX EOF 记录无效')
            eof = True
        elif kind in (2, 4):
            if length != 2 or offset:
                raise ValueError('HEX 扩展地址记录无效')
            upper = int.from_bytes(payload, 'big') << (4 if kind == 2 else 16)
        elif kind in (3, 5):
            if length != 4 or offset:
                raise ValueError('HEX 起始地址记录无效')
        else:
            raise ValueError(f'HEX 不支持记录类型 {kind}')
    if not eof or not cells:
        raise ValueError('HEX 缺少 EOF 或程序数据')
    segments = []
    current = bytearray()
    start = None
    for a in sorted(cells):
        if start is None or a != start + len(current):
            if current:
                segments.append((start, bytes(current)))
            start, current = a, bytearray()
        current.append(cells[a])
    segments.append((start, bytes(current)))
    return FirmwareImage(image_id, filename, raw, 'HEX', tuple(segments))


@dataclass(frozen=True)
class FirmwareSet:
    images: tuple
    flash: bytes
    written: bytes
    boot_address: int
    sp: int
    entry: int
    boot_image_id: str

    def exported(self):
        return {'images': [im.exported() for im in self.images], 'bootAddress': f'0x{self.boot_address:08X}'}


def assemble(images, boot_address):
    if not images:
        raise ValueError('至少需要一个固件文件')
    boot_address = address_value(boot_address, '启动向量地址')
    if boot_address % 128 or not FLASH <= boot_address <= FLASH + FLASH_SIZE - 8:
        raise ValueError('启动向量地址必须在 Flash 内并按 128 字节对齐')
    flash = bytearray(b'\xff' * FLASH_SIZE)
    written = bytearray(FLASH_SIZE)
    seen = set()
    boot_image_id = None
    for im in images:
        if im.id in seen:
            raise ValueError('固件 id 重复')
        seen.add(im.id)
        for a, data in im.segments:
            p, n = a - FLASH, len(data)
            if any(written[p:p+n]):
                raise ValueError(f'固件实际字节地址重叠：{im.name} @ 0x{a:08X}')
            flash[p:p+n] = data
            written[p:p+n] = b'\x01' * n
            if a <= boot_address < a + n:
                boot_image_id = im.id
    offset = boot_address - FLASH
    if not all(written[offset:offset+8]):
        raise ValueError('启动向量的 8 字节未完整烧录')
    sp, entry = struct.unpack_from('<II', flash, offset)
    if not valid_sp(sp):
        raise ValueError(f'初始 SP 0x{sp:08X} 不在 SRAM 范围内')
    target = (entry & ~1) - FLASH
    if not entry & 1 or not 0 <= target < FLASH_SIZE - 1 or not all(written[target:target+2]):
        raise ValueError(f'复位向量 0x{entry:08X} 无效或入口未实际烧录')
    program = FirmwareSet(tuple(images), bytes(flash), bytes(written), boot_address, sp, entry, boot_image_id)
    # Count the complete portable representation, including generated IDs and
    # base64/JSON escaping. References cannot grow a set past its restore budget.
    exported_size = len(json.dumps(program.exported(), ensure_ascii=True, separators=(',', ':')))
    if exported_size > MAX_SET_EXPORT_SIZE:
        raise ValueError('固件集合数据超过 8MiB，无法保证工程完整保存与重新导入；请减少文件或精简 HEX 记录')
    return program


def prepare_set(data, existing=(), allow_references=True):
    if not isinstance(data, dict) or not isinstance(data.get('images'), list) or not data['images']:
        raise ValueError('images 必须是非空固件列表')
    if 'bootAddress' in data and 'bootIndex' in data:
        raise ValueError('bootAddress 与 bootIndex 不能同时指定')
    known = {im.id: im for im in existing}
    images = []
    for item in data['images']:
        if not isinstance(item, dict):
            raise ValueError('固件条目必须是对象')
        if set(item) == {'id'}:
            ident = item['id']
            if not isinstance(ident, str) or not allow_references or ident not in known:
                raise ValueError('引用的固件 id 不存在')
            images.append(known[ident])
            continue
        if 'data' not in item or 'filename' not in item:
            raise ValueError('新固件缺少 filename 或 data')
        if allow_references and 'id' in item:
            raise ValueError('新固件不能同时携带既有 id')
        if not isinstance(item['data'], str):
            raise ValueError('固件 data 必须是 base64 字符串')
        raw = base64.b64decode(item['data'], validate=True)
        filename = item['filename']
        if not isinstance(filename, str):
            raise ValueError('固件文件名无效')
        if not filename.lower().endswith('.hex') and 'address' not in item:
            raise ValueError('BIN 文件必须指定烧录地址')
        images.append(parse_image(raw, filename, item.get('address', FLASH), item.get('id')))
    if 'bootIndex' in data:
        index = data['bootIndex']
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(images):
            raise ValueError('启动固件索引无效')
        boot = images[index].base
    else:
        boot = data.get('bootAddress', images[0].base)
    return assemble(images, boot)


def parse_firmware(data, filename, address=FLASH):
    """Legacy single-file tuple, retaining strict startup validation."""
    im = parse_image(data, filename, address)
    program = assemble((im,), im.base)
    return program.flash[im.base-FLASH:im.end-FLASH], im.base, program.sp, program.entry, im.format
