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

    internal static bool Dead(WorldEntity e) => e.Stats?.Dead == true || e.Player?.Dead == true;

    /// <summary>
    /// The client to read: the one NEOCRON_PID names (the suite's client picker, when two are open), else the only
    /// one running; or an error a person can act on. PlayerReader picks the same process by NEOCRON_PID.
    /// </summary>
    internal static string ClientExecutable()
    {
        var procs = Process.GetProcessesByName("neocronclient");
        try
        {
            if (procs.Length == 0) throw new InvalidOperationException("Neocron is not running.");
            var chosen = int.TryParse(Environment.GetEnvironmentVariable("NEOCRON_PID"), out int pid) ? procs.FirstOrDefault(p => p.Id == pid) : null;
            if (chosen == null)
            {
                // A client under another Windows account (another sign-in or remote session) cannot be read from here:
                // with nothing picked, the one in this session is meant (5 Nov).
                int session = Process.GetCurrentProcess().SessionId;
                var here = procs.Where(p => { try { return p.SessionId == session; } catch (InvalidOperationException) { return false; } }).ToArray();
                if (here.Length == 1) chosen = here[0];
                else if (procs.Length > 1)
                    throw new InvalidOperationException("Two Neocron clients are open: pick the one to use in the suite's Client list.");
                else chosen = procs[0];
                // PlayerReader picks its process by NEOCRON_PID when more than one is running.
                Environment.SetEnvironmentVariable("NEOCRON_PID", chosen.Id.ToString(System.Globalization.CultureInfo.InvariantCulture));
            }
            return chosen.MainModule?.FileName ?? "";
        }
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
            try { if (sector is { } id) sectorName = Catalog(install).Areas.FirstOrDefault(a => a.WorldId == id)?.Name; }
            catch (Exception e) when (e is IOException or InvalidDataException) { }
            var rows = Followable(snapshot).Where(n => radius <= 0 || n.GroundDistance <= radius);
            result = new
            {
                live = true, sector, sectorName,
                player = new { x = Round(snapshot.PlayerPosition.X), y = Round(snapshot.PlayerPosition.Y), z = Round(snapshot.PlayerPosition.Z) },
                entities = rows.Select(n => new
                {
                    id = Id(n.Entity), name = n.Entity.Name, kind = Kind(n.Entity), distance = Round(n.GroundDistance), dead = Dead(n.Entity),
                    faction = n.Entity.ReferenceData?.FactionName, factionId = n.Entity.Stats?.FactionId,
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

    /// <summary>follow &lt;entity id&gt; [--distance 150] [--run] [--pulse N] [--arrive] [--body] [--calibration speed,gain] [--gains yaw,pitch]: live, until F8, Stop, focus loss, the target going, or a zone change. --arrive ends on reaching an NPC, or with --body a dead one, for the hunt, which passes on the first run's calibration so each walk needs no test step. A healer's retry passes both, for no test moves at all.</summary>
    public static int Follow(List<string> rest, string root, int pulse, bool run)
    {
        bool heal = rest.Remove("--heal"), arrive = rest.Remove("--arrive"), body = arrive && rest.Remove("--body");
        (float, float)? Pair(string name)
        {
            int i = rest.IndexOf(name);
            if (i < 0 || i + 1 >= rest.Count) return null;
            var parts = rest[i + 1].Split(',');
            rest.RemoveRange(i, 2);
            return (float.Parse(parts[0], CultureInfo.InvariantCulture), float.Parse(parts[1], CultureInfo.InvariantCulture));
        }
        string? teamArg = null;
        int t = rest.IndexOf("--team");
        if (t >= 0 && t + 1 < rest.Count) { teamArg = rest[t + 1]; rest.RemoveRange(t, 2); }
        LiveSteer.Calibration? known = Pair("--calibration") is { } c ? new(c.Item1, c.Item2) : null;
        (float Yaw, float Pitch)? aim = heal ? Pair("--gains") : null;
        float distance = FollowBand.DefaultDistance;
        int d = rest.IndexOf("--distance");
        if (d >= 0 && d + 1 < rest.Count)
        {
            if (!float.TryParse(rest[d + 1], CultureInfo.InvariantCulture, out distance)) throw new InvalidOperationException($"--distance wants a number of units, not '{rest[d + 1]}'.");
            rest.RemoveRange(d, 2);
        }
        if (rest.Count < 1) throw new InvalidOperationException("Usage: follow <entity id from 'nearby'> [--distance 150] [--run] [--heal]");

        using var reader = new PlayerReader(ClientExecutable());
        var sample = reader.ReadSteady();
        int sector = reader.ReadSectorId(sample.World) ?? throw new InvalidOperationException("The current sector is unavailable. Finish zoning.");
        var target = Pick(reader, rest[0], body);
        string fighterFile = Path.Combine(root, FighterFile);
        if (heal && !CameraAim.IsFighter(File.Exists(fighterFile) ? File.ReadAllText(fighterFile) : null, target.Name, target.Identity.Kind))
            throw new InvalidOperationException($"{target.Name} is not the fighter named on the tab. Follow and heal only works on your own fighter.");
        if (arrive && !CameraAim.MayHold(target.Identity.Kind)) throw new InvalidOperationException($"{target.Name} is not an NPC: the hunt walks to NPCs only.");
        TeamHeal? team = null;
        if (teamArg != null)
        {
            if (!heal) throw new InvalidOperationException("--team goes with --heal.");
            team = new TeamHeal(new[] { target.Name }.Concat(teamArg.Split(',')), reader.Window, new TeamPanel());
            Console.WriteLine($"Team: {string.Join(", ", team.Names)}.");
        }
        var band = new FollowBand(distance);
        Console.WriteLine($"Following {target.Name} ({Kind(target)}) at {band.Distance:F0} units{(band.Distance != distance ? $" (asked {distance:F0}; allowed {FollowBand.MinDistance:F0}-{FollowBand.MaxDistance:F0})" : "")}.");

        string install = Path.GetDirectoryName(reader.Executable)!;
        var nav = Mapped(install, sector, root);
        Console.WriteLine($"{nav.World.Summary.Name} (world {sector}): navmesh baked in {nav.BakeTime.TotalSeconds:F1}s");
        var catalog = Catalog(install);
        string Name(int s) => catalog.Areas.FirstOrDefault(a => a.WorldId == s)?.Name ?? $"sector {s}";

        string logs = Path.Combine(root, "logs"); Directory.CreateDirectory(logs);
        string stamp = $"{DateTime.UtcNow:yyyyMMdd-HHmmss}";
        using var hud = new Hud();
        Travel.FocusGame(reader.Window);
        // A healer does without the test step: in a VM slow frames failed it three runs in three (1 Nov). So does a hunt, where "did not
        // settle after releasing W" ended it (2 Nov). TurnController learns the gain as it walks.
        var calibration = known ?? (heal || arrive ? FollowWalk.Typical : null);
        if (calibration == null)
        {
            // LiveSteer's own countdown and calibration (test step + turn probe), then nothing else.
            var calibrate = new LiveSteer(reader, nav, sector, sample.Position, true, target.Name, pulse,
                Path.Combine(logs, $"steer-{stamp}-follow-calibration.jsonl"), hud, run, countdown: !arrive) { CalibrateOnly = true };
            calibrate.Run();
            calibration = calibrate.Measured ?? throw new InvalidOperationException("Calibration did not finish.");
            Console.WriteLine(string.Create(CultureInfo.InvariantCulture, $"calibration {calibration.Speed} {calibration.Gain}"));
        }
        if (heal && aim == null)
        {
            var measure = new CameraWatch(reader, target, pulse, new CameraPlan(Now: true, MeasureOnly: true), hud, Path.Combine(logs, $"camera-{stamp}-gain.jsonl"));
            measure.Run();
            aim = measure.Measured;
        }

        var exits = nav.World.Summary.Features.Where(f => f.Kind == "WorldChange"
                && int.TryParse(f.Properties.GetValueOrDefault("NextLevelStartIndex"), out int start) && start > 0
                && int.TryParse(f.Properties.GetValueOrDefault("NextLevel"), out int to) && to > 0 && to != sector)
            .Select(f => (f.Position, int.Parse(f.Properties["NextLevel"]))).ToList();
        for (int tried = 0; ; tried++)
        {
            try
            {
                Console.WriteLine(new FollowWalk(reader, nav, sector, target, band, calibration, pulse, run, hud,
                    Path.Combine(logs, $"follow-{stamp}-{tried}.jsonl"), exits, Name, aim, arrive, team).Run());
                return 0;
            }
            catch (LiveSteer.BlockedAt blocked) when (tried < GoRoundTries)
            {
                MapBlock(root, sector, blocked);
                nav = Mapped(install, sector, root);
            }
        }
    }

    /// <summary>How many things one walk maps and goes round before giving up. The map holds buildings it doesn't know, like K 16's Warp Garage (2 Nov).</summary>
    internal const int GoRoundTries = 5;

    /// <summary>The sector's navmesh, with every spot found blocked cut out, so all walks go round them from now on. Kept between a serve's lines.</summary>
    internal static NavWorld Mapped(string install, int sector, string root)
    {
        var obstacles = Travel.LoadObstacles(Path.Combine(root, "logs")).GetValueOrDefault(sector);
        var key = (sector, obstacles?.Count ?? 0);
        return Baked.TryGetValue(key, out var nav) ? nav : Baked[key] = NavWorld.Bake(install, sector, obstacles: obstacles);
    }

    private static readonly Dictionary<(int Sector, int Obstacles), NavWorld> Baked = new();

    internal static EnvironmentCatalog Catalog(string install) => _catalog ??= new EnvironmentCatalog(install);
    private static EnvironmentCatalog? _catalog;

    /// <summary>Printed after each line of a serve.</summary>
    public const string ServeDone = "<<done>>";

    /// <summary>serve: reads tab-separated commands from stdin and runs them one after another, for a loop of many short runs: a new process for each took 2 s, nearly all of it baking the same map. Stop ends it.</summary>
    public static int Serve(string root)
    {
        while (Console.ReadLine() is { } line)
        {
            var rest = line.Split('\t').ToList();
            string command = rest[0];
            rest.RemoveAt(0);
            bool run = rest.Remove("--run");
            int at = rest.IndexOf("--pulse"), pulse = 6;
            if (at >= 0 && at + 1 < rest.Count) { pulse = int.Parse(rest[at + 1], CultureInfo.InvariantCulture); rest.RemoveRange(at, 2); }
            try
            {
                switch (command)
                {
                    case "nearby": Nearby(rest); break;
                    case "spot": Spot(); break;
                    case "follow": Follow(rest, root, pulse, run); break;
                    case "camera": Camera(rest, root, pulse); break;
                    case "usespot": UseSpot(rest, root, pulse); break;
                    default: throw new InvalidOperationException($"serve does not run {command}.");
                }
            }
            catch (OperationCanceledException error)
            {
                Console.WriteLine($"Stopped: {error.Message}");
                return 1;
            }
            catch (Exception error) when (error is InvalidOperationException or InvalidDataException or IOException)
            {
                Console.WriteLine($"Stopped: {error.Message}");
            }
            Console.WriteLine(ServeDone);
        }
        return 0;
    }

    internal static void MapBlock(string root, int sector, LiveSteer.BlockedAt blocked)
    {
        var spot = blocked.Position + Vector3.Normalize(new Vector3(blocked.Forward.X, 0, blocked.Forward.Z)) * 48;
        Travel.SaveObstacle(Path.Combine(root, "logs"), sector, spot);
        Console.WriteLine($"Something is in the way at {spot.X:F0},{spot.Z:F0}; mapping it and going round.");
    }

    /// <summary>The user's fighter, named on the suite's tab, in this folder.</summary>
    private const string FighterFile = "fighter.txt";

    /// <summary>The living, nearby actor with this id from 'nearby'.</summary>
    private static WorldEntity Pick(PlayerReader reader, string idText, bool dead = false)
    {
        string id = idText.Trim().ToLowerInvariant();
        if (id.StartsWith("0x")) id = id[2..];
        var target = Followable(ReadSnapshot(reader)).FirstOrDefault(n => Id(n.Entity) == id)?.Entity
            ?? throw new InvalidOperationException($"Nobody with id {id} is nearby any more. Press Refresh and pick again.");
        if (Dead(target) != dead) throw new InvalidOperationException($"{target.Name} is {(dead ? "still alive" : "dead")}.");
        return target;
    }

    /// <summary>flee [--pulse N] [--calibration speed,gain]: live, runs to the nearest spot no NPC can see, for the hunt when hurt.</summary>
    public static int Flee(List<string> rest, string root, int pulse)
    {
        int c = rest.IndexOf("--calibration");
        LiveSteer.Calibration known = FollowWalk.Typical;
        if (c >= 0 && c + 1 < rest.Count)
        {
            var parts = rest[c + 1].Split(',');
            known = new(float.Parse(parts[0], CultureInfo.InvariantCulture), float.Parse(parts[1], CultureInfo.InvariantCulture));
        }
        using var reader = new PlayerReader(ClientExecutable());
        int sector = reader.ReadSectorId(reader.ReadSteady().World) ?? throw new InvalidOperationException("The current sector is unavailable. Finish zoning.");
        string install = Path.GetDirectoryName(reader.Executable)!;
        var mobs = Followable(ReadSnapshot(reader)).Where(n => n.Entity.Identity.Kind == EntityKind.Npc && !Dead(n.Entity)).Select(n => n.Entity.Position).ToList();
        var heights = TerrainCell.Exists(install, sector) ? TerrainCell.ReadHeights(install, sector) : null;
        var cover = new Cover(heights, Shots(reader) ?? new ShotLine(Array.Empty<SectorObjects.Prop>()));
        string logs = Path.Combine(root, "logs"); Directory.CreateDirectory(logs);
        using var hud = new Hud();
        Travel.FocusGame(reader.Window);
        for (int tried = 0; ; tried++)
        {
            var nav = Mapped(install, sector, root);
            var here = reader.ReadSteady().Position;
            Vector3? Ground(Vector3 p) => nav.Snap(heights == null ? p : p with { Y = TerrainCell.Sample(heights, p.X, p.Z) }, out _, out var on, true) ? on : null;
            bool Runnable(Vector3 spot)
            {
                var route = nav.Route(here, spot, out bool complete);
                return route.Count >= 2 && complete && new RouteFollower(route).Total <= Cover.MostRun;
            }
            var spots = cover.Spots(here, mobs, Ground).Where(Runnable).Take(1).ToList();
            if (spots.Count == 0) throw new InvalidOperationException("No way to run to.");
            int seen = mobs.Count(m => PointNavigation.Distance(m, spots[0]) <= Cover.LooksThisFar && !cover.Hidden(m, spots[0]));
            Console.WriteLine(seen == 0 ? "Running to cover." : $"Nowhere fully hidden: running to where {seen} can see.");
            try
            {
                new LiveSteer(reader, nav, sector, spots[0], false, "cover", pulse, Path.Combine(logs, $"flee-{DateTime.UtcNow:yyyyMMdd-HHmmss}-{tried}.jsonl"), hud,
                    run: true, countdown: false, known: known).Run();
                Console.WriteLine("Reached cover.");
                return 0;
            }
            catch (LiveSteer.BlockedAt blocked) when (tried < GoRoundTries) { MapBlock(root, sector, blocked); }
        }
    }

    /// <summary>What can stand in a shot's way in a wasteland cell, from its spawn file. Null elsewhere: the target bar alone decides.</summary>
    private static ShotLine? Shots(PlayerReader reader)
    {
        string install = Path.GetDirectoryName(reader.Executable)!;
        if (reader.ReadSectorId(reader.ReadSteady().World) is not { } sector || !TerrainCell.Exists(install, sector)) return null;
        try { return new ShotLine(SectorObjects.ReadDat(install, Path.Combine(install, "terrain", $"pak_{TerrainCell.CodeOf(sector)}.dat")).Props); }
        catch (Exception e) when (e is IOException or InvalidDataException) { return null; }
    }

    /// <summary>spot: read-only, where you stand and where you look, as one JSON line, so usespot can come back to it.</summary>
    public static int Spot()
    {
        object result;
        try
        {
            using var reader = new PlayerReader(ClientExecutable());
            var sample = reader.ReadSteady();
            var view = reader.ReadCamera(sample) ?? throw new InvalidOperationException("The camera's angles could not be read on this game build.");
            result = new { live = true, x = sample.Position.X, y = sample.Position.Y, z = sample.Position.Z, yaw = view.Yaw, pitch = view.Pitch };
        }
        catch (Exception e) when (e is InvalidOperationException or IOException or System.ComponentModel.Win32Exception or UnauthorizedAccessException)
        {
            result = new { live = false, why = e.Message };
        }
        Console.WriteLine(JsonSerializer.Serialize(result));
        return 0;
    }

    /// <summary>usespot x,y,z yaw,pitch [--exact] [--pulse N] [--calibration speed,gain] [--gains yaw,pitch]: live, walks back to a place from 'spot', looks the same way and right-clicks what is there: the mission terminal, which is no actor.</summary>
    public static int UseSpot(List<string> rest, string root, int pulse)
    {
        (float, float)? Pair(string name)
        {
            int i = rest.IndexOf(name);
            if (i < 0 || i + 1 >= rest.Count) return null;
            var parts = rest[i + 1].Split(',');
            rest.RemoveRange(i, 2);
            return (float.Parse(parts[0], CultureInfo.InvariantCulture), float.Parse(parts[1], CultureInfo.InvariantCulture));
        }
        var known = Pair("--calibration") is { } c ? new LiveSteer.Calibration(c.Item1, c.Item2) : FollowWalk.Typical;
        (float Yaw, float Pitch)? gains = Pair("--gains");
        bool exact = rest.Remove("--exact");
        if (rest.Count < 2) throw new InvalidOperationException("Usage: usespot x,y,z yaw,pitch");
        float[] at = rest[0].Split(',').Select(v => float.Parse(v, CultureInfo.InvariantCulture)).ToArray(), look = rest[1].Split(',').Select(v => float.Parse(v, CultureInfo.InvariantCulture)).ToArray();
        var spot = new Vector3(at[0], at[1], at[2]);
        using var reader = new PlayerReader(ClientExecutable());
        int sector = reader.ReadSectorId(reader.ReadSteady().World) ?? throw new InvalidOperationException("The current sector is unavailable. Finish zoning.");
        string install = Path.GetDirectoryName(reader.Executable)!;
        string logs = Path.Combine(root, "logs"); Directory.CreateDirectory(logs);
        string stamp = $"{DateTime.UtcNow:yyyyMMdd-HHmmss}";
        using var hud = new Hud();
        Travel.FocusGame(reader.Window);
        for (int tried = 0; PointNavigation.Distance(reader.ReadSteady().Position, spot) > (exact ? SpotExact : SpotQuick); tried++)
        {
            try
            {
                new LiveSteer(reader, Mapped(install, sector, root), sector, spot, false, "terminal", pulse, Path.Combine(logs, $"spot-{stamp}-{tried}.jsonl"), hud,
                    run: true, countdown: false, known: known, near: exact ? 0 : SpotQuick).Run();
                break;
            }
            catch (LiveSteer.BlockedAt blocked) when (tried < GoRoundTries) { MapBlock(root, sector, blocked); }
        }
        if (gains == null)
        {
            var anyone = Followable(ReadSnapshot(reader)).FirstOrDefault(n => n.Entity.Identity.Kind == EntityKind.Npc)?.Entity ?? throw new InvalidOperationException("No NPC here to measure the mouse with.");
            var measure = new CameraWatch(reader, anyone, pulse, new CameraPlan(Now: true, MeasureOnly: true), hud, Path.Combine(logs, $"camera-{stamp}-gain.jsonl"));
            measure.Run();
            gains = measure.Measured;
            Console.WriteLine(string.Create(CultureInfo.InvariantCulture, $"gains {gains!.Value.Yaw} {gains.Value.Pitch}"));
        }
        using var input = new SteerInput(reader, pulse);
        var snap = new SnapAim();
        var clock = Stopwatch.StartNew();
        while (!snap.Done)
        {
            if (StopRequest.Made()) throw new OperationCanceledException("Stop pressed.");
            if (clock.ElapsedMilliseconds > SpotAimMs) throw new InvalidOperationException("Could not look back at the terminal.");   // A right-click lands on whatever is there.
            reader.RequireForeground();
            var view = reader.ReadCamera(reader.ReadSteady()) ?? throw new InvalidOperationException("The camera's angles could not be read on this game build.");
            float yawError = PointNavigation.SignedAngle(CameraAim.Facing(view.Yaw), CameraAim.Facing(look[0])), pitchError = look[1] - view.Pitch;
            var turn = snap.Step(clock.ElapsedMilliseconds, yawError, pitchError);
            input.LookBurst((int)MathF.Round(turn.Yaw / gains!.Value.Yaw), (int)MathF.Round(turn.Pitch / gains.Value.Pitch));
            Thread.Sleep(15);
        }
        input.Use();
        Console.WriteLine("Right-clicked the terminal.");
        return 0;
    }

    /// <summary>How near the spot counts as back there: the quick way, and with --exact when the quick way missed the terminal.</summary>
    private const float SpotQuick = 11, SpotExact = 8;
    private const int SpotAimMs = 6000;

    /// <summary>camera &lt;entity id&gt; [--pulse N] [--hold-left] [--give-up S] [--now] [--gains yaw,pitch] [--box] [--use] [--sight] [--back-off units]: live, turns the camera to keep facing the target; never walks, and clicks only to hold the left button on an NPC. --box runs to a dead NPC and right-clicks its loot box instead, and --use aims at a living NPC and right-clicks it to talk.</summary>
    public static int Camera(List<string> rest, string root, int pulse)
    {
        string? Option(string name)
        {
            int i = rest.IndexOf(name); if (i < 0 || i + 1 >= rest.Count) return null;
            string value = rest[i + 1]; rest.RemoveRange(i, 2); return value;
        }
        bool holdLeft = rest.Remove("--hold-left"), now = rest.Remove("--now"), box = rest.Remove("--box"), use = rest.Remove("--use"), sight = rest.Remove("--sight"),
            pin = rest.Remove("--pin"), pushers = rest.Remove("--pushers"), kite = rest.Remove("--kite"), stay = rest.Remove("--stay");
        var avoid = (Option("--avoid") ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Select(n => string.Join(' ', n.ToLowerInvariant().Split(' ', StringSplitOptions.RemoveEmptyEntries))).Where(n => n.Length > 0).ToList();
        float backTo = float.Parse(Option("--back-off") ?? "0", CultureInfo.InvariantCulture);
        double giveUp = double.Parse(Option("--give-up") ?? "0", CultureInfo.InvariantCulture);
        (float, float)? gains = Option("--gains")?.Split(',') is [var yaw, var pitch]
            ? (float.Parse(yaw, CultureInfo.InvariantCulture), float.Parse(pitch, CultureInfo.InvariantCulture)) : null;
        if (rest.Count < 1) throw new InvalidOperationException("Usage: camera <entity id from 'nearby'> [--hold-left]");
        using var reader = new PlayerReader(ClientExecutable());
        var target = Pick(reader, rest[0], box);
        if ((holdLeft || box || use) && !CameraAim.MayHold(target.Identity.Kind)) throw new InvalidOperationException($"{target.Name} is not an NPC: the mouse buttons are used on NPCs only.");
        string logs = Path.Combine(root, "logs"); Directory.CreateDirectory(logs);
        using var hud = new Hud();
        Travel.FocusGame(reader.Window);
        Console.WriteLine(new CameraWatch(reader, target, pulse, new CameraPlan(holdLeft, now, gains, giveUp, box, Sight: sight, BackTo: backTo, Shots: sight ? Shots(reader) : null, Use: use,
            Pin: pin, Pushers: pushers, Avoid: avoid, Kite: kite, Stay: stay), hud, Path.Combine(logs, $"camera-{DateTime.UtcNow:yyyyMMdd-HHmmss}.jsonl")).Run());
        return 0;
    }
}

/// <summary>The live follow loop. Ends by returning why it stopped, or by throwing (F8, focus, zone change, stuck).</summary>
internal sealed class FollowWalk(PlayerReader reader, NavWorld nav, int sector, WorldEntity target, FollowBand band,
    LiveSteer.Calibration calibration, int pulse, bool run, Hud hud, string logPath,
    IReadOnlyList<(Vector3 Position, int To)> exits, Func<int, string> sectorName, (float Yaw, float Pitch)? heal = null, bool arrive = false, TeamHeal? team = null)
{
    private const int Tick = 33, PulseGap = 16, ReadEveryMs = 150;
    private const double UnreachableSeconds = 15, StallSeconds = 2.5;
    private const int MaxStalls = 3, MaxOffRoutePer20s = 6;
    private const float RouteRanOut = 20, ArriveRunsTo = 30;
    /// <summary>Measured live on 29 Oct.</summary>
    public static readonly LiveSteer.Calibration Typical = new(190, 0.0024f);

    private sealed record Plan(RouteFollower Route, Vector3 Goal, float Miss, double At);

    public string Run()
    {
        using var log = new StreamWriter(logPath) { AutoFlush = true };
        using var input = new SteerInput(reader, pulse, run);
        var clock = Stopwatch.StartNew();
        string title = $"FOLLOW  {target.Name}";
        var origin = reader.ReadSteady();
        var previous = origin;
        var lapse = new ReadLapse();
        double previousAt = 0;
        bool riding = false;   // in a gravity lift: only a sideways jump is a teleport
        var jumps = new PositionJumps();

        void Record(string kind, PlayerSample s, object? detail = null) => log.WriteLine(JsonSerializer.Serialize(new {
            timeUtc = DateTimeOffset.UtcNow, elapsedSeconds = clock.Elapsed.TotalSeconds, kind,
            position = new { s.Position.X, s.Position.Y, s.Position.Z }, forward = new { s.Forward.X, s.Forward.Z },
            walking = input.Walking, detail }));

        // As LiveSteer's guard on an ordinary walk: F8, focus, identity, sector, teleports.
        PlayerSample Guard()
        {
            if (StopRequest.Made()) throw new OperationCanceledException("Stop pressed.");
            reader.RequireForeground();
            if (lapse.Read(reader.ReadSample, clock.Elapsed.TotalSeconds, "Follow stopped.") is not { } s) return previous;
            if (s.Player != origin.Player || s.World != origin.World || s.Physics != origin.Physics)
                throw new InvalidOperationException("You changed zone (the player or world changed). Follow stopped; following through zones is not supported yet.");
            int? now = reader.ReadSectorId(s.World);
            if (now != sector)
                throw new InvalidOperationException($"You changed zone, to {(now is { } n ? sectorName(n) : "a loading screen")}. Follow stopped; following through zones is not supported yet.");
            // Timed from the position's last change: at a few frames a second it stands still, then moves a whole frame's worth.
            double t = clock.Elapsed.TotalSeconds, dt = t - previousAt;
            float jump = riding ? PointNavigation.Distance(s.Position, previous.Position) : Vector3.Distance(s.Position, previous.Position);
            if (jump > 60 + 900 * (float)Math.Min(dt, 2))
            {
                // One jump is the game correcting your position (live: 70 units on stairs, standing still). A route plans on from anywhere.
                if (jumps.TooMany(t)) throw new InvalidOperationException($"Unexpected position jumps ({jump:F0} units in {dt:F2} s, the third in {PositionJumps.WithinSeconds:F0} s). Stopped.");
                Record("jump", s, new { jump, dt });
            }
            if (s.Position != previous.Position) previousAt = t;
            previous = s;
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
        // Vanished near a zone exit: it most likely crossed.
        string? Crossed(Vector3 seenAt) => FollowLogic.NearestExit(seenAt, exits) is { } x
            ? $"{target.Name} crossed the zone line toward {sectorName(x.To)} (last seen {PointNavigation.Distance(seenAt, x.Position):F0} units from that exit). Follow stopped; following through zones is not supported yet."
            : null;
        var watch = new TargetWatch(target, () => reader.ReadEntities().Entities, () => clock.ElapsedMilliseconds, ReadEveryMs, "Follow stopped.", Crossed, arrive && target.Stats?.Dead == true);

        // ---- the route ----
        Plan? plan = null, doorPlan = null;
        double unreachableSince = -1, retryAt = 0;
        // A healer walks to its place beside or behind the fighter (HealerPlace); everyone else to the target itself.
        var place = heal != null && team == null ? new HealerPlace() : null;
        Vector3 goal = target.Position;
        long mobsAt = 0;
        Vector3? mob = null;
        Plan? PlanTo(Vector3 from, Vector3 to)
        {
            var corners = nav.RouteNear(from, to, out bool complete);
            // On the target's floor, not the one under it (gravity lifts join stacked floors).
            if (corners.Count < 2 || !complete || MathF.Abs(corners[^1].Y - to.Y) > 150) return null;
            return new(new RouteFollower(corners), to, PointNavigation.Distance(corners[^1], to), clock.Elapsed.TotalSeconds);
        }
        // A place in a wall or off the floor: the fighter will do.
        Plan? MakePlan(Vector3 from) => PlanTo(from, goal) ?? (place != null ? PlanTo(from, watch.SeenAt) : null);

        try
        {
            var turns = new TurnController(calibration.Gain);
            float lookahead = Steering.Lookahead(calibration.Speed);
            var rider = new LiftRider(Guard, Wait, Turn, input, turns, pulse, (k, at, d) => Record(k, at, d), text => hud.Show(Hud.Cyan, title, text, "F8 stops"));
            var doors = new DoorOpener(nav.Doors);
            var stamina = new SprintGuard();
            int lastPixels = 0;
            var first = Guard();
            Vector3 lastForward = first.Forward;
            goal = watch.SeenAt;
            plan = MakePlan(first.Position);
            float startGap = FollowLogic.Gap(FollowLogic.Straight(first.Position, watch.SeenAt), plan?.Route.Remaining, plan?.Miss ?? 0);
            band.Start(startGap);
            Record("start", first, new { target = target.Name, id = FollowCommand.Id(target), distance = band.Distance, resume = band.Resume, calibration.Speed, calibration.Gain });
            Console.WriteLine($"Following. Stops within {band.Distance:F0} units and sets off again past {band.Resume:F0}. F8 stops.");
            var offRoute = new Queue<double>();
            Vector3 stallFrom = first.Position; double stallMark = 0; int stalls = 0;
            double turningSince = -1;
            bool wasMoving = !band.Moving;
            double castEnds = -1, castFrom = 0;
            var cycle = new CastCycle();
            CastCycle.Cast? casting = null;
            int? inHand = null;
            Vector3 teamGoal = watch.SeenAt;
            float teamStop = 40;
            bool teamMove = false;

            while (true)
            {
                var s = Guard();
                double now = clock.Elapsed.TotalSeconds;
                if (castEnds >= 0 && now >= castEnds)
                {
                    input.HoldLeft(false);
                    castEnds = -1; castFrom = now + CastCycle.BetweenCasts;
                    if (casting != null)
                    {
                        if (team != null && casting.Spell != null) team.Cast(casting.Who!, casting.Spell, now);
                        else cycle.Done(casting, now);
                    }
                    casting = null;
                }
                if (watch.Read() is { } gone) { input.Walk(false); Record("lost", s, new { gone, seenAt = new[] { watch.SeenAt.X, watch.SeenAt.Y, watch.SeenAt.Z } }); hud.Post(Hud.Cyan, title, gone); return gone; }

                goal = watch.SeenAt;
                if (place != null)
                {
                    if (clock.ElapsedMilliseconds >= mobsAt)
                    {
                        mobsAt = clock.ElapsedMilliseconds + 500;
                        var fighter = watch.SeenAt;
                        mob = FollowCommand.ReadSnapshot(reader).Entities.Where(e => SweepTargets.Hunted(e) && !FollowCommand.Dead(e))
                            .Select(e => e.Position).OrderBy(p => PointNavigation.Distance(p, fighter)).Cast<Vector3?>().FirstOrDefault();
                    }
                    place.Observe(now, watch.SeenAt, mob);
                    goal = place.Station(s.Position, watch.SeenAt, band.Distance * .85f);
                }
                TeamHeal.Move? teamPlan = null;
                if (team != null)
                {
                    if (clock.ElapsedMilliseconds >= mobsAt)
                    {
                        mobsAt = clock.ElapsedMilliseconds + 500;
                        var around = FollowCommand.ReadSnapshot(reader).Entities;
                        team.Observe(around);
                        var centre = team.Positions.Count == 0 ? watch.SeenAt : team.Positions.Aggregate(Vector3.Zero, (a, b) => a + b) / team.Positions.Count;
                        mob = around.Where(e => SweepTargets.Hunted(e) && !FollowCommand.Dead(e)).Select(e => e.Position)
                            .OrderBy(p => PointNavigation.Distance(p, centre)).Cast<Vector3?>().FirstOrDefault();
                    }
                    team.ReadPanel(now, wasMoving ? 5 : 1.5);
                    teamPlan = casting != null ? new TeamHeal.Move(null, null, null, 0) : team.Decide(now, s.Position, mob, band.Distance);
                    if (teamPlan.Goal is { } g) { teamGoal = g; teamStop = teamPlan.Stop; }
                    goal = teamGoal;
                }
                float straight = FollowLogic.Straight(s.Position, goal);
                float off = plan?.Route.Update(s.Position) ?? 0;
                float gap = FollowLogic.Gap(straight, plan?.Route.Remaining, plan?.Miss ?? 0);
                var why = FollowLogic.Decide(plan != null, plan == null ? 0 : PointNavigation.Distance(plan.Goal, goal), gap, (place != null ? wasMoving : band.Moving) ? off : 0,
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
                        if (unreachableSince < 0) { unreachableSince = now; Record("unreachable", s, new { seenAt = new[] { watch.SeenAt.X, watch.SeenAt.Y, watch.SeenAt.Z } }); }
                    }
                }

                // The hunt needs the target itself in reach, unless the route has run out; a route's end can be short of an NPC off the mesh.
                if (arrive && gap <= band.Distance && (straight <= band.Distance || plan == null || plan.Route.Remaining < RouteRanOut))
                {
                    input.Walk(false);
                    Record("arrived", s, new { gap, straight });
                    return $"Reached {target.Name}, {straight:F0} units away.";
                }
                bool moving;
                if (team != null)
                {
                    teamMove = teamPlan!.Goal != null && (teamMove ? straight > teamStop : straight > teamStop + 50);
                    moving = teamMove;
                }
                else moving = arrive || (place != null ? place.Update(s.Position, watch.SeenAt, band.Distance, band.Resume) : band.Update(gap));
                // A blocking step ahead (a lift, a door) must not start with the cast's button down.
                if (moving && castEnds >= 0) { input.HoldLeft(false); castEnds = -1; casting = null; }
                if (moving != wasMoving)
                {
                    doors.Reset();
                    if (moving && unreachableSince >= 0) unreachableSince = now;   // Time spent standing is not time spent looking for a way.
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
                    // In reach of the fighter: the aim of the camera follow, up at the empty sky for a cast on itself, and the cycle of casts.
                    // A camera reading that fails for a moment waits for the next tick: on a slow machine it ended the follow.
                    if (!moving && heal is { } gains && reader.ReadCamera(s) is { } view)
                    {
                        CastCycle.Cast? cast = casting;
                        if (cast == null && now >= castFrom)
                            cast = team == null ? cycle.Due(now)
                                : teamPlan?.Due is { } d && teamPlan.Goal == null ? new CastCycle.Cast(d.Spell.Slot, d.Who != TeamRounds.Self, d.Spell.Every) { Who = d.Who, Spell = d.Spell } : null;
                        Vector3 aimAt = team != null && cast?.Who is { Length: > 0 } ally && team.Position(ally) is { } allyAt ? allyAt : watch.SeenAt;
                        if (cast != null && castEnds < 0 && inHand != cast.Slot && now >= castFrom)
                        {
                            inHand = CastCycle.KeyFor(cast.Slot, inHand);
                            input.Slot(inHand.Value);
                            castFrom = now + CastCycle.SlotWait;
                            Record("slot", s, new { slot = inHand });
                        }
                        float yawError = PointNavigation.SignedAngle(CameraAim.Facing(view.Yaw), aimAt - s.Position);
                        float pitch = cast is { OnFighter: false } ? CastCycle.SkyPitch : CameraAim.PitchTo(s.Position, aimAt + new Vector3(0, CameraAim.BodyMiddle, 0));
                        float pitchError = pitch - view.Pitch;
                        input.LookPulse((int)MathF.Round(CameraAim.Turn(yawError) / gains.Yaw), (int)MathF.Round(CameraAim.Turn(pitchError) / gains.Pitch));
                        if (cast != null && castEnds < 0 && inHand == cast.Slot && now >= castFrom && CameraAim.OnTarget(yawError, pitchError))
                        {
                            input.HoldLeft(true);
                            casting = cast;
                            castEnds = now + CameraAim.CastHoldSeconds;
                            Record("cast", s, new { cast.Slot, cast.OnFighter, yawError, pitchError, gap });
                            Console.WriteLine($"Slot {cast.Slot} on {(cast.Who is { Length: > 0 } w ? w : cast.OnFighter ? target.Name : "yourself")}.");
                        }
                    }
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
                    watch.Read();
                    plan = MakePlan(s.Position);
                    Record("replan", s, new { why = "lift", corners = plan?.Route.Corners.Count ?? 0 });
                    stallFrom = s.Position; stallMark = clock.Elapsed.TotalSeconds; stalls = 0; turningSince = -1; lastPixels = 0;
                    lastForward = s.Forward;
                    continue;
                }
                // Walking: the same pure pursuit and capped turning as LiveSteer.
                bool rested = stamina.MayRun(now, s.Position, input.Sprinting);
                input.Sprint(rested && gap - band.Distance > (arrive ? ArriveRunsTo : 120));
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
                Record("steer", s, new { aim = new[] { aim.X, aim.Y, aim.Z }, decision.Angle, pixels = sent, off, gap, target = new[] { watch.SeenAt.X, watch.SeenAt.Z } });
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
                // Judged on this route's own progress: the gap also stays flat behind a target walking at your speed.
                if (!ReferenceEquals(plan, doorPlan)) { doors.Reset(); doorPlan = plan; }
                if (doors.Blocking(s.Position, plan.Route.Remaining, (long)(now * 1000)) is { } door)
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
                        throw new LiveSteer.BlockedAt($"Blocked {gap:F0} units from {target.Name}: the navmesh says walkable, the game disagrees (door, prop or step?). Follow stopped.", s.Position, s.Forward);
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
