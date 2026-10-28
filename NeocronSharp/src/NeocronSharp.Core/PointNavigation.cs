using System.Numerics;

namespace NeocronSharp.Core;

public sealed record NavigationDecision(TravelInput Travel, int MouseX, bool NearDestination, float Distance);

public static class PointNavigation
{
    public const float ArrivalTolerance = 2;
    public const float MaximumDestinationDistance = 10_000;

    public static void ValidateDestination(Vector3 position, Vector3 destination)
    {
        StraightLineRoute.RequireFinite(position); StraightLineRoute.RequireFinite(destination);
        float distance = Distance(position, destination);
        if (distance > MaximumDestinationDistance)
            throw new InvalidOperationException($"The saved spot is {distance:F0} units away. Save a destination within the current area.");
        if (Math.Abs(position.Y - destination.Y) > 12)
            throw new InvalidOperationException("The saved spot is on a different floor. Save a spot on the same flat ground.");
    }

    public static Vector3 Planar(Vector3 vector)
    {
        StraightLineRoute.RequireFinite(vector);
        vector.Y = 0;
        if (vector.LengthSquared() < 0.01f) throw new InvalidOperationException("Look closer to the horizon before navigating.");
        return Vector3.Normalize(vector);
    }

    public static float SignedAngle(Vector3 from, Vector3 to)
    {
        from = Planar(from); to = Planar(to);
        return MathF.Atan2(from.X * to.Z - from.Z * to.X, Vector3.Dot(from, to));
    }

    public static float Distance(Vector3 a, Vector3 b) => new Vector2(a.X - b.X, a.Z - b.Z).Length();

    public static Vector3 ForwardFromTransform(ReadOnlySpan<float> matrix)
    {
        if (matrix.Length < 12) throw new ArgumentException("A native transform contains 12 floats.");
        var a = new Vector3(matrix[0], matrix[1], matrix[2]);
        var b = new Vector3(matrix[3], matrix[4], matrix[5]);
        var c = new Vector3(matrix[6], matrix[7], matrix[8]);
        StraightLineRoute.RequireFinite(a); StraightLineRoute.RequireFinite(b); StraightLineRoute.RequireFinite(c);
        if (Math.Abs(a.LengthSquared() - 1) > 0.05f || Math.Abs(b.LengthSquared() - 1) > 0.05f ||
            Math.Abs(c.LengthSquared() - 1) > 0.05f || Math.Abs(Vector3.Dot(a,b)) > 0.05f ||
            Math.Abs(Vector3.Dot(a,c)) > 0.05f || Math.Abs(Vector3.Dot(b,c)) > 0.05f)
            throw new InvalidOperationException("Player orientation is not a valid rotation transform.");
        // Genesis-style native transform: the view's inward axis is minus column Z.
        // Live movement must independently confirm this convention before navigation.
        return Planar(new(-matrix[2], -matrix[5], -matrix[8]));
    }

    public static void VerifyForward(Vector3 expected, Vector3 measured)
    {
        if (measured.Length() < 2 || measured.Length() > 35 || Math.Abs(measured.Y) > 3 ||
            Vector3.Dot(Planar(expected), Planar(measured)) < 0.97f)
            throw new InvalidOperationException("The measured forward movement does not match the native heading. Navigation stopped.");
    }

    public static NavigationDecision Decide(Vector3 position, Vector3 forward, Vector3 destination, float radiansPerMousePixel)
    {
        ValidateDestination(position, destination);
        if (!float.IsFinite(radiansPerMousePixel) || Math.Abs(radiansPerMousePixel) < 0.00005f || Math.Abs(radiansPerMousePixel) > 0.08f)
            throw new InvalidOperationException("Mouse steering has not been calibrated.");
        float distance = Distance(position, destination);
        if (distance <= ArrivalTolerance)
        {
            if (Math.Abs(position.Y - destination.Y) > ArrivalTolerance)
                throw new InvalidOperationException("The destination is above or below the character; a flat direct path cannot reach it.");
            return new(TravelInput.None, 0, true, distance);
        }
        Vector3 direction = Planar(destination - position);
        float angle = SignedAngle(forward, direction);
        // A small overshoot is corrected backwards without turning the camera around.
        bool reverse = distance < 24 && Math.Abs(angle) > MathF.PI * 0.75f;
        if (reverse) angle = SignedAngle(forward, -direction);
        if (Math.Abs(angle) > 0.065f)
        {
            float pixels = angle / radiansPerMousePixel * 0.65f;
            int move = Math.Clamp((int)MathF.Round(pixels), -24, 24);
            if (move == 0) move = pixels > 0 ? 1 : -1;
            return new(TravelInput.None, move, false, distance);
        }
        return new(reverse ? TravelInput.Backward : TravelInput.Forward, 0, false, distance);
    }
}
