using System.Runtime.InteropServices;
using NeocronSharp;

namespace NavmeshPrototype;

internal static class KeyProbe
{
    public static void Send(ushort scan, bool up)
    {
        var packet = new Native.Input { Type = 1, Data = new Native.InputUnion {
            Keyboard = new Native.KeyboardInput { ScanCode = scan, Flags = 0x0008u | (up ? 0x0002u : 0u) } } };
        Native.SendInput(1, new[] { packet }, Marshal.SizeOf<Native.Input>());
    }
}
