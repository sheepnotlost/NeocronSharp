using System.Numerics;

namespace NeocronSharp.Core;

public enum TravelInput { None, Forward, Backward }
public sealed record RouteDecision(TravelInput Input, bool Arrived, bool Complete, int CompletedLegs);

/// <summary>After recording A->B, measure and drive the remaining A,B,A endpoints.</summary>
public sealed class StraightLineRoute
{
    public Vector3 A { get; }
    public Vector3 B { get; }
    public float Length { get; }
    public float Tolerance { get; }
    public int CompletedLegs { get; private set; } = 1;
    public bool Complete => CompletedLegs == 4;
    private readonly Vector3 _axis;
    private readonly float _corridor;
    private readonly float _overshootAllowance;

    public StraightLineRoute(Vector3 a, Vector3 b)
    {
        RequireFinite(a); RequireFinite(b);
        A = a; B = b; Length = Vector3.Distance(a, b);
        if (Length < 5 || Length > 400)
            throw new InvalidOperationException("The recorded segment must be between 5 and 400 world units.");
        _axis = (b - a) / Length;
        Tolerance = Math.Clamp(Length * 0.015f, 0.5f, 2f);
        _corridor = Math.Max(3, Length * 0.04f);
        _overshootAllowance = Math.Max(15, Length * 0.15f);
    }

    public RouteDecision Observe(Vector3 position, bool commitArrival = true)
    {
        RequireFinite(position);
        if (Complete) return new(TravelInput.None, false, true, CompletedLegs);
        Vector3 relative = position - A;
        float progress = Vector3.Dot(relative, _axis);
        float lateral = (relative - _axis * progress).Length();
        if (lateral > _corridor)
            throw new InvalidOperationException("Character moved sideways away from the recorded straight line.");
        if (progress < -_overshootAllowance || progress > Length + _overshootAllowance)
            throw new InvalidOperationException("Character moved too far beyond an endpoint.");
        float target = CompletedLegs % 2 == 1 ? 0 : Length;
        // Require measured 3D endpoint proximity, including any sideways drift.
        Vector3 endpoint = target == 0 ? A : B;
        if (Vector3.Distance(position, endpoint) <= Tolerance)
        {
            if (commitArrival) CompletedLegs++;
            return new(TravelInput.None, true, Complete, CompletedLegs);
        }
        if (Math.Abs(target - progress) <= Tolerance)
            throw new InvalidOperationException("Endpoint is beside the character; reposition and record a new line.");
        return new(target > progress ? TravelInput.Forward : TravelInput.Backward, false, false, CompletedLegs);
    }

    public static void RequireFinite(Vector3 position)
    {
        if (!float.IsFinite(position.X) || !float.IsFinite(position.Y) || !float.IsFinite(position.Z) ||
            Math.Abs(position.X) > 1_000_000 || Math.Abs(position.Y) > 1_000_000 || Math.Abs(position.Z) > 1_000_000)
            throw new InvalidOperationException("Invalid player coordinates.");
    }
}
