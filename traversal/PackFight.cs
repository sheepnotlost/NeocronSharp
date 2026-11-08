using System.Diagnostics;
using System.Globalization;
using System.Numerics;
using System.Text.Json;
using NeocronSharp;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// Kiting a pack of melee mobs round a fixed circle, all of it in one run (8 Nov, snakes in K 11: one pulled brings the
/// rest). Never be hit, and never fire without the crosshair on a body, so it either shoots or runs:
/// <list type="bullet">
/// <item>Shoot: stand still and crouched (Ctrl), the camera on the nearest, the button down only while this very look has
/// the crosshair inside its brackets.</item>
/// <item>Escape: once the nearest is within <see cref="PackPlan.RunAt"/>, stand up, turn and sprint away from the pack
/// round the ring until it is out past <see cref="PackPlan.ShootFrom"/>, then turn back and shoot. (Strafing and backing
/// with the camera on them lost ground: they closed from 800 to 475 every time and it never got to shoot, 8 Nov.)</item>
/// <item>Vantage: shooting, but the target has been out of sight (a cactus, a hill) for <see cref="PackFight.HiddenSeconds"/>:
/// run on round the ring, the camera on it, until its brackets show again.</item>
/// </list>
/// Ends when no wanted mob is left near; every kill is printed as "Killed &lt;id&gt; &lt;name&gt;" for the loot that follows.
/// </summary>
internal sealed record PackPlan(Vector2 Centre, float Ring, float RunAt, float Area, IReadOnlyCollection<string> Only,
    IReadOnlyCollection<string> Avoid, (float Yaw, float Pitch) Gains, bool Pin, double GiveUpSeconds)
{
    /// <summary>Units: past this the sprint stops and shooting starts again.</summary>
    public float ShootFrom => RunAt * PackFight.ShootShare;
}

internal enum PackPhase { Shoot, Vantage, Escape }

/// <summary>The phase from the nearest mob's distance and whether the target is in sight: pure, so it can be tested.</summary>
internal sealed class PackPhases(float runAt)
{
    public PackPhase Now { get; private set; } = PackPhase.Shoot;

    /// <param name="hidden">Shooting, and no brackets on the target for <see cref="PackFight.HiddenSeconds"/>.</param>
    /// <param name="inSight">Its brackets were on screen just now.</param>
    public PackPhase Update(float nearest, bool hidden = false, bool inSight = true)
    {
        Now = Now switch
        {
            not PackPhase.Escape when nearest < runAt => PackPhase.Escape,
            PackPhase.Escape when nearest > runAt * PackFight.ShootShare => PackPhase.Shoot,
            PackPhase.Shoot when hidden => PackPhase.Vantage,
            PackPhase.Vantage when inSight => PackPhase.Shoot,
            _ => Now,
        };
        return Now;
    }
}

internal static class PackRing
{
    /// <summary>
    /// Which way to go, on the flat (x, z), to kite round the ring: along it (way +1 or -1), pulled back onto it when off
    /// it, and pushed straight away from the nearest mob as it closes in.
    /// </summary>
    /// <param name="leastPush">At least this much straight away from the nearest (1 sprinting: a ring bent round lets them cut across).</param>
    public static Vector2 Heading(Vector2 me, Vector2 centre, float ring, int way, Vector2 nearest, float runAt, float leastPush = 0)
    {
        var out_ = me - centre;
        float r = out_.Length();
        var radial = r > 1 ? out_ / r : Vector2.UnitX;
        var along = new Vector2(radial.Y, -radial.X) * way;
        float back = Math.Clamp((ring - r) / Math.Max(ring, 1) * 2, -1, 1);       // + outwards when inside the ring
        var away = me - nearest;
        float d = away.Length();
        float push = d > 1 ? Math.Max(leastPush, Math.Clamp((runAt - d) / runAt * 2, 0, 1.5f)) : 1.5f;
        var dir = along + radial * back + (d > 1 ? away / d : Vector2.Zero) * push;
        return dir.LengthSquared() > 1e-6f ? Vector2.Normalize(dir) : along;
    }

    /// <summary>The way round (+1 or -1) that starts away from the pack.</summary>
    public static int Way(Vector2 me, Vector2 centre, Vector2 pack)
    {
        var radial = me - centre;
        if (radial.LengthSquared() < 1) radial = Vector2.UnitX;
        var along = Vector2.Normalize(new Vector2(radial.Y, -radial.X));
        return Vector2.Dot(along, me - pack) >= 0 ? 1 : -1;
    }

    /// <summary>
    /// The keys for a heading, given where the camera faces (both on the flat): forward or back, and strafe right (+1) or
    /// left (-1). Right is (z, -x) of the facing, as ShotLine.ClearSide has it.
    /// </summary>
    public static (bool Forward, bool Back, int Side) Keys(Vector2 facing, Vector2 heading)
    {
        var f = Vector2.Normalize(facing);
        var right = new Vector2(f.Y, -f.X);
        float ahead = Vector2.Dot(heading, f), side = Vector2.Dot(heading, right);
        const float Part = .38f;   // about 22 degrees: a heading this far off an axis uses that key too
        return (ahead > Part, ahead < -Part, side > Part ? 1 : side < -Part ? -1 : 0);
    }
}

internal sealed class PackFight(PlayerReader reader, WorldEntity first, int pulse, PackPlan plan, Hud hud, string logPath)
{
    /// <summary>Of RunAt: the sprint goes on until the nearest is this far, then it turns and shoots.</summary>
    public const float ShootShare = 1.5f;
    /// <summary>Seconds: shooting with no brackets on the target this long, it is hidden; brackets this recent, it is in sight.</summary>
    public const double HiddenSeconds = 1.5, InSightSeconds = .2;
    /// <summary>
    /// Crouch is a tap that toggles. Measured over this window after standing up to run, a speed under
    /// <see cref="CrouchedSpeed"/> units a second (a sprint is about 280) means you are still crouched, so it taps once more.
    /// </summary>
    public const double StandCheckFrom = .4, StandCheckTo = 1.2;
    public const float CrouchedSpeed = 150, StuckSpeed = 15;
    /// <summary>Seconds: the crosshair counts as on the body only if a look this recent had it inside the brackets.</summary>
    public const double OnBodySeconds = .15;
    /// <summary>Of RunAt: a mob nearer than the target by this share is shot first instead.</summary>
    public const float SwitchShare = .75f;
    private const int Tick = 16, ReadEveryMs = 150, MarkEveryMs = 60;

    public List<(string Id, string Name)> Killed { get; } = new();

    public string Run()
    {
        using var log = new StreamWriter(logPath) { AutoFlush = true };
        using var input = new SteerInput(reader, pulse);
        var clock = Stopwatch.StartNew();
        var origin = reader.ReadSteady();
        int? sector = reader.ReadSectorId(origin.World);
        var previous = origin;
        var lapse = new ReadLapse();
        string logs = Path.GetDirectoryName(logPath) ?? ".";
        var (yawGain, pitchGain) = plan.Gains;
        using var pin = plan.Pin ? CameraWriter.Open(reader.Process.Id) : null;
        bool pinned = pin != null;

        void Record(string kind, PlayerSample s, object? detail = null) => log.WriteLine(JsonSerializer.Serialize(new {
            timeUtc = DateTimeOffset.UtcNow, elapsedSeconds = clock.Elapsed.TotalSeconds, kind,
            position = new { s.Position.X, s.Position.Z }, detail }));

        PlayerSample Guard()
        {
            if (StopRequest.Made()) throw new OperationCanceledException("Stop pressed.");
            reader.RequireForeground();
            if (lapse.Read(reader.ReadSample, clock.Elapsed.TotalSeconds, "Pack fight stopped.") is not { } s) return previous;
            if (s.Player != origin.Player || s.World != origin.World || s.Physics != origin.Physics || reader.ReadSectorId(s.World) != sector)
                throw new InvalidOperationException("You changed zone. Pack fight stopped.");
            return previous = s;
        }

        (float Yaw, float Pitch) View(PlayerSample s) => reader.ReadCamera(s)
            ?? throw new InvalidOperationException("The camera's angles could not be read on this game build. Pack fight stopped.");

        bool Wanted(WorldEntity e) => SweepTargets.Hunted(e) && !FollowCommand.Dead(e)
            && (plan.Only.Count == 0 || SweepTargets.Spared(e.Name, plan.Only))
            && !(plan.Avoid.Count > 0 && SweepTargets.Spared(e.Name, plan.Avoid));

        // The pack: wanted mobs inside the area, and any that have come after you out of it.
        List<WorldEntity> Pack(IReadOnlyList<WorldEntity> around, Vector3 me) => around.Where(e => Wanted(e)
            && (Vector2.Distance(Flat(e.Position), plan.Centre) <= plan.Area || PointNavigation.Distance(me, e.Position) < plan.ShootFrom * 1.5f)).ToList();

        var target = first;
        string TargetId() => FollowCommand.Id(target);
        var skip = new HashSet<string>();
        var phases = new PackPhases(plan.RunAt);
        var track = new TrackAim();
        ScreenAim screen = null!;
        float aimHeight = 0;
        int? health = null;
        double hurtAt = 0, firedSince = -1;
        long readAt = -ReadEveryMs, markAt = 0;
        List<WorldEntity> pack = new() { first };
        Vector3 targetAt = first.Position;
        int way = 0;
        PackPhase was = PackPhase.Shoot;
        double phaseSince = 0, aimedAt = 0, standAt = -1;
        bool crouched = false;
        Vector3? standFrom = null;

        void Aim(WorldEntity e)
        {
            target = e; targetAt = e.Position;
            var learned = HuntNotes.Recall(logs, e.Name);
            aimHeight = learned?.BodyHeight is { } body ? Math.Clamp(body, -30, 150) : ScreenAim.MemoryHeight;
            screen = new ScreenAim(learned is { WidthAtRange: { } w, HeightAtRange: { } h } ? (w, h) : null);
            track = new TrackAim();
            health = e.Stats?.Health?.RawCurrent;
            hurtAt = aimedAt = clock.Elapsed.TotalSeconds; firedSince = -1;
            Console.WriteLine($"Target: {e.Name} ({TargetId()}).");
        }
        Aim(first);

        Console.WriteLine($"Pack fight: shooting crouched, sprinting round the ring once one is within {plan.RunAt:F0} until it is past {plan.ShootFrom:F0}. F8 stops.");
        try
        {
            while (true)
            {
                var s = Guard();
                double now = clock.Elapsed.TotalSeconds;
                if (clock.ElapsedMilliseconds - readAt >= ReadEveryMs)
                {
                    readAt = clock.ElapsedMilliseconds;
                    IReadOnlyList<WorldEntity> around;
                    try { around = FollowCommand.ReadSnapshot(reader).Entities; }
                    catch (InvalidOperationException) { around = Array.Empty<WorldEntity>(); }
                    if (around.Count > 0)
                    {
                        var live = around.FirstOrDefault(e => FollowCommand.Id(e) == TargetId() && e.Name == target.Name);
                        if (live == null || FollowCommand.Dead(live))
                        {
                            if (live != null) { Killed.Add((TargetId(), target.Name)); Console.WriteLine($"Killed {TargetId()} {target.Name}"); Record("killed", s, new { target.Name }); }
                            else skip.Add(TargetId());
                            input.HoldLeft(false);
                        }
                        else
                        {
                            targetAt = live.Position;
                            int? now_ = live.Stats?.Health?.RawCurrent;
                            if (now_ < health) hurtAt = now;
                            health = now_ ?? health;
                        }
                        pack = Pack(around, s.Position).Where(e => !skip.Contains(FollowCommand.Id(e))).ToList();
                        if (pack.Count == 0)
                        {
                            Record("cleared", s, new { killed = Killed.Count });
                            return $"Pack cleared: {Killed.Count} killed.";
                        }
                        var nearest = pack.MinBy(e => PointNavigation.Distance(s.Position, e.Position))!;
                        bool targetGone = live == null || FollowCommand.Dead(live) || !pack.Any(e => FollowCommand.Id(e) == TargetId());
                        if (targetGone || (FollowCommand.Id(nearest) != TargetId()
                            && PointNavigation.Distance(s.Position, nearest.Position) < PointNavigation.Distance(s.Position, targetAt) * SwitchShare))
                        {
                            input.HoldLeft(false);
                            Record("target", s, new { from = target.Name, to = nearest.Name, id = FollowCommand.Id(nearest) });
                            Aim(nearest);
                        }
                    }
                }
                float nearestAway = pack.Count > 0 ? pack.Min(e => PointNavigation.Distance(s.Position, e.Position)) : float.MaxValue;
                var nearestAt = pack.Count > 0 ? pack.MinBy(e => PointNavigation.Distance(s.Position, e.Position))!.Position : targetAt;
                bool hidden = was == PackPhase.Shoot && now - Math.Max(screen.SeenAt, Math.Max(phaseSince, aimedAt)) > HiddenSeconds;
                bool inSight = now - screen.SeenAt <= InSightSeconds;
                var phase = phases.Update(Math.Min(nearestAway, PointNavigation.Distance(s.Position, targetAt)), hidden, inSight);
                if (phase != was)
                {
                    Record("phase", s, new { phase = phase.ToString(), nearest = nearestAway });
                    if (way == 0) way = PackRing.Way(Flat(s.Position), plan.Centre, Flat(nearestAt));
                    Console.WriteLine(phase switch
                    {
                        PackPhase.Shoot => $"Room ({nearestAway:F0} units) and in sight: crouching to shoot.",
                        PackPhase.Vantage => $"{target.Name} is out of sight: round the ring for a clear view.",
                        _ => $"One is {nearestAway:F0} units away: sprinting clear.",
                    });
                    // Crouched only to shoot: stand up (a tap) before running.
                    if ((phase == PackPhase.Shoot) != crouched)
                    {
                        input.HoldLeft(false);
                        input.CrouchTap();
                        crouched = phase == PackPhase.Shoot;
                        standAt = crouched ? -1 : now; standFrom = null;
                        Record("crouch", s, new { crouched });
                    }
                    was = phase; phaseSince = now;
                }
                // Still crouched after all? Running crouched is too slow to keep them off.
                if (standAt >= 0 && now - standAt >= StandCheckFrom && standFrom == null) standFrom = s.Position;
                else if (standAt >= 0 && now - standAt >= StandCheckTo && standFrom is { } from)
                {
                    float speed = Vector2.Distance(Flat(from), Flat(s.Position)) / (float)(StandCheckTo - StandCheckFrom);
                    if (speed > StuckSpeed && speed < CrouchedSpeed)
                    {
                        input.CrouchTap();
                        Record("crouch-fix", s, new { speed });
                        Console.WriteLine($"Running at only {speed:F0} units a second: still crouched, standing up.");
                    }
                    standAt = -1; standFrom = null;
                }

                var view = View(s);
                float away = PointNavigation.Distance(s.Position, targetAt);
                var point = targetAt + new Vector3(0, aimHeight, 0);
                float yawToMemory = away < CameraWatch.TooClose ? 0 : PointNavigation.SignedAngle(CameraAim.Facing(view.Yaw), targetAt - s.Position);
                float pitchToMemory = CameraAim.PitchTo(s.Position, point) - view.Pitch;
                if (phase != PackPhase.Escape && clock.ElapsedMilliseconds >= markAt)
                {
                    markAt = clock.ElapsedMilliseconds + MarkEveryMs;
                    if (TargetLock.Look(reader.Window) is { } look)
                        screen.See(now, look.Marks, yawToMemory, pitchToMemory, look.ClientHeight, MathF.Sign(yawGain), away);
                }

                // Where the camera should look: the target (Shoot and Move), or the way out (Escape).
                var heading = PackRing.Heading(Flat(s.Position), plan.Centre, plan.Ring, way == 0 ? 1 : way, Flat(nearestAt), plan.RunAt,
                    phase == PackPhase.Escape ? 1 : 0);
                (float Yaw, float Pitch) error = phase == PackPhase.Escape
                    ? (PointNavigation.SignedAngle(CameraAim.Facing(view.Yaw), new Vector3(heading.X, 0, heading.Y)), -view.Pitch)
                    : screen.Error(now, yawToMemory, pitchToMemory, away);
                if (pinned && !pin!.Turn(s.Player, error.Yaw, error.Pitch) && !pin.Works)
                {
                    pinned = false;
                    Console.WriteLine("The game put its own camera back: the mouse aims instead.");
                }
                else if (!pinned)
                {
                    var want = track.Want(now, error.Yaw, error.Pitch, phase == PackPhase.Escape ? 0 : away);
                    int x = Math.Clamp((int)MathF.Round(want.Yaw / yawGain), -4 * input.Pulse, 4 * input.Pulse);
                    int y = Math.Clamp((int)MathF.Round(want.Pitch / pitchGain), -4 * input.Pulse, 4 * input.Pulse);
                    input.LookSteps(x, y);
                    track.Sent(now, x * yawGain, y * pitchGain);
                }

                // Feet: still while shooting; along the ring at a run otherwise (sprinting forward when escaping).
                if (phase == PackPhase.Shoot)
                {
                    input.Walk(false); input.Back(false); input.Strafe(0); input.RunKey(false);
                }
                else
                {
                    var keys = PackRing.Keys(Flat(CameraAim.Facing(view.Yaw)), heading);
                    input.RunKey(true);
                    input.Walk(keys.Forward); input.Back(keys.Back); input.Strafe(keys.Side);
                }

                // The trigger: only standing, and only with this look's crosshair inside the brackets.
                bool onBody = phase == PackPhase.Shoot && now - screen.InsideAt <= OnBodySeconds;
                if (onBody != input.LeftHeld)
                {
                    input.HoldLeft(onBody);
                    Record("fire", s, new { on = onBody, away, target = target.Name });
                    if (onBody && firedSince < 0) firedSince = now;
                }
                if (firedSince >= 0 && plan.GiveUpSeconds > 0 && now - Math.Max(hurtAt, firedSince) > plan.GiveUpSeconds)
                {
                    Console.WriteLine($"No damage to {target.Name} for {plan.GiveUpSeconds:F0} s: leaving it.");
                    Record("gave-up", s, new { target.Name });
                    skip.Add(TargetId()); input.HoldLeft(false); readAt = -ReadEveryMs;
                }
                hud.Show(phase == PackPhase.Shoot ? Hud.Green : Hud.Amber, $"PACK  {phase}", $"{target.Name}: {away:F0} units, nearest {nearestAway:F0}; {Killed.Count} killed", "F8 stops");
                Thread.Sleep(Tick);
            }
        }
        catch (Exception error)
        {
            Record("stopped", previous, new { error.Message });
            hud.Post(Hud.Red, "PACK  stopped", error.Message);
            throw;
        }
        finally
        {
            if (crouched) try { input.CrouchTap(); } catch (InvalidOperationException) { }   // stand up for the loot run
        }
    }

    private static Vector2 Flat(Vector3 v) => new(v.X, v.Z);
}
