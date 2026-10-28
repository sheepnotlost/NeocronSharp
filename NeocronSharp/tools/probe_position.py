"""Read-only diagnostic for the inspected Evolution 2.5.902 executable.

Candidate fields are diagnostic evidence, not verified movement telemetry.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
import pathlib
import struct
from inspect_client import Image


class Reader:
    def __init__(self, pid):
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.kernel.OpenProcess.restype = w.HANDLE
        self.kernel.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
        self.kernel.ReadProcessMemory.restype = w.BOOL
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.kernel.OpenProcess(0x410, False, pid)
        if not self.handle:
            raise c.WinError(c.get_last_error())
        psapi = c.WinDLL('psapi', use_last_error=True)
        psapi.EnumProcessModulesEx.argtypes = [w.HANDLE, c.c_void_p, w.DWORD, c.POINTER(w.DWORD), w.DWORD]
        modules = (c.c_void_p * 1024)()
        needed = w.DWORD()
        if not psapi.EnumProcessModulesEx(self.handle, modules, c.sizeof(modules), c.byref(needed), 3):
            raise c.WinError(c.get_last_error())
        self.base = modules[0]

    def read(self, address, size):
        buffer = c.create_string_buffer(size)
        read = c.c_size_t()
        if not self.kernel.ReadProcessMemory(self.handle, address, buffer, size, c.byref(read)) or read.value != size:
            raise OSError(f'Unreadable memory at {address:#x}')
        return buffer.raw

    def pointer(self, address):
        return struct.unpack('<Q', self.read(address, 8))[0]

    def close(self):
        self.kernel.CloseHandle(self.handle)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('pid', type=int)
    args = parser.parse_args()
    image = Image(pathlib.Path(__file__).parents[2] / 'Neocron Evolution 2.5/neocronclient.exe')
    reader = Reader(args.pid)
    try:
        print(f'pid={args.pid} module={reader.base:#x}')
        _, rva, size, _, _ = next(section for section in image.sections if section[0] == '.data')
        data = reader.read(reader.base+rva, size)
        tested, found = set(), 0
        tables = {reader.base+0x616ac0: 'client', reader.base+0x58f758: 'vehicle',
                  reader.base+0x60c6e8: 'worldclient', reader.base+0x58b6a8: 'playercontrol',
                  reader.base+0x584418: 'worldmanager', reader.base+0x57de08: 'host'}
        for offset in range(0, len(data)-7, 8):
            value = struct.unpack_from('<Q', data, offset)[0]
            if value in tables:
                print('embedded', tables[value], hex(rva+offset))
            if value < 0x10000 or value > 0x7fffffffffff or value % 8 or value in tested:
                continue
            tested.add(value)
            try:
                table = reader.pointer(value)
            except OSError:
                continue
            if table not in tables:
                continue
            found += 1
            print('root', hex(rva+offset), tables[table], hex(value))
            if tables[table] == 'vehicle':
                print('actor position candidate', struct.unpack('<fff', reader.read(value+0xd8, 12)))
            elif tables[table] in ('client', 'worldclient'):
                camera = reader.pointer(value+0xa8)
                print('camera', hex(camera))
                if camera:
                    vtable = reader.pointer(camera)
                    function = reader.pointer(vtable+0x98)
                    print('camera get-position RVA', hex(function-reader.base))
            elif tables[table] == 'host':
                for childoff in range(8, 0x500, 8):
                    child = reader.pointer(value+childoff)
                    try:
                        childtable = reader.pointer(child)
                    except OSError:
                        continue
                    if childtable in tables:
                        print('host child', hex(childoff), tables[childtable], hex(child))
        print('unique pointers checked', len(tested), 'matching roots', found)
    finally:
        reader.close()
