import sys,struct,json
sys.path.insert(0,r'C:\Users\Kainen\Documents\Neocron AoSharp\NeocronSharp\tools')
from probe_position import Reader
r=Reader(36636)
try:
 w=r.pointer(r.base+0xd68330);reg=r.pointer(r.pointer(w+0x58)+0x68);buckets=r.pointer(reg);n=struct.unpack('<i',r.read(reg+8,4))[0]
 print('sector',struct.unpack('<i',r.read(w+0x258,4))[0])
 for b in struct.unpack('<'+'Q'*n,r.read(buckets,n*8)):
  while b:
   raw=r.read(b,32);key=struct.unpack_from('<i',raw,8)[0];p,b=struct.unpack_from('<QQ',raw,16)
   if r.pointer(p)!=r.base+0x5bbbb8:continue
   a=r.pointer(p+0x608)
   if a<0x10000:continue
   h=r.read(a,0x38);ns=struct.unpack_from('<H',h,8)[0];nb=struct.unpack_from('<H',h,0x18)[0];ss,bs=struct.unpack_from('<Q',h,0x10)[0],struct.unpack_from('<Q',h,0x20)[0]
   print('ACTOR',key,'pos',struct.unpack('<fff',r.read(p+0xd8,12)),'appearance',hex(a),'counts',ns,nb)
   print('SCALARS',[(j,struct.unpack('<f',r.read(ss+j*16,4))[0]) for j in range(min(ns,64))])
   for j in range(min(nb,32)):
    raw=r.read(bs+j*16,16);ptr,size=struct.unpack_from('<QH',raw)
    if ptr>=0x10000 and 0<size<=2048:
     data=r.read(ptr,size);print('BLOB',j,'len',size,'hex',data[:160].hex(),'text',repr(data[:160]))
finally:r.close()
