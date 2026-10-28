namespace NeocronSharp.Core;

public static class SteeringPulses
{
    // Spread a correction across game frames instead of trusting one cursor event
    // between the client's cursor sampling and its recenter operation.
    public static IEnumerable<int> Split(int pixels)
    {
        if (pixels is < -24 or > 24) throw new ArgumentOutOfRangeException(nameof(pixels));
        while (pixels != 0)
        {
            int pulse = Math.Clamp(pixels, -2, 2);
            yield return pulse;
            pixels -= pulse;
        }
    }
}
