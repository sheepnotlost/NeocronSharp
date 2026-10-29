import sys
sys.path.insert(0,r'C:\Users\Kainen\Documents\Neocron AoSharp\NeocronSharp\tools')
from inspect_client import Image
from capstone import Cs,CS_ARCH_X86,CS_MODE_64
im=Image(r'C:\Users\Kainen\Documents\Neocron AoSharp\Neocron Evolution 2.5\neocronclient.exe')
for arg in sys.argv[1:]:
 a,n=(int(x,0) for x in arg.split(':')); print('CODE',hex(a))
 for ins in Cs(CS_ARCH_X86,CS_MODE_64).disasm(im.data[im.raw(a):im.raw(a)+n],im.base+a):print(hex(ins.address-im.base),ins.mnemonic,ins.op_str)
