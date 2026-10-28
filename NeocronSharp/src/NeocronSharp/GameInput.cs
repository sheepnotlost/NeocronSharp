using System.Runtime.InteropServices;
using NeocronSharp.Core;

namespace NeocronSharp;

internal sealed class GameInput : IDisposable
{
    private TravelInput _held;
    private readonly PlayerReader _reader;
    public GameInput(PlayerReader reader) => _reader = reader;

    public void Set(TravelInput input)
    {
        if (input == _held) return;
        Release();
        if (input == TravelInput.None) return;
        _reader.RequireForeground();
        ushort scan = input == TravelInput.Forward ? (ushort)0x11 : (ushort)0x1f; // W / S
        // Track the key before attempting input, so even uncertain delivery gets a key-up.
        _held = input;
        Send(scan, false);
    }

    public void Release()
    {
        if (_held == TravelInput.None) return;
        ushort scan = _held == TravelInput.Forward ? (ushort)0x11 : (ushort)0x1f;
        Send(scan, true);
        _held = TravelInput.None;
    }

    public void Turn(int horizontalPixels)
    {
        if (horizontalPixels is < -24 or > 24) throw new ArgumentOutOfRangeException(nameof(horizontalPixels));
        Release();
        _reader.RequireForeground();
        var packet = new Native.Input { Type = 0, Data = new Native.InputUnion {
            Mouse = new Native.MouseInput { X = horizontalPixels, Flags = 0x0001 }
        }};
        if (Native.SendInput(1, new[] { packet }, Marshal.SizeOf<Native.Input>()) != 1)
            throw new InvalidOperationException("Windows rejected steering input.");
    }

    private static void Send(ushort scan, bool up)
    {
        var packet = new Native.Input { Type = 1, Data = new Native.InputUnion {
            Keyboard = new Native.KeyboardInput { ScanCode = scan, Flags = 0x0008u | (up ? 0x0002u : 0u) }
        }};
        if (Native.SendInput(1, new[] { packet }, Marshal.SizeOf<Native.Input>()) != 1)
            throw new InvalidOperationException("Windows rejected movement input.");
    }

    public void Dispose() => Release();
}
