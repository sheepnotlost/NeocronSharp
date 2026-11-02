using System.Runtime.InteropServices;
using NeocronSharp;

namespace NavmeshPrototype;

/// <summary>
/// Stop now: F8 on the keyboard, or the suite's Stop button, which leaves this file in the working folder.
/// (The button used to send F8 itself, but the game gets that too: it is the Missions key, and it opens the
/// game's menus and leaves mouse-look. 31 Oct.)
/// </summary>
internal static class StopRequest
{
    public const string File = "stop.request";
    public static bool Made() => (Native.GetAsyncKeyState(0x77) & 0x8000) != 0 || System.IO.File.Exists(File);
}

/// <summary>
/// Like the app's GameInput, but a turn keeps W held so the character can steer
/// while walking, and mouse pulses are a configurable size.
/// </summary>
internal sealed class SteerInput : IDisposable
{
    private const ushort W = 0x11, S = 0x1f, A = 0x1e, D = 0x20, Shift = 0x2a, Space = 0x39, FirstSlot = 0x02;   // keys.ini: W = Forward, S = Back, A and D = Strafe, SHIFT = Run, SPACE = Jump, 1 = Slot 1
    private const int BurstStep = 6;   // the size the gains are measured at
    private readonly PlayerReader _reader;
    public int Pulse { get; }
    public bool Run { get; }
    public bool Walking { get; private set; }
    public bool Backing { get; private set; }
    private int _strafe;
    public bool LeftHeld { get; private set; }
    private bool _sprint = true;
    /// <summary>Shift and W are both down.</summary>
    public bool Sprinting => Run && _sprint && Walking;
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

    public void Back(bool on)
    {
        if (on == Backing) return;
        if (on) _reader.RequireForeground();
        Backing = on;
        Key(S, !on);
    }

    /// <summary>Strafe right (positive), left (negative) or not at all.</summary>
    public void Strafe(int side)
    {
        side = Math.Sign(side);
        if (side == _strafe) return;
        if (side != 0) _reader.RequireForeground();
        if (_strafe != 0) Key(_strafe > 0 ? D : A, true);
        _strafe = side;
        if (side != 0) Key(side > 0 ? D : A, false);
    }

    /// <summary>One tap of a slot's number key, 1 to 9.</summary>
    public void Slot(int slot)
    {
        _reader.RequireForeground();
        Key((ushort)(FirstSlot + slot - 1), false);
        Thread.Sleep(60);
        Key((ushort)(FirstSlot + slot - 1), true);
    }

    /// <summary>Send one mouse pulse of at most <see cref="Pulse"/> pixels; returns the pixels sent.</summary>
    public int TurnPulse(int pixels)
    {
        int move = Math.Clamp(pixels, -Pulse, Pulse);
        LookPulse(move, 0);
        return move;
    }

    /// <summary>Send one mouse pulse, right and down in pixels (each at most <see cref="Pulse"/>).</summary>
    public void LookPulse(int x, int y)
    {
        if (x == 0 && y == 0) return;
        _reader.RequireForeground();
        var packet = new Native.Input { Type = 0, Data = new Native.InputUnion { Mouse = new Native.MouseInput {
            X = Math.Clamp(x, -Pulse, Pulse), Y = Math.Clamp(y, -Pulse, Pulse), Flags = 0x0001 } } };
        if (Native.SendInput(1, new[] { packet }, Marshal.SizeOf<Native.Input>()) != 1)
            throw new InvalidOperationException("Windows rejected steering input.");
    }

    /// <summary>A whole turn in one call, as many small packets: Windows' acceleration sends a big one twice as far, and the game adds these up in a frame.</summary>
    public void LookBurst(int x, int y)
    {
        if (x == 0 && y == 0) return;
        _reader.RequireForeground();
        int steps = Math.Max(1, (Math.Max(Math.Abs(x), Math.Abs(y)) + BurstStep - 1) / BurstStep), sentX = 0, sentY = 0;
        var packets = new Native.Input[steps];
        for (int i = 0; i < steps; i++)
        {
            int toX = x * (i + 1) / steps, toY = y * (i + 1) / steps;
            packets[i] = new Native.Input { Type = 0, Data = new Native.InputUnion { Mouse = new Native.MouseInput { X = toX - sentX, Y = toY - sentY, Flags = 0x0001 } } };
            sentX = toX; sentY = toY;
        }
        if (Native.SendInput((uint)steps, packets, Marshal.SizeOf<Native.Input>()) != steps)
            throw new InvalidOperationException("Windows rejected steering input.");
    }

    /// <summary>Press or release the left mouse button. Let go in <see cref="Dispose"/> however a run ends.</summary>
    public void HoldLeft(bool on)
    {
        if (on == LeftHeld) return;
        if (on) _reader.RequireForeground();
        // Track the button before sending, so even uncertain delivery gets a release.
        LeftHeld = on;
        var packet = new Native.Input { Type = 0, Data = new Native.InputUnion { Mouse = new Native.MouseInput { Flags = on ? 0x0002u : 0x0004u } } };
        if (Native.SendInput(1, new[] { packet }, Marshal.SizeOf<Native.Input>()) != 1)
            throw new InvalidOperationException("Windows rejected the left mouse button.");
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

    /// <summary>
    /// One tap of Space (keys.ini: SPACE = Jump). Seated in the subway train it leaves the car, which
    /// is the only thing it is used for.
    /// </summary>
    public void Jump()
    {
        _reader.RequireForeground();
        Key(Space, false);
        Thread.Sleep(60);
        Key(Space, true);
    }

    /// <summary>Run (Shift held) or walk while moving; only matters when <see cref="Run"/> is on.</summary>
    public void Sprint(bool on)
    {
        if (!Run || on == _sprint) return;
        _sprint = on;
        if (Walking) Key(Shift, !on);
    }

    public void Dispose()
    {
        try { HoldLeft(false); }
        finally
        {
            if (Walking) { Walking = false; Key(W, true); if (Run) Key(Shift, true); }
            if (Backing) { Backing = false; Key(S, true); }
            Strafe(0);
        }
    }
}
