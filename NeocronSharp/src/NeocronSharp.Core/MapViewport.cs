using System.Numerics;

namespace NeocronSharp.Core;

public sealed class MapViewport
{
    public Vector2 ViewSize { get; set; } = new(1, 1);
    public Vector2 ImageSize { get; set; } = new(256, 256);
    public float Zoom { get; private set; } = 1;
    public Vector2 Pan { get; private set; }
    public float Scale => Math.Max(0.001f, Math.Min(Math.Max(1, ViewSize.X - 32) / ImageSize.X,
        Math.Max(1, ViewSize.Y - 32) / ImageSize.Y)) * Zoom;
    public Vector2 ToScreen(Vector2 pixel) => ViewSize / 2 + Pan + (pixel - ImageSize / 2) * Scale;
    public Vector2 FromScreen(Vector2 screen) => (screen - ViewSize / 2 - Pan) / Scale + ImageSize / 2;
    public void Reset() { Zoom = 1; Pan = Vector2.Zero; }
    public void Drag(Vector2 delta) => Pan += delta;
    public void Center(Vector2 pixel) => Pan = -(pixel - ImageSize / 2) * Scale;
    public void ZoomAt(Vector2 screen, float factor)
    {
        if (!float.IsFinite(factor) || factor <= 0) throw new ArgumentOutOfRangeException(nameof(factor));
        Vector2 anchor = FromScreen(screen);
        Zoom = Math.Clamp(Zoom * factor, 1, 12);
        Pan += screen - ToScreen(anchor);
    }
}
