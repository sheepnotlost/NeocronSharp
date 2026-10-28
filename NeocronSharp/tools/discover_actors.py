"""Bounded, read-only inspection of actor-container candidates at known roots."""
import argparse
import collections
import pathlib
import struct
from inspect_client import Image
from probe_position import Reader


class Types:
    def __init__(self, image, reader):
        self.image, self.reader, self.cache = image, reader, {}

    def table(self, table):
        if table in self.cache:
            return self.cache[table]
        result = None
        rva = table-self.reader.base
        try:
            if 0x577000 <= rva < 0x6b9000:
                col = struct.unpack_from('<Q', self.image.data, self.image.raw(rva)-8)[0]-self.image.base
                signature, offset, _, descriptor, _, own = struct.unpack_from('<IIIIII', self.image.data, self.image.raw(col))
                if signature == 1 and own == col:
                    raw = self.image.raw(descriptor)+16
                    end = self.image.data.index(b'\0',raw,raw+160)
                    name = self.image.data[raw:end].decode('ascii')
                    if name.startswith('.?AV'):
                        result = (name[4:-2], offset)
        except (ValueError, struct.error, UnicodeError):
            pass
        self.cache[table] = result
        return result

    def object(self, pointer):
        if pointer < 0x10000 or pointer > 0x7fffffffffff or pointer % 8:
            return None
        try:
            found = self.table(self.reader.pointer(pointer))
            if found:
                return found
            # Some virtually inherited actors start with a vbtable, with their
            # first RTTI-bearing vtable in a following subobject.
            for offset in (8,16,24,32):
                found = self.table(self.reader.pointer(pointer+offset))
                if found and found[1] == offset:
                    return (found[0],0)
            return None
        except OSError:
            return None


def inspect(image, reader):
    types = Types(image,reader)
    world = reader.pointer(reader.base+0xd68330)
    roots = {'worldclient':world, 'worldmanager':reader.pointer(world+0x58),
             'gamenetmanager':reader.pointer(world+0x68)}
    for label, root in roots.items():
        print('ROOT',label,hex(root),types.object(root))
        data = reader.read(root,0x700)
        words = struct.unpack('<224Q',data)
        for index,pointer in enumerate(words):
            offset=index*8
            kind = types.object(pointer)
            if kind:
                print('typed',label,hex(offset),hex(pointer),kind)
            # A conventional vector of pointers, validated by the pointee RTTI.
            if index+2 < len(words):
                end,capacity=words[index+1:index+3]
                if pointer >= 0x10000 and pointer%8==0 and pointer < end <= capacity and capacity-pointer <= 8192*8 and (end-pointer)%8==0:
                    try:
                        values=struct.unpack('<'+str(min(128,(end-pointer)//8))+'Q',reader.read(pointer,min(128*8,end-pointer)))
                        names=collections.Counter(str(types.object(value)) for value in values)
                        if any(name!='None' for name in names):print('VECTOR',label,hex(offset),'count',(end-pointer)//8,names)
                    except OSError:
                        pass
            if not kind and pointer >= 0x10000 and pointer%8==0 and pointer < 0x7fffffffffff:
                try:
                    child=struct.unpack('<16Q',reader.read(pointer,128))
                except OSError:
                    continue
                hits=[(hex(i*8),hex(value),types.object(value)) for i,value in enumerate(child) if types.object(value)]
                if hits:print('container',label,hex(offset),hex(pointer),'hits',hits[:8])
        print()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('pid',type=int);args=parser.parse_args()
    image=Image(pathlib.Path(__file__).parents[2]/'Neocron Evolution 2.5/neocronclient.exe')
    reader=Reader(args.pid)
    try:inspect(image,reader)
    finally:reader.close()
