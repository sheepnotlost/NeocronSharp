using NeocronSharp.Core;
using System.Text.Json;

internal static class PluginTests
{
    public static void Run(Action<string, Action> test, Action<bool, string> check)
    {
        test("Separate plugin is disabled until enabled, uses settings and stops on shutdown", () =>
        {
            string root = TempRoot();
            try
            {
                Install(root, "hello", File.ReadAllText(Path.Combine(Fixture(), "plugin.json")));
                using (var host = new PluginHost(root))
                {
                    host.Discover(); var entry = host.Entries.Single();
                    check(!entry.Enabled && !entry.Running, "New plugin must be disabled");
                    host.WriteSettings(entry, "{\"greeting\":\"testing settings\"}");
                    host.Enable(entry);
                    check(entry.Enabled && entry.Running, "Plugin starts after explicit enable");
                    check(host.ReadRecentLog(entry).Contains("testing settings"), "Plugin reads its settings and logs");
                }
                using (var host = new PluginHost(root))
                {
                    host.Discover(); var entry = host.Entries.Single();
                    check(entry.Enabled && !entry.Running, "Enabled preference persists independently of process");
                    host.StartEnabled(); check(entry.Running, "Enabled module starts on next app launch");
                    check(host.ReadRecentLog(entry).Contains("Example plugin stopped."), "Shutdown invoked Stop");
                    host.Disable(entry); check(!entry.Enabled && !entry.Running, "Disable stops the module");
                }
                using var final = new PluginHost(root); final.Discover();
                check(!final.Entries.Single().Enabled, "Disabled preference persists");
            }
            finally { Directory.Delete(root, recursive: true); }
        });
        test("A plugin shipped enabled by default starts enabled on a fresh download until the user chooses", () =>
        {
            string root = TempRoot();
            try
            {
                var manifest = JsonSerializer.Deserialize<Dictionary<string, object>>(File.ReadAllText(Path.Combine(Fixture(), "plugin.json")))!;
                manifest["enabledByDefault"] = true;
                Install(root, "bundled", JsonSerializer.Serialize(manifest));
                using (var host = new PluginHost(root))
                {
                    host.Discover(); var entry = host.Entries.Single();
                    check(entry.Enabled, "A bundled plugin is enabled with no saved choice");
                    host.StartEnabled(); check(entry.Running, "and starts with the app");
                    host.Disable(entry);
                }
                using var again = new PluginHost(root); again.Discover();
                check(!again.Entries.Single().Enabled, "The user's choice to disable it wins over the default");
            }
            finally { Directory.Delete(root, recursive: true); }
        });
        test("Plugin refresh preserves a running instance and settings validation rejects invalid JSON", () =>
        {
            string root = TempRoot();
            try
            {
                Install(root, "hello", File.ReadAllText(Path.Combine(Fixture(), "plugin.json")));
                using var host = new PluginHost(root); host.Discover(); var entry = host.Entries.Single(); host.Enable(entry);
                host.Discover(); check(ReferenceEquals(entry, host.Entries.Single()) && entry.Running, "Refresh must not restart a running module");
                try { host.WriteSettings(entry, "[]"); throw new Exception("Expected invalid settings rejection"); }
                catch (InvalidDataException) { }
                try { host.WriteSettings(entry, "{"); throw new Exception("Expected invalid JSON rejection"); }
                catch (JsonException) { }
                check(host.ReadSettings(entry) == "{}", "Invalid settings cannot replace the saved object");
            }
            finally { Directory.Delete(root, recursive: true); }
        });
        test("Bad plugin and duplicate IDs are reported without blocking valid plugins", () =>
        {
            string root = TempRoot();
            try
            {
                string json = File.ReadAllText(Path.Combine(Fixture(), "plugin.json"));
                Install(root, "a-valid", json);
                Install(root, "b-duplicate", json);
                Install(root, "c-missing-type", json.Replace("neocronsharp.example", "broken.plugin").Replace("HelloPlugin.ExamplePlugin", "HelloPlugin.Missing"));
                Install(root, "d-traversal", json.Replace("neocronsharp.example", "evil.plugin").Replace("HelloPlugin.dll", "../outside.dll"));
                using var host = new PluginHost(root); host.Discover();
                check(host.Entries.Count == 4 && host.Entries.Count(e => e.Manifest == null) == 2, "Invalid manifests must be visible");
                var valid = host.Entries.Single(e => e.Manifest?.Id == "neocronsharp.example"); host.Enable(valid);
                var broken = host.Entries.Single(e => e.Manifest?.Id == "broken.plugin"); host.Enable(broken);
                check(valid.Running && broken.Status == "Error" && !broken.Enabled, "Failure cannot crash or enable the bad plugin");
            }
            finally { Directory.Delete(root, recursive: true); }
        });
        test("Plugin telemetry is read-only, optional, and supplied by the host", () =>
        {
            string root = TempRoot();
            try
            {
                string folder = Path.Combine(root, "plugins", "probe"); Directory.CreateDirectory(folder);
                File.Copy(Path.Combine(Fixture(), "PluginTelemetryFixture.dll"), Path.Combine(folder, "PluginTelemetryFixture.dll"));
                File.WriteAllText(Path.Combine(folder, "plugin.json"), "{\"id\":\"test.telemetry\",\"name\":\"Probe\",\"version\":\"1\",\"description\":\"Fixture\",\"assembly\":\"PluginTelemetryFixture.dll\",\"type\":\"PluginTelemetryFixture.TelemetryProbe\"}");
                using var host = new PluginHost(root, () => new PluginTelemetry(DateTimeOffset.UtcNow, 123, 45, 678, 7, 1, (nint)42));
                host.Discover(); var entry = host.Entries.Single(); host.Enable(entry);
                check(entry.Running && host.ReadRecentLog(entry).Contains("X=123;NPCs=7;window=42"), "Plugin receives only the published telemetry snapshot");
                host.Disable(entry);
                using var empty = new PluginHost(root); empty.Discover(); var noData = empty.Entries.Single(); empty.Enable(noData);
                check(noData.Running && empty.ReadRecentLog(noData).Contains("no live telemetry"), "Missing provider returns unavailable without failing plugin startup");
            }
            finally { Directory.Delete(root, recursive: true); }
        });
    }
    private static string Fixture() => Path.Combine(AppContext.BaseDirectory, "plugin-fixture");
    private static string TempRoot() { string root = Path.Combine(Path.GetTempPath(), "neocron-plugin-test-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(root); return root; }
    private static void Install(string root, string name, string manifest)
    {
        string path = Path.Combine(root, "plugins", name); Directory.CreateDirectory(path);
        File.Copy(Path.Combine(Fixture(), "HelloPlugin.dll"), Path.Combine(path, "HelloPlugin.dll"));
        File.WriteAllText(Path.Combine(path, "plugin.json"), manifest);
    }
}
