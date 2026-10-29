using System.Diagnostics;
using System.Globalization;
using System.Numerics;
using System.Text.Json;
using NeocronSharp;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// "nearby" (read-only: the players and NPCs around you, as JSON) and "follow" (live: keep
/// walking after one of them at a set distance). Actors come from the app's own tracker
/// reader (EntityReader.cs, linked), the walk from LiveSteer's calibration and the shared
/// steering (RouteFollower, Steering, TurnController, SteerInput).
/// </summary>
internal static class FollowCommand
{
    /// <summary>The actor's id on the command line: its registry node address, in hex. Stable while the actor exists.</summary>
    public static string Id(WorldEntity e) => e.Identity.Node.ToString("x", CultureInfo.InvariantCulture);

    public static string Kind(WorldEntity e) => e.Identity.Kind switch { EntityKind.Player => "player", EntityKind.Npc => "npc", _ => "unknown" };

    private static bool Dead(WorldEntity e) => e.Stats?.Dead == true || e.Player?.Dead == true;

    /// <summary>The single running client, or an error a person can act on.</summary>
    private static string ClientExecutable()
    {
        var procs = Process.GetProcessesByName("neocronclient");
        try { return procs.Length == 1 ? procs[0].MainModule?.FileName ?? "" : throw new InvalidOperationException(procs.Length == 0 ? "Neocron is not running." : "Open exactly one Neocron client."); }
        finally { foreach (var p in procs) p.Dispose(); }
    }

    /// <summary>The actor list, retried briefly: sampling can catch the registry mid-update.</summary>
    public static EntitySnapshot ReadSnapshot(PlayerReader reader, int tries = 5)
    {
        for (int i = 0; ; i++)
        {
            try { return reader.ReadEntities(); }
            catch (InvalidOperationException) when (i + 1 < tries) { Thread.Sleep(30); }
        }
    }

    /// <summary>Players and NPCs (not unclassified actors), nearest first.</summary>
    public static IReadOnlyList<NearbyEntity> Followable(EntitySnapshot snapshot) =>
        EntityQuery.Nearby(snapshot).Where(n => n.Entity.Identity.Kind is EntityKind.Player or EntityKind.Npc)
            .OrderBy(n => n.GroundDistance).ThenBy(n => n.Entity.Name, StringComparer.OrdinalIgnoreCase).ToList();

    /// <summary>nearby [--radius N]: one JSON line. Never sends input; prints live=false when the game cannot be read.</summary>
    public static int Nearby(List<string> rest)
    {
        float radius = 0;
        int r = rest.IndexOf("--radius");
        if (r >= 0 && r + 1 < rest.Count && !float.TryParse(rest[r + 1], CultureInfo.InvariantCulture, out radius)) radius = 0;
        object result;
        try
        {
            using var reader = new PlayerReader(ClientExecutable());
            var snapshot = ReadSnapshot(reader);
            string install = Path.GetDirectoryName(reader.Executable)!;
            int? sector = snapshot.Sector?.WorldId;
            string? sectorName = null;
            try { if (sector is { } id) sectorName = new EnvironmentCatalog(install).Areas.FirstOrDefault(a => a.WorldId == id)?.Name; }
            catch (Exception e) when (e is IOException or InvalidDataException) { }
            var rows = Followable(snapshot).Where(n => radius <= 0 || n.GroundDistance <= radius);
            result = new
            {
                live = true, sector, sectorName,
                player = new { x = Round(snapshot.PlayerPosition.X), y = Round(snapshot.PlayerPosition.Y), z = Round(snapshot.PlayerPosition.Z) },
                entities = rows.Select(n => new
                {
                    id = Id(n.Entity), name = n.Entity.Name, kind = Kind(n.Entity), distance = Round(n.GroundDistance), dead = Dead(n.Entity),
                    x = Round(n.Entity.Position.X), y = Round(n.Entity.Position.Y), z = Round(n.Entity.Position.Z),
                }).ToList(),
            };
        }
        catch (Exception e) when (e is InvalidOperationException or IOException or System.ComponentModel.Win32Exception or UnauthorizedAccessException)
        {
            result = new { live = false, why = e.Message, entities = Array.Empty<object>() };
        }
        Console.WriteLine(JsonSerializer.Serialize(result));
        return 0;

        static float Round(float v) => MathF.Round(v, 1);
    }

    /// <summary>follow &lt;entity id&gt; [--distance 150] [--run] [--pulse N]: live, until F8, Stop, focus loss, the target going, or a zone change.</summary>
    public static int Follow(List<string> rest, string root, int pulse, bool run)
    {
        float distance = FollowBand.DefaultDistance;
        int d = rest.IndexOf("--distance");
        if (d >= 0 && d + 1 < rest.Count)
        {
            if (!float.TryParse(rest[d + 1], CultureInfo.InvariantCulture, out distance)) throw new InvalidOperationException($"--distance wants a number of units, not '{rest[d + 1]}'.");
            rest.RemoveRange(d, 2);
        }
        if (rest.Count < 1) throw new InvalidOperationException("Usage: follow <entity id from 'nearby'> [--distance 150] [--run]");
        string id = rest[0].Trim().ToLowerInvariant();
        if (id.StartsWith("0x")) id = id[2..];

        using var reader = new PlayerReader(ClientExecutable());
        var sample = reader.ReadSample();
        int sector = reader.ReadSectorId(sample.World) ?? throw new InvalidOperationException("The current sector is unavailable. Finish zoning.");
        var target = Followable(ReadSnapshot(reader)).FirstOrDefault(n => Id(n.Entity) == id)?.Entity
            ?? throw new InvalidOperationException($"Nobody with id {id} is nearby any more. Press Refresh and pick again.");
        if (Dead(target)) throw new InvalidOperationException($"{target.Name} is dead.");
        var band = new FollowBand(distance);
        Console.WriteLine($"Following {target.Name} ({Kind(target)}) at {band.Distance:F0} units{(band.Distance != distance ? $" (asked {distance:F0}; allowed {FollowBand.MinDistance:F0}-{FollowBand.MaxDistance:F0})" : "")}.");

        string install = Path.GetDirectoryName(reader.Executable)!;
        var nav = NavWorld.Bake(install, sector);
        Console.WriteLine($"{nav.World.Summary.Name} (world {sector}): navmesh baked in {nav.BakeTime.TotalSeconds:F1}s");
        var catalog = new EnvironmentCatalog(install);
        string Name(int s) => catalog.Areas.FirstOrDefault(a => a.WorldId == s)?.Name ?? $"sector {s}";

        string logs = Path.Combine(root, "logs"); Directory.CreateDirectory(logs);
        string stamp = $"{DateTime.UtcNow:yyyyMMdd-HHmmss}";
        using var hud = new Hud();
        Travel.FocusGame(reader.Window);
        // LiveSteer's own countdown and calibration (test step + turn probe), then nothing else.
        var calibrate = new LiveSteer(reader, nav, sector, sample.Position, true, target.Name, pulse,
            Path.Combine(logs, $"steer-{stamp}-follow-calibration.jsonl"), hud, run) { CalibrateOnly = true };
        calibrate.Run();
        var calibration = calibrate.Measured ?? throw new InvalidOperationException("Calibration did not finish.");

        var exits = nav.World.Summary.Features.Where(f => f.Kind == "WorldChange"
                && int.TryParse(f.Properties.GetValueOrDefault("NextLevelStartIndex"), out int start) && start > 0
                && int.TryParse(f.Properties.GetValueOrDefault("NextLevel"), out int to) && to > 0 && to != sector)
            .Select(f => (f.Position, int.Parse(f.Properties["NextLevel"]))).ToList();
        string why = new FollowWalk(reader, nav, sector, target, band, calibration, pulse, run, hud,
            Path.Combine(logs, $"follow-{stamp}.jsonl"), exits, Name).Run();
        Console.WriteLine(why);
        return 0;
    }
}

/// <summary>The live follow loop. Ends by returning why it stopped, or by throwing (F8, focus, zone change, stuck).</summary>
internal sealed class FollowWalk(PlayerReader reader, NavWorld nav, int sector, WorldEntity target, FollowBand band,
    LiveSteer.Calibration calibration, int pulse, bool run, Hud hud, string logPath,
    IReadOnlyList<(Vector3 Position, int To)> exits, Func<int, string> sectorName)
{
    private const int Tick = 33, PulseGap = 16, ReadEveryMs = 150, MissesToLose = 4;
    private const double UnreachableSeconds = 15, StallSeconds = 2.5;
    private const int MaxStalls = 3, MaxOffRoutePer20s = 6;

    private sealed record Plan(RouteFollower Route, Vector3 Goal, float Miss, double At);

    public string Run()
    {
        using var log = new StreamWriter(logPath) { AutoFlush = true };
        using var input = new SteerInput(reader, pulse, run);
        var clock = Stopwatch.StartNew();
        string title = $"FOLLOW  {target.Name}";
        var origin = reader.ReadSample();
        var previous = origin;
        double previousAt = 0;
        bool riding = false;   // in a gravity lift: only a sideways jump is a teleport

        void Record(string kind, PlayerSample s, object? detail = null) => log.WriteLine(JsonSerializer.Serialize(new {
            timeUtc = DateTimeOffset.UtcNow, elapsedSeconds = clock.Elapsed.TotalSeconds, kind,
            position = new { s.Position.X, s.Position.Y, s.Position.Z }, forward = new { s.Forward.X, s.Forward.Z },
            walking = input.Walking, detail }));

        // As LiveSteer's guard on an ordinary walk: F8, focus, identity, sector, teleports.
        PlayerSample Guard()
        {
            if ((Native.GetAsyncKeyState(0x77) & 0x8000) != 0) throw new OperationCanceledException("F8 stop pressed.");
            reader.RequireForeground();
            PlayerSample s;
            try { s = reader.ReadSample(); }
            catch (InvalidOperationException) { throw new InvalidOperationException("Your character could not be read (zoning?). Follow stopped."); }
            if (s.Player != origin.Player || s.World != origin.World || s.Physics != origin.Physics)
                throw new InvalidOperationException("You changed zone (the player or world changed). Follow stopped; following through zones is not supported yet.");
            int? now = reader.ReadSectorId(s.World);
            if (now != sector)
                throw new InvalidOperationException($"You changed zone, to {(now is { } n ? sectorName(n) : "a loading screen")}. Follow stopped; following through zones is not supported yet.");
            double t = clock.Elapsed.TotalSeconds, dt = previousAt == 0 ? 0 : t - previousAt;
            float jump = riding ? PointNavigation.Distance(s.Position, previous.Position) : Vector3.Distance(s.Position, previous.Position);
            if (jump > 60 + 900 * (float)Math.Min(dt, 2)) throw new InvalidOperationException($"Unexpected position jump ({jump:F0} units in {dt:F2} s). Stopped.");
            previous = s; previousAt = t;
            return s;
        }

        PlayerSample Wait(int ms)
        {
            long until = clock.ElapsedMilliseconds + ms;
            var s = Guard();
            while (clock.ElapsedMilliseconds < until) { Thread.Sleep((int)Math.Clamp(until - clock.ElapsedMilliseconds, 1, 15)); s = Guard(); }
            return s;
        }

        int Turn(int pixels, int pulses)
        {
            int sent = 0;
            for (int i = 0; i < pulses && sent != pixels; i++) { sent += input.TurnPulse(pixels - sent); Wait(PulseGap); }
            return sent;
        }

        // ---- the target ----
        Vector3 seenAt = target.Position;
        long readAt = -ReadEveryMs;
        int misses = 0, unreadable = 0;
        // Returns why the target is gone, or null while it is still there.
        string? ReadTarget()
        {
            if (clock.ElapsedMilliseconds - readAt < ReadEveryMs) return null;
            readAt = clock.ElapsedMilliseconds;
            WorldEntity? live = null;
            try
            {
                live = reader.ReadEntities().Entities.FirstOrDefault(e => e.Identity.Node == target.Identity.Node && e.Identity.Physics == target.Identity.Physics);
            }
            catch (InvalidOperationException e)
            {
                // Caught the registry mid-update: try again next time. For seconds on end, give up.
                if (++unreadable >= 20) throw new InvalidOperationException($"The actors around you could not be read for 3 s ({e.Message}). Follow stopped.");
                return null;
            }
            unreadable = 0;
            // A different actor at a reused address is not the target. (A player's name can fail to
            // read for a moment, showing as an unclassified character; that is still them.)
            if (live != null && live.Name != target.Name && live.Identity.Kind != EntityKind.UnclassifiedCharacter) live = null;
            if (live == null)
            {
                if (++misses < MissesToLose) return null;
                var exit = FollowLogic.NearestExit(seenAt, exits);
                return exit is { } x
                    ? $"{target.Name} crossed the zone line toward {sectorName(x.To)} (last seen {PointNavigation.Distance(seenAt, x.Position):F0} units from that exit). Follow stopped; following through zones is not supported yet."
                    : $"{target.Name} is gone (out of range, logged off, despawned, or went through a door). Follow stopped.";
            }
            misses = 0;
            if (live.Stats?.Dead == true || live.Player?.Dead == true) return $"{target.Name} died. Follow stopped.";
            seenAt = live.Position;
            return null;
        }

        // ---- the route ----
        Plan? plan = null;
        double unreachableSince = -1, retryAt = 0;
        Plan? MakePlan(Vector3 from)
        {
            var corners = nav.RouteNear(from, seenAt, out bool complete);
            // On the target's floor, not the one under it (gravity lifts join stacked floors).
            if (corners.Count < 2 || !complete || MathF.Abs(corners[^1].Y - seenAt.Y) > 150) return null;
            return new(new RouteFollower(corners), seenAt, PointNavigation.Distance(corners[^1], seenAt), clock.Elapsed.TotalSeconds);
        }

        try
        {
            var turns = new TurnController(calibration.Gain);
            float lookahead = Steering.Lookahead(calibration.Speed);
            var rider = new LiftRider(Guard, Wait, Turn, input, turns, pulse, (k, at, d) => Record(k, at, d), text => hud.Show(Hud.Cyan, title, text, "F8 stops"));
            var doors = new DoorOpener(nav.Doors);
            int lastPixels = 0;
            var first = Guard();
            Vector3 lastForward = first.Forward;
            plan = MakePlan(first.Position);
            float startGap = FollowLogic.Gap(FollowLogic.Straight(first.Position, seenAt), plan?.Route.Remaining, plan?.Miss ?? 0);
            band.Start(startGap);
            Record("start", first, new { target = target.Name, id = FollowCommand.Id(target), distance = band.Distance, resume = band.Resume, calibration.Speed, calibration.Gain });
            Console.WriteLine($"Following. Stops within {band.Distance:F0} units and sets off again past {band.Resume:F0}. F8 stops.");
            var offRoute = new Queue<double>();
            Vector3 stallFrom = first.Position; double stallMark = 0; int stalls = 0;
            double turningSince = -1;
            bool wasMoving = !band.Moving;

            while (true)
            {
                var s = Guard();
                double now = clock.Elapsed.TotalSeconds;
                if (ReadTarget() is { } gone) { input.Walk(false); Record("lost", s, new { gone, seenAt = new[] { seenAt.X, seenAt.Y, seenAt.Z } }); hud.Post(Hud.Cyan, title, gone); return gone; }

                float straight = FollowLogic.Straight(s.Position, seenAt);
                float off = plan?.Route.Update(s.Position) ?? 0;
                float gap = FollowLogic.Gap(straight, plan?.Route.Remaining, plan?.Miss ?? 0);
                var why = FollowLogic.Decide(plan != null, plan == null ? 0 : PointNavigation.Distance(plan.Goal, seenAt), gap, band.Moving ? off : 0,
                    plan?.Route.Remaining ?? 0, plan == null ? 0 : now - plan.At);
                // With no route, retry twice a second rather than every tick.
                if (why == FollowReplan.First && now < retryAt) why = FollowReplan.None;
                if (why != FollowReplan.None)
                {
                    if (why == FollowReplan.OffRoute)
                    {
                        while (offRoute.Count > 0 && now - offRoute.Peek() > 20) offRoute.Dequeue();
                        offRoute.Enqueue(now);
                        if (offRoute.Count > MaxOffRoutePer20s) throw new InvalidOperationException("Kept leaving the route; the navmesh and the game disagree here.");
                    }
                    plan = MakePlan(s.Position);
                    if (plan != null)
                    {
                        unreachableSince = -1;
                        off = plan.Route.Update(s.Position);
                        gap = FollowLogic.Gap(straight, plan.Route.Remaining, plan.Miss);
                        if (why != FollowReplan.Refresh) Record("replan", s, new { why = why.ToString(), corners = plan.Route.Corners.Count, length = plan.Route.Total, plan.Miss });
                    }
                    else
                    {
                        retryAt = now + 0.5;
                        if (unreachableSince < 0) { unreachableSince = now; Record("unreachable", s, new { seenAt = new[] { seenAt.X, seenAt.Y, seenAt.Z } }); }
                    }
                }

                bool moving = band.Update(gap);
                if (moving != wasMoving)
                {
                    Record(moving ? "resume" : "hold", s, new { gap });
                    Console.WriteLine(moving ? $"{target.Name} is {gap:F0} units away: following." : $"Within {gap:F0} units of {target.Name}: waiting.");
                    wasMoving = moving;
                    stallFrom = s.Position; stallMark = now; stalls = 0; turningSince = -1;
                }

                if (!moving || plan == null)
                {
                    input.Walk(false);
                    if (moving && unreachableSince >= 0 && now - unreachableSince > UnreachableSeconds)
                        throw new InvalidOperationException($"No walkable way to {target.Name} for {UnreachableSeconds:F0} s (on a ledge or behind a wall?). Follow stopped.");
                    hud.Show(moving ? Hud.Amber : Hud.Cyan, title,
                        moving ? $"{straight:F0} units away; no walkable way there yet" : $"waiting, {gap:F0} units away (moves on past {band.Resume:F0})", "F8 stops");
                    Wait(Tick);
                    stallFrom = s.Position; stallMark = now; lastPixels = 0;
                    continue;
                }

                // A gravity lift on the way: at its start, ride it (a timed step), then plan on from the landing.
                var lift = Lifts.Ahead(nav, plan.Route);
                if (lift is { } l && Lifts.AtStart(l.Link, s.Position))
                {
                    riding = true;
                    try { rider.Ride(l.Link); }
                    finally { riding = false; }
                    s = Guard();
                    ReadTarget();
                    plan = MakePlan(s.Position);
                    Record("replan", s, new { why = "lift", corners = plan?.Route.Corners.Count ?? 0 });
                    stallFrom = s.Position; stallMark = clock.Elapsed.TotalSeconds; stalls = 0; turningSince = -1; lastPixels = 0;
                    lastForward = s.Forward;
                    continue;
                }
                // Walking: the same pure pursuit and capped turning as LiveSteer.
                input.Sprint(gap - band.Distance > 120);
                turns.Observe(lastPixels, PointNavigation.SignedAngle(lastForward, s.Forward));
                lastForward = s.Forward;
                // Walk to a lift's start exactly: the look-ahead would cut past it into the beam.
                var aim = lift is { } next && next.Arc - plan.Route.Progress < lookahead ? next.Link.Start : plan.Route.Aim(s.Position, lookahead, nav.Clear);
                var decision = Steering.Decide(s.Position, s.Forward, aim);
                input.Walk(decision.Walk);
                int pixels = turns.Pixels(decision.TurnRadians, pulse * 2);
                int sent = pixels == 0 ? 0 : Turn(pixels, 2);
                lastPixels = sent;
                hud.Show(Hud.Green, title, $"{gap:F0} units away, stopping at {band.Distance:F0}",
                    $"{(decision.Walk ? (run ? "running" : "walking") : "turning in place")}   F8 stops");
                Record("steer", s, new { aim = new[] { aim.X, aim.Y, aim.Z }, decision.Angle, pixels = sent, off, gap, target = new[] { seenAt.X, seenAt.Z } });
                if (!decision.Walk)
                {
                    if (turningSince < 0) turningSince = now;
                    if (now - turningSince > 10) throw new InvalidOperationException("Could not face the route. Check mouse-look mode.");
                    stallFrom = s.Position; stallMark = now;
                    if (sent == 0) Wait(20);
                    continue;
                }
                turningSince = -1;
                // Held W but went nowhere: replan from here; a few times running means the game blocks us.
                // A door inside the sector: when the gap stops shrinking near one, face it, step up
                // to it and right-click it (the game says "already in use" while it moves).
                if (doors.Blocking(s.Position, gap, (long)(now * 1000)) is { } door)
                {
                    if (!doors.Try(door)) throw new InvalidOperationException($"{DoorOpener.Failed} {target.Name} is beyond it, {gap:F0} units away. Follow stopped.");
                    hud.Post(Hud.Amber, title, $"A door is in the way: opening it (right click, try {doors.Tries(door)} of {DoorOpener.MaxTries}).");
                    Console.WriteLine($"A door is in the way: right-clicking it (try {doors.Tries(door)} of {DoorOpener.MaxTries}).");
                    DoorOpener.Open(door, Guard, a => turns.Pixels(a, pulse * 4), px => Turn(px, 4), input.Walk, input.Use, ms => Wait(ms));
                    Record("use", Guard(), new { reason = "door", door = door.Name, at = new[] { door.Position.X, door.Position.Y, door.Position.Z }, tries = doors.Tries(door) });
                    doors.Reset();
                    stallFrom = Guard().Position; stallMark = clock.Elapsed.TotalSeconds;
                    plan = MakePlan(stallFrom);
                    continue;
                }
                if (PointNavigation.Distance(s.Position, stallFrom) > 20) { stallFrom = s.Position; stallMark = now; stalls = 0; }
                else if (now - stallMark > StallSeconds)
                {
                    if (++stalls >= MaxStalls)
                        throw new InvalidOperationException($"Blocked {gap:F0} units from {target.Name}: the navmesh says walkable, the game disagrees (door, prop or step?). Follow stopped.");
                    Record("stalled", s, new { stalls });
                    input.Walk(false);
                    plan = MakePlan(s.Position);
                    stallMark = now;
                }
                if (sent == 0) Wait(Tick);
            }
        }
        catch (Exception error)
        {
            input.Dispose();
            Record("stopped", previous, new { error.Message });
            hud.Post(Hud.Red, $"FOLLOW  stopped", error.Message);
            throw;
        }
    }
}
