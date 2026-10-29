import sys,struct
sys.path.insert(0,r'C:\Users\Kainen\Documents\Neocron AoSharp\NeocronSharp\tools')
from inspect_client import Image
from capstone import Cs,CS_ARCH_X86,CS_MODE_64
i=Image(r'C:\Users\Kainen\Documents\Neocron AoSharp\Neocron Evolution 2.5\neocronclient.exe')
for slot in (0x30,0x38,0x40,0x48):
 start=struct.unpack_from('<Q',i.data,i.raw(0x5c5d90+slot))[0]-i.base;print('SLOT',hex(slot),hex(start))
 for ins in Cs(CS_ARCH_X86,CS_MODE_64).disasm(i.data[i.raw(start):i.raw(start)+420],i.base+start):print(hex(ins.address-i.base),ins.mnemonic,ins.op_str)
