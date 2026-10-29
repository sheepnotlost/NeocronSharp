using System.Runtime.InteropServices;
using NeocronSharp;

namespace NavmeshPrototype;

/// <summary>
/// Like the app's GameInput, but a turn keeps W held so the character can steer
/// while walking, and mouse pulses are a configurable size.
/// </summary>
internal sealed class SteerInput : IDisposable
{
    private const ushort W = 0x11, Shift = 0x2a;   // keys.ini: W = Forward, SHIFT = Run
    private readonly PlayerReader _reader;
    public int Pulse { get; }
    public bool Run { get; }
    public bool Walking { get; private set; }
    private bool _sprint = true;
    public SteerInput(PlayerReader reader, int pulse, bool run = false)
    {
        Run = run;
        if (pulse is < 1 or > 40) throw new ArgumentOutOfRangeException(nameof(pulse), "Pulse must be 1..40 pixels.");
        _reader = reader; Pulse = pulse;
    }

    public void Walk(bool on)
    {
        if (on == Walking) return;
        if (on) _reader.RequireForeground();
        // Track the key before sending, so even uncertain delivery gets a key-up.
        Walking = on;
        // Shift is held only while moving, pressed before W and released after it.
        if (on && Run && _sprint) Key(Shift, false);
        Key(W, !on);
        if (!on && Run && _sprint) Key(Shift, true);
    }

    /// <summary>Send one mouse pulse of at most <see cref="Pulse"/> pixels; returns the pixels sent.</summary>
    public int TurnPulse(int pixels)
    {
        int move = Math.Clamp(pixels, -Pulse, Pulse);
        if (move == 0) return 0;
        _reader.RequireForeground();
        var packet = new Native.Input { Type = 0, Data = new Native.InputUnion { Mouse = new Native.MouseInput { X = move, Flags = 0x0001 } } };
        if (Native.SendInput(1, new[] { packet }, Marshal.SizeOf<Native.Input>()) != 1)
            throw new InvalidOperationException("Windows rejected steering input.");
        return move;
    }

    private static void Key(ushort scan, bool up)
    {
        var packet = new Native.Input { Type = 1, Data = new Native.InputUnion {
            Keyboard = new Native.KeyboardInput { ScanCode = scan, Flags = 0x0008u | (up ? 0x0002u : 0u) } } };
        if (Native.SendInput(1, new[] { packet }, Marshal.SizeOf<Native.Input>()) != 1)
            throw new InvalidOperationException("Windows rejected movement input.");
    }

    /// <summary>
    /// "Use" what the crosshair points at (keys.ini binds Use to MBUTTON 2, the right
    /// mouse button): opens the door in front, which is how most exits into buildings work.
    /// </summary>
    public void Use()
    {
        _reader.RequireForeground();
        foreach (uint flag in new[] { 0x0008u, 0x0010u })   // right button down, then up
        {
            var packet = new Native.Input { Type = 0, Data = new Native.InputUnion { Mouse = new Native.MouseInput { Flags = flag } } };
            if (Native.SendInput(1, new[] { packet }, Marshal.SizeOf<Native.Input>()) != 1)
                throw new InvalidOperationException("Windows rejected the use click.");
            Thread.Sleep(60);
        }
    }

    /// <summary>Run (Shift held) or walk while moving; only matters when <see cref="Run"/> is on.</summary>
    public void Sprint(bool on)
    {
        if (!Run || on == _sprint) return;
        _sprint = on;
        if (Walking) Key(Shift, !on);
    }

    public void Dispose() { if (Walking) { Walking = false; Key(W, true); if (Run) Key(Shift, true); } }
}
