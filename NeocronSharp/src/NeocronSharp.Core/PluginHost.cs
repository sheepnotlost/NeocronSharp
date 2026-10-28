using System.Reflection;
using System.Runtime.Loader;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace NeocronSharp.Core;

/// <summary>Contract for trusted, in-process plugins. Stop must end background work.</summary>
public interface INeocronPlugin
{
    void Start(IPluginContext context);
    void Stop();
}

public interface IPluginContext
{
    string PluginId { get; }
    JsonElement ReadSettings();
    void WriteSettings(string json);
    void Log(string message);
}

/// <summary>Optional read-only view of the currently verified game session.</summary>
public interface IGameTelemetryContext
{
    PluginTelemetry? ReadGameTelemetry();
}

public sealed record PluginTelemetry(DateTimeOffset CapturedAt, float X, float Y, float Z,
    int NearbyNpcCount, int? SectorId, nint GameWindow);

public sealed record PluginManifest(string Id, string Name, string Version, string Description, string Assembly, string Type);

public sealed class PluginEntry
{
    public string Folder { get; internal init; } = "";
    public PluginManifest? Manifest { get; internal init; }
    public string Error { get; internal set; } = "";
    public bool Enabled { get; internal set; }
    public bool Running => Instance != null;
    public string Status => Error.Length > 0 ? "Error" : Running ? "Running" : Enabled ? "Enabled" : "Disabled";
    internal INeocronPlugin? Instance;
    internal AssemblyLoadContext? LoadContext;
}

public sealed class PluginHost : IDisposable
{
    private readonly string _plugins, _settings, _logs, _preferences;
    private readonly Dictionary<string, bool> _enabled = new(StringComparer.OrdinalIgnoreCase);
    private readonly Func<PluginTelemetry?>? _telemetry;
    private readonly List<PluginEntry> _entries = new();
    public IReadOnlyList<PluginEntry> Entries => _entries;
    public string DiscoveryError { get; private set; } = "";
    private bool _disposed;
    private static readonly JsonSerializerOptions JsonOptions = new() { PropertyNameCaseInsensitive = true, WriteIndented = true };

    public PluginHost(string root, Func<PluginTelemetry?>? telemetry = null)
    {
        _telemetry = telemetry;
        root = Path.GetFullPath(root);
        _plugins = Path.Combine(root, "plugins"); _settings = Path.Combine(root, "settings", "plugins");
        _logs = Path.Combine(root, "logs", "plugins"); _preferences = Path.Combine(root, "settings", "plugins-enabled.json");
        try
        {
            if (File.Exists(_preferences))
                foreach (var pair in JsonSerializer.Deserialize<Dictionary<string, bool>>(File.ReadAllText(_preferences), JsonOptions) ?? new())
                    _enabled[pair.Key] = pair.Value;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or JsonException)
        { DiscoveryError = "Could not read enabled preferences: " + e.Message; }
    }

    public void Discover()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        // Preserve running instances across refresh; removed or changed modules stop.
        var previous = _entries.Where(e => e.Manifest != null).ToDictionary(e => e.Manifest!.Id, StringComparer.OrdinalIgnoreCase);
        var found = new List<PluginEntry>(); var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        try
        {
            Directory.CreateDirectory(_plugins);
            foreach (string folder in Directory.EnumerateDirectories(_plugins).OrderBy(x => x, StringComparer.OrdinalIgnoreCase))
            {
                string manifestFile = Path.Combine(folder, "plugin.json");
                if (!File.Exists(manifestFile)) continue;
                try
                {
                    if (new FileInfo(manifestFile).Length > 32768) throw new InvalidDataException("Manifest exceeds 32 KB.");
                    var manifest = JsonSerializer.Deserialize<PluginManifest>(File.ReadAllText(manifestFile), JsonOptions) ?? throw new InvalidDataException("Empty manifest.");
                    Validate(manifest, folder);
                    if (!seen.Add(manifest.Id)) throw new InvalidDataException("Duplicate plugin ID: " + manifest.Id);
                    if (previous.Remove(manifest.Id, out var old) && old.Folder == folder && old.Manifest == manifest) { found.Add(old); continue; }
                    if (old != null) Stop(old);
                    found.Add(new PluginEntry { Folder = folder, Manifest = manifest, Enabled = _enabled.GetValueOrDefault(manifest.Id) });
                }
                catch (Exception e) when (e is IOException or UnauthorizedAccessException or JsonException or InvalidDataException or ArgumentException)
                { found.Add(new PluginEntry { Folder = folder, Error = e.Message }); }
            }
            foreach (var removed in previous.Values) Stop(removed);
            _entries.Clear(); _entries.AddRange(found);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        { DiscoveryError = "Could not scan plugins: " + e.Message; }
    }

    private static void Validate(PluginManifest m, string folder)
    {
        if (m.Id == null || !Regex.IsMatch(m.Id, "^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")) throw new InvalidDataException("Invalid plugin ID.");
        if (string.IsNullOrWhiteSpace(m.Name) || m.Name.Length > 120 || string.IsNullOrWhiteSpace(m.Version) || m.Version.Length > 80 ||
            m.Description == null || m.Description.Length > 1000 || string.IsNullOrWhiteSpace(m.Type) || m.Type.Length > 500)
            throw new InvalidDataException("Manifest needs a valid name, version, description, and type.");
        if (string.IsNullOrWhiteSpace(m.Assembly) || Path.GetFileName(m.Assembly) != m.Assembly || !m.Assembly.EndsWith(".dll", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Assembly must be a DLL filename in the plugin folder.");
        if (!File.Exists(Path.Combine(folder, m.Assembly))) throw new InvalidDataException("Plugin DLL not found: " + m.Assembly);
    }

    public void StartEnabled()
    {
        foreach (var entry in _entries.Where(e => e.Manifest != null && e.Enabled && !e.Running).ToArray()) Start(entry);
    }

    public void Enable(PluginEntry entry)
    {
        EnsureEntry(entry);
        if (!entry.Running && !Start(entry)) return;
        entry.Enabled = true; _enabled[entry.Manifest!.Id] = true; SavePreferences();
    }

    public void Disable(PluginEntry entry)
    {
        EnsureEntry(entry); Stop(entry);
        entry.Enabled = false; _enabled[entry.Manifest!.Id] = false; SavePreferences();
    }

    private bool Start(PluginEntry entry)
    {
        PluginLoadContext? context = null; INeocronPlugin? instance = null;
        try
        {
            var manifest = entry.Manifest!;
            context = new PluginLoadContext(Path.Combine(entry.Folder, manifest.Assembly));
            var assembly = context.LoadFile(Path.Combine(entry.Folder, manifest.Assembly));
            var type = assembly.GetType(manifest.Type, throwOnError: true)!;
            if (!typeof(INeocronPlugin).IsAssignableFrom(type) || type.IsAbstract) throw new InvalidDataException("Type does not implement INeocronPlugin.");
            instance = (INeocronPlugin)(Activator.CreateInstance(type) ?? throw new InvalidDataException("Plugin constructor returned null."));
            instance.Start(new Context(this, manifest.Id));
            entry.LoadContext = context; entry.Instance = instance; entry.Error = ""; Log(manifest.Id, "Started.");
            return true;
        }
        catch (Exception e)
        {
            try { instance?.Stop(); } catch (Exception stopError) { Log(entry.Manifest!.Id, "Cleanup failed: " + stopError.GetBaseException().Message); }
            context?.Unload(); entry.Error = "Start failed: " + e.GetBaseException().Message; Log(entry.Manifest!.Id, entry.Error); return false;
        }
    }

    private void Stop(PluginEntry entry)
    {
        if (entry.Instance == null) return;
        try { entry.Instance.Stop(); entry.Error = ""; Log(entry.Manifest!.Id, "Stopped."); }
        catch (Exception e) { entry.Error = "Stop failed: " + e.GetBaseException().Message; Log(entry.Manifest!.Id, entry.Error); }
        finally { entry.Instance = null; entry.LoadContext?.Unload(); entry.LoadContext = null; }
    }

    public string ReadSettings(PluginEntry entry) { EnsureEntry(entry); return ReadSettings(entry.Manifest!.Id); }
    public void WriteSettings(PluginEntry entry, string json) { EnsureEntry(entry); WriteSettings(entry.Manifest!.Id, json); }
    public string ReadRecentLog(PluginEntry entry)
    {
        EnsureEntry(entry);
        string path = Path.Combine(_logs, entry.Manifest!.Id + ".log");
        if (!File.Exists(path)) return "No log entries yet.";
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        if (stream.Length > 32768) stream.Seek(-32768, SeekOrigin.End);
        using var reader = new StreamReader(stream);
        return reader.ReadToEnd();
    }
    private string ReadSettings(string id)
    {
        string path = Path.Combine(_settings, id + ".json");
        return File.Exists(path) ? File.ReadAllText(path) : "{}";
    }
    private void WriteSettings(string id, string json)
    {
        if (json.Length > 262144) throw new InvalidDataException("Settings exceed 256 KB.");
        using var parsed = JsonDocument.Parse(json);
        if (parsed.RootElement.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Settings must be a JSON object.");
        Directory.CreateDirectory(_settings); AtomicWrite(Path.Combine(_settings, id + ".json"), JsonSerializer.Serialize(parsed.RootElement, JsonOptions));
        Log(id, "Settings saved; apply on next start.");
    }
    private void SavePreferences()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(_preferences)!); AtomicWrite(_preferences, JsonSerializer.Serialize(_enabled, JsonOptions));
    }
    private static void AtomicWrite(string path, string text)
    {
        string temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try { File.WriteAllText(temp, text); File.Move(temp, path, true); }
        finally { if (File.Exists(temp)) File.Delete(temp); }
    }
    private void Log(string id, string message)
    {
        try { Directory.CreateDirectory(_logs); File.AppendAllText(Path.Combine(_logs, id + ".log"), $"{DateTimeOffset.UtcNow:O} {message.Replace('\r', ' ').Replace('\n', ' ')}{Environment.NewLine}"); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { /* Logging must not crash the host. */ }
    }
    private void EnsureEntry(PluginEntry entry)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (!_entries.Contains(entry) || entry.Manifest == null) throw new InvalidOperationException("Select a valid discovered plugin.");
    }
    public void Dispose()
    {
        if (_disposed) return;
        foreach (var entry in _entries) Stop(entry);
        _disposed = true;
    }
    private sealed class Context(PluginHost host, string id) : IPluginContext, IGameTelemetryContext
    {
        public string PluginId => id;
        public JsonElement ReadSettings() { using var json = JsonDocument.Parse(host.ReadSettings(id)); return json.RootElement.Clone(); }
        public void WriteSettings(string json) => host.WriteSettings(id, json);
        public void Log(string message) => host.Log(id, message ?? "");
        public PluginTelemetry? ReadGameTelemetry() => host._telemetry?.Invoke();
    }
    private sealed class PluginLoadContext(string mainAssembly) : AssemblyLoadContext(isCollectible: true)
    {
        private readonly string _folder = Path.GetDirectoryName(Path.GetFullPath(mainAssembly))!;
        internal Assembly LoadFile(string path)
        {
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            return LoadFromStream(stream);
        }
        protected override Assembly? Load(AssemblyName name)
        {
            if (name.Name == typeof(INeocronPlugin).Assembly.GetName().Name) return typeof(INeocronPlugin).Assembly;
            if (name.Name == null || Path.GetFileName(name.Name) != name.Name) return null;
            string path = Path.Combine(_folder, name.Name + ".dll");
            return File.Exists(path) ? LoadFile(path) : null;
        }
    }
}
