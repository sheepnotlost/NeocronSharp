"""Inspect this local PE without loading or modifying the game executable."""
import argparse
import hashlib
import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / '.deps'))
from capstone import Cs, CS_ARCH_X86, CS_MODE_64


class Image:
    def __init__(self, path):
        self.data = pathlib.Path(path).read_bytes()
        pe = struct.unpack_from('<I', self.data, 0x3c)[0]
        optional = pe + 24
        self.base = struct.unpack_from('<Q', self.data, optional + 24)[0]
        count = struct.unpack_from('<H', self.data, pe + 6)[0]
        size = struct.unpack_from('<H', self.data, pe + 20)[0]
        self.sections = []
        for i in range(count):
            at = optional + size + i * 40
            name = self.data[at:at+8].rstrip(b'\0').decode()
            virtual_size, virtual, raw_size, raw = struct.unpack_from('<IIII', self.data, at+8)
            self.sections.append((name, virtual, max(virtual_size, raw_size), raw, raw_size))
        self.functions = []
        for name, virtual, _, raw, size in self.sections:
            if name == '.pdata':
                self.functions = [struct.unpack_from('<III', self.data, at)[:2]
                                  for at in range(raw, raw+size-11, 12)]

    def raw(self, rva):
        for _, virtual, size, raw, _ in self.sections:
            if virtual <= rva < virtual+size:
                return raw+rva-virtual
        raise ValueError(hex(rva))

    def rva(self, raw_offset):
        for _, virtual, _, raw, size in self.sections:
            if raw <= raw_offset < raw+size:
                return virtual+raw_offset-raw
        raise ValueError(hex(raw_offset))

    def disassemble(self, rva, before=12, after=28):
        function = next(((a, z) for a, z in self.functions if a <= rva < z), None)
        start, end = function or (rva, rva+256)
        print(f'function RVA {start:#x}..{end:#x}, focus {rva:#x}')
        raw = self.raw(start)
        instructions = list(Cs(CS_ARCH_X86, CS_MODE_64).disasm(
            self.data[raw:raw+end-start], self.base+start))
        focus = next((i for i, x in enumerate(instructions) if x.address >= self.base+rva), 0)
        for instruction in instructions[max(0, focus-before):focus+after]:
            print(f'{instruction.address-self.base:08x}  {instruction.mnemonic:8} {instruction.op_str}')

    def xrefs(self, text):
        targets = {}
        for match in re.finditer(re.escape(text.encode()), self.data):
            for delta in (0, -1):
                targets[self.base+self.rva(match.start()+delta)] = match.start()+delta
        for name, virtual, _, raw, size in self.sections:
            if name != '.text':
                continue
            for match in re.finditer(rb'[\x48\x4c][\x8d\x8b][\x05\x0d\x15\x1d\x25\x2d\x35\x3d]', self.data[raw:raw+size]):
                offset = raw+match.start()
                source = self.rva(offset)
                destination = self.base+source+7+struct.unpack_from('<i', self.data, offset+3)[0]
                if destination in targets:
                    print(f'xref RVA {source:#x}, string RVA {destination-self.base:#x}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--client', default=str(pathlib.Path(__file__).parents[2] / 'Neocron Evolution 2.5' / 'neocronclient.exe'))
    parser.add_argument('--xref')
    parser.add_argument('--disassemble', type=lambda value: int(value, 0))
    parser.add_argument('--before', type=int, default=12)
    parser.add_argument('--after', type=int, default=28)
    args = parser.parse_args()
    image = Image(args.client)
    print('sha256', hashlib.sha256(image.data).hexdigest())
    if args.xref:
        image.xrefs(args.xref)
    if args.disassemble is not None:
        image.disassemble(args.disassemble, args.before, args.after)
