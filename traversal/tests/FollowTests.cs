using System.Numerics;
using NavmeshPrototype;
using NeocronSharp.Core;

/// <summary>Offline tests for following an actor: the distance band, the gap and the replan decision (<see cref="FollowLogic"/>).</summary>
internal static class FollowTests
{
    private static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }

    private static WorldEntity Actor(string name, Vector3 at, EntityKind kind = EntityKind.Player, PlayerDetails? player = null) =>
        new(new EntityIdentity(1, 2, 3, 4, 0, kind), name, at, "test", Player: player);

    public static void Run(Action<string, Action> test)
    {
        test("Position jumps: one or two are the game correcting you, a third close by is not", () =>
        {
            var jumps = new PositionJumps();
            Check(!jumps.TooMany(0) && !jumps.TooMany(4), "two are allowed");
            Check(jumps.TooMany(8), "the third within 10 s stops");
            var spread = new PositionJumps();
            Check(!spread.TooMany(0) && !spread.TooMany(8) && !spread.TooMany(16) && !spread.TooMany(24), "far apart they never add up");
        });

        test("Camera aim: small steady corrections near the target, a quick swing when far off, nothing on it", () =>
        {
            Check(CameraAim.Turn(0.005f) == 0 && CameraAim.Turn(-0.005f) == 0, "within the deadband nothing moves");
            Check(MathF.Abs(CameraAim.Turn(0.1f) - 0.03f) < 1e-5f, "near it, a share of the error");
            Check(CameraAim.Turn(0.34f) == CameraAim.MaxNearTurn && CameraAim.Turn(-0.34f) == -CameraAim.MaxNearTurn, "capped near it");
            Check(CameraAim.Turn(1f) == CameraAim.FarShare && CameraAim.Turn(-1f) == -CameraAim.FarShare, "far off, a big share");
            Check(MathF.Abs(CameraAim.Facing(MathF.PI / 2).Z - 1) < 1e-5f && MathF.Abs(PointNavigation.SignedAngle(CameraAim.Facing(0), CameraAim.Facing(0.5f)) - 0.5f) < 1e-5f, "a heading as a flat direction");
        });

        test("Camera aim: the angle above level, from the eye to the target", () =>
        {
            var eye = new Vector3(0, -CameraAim.EyeHeight, 0);
            Check(MathF.Abs(CameraAim.PitchTo(eye, new Vector3(100, 0, 0))) < 1e-5f, "same height as the eye: level");
            Check(MathF.Abs(CameraAim.PitchTo(eye, new Vector3(200, 100, 0)) - MathF.Atan(0.5f)) < 1e-5f, "half as far up as along");
            Check(CameraAim.PitchTo(eye, new Vector3(10, 900, 0)) == CameraAim.MaxPitch, "no higher than the game lets you look");
            Check(CameraAim.PitchTo(default, new Vector3(10, -900, 0)) == -CameraAim.MaxPitch, "and no lower");
            Check(CameraAim.PitchTo(default, new Vector3(100, 0, 0)) < 0, "an actor on your own floor is below your eye");
            Check(MathF.Abs(CameraAim.PitchTo(eye, eye) ) < 1.6f && float.IsFinite(CameraAim.PitchTo(eye, eye)), "standing on it stays finite");
        });

        test("Target watch: follows the actor, and rides out misses and a registry caught mid-update", () =>
        {
            long now = 0;
            var buddy = Actor("Buddy", new Vector3(1, 0, 1));
            IReadOnlyList<WorldEntity> seen = [buddy with { Position = new Vector3(50, 0, 60) }];
            bool torn = false;
            var watch = new TargetWatch(buddy, () => torn ? throw new InvalidOperationException("mid-update") : seen, () => now, 100, "Stopped.");
            Check(watch.Read() == null && watch.SeenAt.X == 50, "its new position is read");
            seen = [buddy with { Position = new Vector3(70, 0, 60) }];
            now = 50;
            Check(watch.Read() == null && watch.SeenAt.X == 50, "not read again before the interval");
            now = 100;
            torn = true;
            Check(watch.Read() == null, "a torn read is not the end");
            torn = false;
            seen = [];
            for (int i = 0; i < 3; i++) { now += 100; Check(watch.Read() == null, "three misses are not the end"); }
            seen = [buddy];
            now += 100;
            Check(watch.Read() == null, "back again: the misses start over");
            seen = [];
            for (int i = 0; i < 3; i++) { now += 100; watch.Read(); }
            now += 100;
            Check(watch.Read() == "Buddy is gone (out of range, logged off, despawned, or went through a door). Stopped.", "the fourth miss in a row ends it");
        });

        test("Target watch: another actor at a reused address is not the target, a nameless read is", () =>
        {
            long now = 0;
            var buddy = Actor("Buddy", default);
            IReadOnlyList<WorldEntity> seen = [Actor("?", new Vector3(9, 0, 9), EntityKind.UnclassifiedCharacter)];
            var watch = new TargetWatch(buddy, () => seen, () => now, 100, "Stopped.", at => $"crossed from {at.X}");
            Check(watch.Read() == null && watch.SeenAt.X == 9, "a name that failed to read is still them");
            seen = [Actor("Stranger", new Vector3(500, 0, 500))];
            for (int i = 0; i < 3; i++) { now += 100; Check(watch.Read() == null && watch.SeenAt.X == 9, "a stranger never moves the aim"); }
            now += 100;
            Check(watch.Read() == "crossed from 9", "and counts as gone, with the zone-exit reason when there is one");
        });

        test("Follow band: stops inside the distance and only sets off again past the resume line", () =>
        {
            var band = new FollowBand(150);
            Check(band.Distance == 150 && band.Resume == 200, $"150 stops, 200 resumes (got {band.Distance}, {band.Resume})");
            Check(band.Start(400), "a target 400 away: walk");
            Check(band.Update(300) && band.Update(151), "still walking until within the distance");
            Check(!band.Update(150), "stops at 150");
            Check(!band.Update(170) && !band.Update(200), "a target shuffling inside the band does not restart the walk");
            Check(band.Update(201), "resumes once past 200");
            Check(band.Update(180), "and keeps walking until back within 150");
            Check(!new FollowBand(150).Start(120), "starting already close: wait");
            Check(!new FollowBand(150).Start(150), "starting exactly at the distance: wait");
        });

        test("Follow band: the distance is clamped and the resume margin grows with it", () =>
        {
            Check(new FollowBand(5).Distance == FollowBand.MinDistance, "too close is raised to the minimum");
            Check(new FollowBand(99999).Distance == FollowBand.MaxDistance, "too far is capped");
            Check(new FollowBand(float.NaN).Distance == FollowBand.DefaultDistance, "nonsense falls back to the default");
            Check(new FollowBand(60).Resume == 110, "at least 50 units of margin");
            Check(new FollowBand(600).Resume == 800, "a third of the distance when that is more");
        });

        test("Follow gap: route length, less what no route can cover", () =>
        {
            Check(FollowLogic.Gap(300, null, 0) == 300, "no route: the straight distance");
            Check(FollowLogic.Gap(100, 400, 0) == 400, "a wall between: the walk round it counts");
            Check(FollowLogic.Gap(180, 2, 180) == 2, "target behind a counter 180 off the floor, walker at the route's end: arrived");
            Check(FollowLogic.Gap(300, 50, 100) == 200, "straight distance less the miss when the route is out of date");
            Check(FollowLogic.Gap(50, 10, 200) == 10, "never below zero from the miss");
        });

        test("Follow replan: first plan, off route, target moved, route ending, refresh", () =>
        {
            Check(FollowLogic.Decide(false, 0, 300, 0, 0, 0) == FollowReplan.First, "no route yet: plan one");
            Check(FollowLogic.Decide(true, 0, 300, Simulator.OffRouteLimit + 1, 200, 0.1) == FollowReplan.OffRoute, "off the route: replan at once");
            Check(FollowLogic.Decide(true, 200, 300, 0, 200, 0.2) == FollowReplan.None, "target moved, but the route is brand new: wait a moment");
            Check(FollowLogic.Decide(true, 100, 300, 0, 200, 0.5) == FollowReplan.TargetMoved, "target moved more than a quarter of the gap (75)");
            Check(FollowLogic.Decide(true, 60, 300, 0, 200, 0.5) == FollowReplan.None, "a smaller move keeps the route");
            Check(FollowLogic.Decide(true, 35, 120, 0, 200, 0.5) == FollowReplan.TargetMoved, "close up the threshold bottoms out at 32");
            Check(FollowLogic.Decide(true, 20, 300, 0, 30, 0.5) == FollowReplan.NearRouteEnd, "about to run out of route while the target is elsewhere");
            Check(FollowLogic.Decide(true, 20, 300, 0, 200, 3.5) == FollowReplan.Refresh, "an old route is renewed when the target moved at all");
            Check(FollowLogic.Decide(true, FollowLogic.Jitter, 300, 0, 30, 10) == FollowReplan.None, "position jitter alone never replans");
            Check(FollowLogic.MoveThreshold(10000) == 250, "far away the threshold is capped at 250");
        });

        test("A target that vanished next to an exit is reported as crossing it", () =>
        {
            var exits = new[] { (new Vector3(1000, 0, 0), 2), (new Vector3(0, 0, 3000), 101) };
            Check(FollowLogic.NearestExit(new(800, 0, 100), exits) is { To: 2 }, "last seen 224 from the exit to sector 2");
            Check(FollowLogic.NearestExit(new(0, 0, 0), exits) is null, "far from every exit: just gone");
        });
    }
}
