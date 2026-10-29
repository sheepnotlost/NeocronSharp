using System.Text;
using NeocronSharp.Core;
using NeocronSharp.Navigation;

namespace NeocronSharp;

/// <summary>--navplan: no window; reads one JSON request per line on stdin and answers with one JSON line on stdout
/// (protocol in NavPlanProtocol). Plans use the live position from the same read-only PlayerReader as --telemetry
/// and a navmesh of the current sector (baked once, then cached under settings/navmesh). It never writes process
/// memory, sends input or focuses windows. Exits when stdin reaches end of input or stdout closes.</summary>
internal static class NavPlanStream
{
    private sealed class Worlds : INavWorlds
    {
        private NavMeshStore? _store;
        private string? _install;
        public string LastSource => _store?.LastSource ?? "";
        public void Use(string install)
        {
            if (_store != null && string.Equals(install, _install, StringComparison.OrdinalIgnoreCase)) return;
            _store = new NavMeshStore(new EnvironmentCatalog(install), Path.Combine(ProjectPaths.Root, "settings", "navmesh"));
            _install = install;
        }
        public NavWorld Get(int worldId) => (_store ?? throw new InvalidOperationException("Not connected.")).Get(worldId);
        public string? WorldName(int worldId) => _store?.WorldName(worldId);
    }

    public static int Run()
    {
        bool hadOutput = TelemetryStream.HasHandle(TelemetryStream.StdOutput);
        if (!hadOutput && TelemetryStream.GetConsoleWindow() == 0) TelemetryStream.AttachConsole(TelemetryStream.AttachParent);
        using var output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false), 65536) { AutoFlush = false, NewLine = "\n" };
        using var input = new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false));

        var worlds = new Worlds();
        var protocol = new NavPlanProtocol(worlds);
        PlayerReader? reader = null;

        NavLocation Locate()
        {
            if (reader != null)
            {
                bool exited; try { exited = reader.Process.HasExited; } catch (Exception) { exited = true; }
                if (exited) { reader.Dispose(); reader = null; }
            }
            reader ??= new PlayerReader(ProjectPaths.Client);
            worlds.Use(Path.GetDirectoryName(reader.Executable)!);
            var fix = reader.ReadCoordinates();
            return new(fix.SectorId, fix.Position);
        }

        try
        {
            for (string? line = input.ReadLine(); line != null; line = input.ReadLine())
            {
                if (string.IsNullOrWhiteSpace(line)) continue;
                string answer;
                try { answer = protocol.Answer(line, Locate); }
                catch (Exception error) when (error is not OutOfMemoryException) { answer = NavPlanProtocol.Error(null, error.Message); }
                output.WriteLine(answer);
                output.Flush();
            }
        }
        catch (IOException) { }            // stdout or stdin closed: nothing left to answer
        catch (ObjectDisposedException) { }
        finally { reader?.Dispose(); }
        return 0;
    }
}
