using System.Diagnostics;
using System.Numerics;
using System.Runtime.InteropServices;
using System.Text.Json;
using NeocronSharp;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// Keys for a client that does not have focus: window messages, after telling the window it is active. Real focus
/// stays where it is. W, A, S, D and a Shoot key get through; the mouse does not, so the camera cannot turn (1 Nov).
/// </summary>
internal sealed class BackgroundKeys(nint window) : IDisposable
{
    internal sealed record Key(uint Vk, uint Scan, bool Extended = false);
    public static readonly Key W = new(0x57, 0x11), S = new(0x53, 0x1f), A = new(0x41, 0x1e), D = new(0x44, 0x20),
        Shift = new(0x10, 0x2a), Shoot = new(0x2d, 0x52, true);   // keys.ini: INSERT = Shoot
    private const uint KeyDown = 0x100, KeyUp = 0x101, Activate = 0x06, SetFocus = 0x07, ActivateApp = 0x1c;
    private readonly HashSet<Key> _held = new();

    [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW")]
    private static extern nint SendMessageTimeout(nint window, uint message, nuint wParam, nint lParam, uint flags, uint millis, out nint result);

    // A hung game must not hang this.
    private void Send(uint message, nuint wParam, nint lParam = 0) => SendMessageTimeout(window, message, wParam, lParam, 2, 200, out _);

    private static nint Bits(Key key) => (nint)(1 | key.Scan << 16 | (key.Extended ? 1u << 24 : 0));

    public void TellActive(bool active)
    {
        Send(ActivateApp, active ? 1u : 0u);
        Send(Activate, active ? 1u : 0u);
        if (active) Send(SetFocus, 0);
    }

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
        TellActive(false);
    }
}

/// <summary>
/// The healer's follow, with the camera fixed: it keeps the place it had beside the target when it started, walking and
/// strafing, so a target under the crosshair then stays under it. Casts with the Shoot key every 30 s when in place.
/// Runs without focus. Ends by returning why it stopped, or by throwing.
/// </summary>
internal sealed class HealWatch(PlayerReader reader, WorldEntity target, string logPath)
{
    private const int Tick = 50, ReadEveryMs = 150, CastEveryMs = 30000, CastHoldMs = 1500, ActiveEveryMs = 5000;

    public string Run()
    {
        using var log = new StreamWriter(logPath) { AutoFlush = true };
        using var keys = new BackgroundKeys(reader.Window);
        var clock = Stopwatch.StartNew();
        var origin = reader.ReadSteady();
        int? sector = reader.ReadSectorId(origin.World);
        (float Yaw, float Pitch) View(PlayerSample s) => reader.ReadCamera(s)
            ?? throw new InvalidOperationException("The camera's angles could not be read on this game build. Stopped.");
        void Record(string kind, PlayerSample s, object? detail = null) => log.WriteLine(JsonSerializer.Serialize(new {
            timeUtc = DateTimeOffset.UtcNow, elapsedSeconds = clock.Elapsed.TotalSeconds, kind,
            position = new { s.Position.X, s.Position.Y, s.Position.Z }, detail }));

        var place = Formation.Place(CameraAim.Facing(View(origin).Yaw), origin.Position, target.Position);
        if (!Formation.Ahead(place)) throw new InvalidOperationException($"{target.Name} is not under the crosshair. Aim the healer at them by hand, then start.");
        var watch = new TargetWatch(target, () => reader.ReadEntities().Entities, () => clock.ElapsedMilliseconds, ReadEveryMs, "Heal follow stopped.");
        var walk = new Formation();
        Record("start", origin, new { target = target.Name, place.Forward, place.Right });
        Console.WriteLine($"Following {target.Name} from {place.Forward:F0} units behind and {place.Right:F0} to the side. Casting every {CastEveryMs / 1000} s.");
        long nextCast = 0, castEnds = -1, nextActive = 0;
        int casts = 0, ticks = 0;
        var last = origin;
        try
        {
            while (true)
            {
                if (StopRequest.Made()) throw new OperationCanceledException("Stop pressed.");
                long now = clock.ElapsedMilliseconds;
                if (now >= nextActive) { keys.TellActive(true); nextActive = now + ActiveEveryMs; }
                PlayerSample s;
                try { s = reader.ReadSteady(); }
                catch (InvalidOperationException) { throw new InvalidOperationException("The healer could not be read (zoning?). Heal follow stopped."); }
                if (s.Player != origin.Player || s.World != origin.World || s.Physics != origin.Physics || reader.ReadSectorId(s.World) != sector)
                    throw new InvalidOperationException("The healer changed zone. Heal follow stopped.");
                last = s;
                if (watch.Read() is { } gone) { Record("lost", s, new { gone }); return gone; }

                var error = Formation.Error(CameraAim.Facing(View(s).Yaw), s.Position, watch.SeenAt, place);
                var (forward, right, run) = walk.Keys(error);
                keys.Set(BackgroundKeys.W, forward > 0); keys.Set(BackgroundKeys.S, forward < 0);
                keys.Set(BackgroundKeys.D, right > 0); keys.Set(BackgroundKeys.A, right < 0);
                keys.Set(BackgroundKeys.Shift, run);

                if (castEnds >= 0 && now >= castEnds) { keys.Set(BackgroundKeys.Shoot, false); castEnds = -1; }
                if (castEnds < 0 && now >= nextCast && Formation.InPlace(error))
                {
                    keys.Set(BackgroundKeys.Shoot, true);
                    castEnds = now + CastHoldMs; nextCast = now + CastEveryMs;
                    Record("cast", s, new { error.Forward, error.Right });
                    Console.WriteLine($"Cast {++casts} on {target.Name}.");
                }
                keys.Repeat();
                if (ticks++ % 10 == 0) Record("step", s, new { error.Forward, error.Right, forward, right, run, target = new[] { watch.SeenAt.X, watch.SeenAt.Y, watch.SeenAt.Z } });
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
