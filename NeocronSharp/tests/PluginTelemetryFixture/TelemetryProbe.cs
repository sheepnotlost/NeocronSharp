using NeocronSharp.Core;

namespace PluginTelemetryFixture;

public sealed class TelemetryProbe : INeocronPlugin
{
    public void Start(IPluginContext context)
    {
        var data = (context as IGameTelemetryContext)?.ReadGameTelemetry();
        context.Log(data == null ? "no live telemetry" : $"X={data.X};NPCs={data.NearbyNpcCount};window={data.GameWindow}");
    }
    public void Stop() { }
}
