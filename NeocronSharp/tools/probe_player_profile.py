import sys,struct,re
sys.path.insert(0,r'C:\Users\Kainen\Documents\Neocron AoSharp\NeocronSharp\tools')
from inspect_client import Image
from capstone import Cs,CS_ARCH_X86,CS_MODE_64
from probe_position import Reader
from discover_actors import Types
i=Image(r'C:\Users\Kainen\Documents\Neocron AoSharp\Neocron Evolution 2.5\neocronclient.exe');r=Reader(36636);t=Types(i,r)
def strings(base,size):
 try:raw=r.read(base,size)
 except OSError:return []
 found=[]
 for off in range(0,len(raw)-32,8):
  ln,cap=struct.unpack_from('<QQ',raw,off+16)
  if 0<ln<=80 and ln<=cap<=1024 and (cap==15 or cap>=16):
   try:
    txt=raw[off:off+ln+1] if cap==15 else r.read(struct.unpack_from('<Q',raw,off)[0],ln+1)
    if txt[-1:]==b'\0' and all(32<=v<127 for v in txt[:-1]):found.append((hex(off),txt[:-1].decode()))
   except OSError:pass
 return found
try:
 for ev in (1,2,0x30,0x42):
  ix=i.data[i.raw(0x1a2824+ev-1)];start=struct.unpack_from('<I',i.data,i.raw(0x1a27bc+ix*4))[0]
  print('EVENT',hex(ev),hex(start))
  for ins in Cs(CS_ARCH_X86,CS_MODE_64).disasm(i.data[i.raw(start):i.raw(start)+180],i.base+start):print(hex(ins.address-i.base),ins.mnemonic,ins.op_str)
 world=r.pointer(r.base+0xd68330);reg=r.pointer(r.pointer(world+0x58)+0x68);buckets=r.pointer(reg);n=struct.unpack('<i',r.read(reg+8,4))[0]
 for b in struct.unpack('<'+'Q'*n,r.read(buckets,n*8)):
  while b:
   raw=r.read(b,32);key=struct.unpack_from('<i',raw,8)[0];p,b=struct.unpack_from('<QQ',raw,16)
   if r.pointer(p)!=r.base+0x5bbbb8:continue
   q=r.pointer(p+0x608);print('ACTOR',key,hex(p),'flags',r.read(p+0x5fc,4).hex(),'info',hex(q))
   if q<0x10000:continue
   print('INFO',t.object(q),'vt',hex(r.pointer(q)-r.base),'strings',strings(q,0x1200))
   raw=r.read(q,0x600)
   for off in range(0,len(raw)-8,8):
    child=struct.unpack_from('<Q',raw,off)[0]
    if 0x10000<=child<=0x7fffffffffff and child%8==0:
     found=strings(child,0x180)
     if found:print('CHILD',hex(off),hex(child),t.object(child),found[:8])
finally:r.close()
