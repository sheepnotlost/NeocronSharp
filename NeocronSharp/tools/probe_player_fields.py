import sys,struct,pathlib,re
sys.path.insert(0,r'C:\Users\Kainen\Documents\Neocron AoSharp\NeocronSharp\tools')
from inspect_client import Image
from capstone import Cs,CS_ARCH_X86,CS_MODE_64
from probe_position import Reader
from discover_actors import Types
i=Image(r'C:\Users\Kainen\Documents\Neocron AoSharp\Neocron Evolution 2.5\neocronclient.exe');r=Reader(36636);t=Types(i,r)
try:
 for start,size in [(0x2e74fb,750),(0x2e4d1c,230),(0x2e3410,200)]:
  print('CODE',hex(start))
  for ins in Cs(CS_ARCH_X86,CS_MODE_64).disasm(i.data[i.raw(start):i.raw(start)+size],i.base+start): print(hex(ins.address-i.base),ins.mnemonic,ins.op_str)
 world=r.pointer(r.base+0xd68330);reg=r.pointer(r.pointer(world+0x58)+0x68);buckets=r.pointer(reg);n=struct.unpack('<i',r.read(reg+8,4))[0]
 for b in struct.unpack('<'+'Q'*n,r.read(buckets,n*8)):
  while b:
   raw=r.read(b,32);p,b=struct.unpack_from('<QQ',raw,16)
   if r.pointer(p)!=r.base+0x5bbbb8:continue
   obj=p-0x1c8; raw=r.read(obj,0x1500); print('OBJECT POINTER STRINGS',hex(obj))
   for off in range(0,len(raw)-8,8):
    q=struct.unpack_from('<Q',raw,off)[0]
    if not 0x10000<=q<=0x7fffffffffff or q%8:continue
    try:
     data=r.read(q,0x280)
     strs=[(hex(m.start()),m.group().decode(errors='replace')) for m in re.finditer(rb'[A-Za-z][A-Za-z0-9 _./-]{3,60}\x00',data)]
     if strs:print(hex(off),hex(q),t.object(q),strs[:8])
    except OSError:pass
   break
  else:continue
  break
finally:r.close()
