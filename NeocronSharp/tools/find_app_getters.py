import sys,struct,re
sys.path.insert(0,r'C:\Users\Kainen\Documents\Neocron AoSharp\NeocronSharp\tools')
from inspect_client import Image
im=Image(r'C:\Users\Kainen\Documents\Neocron AoSharp\Neocron Evolution 2.5\neocronclient.exe')
for m in re.finditer(rb'\xb2([\x0a-\x0e]).{0,22}\xff\x50\x38',im.data,re.S):
 try:
  rv=im.rva(m.start())
  if rv<0x570000:print('getter',hex(rv),m.group(1)[0])
 except ValueError:pass
print('APP VTABLE')
for slot in range(0,0x90,8): print(hex(slot),hex(struct.unpack_from('<Q',im.data,im.raw(0x5c5d90+slot))[0]-im.base))
