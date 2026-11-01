using System.Diagnostics;
using System.Numerics;
using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Win32.SafeHandles;
using NeocronSharp;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// Keys for a client that does not have focus: window messages, after telling the window it has focus. Real focus
/// stays where it is. W, A, S, D and a Shoot key get through; the mouse does not (1 Nov).
/// </summary>
internal sealed class BackgroundKeys(nint window) : IDisposable
{
    internal sealed record Key(uint Vk, uint Scan, bool Extended = false);
    public static readonly Key W = new(0x57, 0x11), S = new(0x53, 0x1f),
        Shift = new(0x10, 0x2a), Shoot = new(0x2d, 0x52, true);   // keys.ini: INSERT = Shoot
    private const uint KeyDown = 0x100, KeyUp = 0x101, SetFocus = 0x07, KillFocus = 0x08;
    private readonly HashSet<Key> _held = new();

    [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW")]
    private static extern nint SendMessageTimeout(nint window, uint message, nuint wParam, nint lParam, uint flags, uint millis, out nint result);

    // A hung game must not hang this.
    private void Send(uint message, nuint wParam, nint lParam = 0) => SendMessageTimeout(window, message, wParam, lParam, 2, 200, out _);

    private static nint Bits(Key key) => (nint)(1 | key.Scan << 16 | (key.Extended ? 1u << 24 : 0));

    /// <summary>The focus message alone is what keys need (tested with each message on its own, 1 Nov).</summary>
    public void TellFocused(bool focused) => Send(focused ? SetFocus : KillFocus, 0);

    public void Set(Key key, bool down)
    {
        if (down) _held.Add(key);
        else if (_held.Remove(key)) Send(KeyUp, key.Vk, Bits(key) | unchecked((nint)(3u << 30)));
    }

    /// <summary>
    /// Held keys repeat, as a held key does on a keyboard: one key-down alone does nothing (1 Nov). Sent, not posted: an unfocused
    /// game works through posted messages late, and a backlog of them kept it walking for over a second after the key-up.
    /// </summary>
    public void Repeat()
    {
        foreach (var key in _held) Send(KeyDown, key.Vk, Bits(key));
    }

    public void Dispose()
    {
        foreach (var key in _held.ToList()) Set(key, false);
        TellFocused(false);
    }
}

/// <summary>
/// Sets the camera angles of the healer's own client, the only thing in this project that writes to the game's memory.
/// The mouse cannot reach an unfocused client and no key turns the camera, so this is how its crosshair follows.
/// </summary>
internal sealed class CameraWriter : IDisposable
{
    private readonly SafeProcessHandle _handle;

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern SafeProcessHandle OpenProcess(uint access, bool inherit, int pid);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool WriteProcessMemory(SafeProcessHandle handle, nint address, byte[] buffer, nuint size, out nuint written);

    public CameraWriter(int pid)
    {
        _handle = OpenProcess(0x28, false, pid);   // VM write and operation
        if (_handle.IsInvalid) throw new System.ComponentModel.Win32Exception();
    }

    /// <summary>Radians, as <see cref="PlayerReader.ReadCamera"/> gives them: the game keeps twice the pitch and 270 minus the yaw, in degrees, twice.</summary>
    public void Set(PlayerSample sample, float yaw, float pitch)
    {
        float degrees = 270 - yaw * 180 / MathF.PI;
        degrees -= 360 * MathF.Floor(degrees / 360);
        var bytes = BitConverter.GetBytes(pitch * 2 * 180 / MathF.PI).Concat(BitConverter.GetBytes(degrees)).ToArray();
        foreach (ulong field in new ulong[] { 0x278, 0x9d4 })
            if (!WriteProcessMemory(_handle, (nint)(sample.Player + field), bytes, 8, out _))
                throw new InvalidOperationException("The healer's camera could not be set. Stopped.");
    }

    public void Dispose() => _handle.Dispose();
}

/// <summary>
/// The healer's follow: keeps the crosshair on the target by setting the camera, walks to keep the distance it started
/// at, and casts with the Shoot key every 30 s when on target. Runs without focus. The caller has checked the target is
/// the character in the user's other client. Ends by returning why it stopped, or by throwing.
/// </summary>
internal sealed class HealWatch(PlayerReader reader, WorldEntity target, string logPath)
{
    private const int Tick = 33, ReadEveryMs = 100, CastEveryMs = 30000, CastHoldMs = 1500, ActiveEveryMs = 5000;
    /// <summary>A position is at the feet (seen live): this is about the middle of a standing character.</summary>
    private const float BodyMiddle = 50;

    public string Run()
    {
        using var log = new StreamWriter(logPath) { AutoFlush = true };
        using var keys = new BackgroundKeys(reader.Window);
        using var camera = new CameraWriter(reader.Process.Id);
        var clock = Stopwatch.StartNew();
        var origin = reader.ReadSteady();
        int? sector = reader.ReadSectorId(origin.World);
        (float Yaw, float Pitch) View(PlayerSample s) => reader.ReadCamera(s)
            ?? throw new InvalidOperationException("The camera's angles could not be read on this game build. Stopped.");
        void Record(string kind, PlayerSample s, object? detail = null) => log.WriteLine(JsonSerializer.Serialize(new {
            timeUtc = DateTimeOffset.UtcNow, elapsedSeconds = clock.Elapsed.TotalSeconds, kind,
            position = new { s.Position.X, s.Position.Y, s.Position.Z }, detail }));

        var hold = new HoldDistance(PointNavigation.Distance(origin.Position, target.Position));
        var watch = new TargetWatch(target, () => reader.ReadEntities().Entities, () => clock.ElapsedMilliseconds, ReadEveryMs, "Heal follow stopped.");
        Record("start", origin, new { target = target.Name, hold.Distance });
        Console.WriteLine($"Keeping the crosshair on {target.Name} and {hold.Distance:F0} units away. Casting every {CastEveryMs / 1000} s.");
        long nextCast = 0, castEnds = -1, nextActive = 0;
        int casts = 0, ticks = 0;
        var last = origin;
        try
        {
            while (true)
            {
                if (StopRequest.Made()) throw new OperationCanceledException("Stop pressed.");
                long now = clock.ElapsedMilliseconds;
                if (now >= nextActive) { keys.TellFocused(true); nextActive = now + ActiveEveryMs; }
                PlayerSample s;
                try { s = reader.ReadSteady(); }
                catch (InvalidOperationException) { throw new InvalidOperationException("The healer could not be read (zoning?). Heal follow stopped."); }
                if (s.Player != origin.Player || s.World != origin.World || s.Physics != origin.Physics || reader.ReadSectorId(s.World) != sector)
                    throw new InvalidOperationException("The healer changed zone. Heal follow stopped.");
                last = s;
                if (watch.Read() is { } gone) { Record("lost", s, new { gone }); return gone; }

                var view = View(s);
                var towards = watch.SeenAt - s.Position;
                float away = PointNavigation.Distance(s.Position, watch.SeenAt);
                float yawError = away < CameraWatch.TooClose ? 0 : CameraAim.Between(view.Yaw, MathF.Atan2(towards.Z, towards.X));
                float pitchError = CameraAim.PitchTo(s.Position, watch.SeenAt + new Vector3(0, BodyMiddle, 0)) - view.Pitch;
                float yawTurn = CameraAim.Turn(yawError), pitchTurn = CameraAim.Turn(pitchError);
                if (yawTurn != 0 || pitchTurn != 0) camera.Set(s, view.Yaw + yawTurn, view.Pitch + pitchTurn);

                var (forward, run) = hold.Keys(away, yawError);
                keys.Set(BackgroundKeys.W, forward > 0); keys.Set(BackgroundKeys.S, forward < 0);
                keys.Set(BackgroundKeys.Shift, run);

                if (castEnds >= 0 && now >= castEnds) { keys.Set(BackgroundKeys.Shoot, false); castEnds = -1; }
                if (castEnds < 0 && now >= nextCast && CameraAim.OnTarget(yawError, pitchError) && hold.InReach(away))
                {
                    keys.Set(BackgroundKeys.Shoot, true);
                    castEnds = now + CastHoldMs; nextCast = now + CastEveryMs;
                    Record("cast", s, new { yawError, pitchError, away });
                    Console.WriteLine($"Cast {++casts} on {target.Name}.");
                }
                keys.Repeat();
                if (ticks++ % 15 == 0) Record("step", s, new { yawError, pitchError, away, forward, run, target = new[] { watch.SeenAt.X, watch.SeenAt.Y, watch.SeenAt.Z } });
                Thread.Sleep(Tick);
            }
        }
        catch (Exception problem)
        {
            Record("stopped", last, new { problem.Message });
            throw;
        }
    }
}
