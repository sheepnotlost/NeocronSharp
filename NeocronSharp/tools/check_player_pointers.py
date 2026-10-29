import sys,struct
sys.path.insert(0,r'C:\Users\Kainen\Documents\Neocron AoSharp\NeocronSharp\tools')
from probe_position import Reader
r=Reader(36636)
try:
 w=r.pointer(r.base+0xd68330);reg=r.pointer(r.pointer(w+0x58)+0x68);buckets=r.pointer(reg);n=struct.unpack('<i',r.read(reg+8,4))[0]
 for b in struct.unpack('<'+'Q'*n,r.read(buckets,n*8)):
  while b:
   raw=r.read(b,32);p,b=struct.unpack_from('<QQ',raw,16)
   if r.pointer(p)!=r.base+0x5bbbb8:continue
   a=r.pointer(p+0x608);print('APP',hex(a))
   if not a:continue
   print('arrays',hex(r.pointer(a+0x10)),hex(r.pointer(a+0x20)))
   v=r.pointer(a+0x20); count=struct.unpack('<H',r.read(a+0x18,2))[0]
   print([(j,hex(r.pointer(v+j*16)),struct.unpack('<H',r.read(v+j*16+8,2))[0]) for j in range(count)])
finally:r.close()
