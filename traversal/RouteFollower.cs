using System.Numerics;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>Tracks how far along a corner path the player is and where to aim next (pure pursuit).</summary>
internal sealed class RouteFollower
{
    public IReadOnlyList<Vector3> Corners { get; }
    public float Total { get; }
    public float Progress { get; private set; }
    private readonly float[] _at; // arc length at each corner

    public RouteFollower(IReadOnlyList<Vector3> corners)
    {
        if (corners.Count < 2) throw new ArgumentException("A route needs two corners.");
        Corners = corners; _at = new float[corners.Count];
        for (int i = 1; i < corners.Count; i++) _at[i] = _at[i - 1] + PointNavigation.Distance(corners[i - 1], corners[i]);
        Total = _at[^1];
    }

    public float Remaining => Total - Progress;

    /// <summary>The route's length (on the flat) up to corner <paramref name="index"/>.</summary>
    public float ArcAt(int index) => _at[Math.Clamp(index, 0, _at.Length - 1)];

    /// <summary>The first corner still ahead of the current progress.</summary>
    public Vector3 NextCorner
    {
        get { int next = Array.FindIndex(_at, a => a > Progress + 1); return next < 0 ? Corners[^1] : Corners[next]; }
    }

    /// <summary>Advance progress to the player's projection; returns the planar distance off the route.</summary>
    public float Update(Vector3 position)
    {
        float best = float.MaxValue, bestAt = Progress;
        // Only look a little behind and a bounded way ahead so a route that
        // doubles back past itself cannot make progress jump.
        for (int i = 0; i < Corners.Count - 1; i++)
        {
            if (_at[i + 1] < Progress - 20 || _at[i] > Progress + 250) continue;
            Vector2 a = new(Corners[i].X, Corners[i].Z), b = new(Corners[i + 1].X, Corners[i + 1].Z), p = new(position.X, position.Z);
            Vector2 ab = b - a; float len2 = ab.LengthSquared();
            float t = len2 < 1e-4f ? 0 : Math.Clamp(Vector2.Dot(p - a, ab) / len2, 0, 1);
            float d = Vector2.Distance(p, a + ab * t);
            if (d < best) { best = d; bestAt = _at[i] + t * (_at[i + 1] - _at[i]); }
        }
        Progress = Math.Max(Progress, bestAt);
        return best;
    }

    public Vector3 PointAt(float arc)
    {
        arc = Math.Clamp(arc, 0, Total);
        int i = Array.FindLastIndex(_at, a => a <= arc); if (i >= Corners.Count - 1) return Corners[^1];
        float span = _at[i + 1] - _at[i];
        return span < 1e-4f ? Corners[i] : Vector3.Lerp(Corners[i], Corners[i + 1], (arc - _at[i]) / span);
    }

    /// <summary>
    /// The farthest aim point up to <paramref name="lookahead"/> ahead that a straight
    /// walk can reach (per <paramref name="clear"/>); falls back to the next corner.
    /// </summary>
    public Vector3 Aim(Vector3 position, float lookahead, Func<Vector3, Vector3, bool> clear)
    {
        for (float ahead = lookahead; ahead > 8; ahead *= 0.6f)
        {
            var candidate = PointAt(Progress + ahead);
            if (clear(position, candidate)) return candidate;
        }
        int next = Array.FindIndex(_at, a => a > Progress + 1);
        return next < 0 ? Corners[^1] : Corners[next];
    }
}

/// <summary>One steering choice: whether to hold forward and how far to turn.</summary>
internal readonly record struct SteerDecision(bool Walk, float TurnRadians, float Angle);

internal static class Steering
{
    public const float TurnInPlaceAbove = 0.6f;   // ~34°: stop and face the aim first
    public const float Deadband = 0.03f;
    // While moving, correct only part of the error each tick and cap it: the game
    // shows a turn a tick or two late, so a bigger share keeps overshooting (sway).
    public const float WalkingShare = 0.3f, MaxWalkingTurn = 0.08f;

    /// <summary>How far ahead to aim: further at higher speed, which also smooths the path.</summary>
    public static float Lookahead(float speed) => Math.Clamp(speed * 0.3f, 40, 100);

    public static SteerDecision Decide(Vector3 position, Vector3 forward, Vector3 aim)
    {
        float angle = PointNavigation.SignedAngle(forward, aim - position);
        if (Math.Abs(angle) > TurnInPlaceAbove) return new(false, angle * 0.8f, angle);
        float turn = Math.Abs(angle) < Deadband ? 0 : Math.Clamp(angle * WalkingShare, -MaxWalkingTurn, MaxWalkingTurn);
        return new(true, turn, angle);
    }
}

/// <summary>
/// Converts a wanted turn into mouse pixels, and keeps re-measuring how far the
/// camera really turns per pixel (Windows pointer acceleration makes the one-off
/// calibration drift by 30% or more).
/// </summary>
internal sealed class TurnController(float gain)
{
    public float Gain { get; private set; } = gain;

    public int Pixels(float radians, int maxPixels) => radians == 0 ? 0 : Math.Clamp((int)MathF.Round(radians / Gain), -maxPixels, maxPixels);

    /// <summary>Learn from the heading change seen since <paramref name="pixels"/> were sent.</summary>
    public void Observe(int pixels, float headingChange)
    {
        if (Math.Abs(pixels) < 4) return;
        float observed = headingChange / pixels;
        if (Math.Sign(observed) != Math.Sign(Gain) || Math.Abs(observed) < Math.Abs(Gain) * 0.25f || Math.Abs(observed) > Math.Abs(Gain) * 4) return;
        Gain = Gain * 0.85f + observed * 0.15f;
    }
}
