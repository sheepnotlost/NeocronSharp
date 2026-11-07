using System.Numerics;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
using NeocronSharp;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// The mouse turn to send each tick while tracking a mob that moves, or while mobs shove you about. The game eases a mouse
/// turn in over about 350 ms (<see cref="SnapAim"/>), so the part of a turn already sent but not yet shown is taken off
/// what is left to turn: most of the error can then go every tick without swinging past. Sending a third of it each tick,
/// as before, left the crosshair trailing a Genotoxic Parasite's shoves (7 Nov).
/// </summary>
internal sealed class TrackAim
{
    public const double EaseSeconds = .35;
    public const float Share = .8f, Least = .002f;
    private readonly List<(double At, float Yaw, float Pitch)> _sent = new();

    /// <summary>The part of turns already sent that the view does not show yet.</summary>
    public (float Yaw, float Pitch) Pending(double now)
    {
        _sent.RemoveAll(s => now - s.At >= EaseSeconds || now < s.At);
        float yaw = 0, pitch = 0;
        foreach (var s in _sent)
        {
            float left = (float)(1 - (now - s.At) / EaseSeconds);
            yaw += s.Yaw * left; pitch += s.Pitch * left;
        }
        return (yaw, pitch);
    }

    /// <summary>The turn wanted now (radians), given the error as the view shows it and the range.</summary>
    public (float Yaw, float Pitch) Want(double now, float yawError, float pitchError, float away)
    {
        var pending = Pending(now);
        float within = away > 0 ? Math.Clamp(CameraAim.AimWithin / away, Least, CameraAim.FineDeadband) : Least;
        float yaw = yawError - pending.Yaw, pitch = pitchError - pending.Pitch;
        return (MathF.Abs(yaw) < within ? 0 : yaw * Share, MathF.Abs(pitch) < within ? 0 : pitch * Share);
    }

    /// <summary>What was really sent, after rounding to pixels and the most one tick may send.</summary>
    public void Sent(double now, float yaw, float pitch)
    {
        if (yaw != 0 || pitch != 0) _sent.Add((now, yaw, pitch));
    }
}

/// <summary>
/// The crosshair pinned by setting the camera's angles in the game's memory, every tick, instead of moving the mouse: no
/// easing and no lag, so a shove can't move it off. Only when asked for (--pin): it writes into the game. The angles are
/// the ones <see cref="PlayerReader.ReadCamera"/> reads: pitch in degrees doubled, yaw in degrees the other way round, at
/// the player plus 0x278 and again at plus 0x9d4. If the game puts its own angles back, it says so and the mouse takes over.
/// </summary>
internal sealed class CameraWriter : IDisposable
{
    private const int Live = 0x278, Copy = 0x9d4;
    private const float MostPitch = 43;
    /// <summary>Writes in a row that left the error where it was before the game is taken to refuse them.</summary>
    private const int RefusedAfter = 8;
    private readonly SafeProcessHandle _handle;
    private float _wrote;
    private int _ignored;

    private CameraWriter(SafeProcessHandle handle) => _handle = handle;

    public bool Works { get; private set; } = true;

    public static CameraWriter? Open(int processId)
    {
        var handle = Native.OpenProcess(0x0438, false, processId);   // query information, VM operation, read and write
        if (handle.IsInvalid) { handle.Dispose(); return null; }
        return new CameraWriter(handle);
    }

    /// <summary>Turns the camera by these errors at once. False once the game has been seen to refuse it.</summary>
    public bool Turn(ulong player, float yawError, float pitchError)
    {
        if (!Works) return false;
        float size = MathF.Max(MathF.Abs(yawError), MathF.Abs(pitchError));
        if (_wrote > .03f && size > .8f * _wrote) { if (++_ignored >= RefusedAfter) { Works = false; return false; } }
        else _ignored = 0;
        var now = new byte[8];
        if (!ReadProcessMemory(_handle, (nint)(player + Live), now, 8, out var read) || read != 8) return false;
        float pitch = BitConverter.ToSingle(now, 0), yaw = BitConverter.ToSingle(now, 4);
        if (!float.IsFinite(pitch) || !float.IsFinite(yaw)) return false;
        var (newPitch, newYaw) = Angles(pitch, yaw, yawError, pitchError);
        var bytes = new byte[8];
        BitConverter.TryWriteBytes(bytes.AsSpan(0, 4), newPitch);
        BitConverter.TryWriteBytes(bytes.AsSpan(4, 4), newYaw);
        bool ok = WriteProcessMemory(_handle, (nint)(player + Live), bytes, 8, out var a) && a == 8
               && WriteProcessMemory(_handle, (nint)(player + Copy), bytes, 8, out var b) && b == 8;
        _wrote = size;
        return ok;
    }

    /// <summary>The stored angles after a turn by these errors (radians: yaw as the aim counts it, pitch up).</summary>
    public static (float Pitch, float Yaw) Angles(float storedPitch, float storedYaw, float yawError, float pitchError)
    {
        float degrees = 180 / MathF.PI;
        return (Math.Clamp(storedPitch + 2 * pitchError * degrees, -2 * MostPitch, 2 * MostPitch), storedYaw - yawError * degrees);
    }

    public void Dispose() => _handle.Dispose();

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool ReadProcessMemory(SafeProcessHandle handle, nint address, byte[] buffer, nuint size, out nuint read);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool WriteProcessMemory(SafeProcessHandle handle, nint address, byte[] buffer, nuint size, out nuint written);
}

/// <summary>A mob shoving you is the one to kill first: the fight on another can't hold its aim while it does.</summary>
internal static class Pushers
{
    /// <summary>Units on the flat, and up or down: this close, a mob is on you.</summary>
    public const float Touching = 150, Floor = 100;

    /// <summary>The nearest living mob the hunt may fight that is on you, other than the target; none while the target is as close.</summary>
    public static WorldEntity? OnYou(Vector3 me, IEnumerable<WorldEntity> actors, WorldEntity target, float targetAway, IReadOnlyCollection<string>? avoid)
    {
        if (targetAway <= Touching + 50) return null;
        string id = FollowCommand.Id(target);
        return actors
            .Where(e => SweepTargets.Hunted(e) && !FollowCommand.Dead(e) && FollowCommand.Id(e) != id
                && !(avoid is { Count: > 0 } && SweepTargets.Spared(e.Name, avoid))
                && PointNavigation.Distance(me, e.Position) <= Touching && MathF.Abs(e.Position.Y - me.Y) <= Floor)
            .MinBy(e => PointNavigation.Distance(me, e.Position));
    }
}

/// <summary>
/// Keeps a mob out in front. In third person a small one close up drops under the view (it stops 43 degrees down) and
/// behind your own back, out of the crosshair's reach: so with the target this close, it walks backwards until there is
/// room again, and when a wall stops the walk it steps sideways, one way then the other.
/// </summary>
internal sealed class Kite
{
    public const float TooClose = 150, Enough = 220, Stuck = 10;
    public const double StuckSeconds = .6, SideSeconds = .8;
    private bool _backing;
    private double _since = -1, _sideUntil = -1;
    private Vector3 _from;
    private int _side = 1;

    /// <summary>Walk backwards? And which way to step (-1 left, 1 right, 0 none).</summary>
    public (bool Back, int Side) Step(double now, float away, Vector3 me)
    {
        if (!_backing && away < TooClose) { _backing = true; _since = now; _from = me; }
        else if (_backing && away > Enough) { _backing = false; _sideUntil = -1; }
        if (!_backing) return (false, 0);
        if (now < _sideUntil) return (true, _side);
        if (now - _since >= StuckSeconds)
        {
            bool stuck = PointNavigation.Distance(me, _from) < Stuck;
            _since = now; _from = me;
            if (stuck) { _side = -_side; _sideUntil = now + SideSeconds; return (true, _side); }
        }
        return (true, 0);
    }
}
