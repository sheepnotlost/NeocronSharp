using System.Numerics;
using NavmeshPrototype;

/// <summary>Offline tests for following an actor: the distance band, the gap and the replan decision (<see cref="FollowLogic"/>).</summary>
internal static class FollowTests
{
    private static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }

    public static void Run(Action<string, Action> test)
    {
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
