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

        test("Heal follow: keeps its distance, facing the target, and only heals your other client", () =>
        {
            var hold = new HoldDistance(100);
            Check(hold.Keys(120, 0) == (1, false), "too far: walks");
            Check(hold.Keys(110, 0) == (1, false), "keeps walking until nearly there");
            Check(hold.Keys(103, 0) == (0, false), "stops when there");
            Check(hold.Keys(110, 0) == (0, false), "and does not start again for a small drift");
            Check(hold.Keys(70, 0) == (0, false), "a target coming closer is left to come");
            Check(hold.Keys(30, 0) == (-1, false), "only right on top of you does it back off");
            Check(hold.Keys(300, 1) == (0, false), "does not walk until it faces the target");
            Check(hold.Keys(300, 0) == (1, false), "walks after the target without burning stamina");
            Check(hold.Keys(400, 0) == (1, true), "sprints only to catch up from far off");
            Check(hold.InReach(150) && !hold.InReach(200), "does not cast out of reach");
            Check(new HoldDistance(5).Distance == HoldDistance.MinDistance && new HoldDistance(9000).Distance == HoldDistance.MaxDistance, "the distance is kept sensible");
            var at = new Vector3(100, 0, 100);
            Check(HoldDistance.SameCharacter(at, 7, at + new Vector3(30, 0, 0), 7), "your other client's character");
            Check(!HoldDistance.SameCharacter(at, 7, at + new Vector3(300, 0, 0), 7), "someone else, elsewhere");
            Check(!HoldDistance.SameCharacter(at, 8, at, 7) && !HoldDistance.SameCharacter(at, null, at, null), "another sector, or an unknown one");
            Check(MathF.Abs(CameraAim.Between(3.1f, -3.1f) - (2 * MathF.PI - 6.2f)) < 0.001f, "the short way across the wrap");
        });

        test("Heal from a VM: only the fighter named on the tab", () =>
        {
            Check(CameraAim.IsFighter(" scooter\n", "Scooter", EntityKind.Player), "the fighter, however it was typed");
            Check(!CameraAim.IsFighter("Scooter", "Adam", EntityKind.Player), "any other player");
            Check(!CameraAim.IsFighter(null, "Scooter", EntityKind.Player) && !CameraAim.IsFighter("", "Scooter", EntityKind.Player), "nobody named");
            Check(!CameraAim.IsFighter("Scooter", "Scooter", EntityKind.Npc), "an NPC of that name");
        });

        test("Camera aim: the left button goes down on the target, and only ever on an NPC", () =>
        {
            Check(CameraAim.OnTarget(0.01f, -0.01f), "within 2 degrees both ways");
            Check(!CameraAim.OnTarget(0.1f, 0) && !CameraAim.OnTarget(0, -0.1f), "either axis off is not on the target");
            Check(CameraAim.MayHold(EntityKind.Npc), "NPCs may be held on");
            Check(!CameraAim.MayHold(EntityKind.Player) && !CameraAim.MayHold(EntityKind.UnclassifiedCharacter), "anything else may not");
        });

        test("Camera aim: small steady corrections near the target, a quick swing when far off, nothing on it", () =>
        {
            Check(CameraAim.Turn(0.005f) == 0 && CameraAim.Turn(-0.005f) == 0, "within the deadband nothing moves");
            Check(MathF.Abs(CameraAim.Turn(0.1f) - 0.03f) < 1e-5f, "near it, a share of the error");
            Check(CameraAim.Turn(0.34f) == CameraAim.MaxNearTurn && CameraAim.Turn(-0.34f) == -CameraAim.MaxNearTurn, "capped near it");
            Check(CameraAim.Turn(1f) == CameraAim.FarShare && CameraAim.Turn(-1f) == -CameraAim.FarShare, "far off, a big share");
            Check(CameraAim.Turn(0.005f, 6000) != 0 && CameraAim.Turn(0.005f, 1000) == 0, "the deadband narrows at long range");
            Check(CameraAim.Turn(0.002f, 6000) == 0, "but stays over a pixel, or the aim would shake");
            var cactus = new SectorObjects.Prop("cactus3", new Vector3(500, 0, 0),
                new[] { new Vector2(470, -30), new Vector2(530, -30), new Vector2(530, 30), new Vector2(470, 30) }, 0, 200);
            var shots = new ShotLine(new[] { cactus });
            var eye = new Vector3(0, 100, 0);
            Check(shots.Blocker(eye, new Vector3(1000, 100, 0)) == "cactus3", "a cactus on the line blocks it");
            Check(shots.Blocker(eye, new Vector3(1000, 100, 100)) == null, "one to the side does not");
            Check(shots.Blocker(eye, new Vector3(1000, 900, 0)) == null, "nor does the line passing over it");
            Check(shots.Blocker(eye, new Vector3(300, 100, 0)) == null, "nor one beyond the target");
            Check(shots.Blocker(new Vector3(1000, 100, 0), new Vector3(2000, 100, 0)) == null, "nor one behind you");
            float? side = shots.ClearSide(eye, new Vector3(1000, 100, 0));
            Check(side is { } clear && shots.Blocker(eye + new Vector3(0, 0, -clear), new Vector3(1000, 100, 0)) == null, "a step to the right, looking along +x, is towards -z, and clears it");
            Check(MathF.Abs(side ?? 999) <= 160, "the shortest step does: half way to the target it moves the line half as far");
            var hedge = new ShotLine(Enumerable.Range(-9, 19).Select(i => cactus with { Position = new Vector3(100, 0, i * 50) }));
            Check(hedge.ClearSide(eye, new Vector3(120, 100, 0)) == null, "a wall of them can't be stepped round");

            var sight = new SightWatch();
            Check(!sight.Seen(0), "nothing targeted yet");
            sight.Update(1, true); sight.Update(1.5, false);
            Check(sight.Seen(1.9) && !sight.Showing, "a gap in the target bar is not losing the target");
            Check(!sight.Seen(2.1), "a second without it is");
            Check(sight.ClearToFire(1.3) && !sight.ClearToFire(1.5), "but firing stops much sooner");

            var back = new BackOff(9000);
            back.Update(0, false, false, 1000, default);
            Check(back.Now == BackOff.Phase.Waiting, "no backing until the game targets the mob");
            back.Update(1, true, true, 1000, default);
            Check(back.Now == BackOff.Phase.Backing, "then back away");
            back.Update(2.5, true, true, 1030, new Vector3(30, 0, 0));
            back.Update(5, true, true, 1100, new Vector3(100, 0, 0));
            Check(back.Now == BackOff.Phase.Backing, "still moving, still backing");
            back.Update(6, false, false, 1130, new Vector3(130, 0, 0));
            Check(back.Now == BackOff.Phase.Returning && back.Limit == 1130, "losing it is the target limit");
            back.Update(6.5, false, true, 1120, new Vector3(120, 0, 0));
            Check(back.Now == BackOff.Phase.Done, "forward until it is back");
            var noticed = new BackOff(9000);
            noticed.Update(0, true, true, 1000, default);
            noticed.Update(1, true, true, 900, default);
            Check(noticed.Now == BackOff.Phase.Done && noticed.Limit == null, "a mob coming at you ends the backing");
            var stuck = new BackOff(9000);
            stuck.Update(0, true, true, 1000, default);
            stuck.Update(4, true, true, 1000, default);
            Check(stuck.Now == BackOff.Phase.Done, "so does backing into something");
            var late = new BackOff(9000);
            late.Update(0, true, true, 1000, default);
            late.Update(2, true, true, 1000, new Vector3(60, 0, 0));
            late.Update(181, true, true, 3000, new Vector3(9000, 0, 0));
            Check(late.Now == BackOff.Phase.Done, "and so does the time limit");
            Check(new BackOff(0).Now == BackOff.Phase.Done, "only when asked for");
            var safe = new BackOff(2500);
            safe.Update(0, true, true, 2600, default);
            Check(safe.Now == BackOff.Phase.Done, "a mob already far enough off needs none");
            var near = new BackOff(2500);
            near.Update(0, true, true, 2400, default);
            near.Update(1, true, true, 2430, new Vector3(30, 0, 0));
            Check(near.Now == BackOff.Phase.Backing, "a nearer one does");
            near.Update(4, true, true, 2510, new Vector3(110, 0, 0));
            Check(near.Now == BackOff.Phase.Done && near.Limit == null, "only as far as the safe distance");

            var cycle = new CastCycle();
            var order = new List<(int, bool)>();
            for (var c = cycle.Due(0); c != null; c = cycle.Due(0)) { order.Add((c.Slot, c.OnFighter)); cycle.Done(c, 0); }
            Check(order.SequenceEqual(new[] { (1, true), (1, false), (2, true), (3, true), (2, false), (3, false) }), "every spell on both people, heals first");
            Check(cycle.Due(29) == null, "then nothing for 30 s");
            var heal = cycle.Due(30);
            Check(heal is { Slot: 1, OnFighter: true }, "the heal comes back at 30 s");
            cycle.Done(heal!, 30);
            var selfHeal = cycle.Due(30)!;
            Check(selfHeal is { Slot: 1, OnFighter: false }, "on both");
            cycle.Done(selfHeal, 30);
            Check(cycle.Due(119) == null || cycle.Due(119)!.Slot == 1, "shields wait");
            Check(CastCycle.KeyFor(1, null) == 2 && CastCycle.KeyFor(2, null) == 1, "with nothing known, another slot first");
            Check(CastCycle.KeyFor(1, 2) == 1, "then the slot itself");

            byte[] Picture(Func<int, (byte B, byte G, byte R)> colour, int width, int height)
            {
                var bytes = new byte[width * height * 4];
                for (int i = 0; i < width * height; i++) { var c = colour(i % width); bytes[i * 4] = c.B; bytes[i * 4 + 1] = c.G; bytes[i * 4 + 2] = c.R; }
                return bytes;
            }
            Check(TargetBar.Looks(Picture(_ => (28, 45, 188), 100, 10), 100, 10), "the red bar is seen");
            Check(TargetBar.Looks(Picture(x => x < 74 ? ((byte)10, (byte)10, (byte)10) : ((byte)72, (byte)210, (byte)134), 100, 10), 100, 10), "so is its green end once the red has drained");
            Check(!TargetBar.Looks(Picture(_ => (171, 171, 171), 100, 10), 100, 10), "plain sky is not");

            Check(CameraAim.Pixels(0.0002f, -0.0014f) == -1 && CameraAim.Pixels(0.01f, 0.002f) == 5 && CameraAim.Pixels(0, 0.002f) == 0, "a turn is at least a pixel");
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

        test("Sprint: rests when a run goes slow, and runs again after", () =>
        {
            var guard = new SprintGuard();
            Vector3 At(float x) => new(x, 0, 0);
            Check(guard.MayRun(0, At(0), true), "starts running");
            Check(guard.MayRun(1, At(300), true), "300 units/s is a run");
            Check(guard.MayRun(1.5, At(450), true), "still inside the window");
            Check(!guard.MayRun(2, At(335), true), "35 units/s means stamina is out");
            Check(!guard.MayRun(2.1, At(340), false), "rests");
            Check(!guard.MayRun(16.9, At(2000), false), "for the whole rest");
            Check(guard.MayRun(17.1, At(2100), false), "then may run again");
            var turning = new SprintGuard();
            turning.MayRun(0, At(0), true);
            Check(turning.MayRun(0.5, At(10), false) && turning.MayRun(1.1, At(10), true) && turning.MayRun(1.2, At(10), true), "stopping to turn is not a crawl");
            var lift = new SprintGuard();
            lift.MayRun(0, At(0), true);
            Check(lift.MayRun(10, At(0), true), "a lift ride between readings is not a crawl");
        });

        test("Target watch: an NPC is never swapped for an unnamed character at its address", () =>
        {
            long now = 0;
            var rat = Actor("Rat", new Vector3(5, 0, 5), EntityKind.Npc);
            IReadOnlyList<WorldEntity> seen = [rat with { Identity = rat.Identity with { Kind = EntityKind.UnclassifiedCharacter }, Name = "?", Position = new Vector3(900, 0, 900) }];
            var watch = new TargetWatch(rat, () => seen, () => now, 100, "Stopped.");
            for (int i = 0; i < 3; i++) { Check(watch.Read() == null && watch.SeenAt.X == 5, "the aim stays where it was"); now += 100; }
            Check(watch.Read() != null, "and it counts as gone");
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
