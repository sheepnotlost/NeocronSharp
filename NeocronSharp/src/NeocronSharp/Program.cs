using System.Runtime.InteropServices;
using System.Text.Json;
using NeocronSharp.Core;

namespace NeocronSharp;

internal static class ProjectPaths
{
    public static string Root
    {
        get
        {
            for (DirectoryInfo? folder = new(AppContext.BaseDirectory); folder != null; folder = folder.Parent)
                if (File.Exists(Path.Combine(folder.FullName, "SPEC.md")) && Directory.Exists(Path.Combine(folder.FullName, "src")))
                    return folder.FullName;
            throw new InvalidOperationException("Keep this application inside the NeocronSharp project folder.");
        }
    }
    /// <summary>The reference client executable (its SHA-256 is checked before any memory read). NeocronSharp now lives
    /// inside the merged suite folder, so look beside the project, in the suite's Research copy, at the running client,
    /// then at the usual install folder; the first that exists wins.</summary>
    public static string Client
    {
        get
        {
            var candidates = new List<string>
            {
                Path.Combine(Root, "..", "Neocron Evolution 2.5", "neocronclient.exe"),
                Path.Combine(Root, "..", "Research", "Neocron Evolution 2.5", "neocronclient.exe"),
            };
            try
            {
                foreach (var process in System.Diagnostics.Process.GetProcessesByName("neocronclient"))
                    using (process)
                        if (process.MainModule?.FileName is string running) candidates.Add(running);
            }
            catch (Exception) { }
            candidates.Add(Path.Combine("C:\\Games", "Neocron Client", "Neocron Evolution 2.5", "neocronclient.exe"));
            foreach (string candidate in candidates)
                if (File.Exists(candidate)) return Path.GetFullPath(candidate);
            return Path.GetFullPath(candidates[0]);
        }
    }
}

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Contains("--loot-index"))
        {
            var loot = new LootCatalog(Path.GetDirectoryName(ProjectPaths.Client)!);
            var report = new { templates = loot.Npcs.Count, assigned = loot.NpcsWithContainer, containers = loot.ContainerCount, items = loot.ItemCount,
                tablesWithCandidates = loot.Npcs.Count(n => n.ContainerId > 0 && loot.Get(n.TemplateId).Items.Count > 0),
                smallSpider = loot.Get(440), warbot = loot.Get(195), source = LootCatalog.SourceNote };
            Console.WriteLine(JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true })); return 0;
        }
        if (args.Contains("--environment-index"))
        {
            var maps = new EnvironmentCatalog(Path.GetDirectoryName(ProjectPaths.Client)!);
            maps.ScanAll((i, total, _) => { if (i % 100 == 0) Console.Error.WriteLine($"Mapped {i}/{total} areas"); });
            var report = new { areas = maps.Areas.Count, mapped = maps.Scanned.Count(s => s.Error == null), failed = maps.Scanned.Count(s => s.Error != null),
                groundPoints = maps.Scanned.Sum(s => s.GroundPoints), transitions = maps.Scanned.Sum(s => s.Transitions),
                summaries = maps.Scanned, plazaToPlaza2 = maps.WorldRoute(1, 2) };
            var options = new JsonSerializerOptions { WriteIndented = true, IncludeFields = true };
            File.WriteAllText(Path.Combine(ProjectPaths.Root, "logs", "environment-index.json"), JsonSerializer.Serialize(report, options));
            Console.WriteLine(JsonSerializer.Serialize(new { report.areas, report.mapped, report.failed, report.groundPoints, report.transitions, report.plazaToPlaza2 })); return 0;
        }
        if (args.Contains("--entities"))
        {
            try
            {
                using var reader = new PlayerReader(ProjectPaths.Client);
                Console.WriteLine(EntityExport.Json(reader.ReadEntities(), reader.Process.Id));
                return 0;
            }
            catch (Exception error) { Console.WriteLine(JsonSerializer.Serialize(new { status = "unavailable", message = error.Message })); return 1; }
        }
        if (args.Contains("--diagnose"))
        {
            try
            {
                using var reader = new PlayerReader(ProjectPaths.Client);
                var sample = reader.ReadSample();
                Console.WriteLine(JsonSerializer.Serialize(new { status = "read-only-ok", processId = reader.Process.Id,
                    executable = reader.Executable, supportedSha256 = PlayerReader.SupportedSha256,
                    position = new { sample.Position.X, sample.Position.Y, sample.Position.Z },
                    forward = new { sample.Forward.X, sample.Forward.Y, sample.Forward.Z },
                    player = $"0x{sample.Player:x}", physics = $"0x{sample.Physics:x}", inputStructSize = Marshal.SizeOf<Native.Input>() }));
                return 0;
            }
            catch (Exception error) { Console.WriteLine(JsonSerializer.Serialize(new { status = "unavailable", message = error.Message })); return 1; }
        }
        ApplicationConfiguration.Initialize();
        AppTheme.Load();
        if (args.Contains("--overlay-render-evidence")) { OverlayEvidenceForm.RenderCounter(); return 0; }
        if (args.Contains("--overlay-evidence"))
        {
            Directory.CreateDirectory(Path.Combine(ProjectPaths.Root, "logs"));
            using var check = new OverlayEvidenceForm(); Application.Run(check); return check.Passed ? 0 : 1;
        }
        using Form form = args.Contains("--recorder") ? new CoordinateRecorderForm(args.Contains("--smoke-ui") ? Path.Combine(ProjectPaths.Root,"logs","recorder-test") : null) :
            args.Contains("--navigation") ? new MainForm() : new TrackerForm();
        if (args.Contains("--embedded") && form is TrackerForm embedded) EmbeddedHost.Attach(embedded, Console.In);
        int smokeExitCode = 0;
        if (args.Contains("--smoke-ui"))
        {
            var timer = new System.Windows.Forms.Timer { Interval = 1800 };
            timer.Tick += async (_, _) =>
            {
                timer.Stop();
                if (args.Contains("--ui-evidence"))
                {
                    try
                    {
                        if (form is CoordinateRecorderForm recorder) await recorder.VerifyEvidence();
                        if (form is TrackerForm tracker && !args.Contains("--quest-evidence") && !args.Contains("--plugin-evidence")) tracker.VerifyLiveView();
                        if (form is TrackerForm questTracker && args.Contains("--quest-evidence")) questTracker.VerifyQuestView();
                        if (form is TrackerForm pluginTracker && args.Contains("--plugin-evidence")) pluginTracker.VerifyPluginView();
                        if (form is TrackerForm skinTracker && args.Contains("--skin-evidence")) skinTracker.SaveSkinEvidence();
                        if (form is TrackerForm expansionTracker && args.Contains("--expansion-evidence")) await expansionTracker.SaveExpansionEvidence();
                        if (form is TrackerForm playerTracker && args.Contains("--player-evidence")) await playerTracker.VerifyPlayers();
                        if (form is TrackerForm sortTracker && args.Contains("--sort-evidence")) sortTracker.VerifyHeaderSorting();
                        using var bitmap = new Bitmap(form.Width, form.Height);
                        form.DrawToBitmap(bitmap, new Rectangle(Point.Empty, bitmap.Size));
                        Directory.CreateDirectory(Path.Combine(ProjectPaths.Root, "logs"));
                        bitmap.Save(Path.Combine(ProjectPaths.Root, "logs", form is CoordinateRecorderForm ? "coordinate-recorder-ui.png" : args.Contains("--quest-evidence") ? "quest-ui.png" : args.Contains("--plugin-evidence") ? "plugin-ui.png" : "tracker-ui.png"));
                        if (form is CoordinateRecorderForm closeRecorder) await closeRecorder.BeginCloseEvidence();
                    }
                    catch (Exception error) { Console.Error.WriteLine(error.Message); smokeExitCode = 1; }
                }
                form.Close(); timer.Dispose();
            };
            form.Shown += (_, _) => timer.Start();
        }
        Application.Run(form);
        if (args.Contains("--smoke-ui") && args.Contains("--ui-evidence") && smokeExitCode == 0 && form is CoordinateRecorderForm checkedRecorder)
        {
            try { checkedRecorder.VerifyClosedEvidence(); }
            catch (Exception error) { Console.Error.WriteLine(error.Message); smokeExitCode = 1; }
        }
        return smokeExitCode;
    }
}
