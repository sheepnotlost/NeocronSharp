import sys,pathlib,struct,re
sys.path.insert(0,r'C:\Users\Kainen\Documents\Neocron AoSharp\NeocronSharp\tools')
from inspect_client import Image
from probe_position import Reader
client=pathlib.Path(r'C:\Users\Kainen\Documents\Neocron AoSharp\Neocron Evolution 2.5\neocronclient.exe')
i=Image(client); r=Reader(36636)
try:
 world=r.pointer(r.base+0xd68330); reg=r.pointer(r.pointer(world+0x58)+0x68); buckets=r.pointer(reg); n=struct.unpack('<i',r.read(reg+8,4))[0]
 found=[]
 for b in struct.unpack('<'+'Q'*n,r.read(buckets,n*8)):
  for _ in range(128):
   if not b:break
   data=r.read(b,32); key=struct.unpack_from('<i',data,8)[0]; p,nxt=struct.unpack_from('<QQ',data,16)
   if r.pointer(p)==r.base+0x5bbbb8:found.append((key,p))
   b=nxt
 print('network characters',len(found))
 for key,p in found[:15]:
  obj=p-0x1c8; raw=r.read(obj,0x1600)
  strings=[]
  for off in range(0,len(raw)-32,8):
   ln,cap=struct.unpack_from('<QQ',raw,off+16)
   if 0<ln<=64 and ln<=cap<=1024 and(cap==15 or cap>=16):
    try:
     txt=raw[off:off+ln+1] if cap==15 else r.read(struct.unpack_from('<Q',raw,off)[0],ln+1)
     if txt[-1:]==b'\0' and all(32<=v<127 for v in txt[:-1]):strings.append((hex(off),txt[:-1].decode()))
    except OSError:pass
  print('ACTOR',key,hex(p),'completevt',hex(r.pointer(obj)-r.base),'position',struct.unpack('<fff',r.read(p+0xd8,12)),'strings',strings)
  print('ASCII',[(hex(m.start()),m.group().decode(errors='replace')) for m in re.finditer(rb'[A-Za-z][A-Za-z0-9 _./-]{3,60}\x00',raw)][:12])
 print('LSTPLAYER physics slots')
 for slot in range(0,0x1a8,8):
  target=struct.unpack_from('<Q',i.data,i.raw(0x5bbbb8+slot))[0]-i.base
  print(hex(slot),hex(target))
 for slot in (0x58,0x60,0x68,0x70):
  target=struct.unpack_from('<Q',i.data,i.raw(0x5bbbb8+slot))[0]-i.base
  i.disassemble(target,0,20)
finally:r.close()
