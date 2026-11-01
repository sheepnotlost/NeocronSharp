using System.Diagnostics;
using System.Globalization;
using System.Numerics;
using System.Text.Json;
using NeocronSharp;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// Is a followed actor still there, and where: read at most every <paramref name="everyMs"/> ms,
/// so a registry caught mid-update or one missed reading never ends a follow. Shared by the walk
/// (<see cref="FollowWalk"/>) and the camera (<see cref="CameraWatch"/>).
/// </summary>
/// <param name="stopped">The end of every message saying the follow is over, e.g. "Follow stopped."</param>
/// <param name="crossed">Why the target is gone when it vanished at a zone exit, if it did.</param>
internal sealed class TargetWatch(WorldEntity target, Func<IReadOnlyList<WorldEntity>> read, Func<long> millis, int everyMs,
    string stopped, Func<Vector3, string?>? crossed = null, bool corpse = false)
{
    private const int MissesToLose = 4, UnreadableToStop = 20;
    private long _readAt = -everyMs;
    private int _misses, _unreadable;

    public Vector3 SeenAt { get; private set; } = target.Position;

    /// <summary>The target's health at the last reading, when it can be read.</summary>
    public int? Health { get; private set; } = target.Stats?.Health?.RawCurrent;

    /// <summary>Returns why the target is gone, or null while it is still there.</summary>
    public string? Read()
    {
        if (millis() - _readAt < everyMs) return null;
        _readAt = millis();
        WorldEntity? live = null;
        try
        {
            live = read().FirstOrDefault(e => e.Identity.Node == target.Identity.Node && e.Identity.Physics == target.Identity.Physics);
        }
        catch (InvalidOperationException e)
        {
            // Caught the registry mid-update: try again next time. For seconds on end, give up.
            if (++_unreadable >= UnreadableToStop) throw new InvalidOperationException($"The actors around you could not be read for 3 s ({e.Message}). {stopped}");
            return null;
        }
        _unreadable = 0;
        // A different actor at a reused address is not the target. (A player's name can fail to
        // read for a moment, showing as an unclassified character; that is still them. Never for
        // an NPC: the unnamed character could be a player, with the left button held.)
        if (live != null && (target.Identity.Kind == EntityKind.Npc
                ? live.Identity.Kind != EntityKind.Npc || live.Name != target.Name
                : live.Name != target.Name && live.Identity.Kind != EntityKind.UnclassifiedCharacter)) live = null;
        if (live == null)
        {
            if (++_misses < MissesToLose) return null;
            return crossed?.Invoke(SeenAt) ?? $"{target.Name} is gone (out of range, logged off, despawned, or went through a door). {stopped}";
        }
        _misses = 0;
        if (!corpse && (live.Stats?.Dead == true || live.Player?.Dead == true)) return $"{target.Name} died. {stopped}";
        SeenAt = live.Position;
        Health = live.Stats?.Health?.RawCurrent ?? Health;
        return null;
    }
}

/// <summary>What a camera run does besides watching. The loot sequence runs one after another, so it skips the
/// countdown (<see cref="Now"/>) and passes on the mouse gains the first run measured.</summary>
internal sealed record CameraPlan(bool HoldLeft = false, bool Now = false, (float Yaw, float Pitch)? Gains = null, double GiveUpSeconds = 0, bool Box = false,
    bool MeasureOnly = false, bool Sight = false, bool BackOff = false);

/// <summary>
/// The live camera follow: mouse pulses only, turning left, right, up and down to keep facing the
/// target. No movement key is ever sent, so you keep walking yourself, and no click unless
/// <paramref name="plan"/> asks for the left button, held from the first time the crosshair is
/// on an NPC until the run ends. With <see cref="CameraPlan.Box"/> it instead runs to a dead NPC and
/// right-clicks its loot box. Ends by returning why it stopped, or by throwing (F8, focus, zone change).
/// </summary>
internal sealed class CameraWatch(PlayerReader reader, WorldEntity target, int pulse, CameraPlan plan, Hud hud, string logPath)
{
    private const int Tick = 16, PulseGap = 16, ReadEveryMs = 80, YawProbe = 96, PitchProbe = 64,
        ProbeStep = 6;   // Windows mouse acceleration: a pixel of a big pulse goes twice as far, and corrections are small.
    /// <summary>Closer than this on the flat, "towards the target" has no useful direction.</summary>
    public const float TooClose = 5;
    /// <summary>Radians per pixel of mouse, once measured.</summary>
    public (float Yaw, float Pitch)? Measured { get; private set; }
    /// <summary>Where a run to a loot box starts to stop. The view stops at 43 degrees down, so the crosshair can't reach the ground nearer than about 88 units, and W up slides on. Not yet set live.</summary>
    public const float BoxReach = 120;
    private const float FacingToRun = 0.35f;
    private const int StuckAfterMs = 3000, BoxAimMs = 2000, LookEveryMs = 120;
    /// <summary>Seconds aimed at the target with the game not targeting it before the shot is called blocked.</summary>
    private const double BlindSeconds = 4;
    private const float StuckBelow = 15;

    public string Run()
    {
        using var log = new StreamWriter(logPath) { AutoFlush = true };
        using var input = new SteerInput(reader, pulse, plan.Box);
        var clock = Stopwatch.StartNew();
        string title = $"CAMERA  {target.Name}";
        var origin = reader.ReadSteady();
        int? sector = reader.ReadSectorId(origin.World);
        var previous = origin;

        void Record(string kind, PlayerSample s, object? detail = null) => log.WriteLine(JsonSerializer.Serialize(new {
            timeUtc = DateTimeOffset.UtcNow, elapsedSeconds = clock.Elapsed.TotalSeconds, kind,
            position = new { s.Position.X, s.Position.Y, s.Position.Z }, forward = new { s.Forward.X, s.Forward.Z }, detail }));

        bool F8() => StopRequest.Made();

        PlayerSample Guard()
        {
            if (F8()) throw new OperationCanceledException("Stop pressed.");
            reader.RequireForeground();
            PlayerSample s;
            try { s = reader.ReadSteady(); }
            catch (InvalidOperationException) { throw new InvalidOperationException("Your character could not be read (zoning?). Camera follow stopped."); }
            if (s.Player != origin.Player || s.World != origin.World || s.Physics != origin.Physics || reader.ReadSectorId(s.World) != sector)
                throw new InvalidOperationException("You changed zone. Camera follow stopped.");
            return previous = s;
        }

        PlayerSample Wait(int ms)
        {
            long until = clock.ElapsedMilliseconds + ms;
            var s = Guard();
            while (clock.ElapsedMilliseconds < until) { Thread.Sleep((int)Math.Clamp(until - clock.ElapsedMilliseconds, 1, 15)); s = Guard(); }
            return s;
        }

        (float Yaw, float Pitch) View(PlayerSample s) => reader.ReadCamera(s)
            ?? throw new InvalidOperationException("The camera's angles could not be read on this game build. Camera follow stopped.");

        // The value once the game has caught up: a turn shows late, so one quick read measures only part of it.
        float Settled(Func<PlayerSample, float> value)
        {
            float last = value(Wait(60));
            int calm = 0;
            for (int i = 0; i < 25 && calm < (plan.MeasureOnly ? 10 : 2); i++)   // A healer may be in a VM, where a frame can take half a second.
            {
                float now = value(Wait(60));
                calm = MathF.Abs(now - last) < 0.0015f ? calm + 1 : 0;
                last = now;
            }
            return last;
        }

        // Radians per pixel: test moves one way then the other, until two agree. The first pulses after
        // focus can be swallowed, so one measurement alone proves nothing (31 Oct: one this far off hunted).
        float Measure(string axis, int pixels, Func<PlayerSample, float> value, Action<int> send)
        {
            float? last = null;
            for (int attempt = 0, way = 1; attempt < 6; attempt++, way = -way)
            {
                float before = Settled(value);
                for (int sent = 0; sent < pixels; sent += ProbeStep) { send(way * ProbeStep); Wait(PulseGap); }
                float gain = (Settled(value) - before) / (way * pixels);
                Record("gain-probe", previous, new { axis, way, gain });
                if (MathF.Abs(gain) < 1e-5f) continue;
                if (last is { } g && Math.Sign(g) == Math.Sign(gain) && MathF.Abs(g - gain) < 0.35f * MathF.Abs(gain)) return (g + gain) / 2;
                last = gain;
            }
            throw new InvalidOperationException("Mouse-look did not respond steadily. Press Tab in Neocron so the free pointer disappears, close chat, try again.");
        }

        // Run to the body facing it, with Shift held, then put the crosshair on it and right-click.
        string RunToBox(float yawGain, float pitchGain)
        {
            var box = target.Position;
            var stuckFrom = Guard().Position;
            long stuckAt = clock.ElapsedMilliseconds;
            while (true)
            {
                var s = Guard();
                float away = PointNavigation.Distance(s.Position, box);
                if (away <= BoxReach) break;
                float error = PointNavigation.SignedAngle(CameraAim.Facing(View(s).Yaw), box - s.Position);
                input.Walk(MathF.Abs(error) < FacingToRun);
                input.LookPulse((int)MathF.Round(CameraAim.Turn(error) / yawGain), 0);
                if (clock.ElapsedMilliseconds - stuckAt > StuckAfterMs)
                {
                    if (PointNavigation.Distance(s.Position, stuckFrom) < StuckBelow) throw new InvalidOperationException($"Could not reach the body of {target.Name}. Stopped.");
                    stuckFrom = s.Position; stuckAt = clock.ElapsedMilliseconds;
                }
                hud.Show(Hud.Green, $"LOOT  {target.Name}", $"{away:F0} units away", "F8 stops");
                Wait(Tick);
            }
            input.Walk(false);
            bool aimed = false;
            for (long until = clock.ElapsedMilliseconds + BoxAimMs; !aimed && clock.ElapsedMilliseconds < until; Wait(Tick))
            {
                var s = Guard();
                var view = View(s);
                float yawError = PointNavigation.Distance(s.Position, box) < TooClose ? 0 : PointNavigation.SignedAngle(CameraAim.Facing(view.Yaw), box - s.Position);
                float pitchError = CameraAim.PitchTo(s.Position, box) - view.Pitch;
                aimed = CameraAim.OnTarget(yawError, pitchError);
                if (!aimed) input.LookPulse((int)MathF.Round(CameraAim.Turn(yawError) / yawGain), (int)MathF.Round(CameraAim.Turn(pitchError) / pitchGain));
            }
            if (!aimed) throw new InvalidOperationException($"Could not aim at the body of {target.Name}.");   // A right-click lands on whatever is there.
            Record("box", previous, new { target = target.Name });
            input.Use();
            return $"Right-clicked the body of {target.Name}.";
        }

        try
        {
            if (!plan.Now) Console.WriteLine("Focus Neocron now (mouse-look on: press Tab so the pointer disappears). Starting in 5 s. F8 stops.");
            for (int i = plan.Now ? 0 : 5; i > 0; i--)
            {
                hud.Post(Hud.Amber, $"CAMERA  starting in {i} s", "Click into Neocron now; press Tab so the pointer is hidden.", "F8 stops at any time.");
                for (int j = 0; j < 20; j++) { if (F8()) throw new OperationCanceledException("Stop pressed."); Thread.Sleep(50); }
            }

            float yawGain, pitchGain;
            if (plan.Gains is { } known) (yawGain, pitchGain) = known;
            else
            {
                var reference = CameraAim.Facing(View(Guard()).Yaw);
                yawGain = Measure("yaw", YawProbe, s => PointNavigation.SignedAngle(reference, CameraAim.Facing(View(s).Yaw)), px => input.LookPulse(px, 0));
                pitchGain = Measure("pitch", PitchProbe, s => View(s).Pitch, px => input.LookPulse(0, px));
                Console.WriteLine(string.Create(CultureInfo.InvariantCulture, $"gains {yawGain} {pitchGain}"));
            }
            Measured = (yawGain, pitchGain);
            if (plan.MeasureOnly) return "";
            if (plan.Box) return RunToBox(yawGain, pitchGain);

            var watch = new TargetWatch(target, () => reader.ReadEntities().Entities, () => clock.ElapsedMilliseconds, ReadEveryMs, "Camera follow stopped.");
            Record("start", previous, new { target = target.Name, id = FollowCommand.Id(target), yawGain, pitchGain });
            Console.WriteLine($"Watching {target.Name}. The camera turns; you keep moving. F8 stops.");
            int ticks = 0;
            int? health = watch.Health;
            long lastHurt = 0, lookAt = 0;
            var sight = new SightWatch();
            var backOff = new BackOff(plan.BackOff);
            double aimedAt = -1;
            while (true)
            {
                var s = Guard();
                if (watch.Read() is { } gone) { Record("lost", s, new { gone }); hud.Post(Hud.Cyan, title, gone); return gone; }
                float away = PointNavigation.Distance(s.Position, watch.SeenAt);
                var view = View(s);
                float yawError = away < TooClose ? 0 : PointNavigation.SignedAngle(CameraAim.Facing(view.Yaw), watch.SeenAt - s.Position);
                float pitchError = CameraAim.PitchTo(s.Position, watch.SeenAt + new Vector3(0, CameraAim.ShotHeight, 0)) - view.Pitch;
                int x = CameraAim.Pixels(CameraAim.Turn(yawError, away), yawGain), y = CameraAim.Pixels(CameraAim.Turn(pitchError, away), pitchGain);
                input.LookPulse(x, y);
                // Any fall counts, not just a new lowest: a mob healing between hits was given up on while it was being hurt.
                if (watch.Health < health) lastHurt = clock.ElapsedMilliseconds;
                health = watch.Health;
                bool onTarget = CameraAim.OnTarget(yawError, pitchError);
                if (plan.Sight)
                {
                    double now = clock.Elapsed.TotalSeconds;
                    if (clock.ElapsedMilliseconds >= lookAt)
                    {
                        lookAt = clock.ElapsedMilliseconds + LookEveryMs;
                        sight.Update(now, TargetBar.Showing(reader.Window));
                    }
                    if (onTarget && aimedAt < 0) aimedAt = now;
                    var was = backOff.Now;
                    backOff.Update(now, sight.Seen(now), sight.Showing, away, s.Position);
                    input.Back(backOff.Now == BackOff.Phase.Backing);
                    input.Walk(backOff.Now == BackOff.Phase.Returning);
                    if (was == BackOff.Phase.Backing && backOff.Now == BackOff.Phase.Returning)
                        Console.WriteLine($"Target limit {backOff.Limit:F0} units.");
                    if (input.LeftHeld && !sight.Seen(now)) input.HoldLeft(false);   // Terrain in the way: the shots would only hit that.
                    if (aimedAt >= 0 && backOff.Now != BackOff.Phase.Returning && now - Math.Max(aimedAt, sight.SeenAt) > BlindSeconds)
                    {
                        string blocked = $"No line of sight to {target.Name}. Camera follow stopped.";
                        Record("blocked", s, new { away });
                        return blocked;
                    }
                }
                if (input.LeftHeld && plan.GiveUpSeconds > 0 && clock.ElapsedMilliseconds - lastHurt > plan.GiveUpSeconds * 1000)
                {
                    string missed = $"No damage to {target.Name} for {plan.GiveUpSeconds:F0} s. Camera follow stopped.";
                    Record("gave-up", s, new { missed });
                    return missed;
                }
                if (plan.HoldLeft && !input.LeftHeld && onTarget && (!plan.Sight || (sight.Seen(clock.Elapsed.TotalSeconds) && backOff.Now == BackOff.Phase.Done)))
                {
                    input.HoldLeft(true);
                    if (lastHurt == 0) lastHurt = clock.ElapsedMilliseconds;
                    Record("hold", s, new { yawError, pitchError, away });
                    Console.WriteLine($"On {target.Name}: holding the left mouse button.");
                }
                hud.Show(Hud.Green, title, $"{away:F0} units away, {MathF.Abs(yawError) * 180 / MathF.PI:F0} deg across, {MathF.Abs(pitchError) * 180 / MathF.PI:F0} deg up/down", "F8 stops");
                // A few lines a second: every tick would be 40 MB an hour.
                if (ticks++ % 10 == 0) Record("track", s, new { Angle = yawError, pitch = pitchError, pixels = x, pixelsY = y, away, target = new[] { watch.SeenAt.X, watch.SeenAt.Y, watch.SeenAt.Z } });
                Wait(Tick);
            }
        }
        catch (Exception error)
        {
            Record("stopped", previous, new { error.Message });
            hud.Post(Hud.Red, "CAMERA  stopped", error.Message);
            throw;
        }
    }
}
