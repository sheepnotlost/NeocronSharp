using System.Numerics;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// Drives a virtual character through the same follower, steering and turn
/// controller the live session uses, with walls modelled by sliding along the
/// navmesh surface. The camera model follows the 29 Oct live logs: a ~48 ms
/// control tick, turns that land two ticks late, and a real mouse gain ~30%
/// higher than the calibration step measures.
/// </summary>
internal static class Simulator
{
    public const float OffRouteLimit = 48, FinalRadius = 24, ArrivalTolerance = 6;
    /// <summary>Within this height of a point counts as on its floor (lifts join floors stacked over each other).</summary>
    public const float SameFloor = 100;
    public const float Tick = 0.048f;

    public sealed record Outcome(bool Arrived, string Reason, float Seconds, float RouteLength, float MaxOffRoute, int Replans,
        int Reversals, float MeanAngleDegrees, int Lifts = 0);

    public static Outcome Run(NavWorld nav, Vector3 from, Vector3 to, float speed, float trueGain, float gainBias, int maxPixelsPerTick, Random random)
    {
        var route = nav.Route(from, to, out bool complete);
        if (route.Count < 2 || !complete) return new(false, "no route", 0, 0, 0, 0, 0, 0);
        var follower = new RouteFollower(route);
        var turns = new TurnController(trueGain / gainBias);   // what calibration would have measured
        float length = follower.Total, limit = length / speed * 2 + 20, lookahead = Steering.Lookahead(speed);
        Vector3 pos = route[0], end = route[^1];
        float yaw = (float)(random.NextDouble() * Math.Tau), maxOff = 0, bestProgress = 0, stallSince = 0;
        var pending = new Queue<int>(new[] { 0, 0 });   // mouse input reaches the heading two ticks later
        int replans = 0, reversals = 0, walkingTicks = 0, lastPixels = 0, lifts = 0; float lastAngle = 0, angleSum = 0, lastYaw = yaw;
        for (float t = 0; t < limit; t += Tick)
        {
            // Turns sent two ticks ago land now, with a little noise on the real gain.
            yaw += pending.Dequeue() * trueGain * (0.9f + 0.2f * (float)random.NextDouble());
            turns.Observe(lastPixels, Wrap(yaw - lastYaw)); lastYaw = yaw;
            Vector3 forward = new(MathF.Cos(yaw), 0, MathF.Sin(yaw));
            float dist = PointNavigation.Distance(pos, end);
            if (dist <= ArrivalTolerance && MathF.Abs(pos.Y - end.Y) < SameFloor) return Done(true, "arrived", t);
            float off = follower.Update(pos); maxOff = Math.Max(maxOff, off);
            // A gravity lift: at its start the ride takes the character to its end (live, LiftRider does this).
            var lift = Lifts.Ahead(nav, follower);
            if (lift is { } l && Lifts.AtStart(l.Link, pos))
            {
                pos = l.Link.End; lifts++;
                t += MathF.Abs(l.Link.Rise) / 150 + 2;
                route = nav.Route(pos, to, out complete);
                if (route.Count < 2 || !complete) return Done(false, "no route from the lift's landing", t);
                follower = new(route); end = route[^1]; bestProgress = 0; stallSince = t;
                limit = Math.Max(limit, t + follower.Total / speed * 2 + 20);
                pending.Enqueue(lastPixels = 0);
                continue;
            }
            if (off > OffRouteLimit)
            {
                if (++replans > 6) return Done(false, "too many replans", t);
                route = nav.Route(pos, to, out complete);
                if (route.Count < 2 || !complete) return Done(false, "replan failed", t);
                follower = new(route); bestProgress = 0; stallSince = t;
                pending.Enqueue(lastPixels = 0);
                continue;
            }
            Vector3 aim = dist <= FinalRadius && MathF.Abs(pos.Y - end.Y) < SameFloor ? end
                : lift is { } next && next.Arc - follower.Progress < lookahead ? next.Link.Start : follower.Aim(pos, lookahead, nav.Clear);
            var decision = Steering.Decide(pos, forward, aim);
            int pixels = turns.Pixels(decision.TurnRadians, maxPixelsPerTick);
            pending.Enqueue(lastPixels = pixels);
            if (decision.Walk)
            {
                walkingTicks++; angleSum += Math.Abs(decision.Angle);
                if (lastAngle * decision.Angle < 0 && Math.Abs(lastAngle) > 0.035f && Math.Abs(decision.Angle) > 0.035f) reversals++;
                lastAngle = decision.Angle;
                float step = dist <= FinalRadius && MathF.Abs(pos.Y - end.Y) < SameFloor ? Math.Min(speed * Tick, Math.Max(1, dist - 2)) : speed * Tick;
                pos = nav.Slide(pos, pos + forward * step);
            }
            if (follower.Progress > bestProgress + 2 || !decision.Walk) { bestProgress = Math.Max(bestProgress, follower.Progress); stallSince = t; }
            else if (t - stallSince > 2) return Done(false, "stalled", t);
        }
        return Done(false, "timeout", limit);

        Outcome Done(bool arrived, string reason, float t) =>
            new(arrived, reason, t, length, maxOff, replans, reversals, walkingTicks == 0 ? 0 : angleSum / walkingTicks * 180 / MathF.PI, lifts);
    }

    private static float Wrap(float a) => MathF.IEEERemainder(a, MathF.Tau);
}
