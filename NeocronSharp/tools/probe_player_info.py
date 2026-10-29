import sys,struct,pathlib
sys.path.insert(0,r'C:\Users\Kainen\Documents\Neocron AoSharp\NeocronSharp\tools')
from inspect_client import Image
from capstone import Cs,CS_ARCH_X86,CS_MODE_64
from probe_position import Reader
from discover_actors import Types
i=Image(r'C:\Users\Kainen\Documents\Neocron AoSharp\Neocron Evolution 2.5\neocronclient.exe');r=Reader(36636);t=Types(i,r)
try:
 world=r.pointer(r.base+0xd68330); reg=r.pointer(r.pointer(world+0x58)+0x68);buckets=r.pointer(reg);n=struct.unpack('<i',r.read(reg+8,4))[0]
 for b in struct.unpack('<'+'Q'*n,r.read(buckets,n*8)):
  while b:
   raw=r.read(b,32);p,b=struct.unpack_from('<QQ',raw,16)
   if r.pointer(p)!=r.base+0x5bbbb8:continue
   obj=p-0x1c8
   print('ACTOR',hex(obj))
   raw=r.read(obj,0x1c8)
   for off in range(0,0x1c8,8):
    q=struct.unpack_from('<Q',raw,off)[0]
    if 0x10000<=q<=0x7fffffffffff:
     print(hex(off),hex(q),'type',t.object(q))
     try:
      data=r.read(q,0x100)
      import re
      print(' text',[(hex(m.start()),m.group().decode(errors='replace')) for m in re.finditer(rb'[A-Za-z][A-Za-z0-9 _./-]{3,60}\x00',data)])
     except OSError:pass
   break
  else:continue
  break
 print('PRIMARY VTABLE')
 for slot in range(0,0x100,8):
  target=struct.unpack_from('<Q',i.data,i.raw(0x5bbd70+slot))[0]-i.base
  print(hex(slot),hex(target))
 print('DISPATCH')
 start=0x2e7190; raw=i.raw(start)
 for ins in Cs(CS_ARCH_X86,CS_MODE_64).disasm(i.data[raw:raw+800],i.base+start):print(hex(ins.address-i.base),ins.mnemonic,ins.op_str)
finally:r.close()
