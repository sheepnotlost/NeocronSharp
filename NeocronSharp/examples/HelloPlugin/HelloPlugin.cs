using System.Text.Json;
using NeocronSharp.Core;

namespace HelloPlugin;

/// <summary>A small, disabled-by-default example of the plugin API.</summary>
public sealed class ExamplePlugin : INeocronPlugin
{
    private IPluginContext? _context;
    public void Start(IPluginContext context)
    {
        _context = context;
        var settings = context.ReadSettings();
        string greeting = settings.TryGetProperty("greeting", out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? "Hello from NeocronSharp" : "Hello from NeocronSharp";
        context.Log(greeting);
    }
    public void Stop()
    {
        _context?.Log("Example plugin stopped.");
        _context = null;
    }
}
