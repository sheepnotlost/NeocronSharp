using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace NavmeshPrototype;

/// <summary>
/// What one fight was like, kept so the hunt can be judged over many fights: how soon the crosshair found the mob's body,
/// how much of the fight it stayed on it, how often it lost it, how long it searched or backed away, and how it ended.
/// Written as one line to logs/fight-notes.jsonl when the fight ends; <see cref="HuntNotes"/> sums the lines up.
/// </summary>
internal sealed class FightNotes(string target, string id, float startAway, float aimHeight)
{
    private int _ticks, _locked, _searching, _backing, _losses, _marks, _measured;
    private bool _wasLocked;
    private double? _firstMark, _firstLock;
    private float _leastAway = startAway;
    private readonly List<float> _bodies = new();
    public bool Pin { get; set; }
    public bool PinRefused { get; set; }

    public void Tick(double now, float away, bool locked, bool searching, bool backing)
    {
        _ticks++;
        if (locked) { _locked++; _firstLock ??= now; }
        else if (_wasLocked) _losses++;
        _wasLocked = locked;
        if (searching) _searching++;
        if (backing) _backing++;
        _leastAway = MathF.Min(_leastAway, away);
    }

    public void Mark(double now, bool measured)
    {
        _marks++;
        if (measured) _measured++;
        _firstMark ??= now;
    }

    /// <summary>Where the body was drawn, in units above the mob's feet, from a look that found it.</summary>
    public void Body(float height) { if (float.IsFinite(height)) _bodies.Add(height); }

    public float? BodyHeight => _bodies.Count >= 3 ? _bodies.Order().ElementAt(_bodies.Count / 2) : null;

    public static string Outcome(string text) =>
        text.Contains(" died", StringComparison.Ordinal) ? "killed"
        : text.StartsWith("Switching to ", StringComparison.Ordinal) ? "switched"
        : text.Contains("No line of sight", StringComparison.Ordinal) ? "no-sight"
        : text.Contains("No damage", StringComparison.Ordinal) ? "no-damage"
        : text.Contains("Stop pressed", StringComparison.Ordinal) || text.Contains("F8", StringComparison.Ordinal) ? "stopped"
        : text.Contains("could not be read", StringComparison.Ordinal) ? "unreadable"
        : text.Contains("changed zone", StringComparison.Ordinal) ? "zoned"
        : "other";

    public JsonObject Line(double seconds, string ended) => new()
    {
        ["at"] = DateTimeOffset.UtcNow.ToString("o", CultureInfo.InvariantCulture),
        ["mob"] = target, ["id"] = id, ["outcome"] = Outcome(ended), ["ended"] = ended,
        ["seconds"] = Math.Round(seconds, 2),
        ["firstMark"] = _firstMark is { } m ? Math.Round(m, 2) : null,
        ["firstLock"] = _firstLock is { } l ? Math.Round(l, 2) : null,
        ["onBody"] = _ticks > 0 ? Math.Round((double)_locked / _ticks, 3) : 0,
        ["searching"] = _ticks > 0 ? Math.Round((double)_searching / _ticks, 3) : 0,
        ["backing"] = _ticks > 0 ? Math.Round((double)_backing / _ticks, 3) : 0,
        ["losses"] = _losses, ["marks"] = _marks, ["measured"] = _measured,
        ["startAway"] = Math.Round(startAway), ["leastAway"] = Math.Round(_leastAway),
        ["aimHeight"] = Math.Round(aimHeight, 1), ["bodyHeight"] = BodyHeight is { } h ? Math.Round(h, 1) : null,
        ["pin"] = Pin, ["pinRefused"] = PinRefused,
    };
}

/// <summary>
/// The hunt's notebook and what it has learned. Every fight adds a line to logs/fight-notes.jsonl; after each, logs/notes.md
/// is written fresh from the last <see cref="Window"/> lines: a table per mob, the last fights, and a list of what looks
/// wrong, for the user (and Claude) to read. logs/learned.json keeps, per mob, how high above its feet its body is drawn
/// and how big its brackets are at a given range, so the next fight aims at the body from the first look.
/// </summary>
internal static class HuntNotes
{
    public const int Window = 400, Recent = 15, Judge = 10, LeastToJudge = 3;
    /// <summary>Of each new fight's measure, the share taken into what is learned.</summary>
    public const float Learn = .35f;

    public static string Lines(string logs) => Path.Combine(logs, "fight-notes.jsonl");
    public static string Digest(string logs) => Path.Combine(logs, "notes.md");
    public static string LearnedFile(string logs) => Path.Combine(logs, "learned.json");

    public sealed record Learned(float? BodyHeight, float? WidthAtRange, float? HeightAtRange, int Fights);

    public static Learned? Recall(string logs, string mob)
    {
        try
        {
            var all = JsonNode.Parse(File.ReadAllText(LearnedFile(logs)))?["mobs"]?[Key(mob)];
            if (all == null) return null;
            return new((float?)all["bodyHeight"], (float?)all["widthAtRange"], (float?)all["heightAtRange"], (int?)all["fights"] ?? 0);
        }
        catch (Exception e) when (e is IOException or JsonException or InvalidOperationException or FormatException) { return null; }
    }

    public static void Remember(string logs, string mob, float? bodyHeight, (float Width, float Height)? sizeAtRange)
    {
        if (bodyHeight == null && sizeAtRange == null) return;
        JsonObject root;
        try { root = JsonNode.Parse(File.ReadAllText(LearnedFile(logs))) as JsonObject ?? new(); }
        catch (Exception e) when (e is IOException or JsonException) { root = new(); }
        var mobs = root["mobs"] as JsonObject ?? (JsonObject)(root["mobs"] = new JsonObject());
        var entry = mobs[Key(mob)] as JsonObject ?? (JsonObject)(mobs[Key(mob)] = new JsonObject());
        static float Blend(float? was, float now) => was is { } w ? w + Learn * (now - w) : now;
        if (bodyHeight is { } h) entry["bodyHeight"] = MathF.Round(Blend((float?)entry["bodyHeight"], h), 1);
        if (sizeAtRange is { } s)
        {
            entry["widthAtRange"] = MathF.Round(Blend((float?)entry["widthAtRange"], s.Width));
            entry["heightAtRange"] = MathF.Round(Blend((float?)entry["heightAtRange"], s.Height));
        }
        entry["fights"] = ((int?)entry["fights"] ?? 0) + 1;
        entry["name"] = mob;
        File.WriteAllText(LearnedFile(logs), root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
    }

    private static string Key(string mob) => string.Join(' ', mob.ToLowerInvariant().Split(' ', StringSplitOptions.RemoveEmptyEntries));

    public static void Add(string logs, JsonObject line)
    {
        File.AppendAllText(Lines(logs), line.ToJsonString() + Environment.NewLine);
        File.WriteAllText(Digest(logs), Write(Read(logs), DateTimeOffset.Now));
    }

    public static List<JsonObject> Read(string logs)
    {
        if (!File.Exists(Lines(logs))) return new();
        return File.ReadLines(Lines(logs)).TakeLast(Window)
            .Select(l => { try { return JsonNode.Parse(l) as JsonObject; } catch (JsonException) { return null; } })
            .OfType<JsonObject>().ToList();
    }

    private static string Pct(double v) => (v * 100).ToString("F0", CultureInfo.InvariantCulture) + "%";

    private static double Median(IEnumerable<double> values)
    {
        var v = values.Order().ToList();
        return v.Count == 0 ? double.NaN : v[v.Count / 2];
    }

    /// <summary>What looks wrong, mob by mob, over each one's last few fights.</summary>
    public static List<string> Flags(IReadOnlyList<JsonObject> fights)
    {
        var flags = new List<string>();
        foreach (var mob in fights.GroupBy(f => (string?)f["mob"] ?? "?"))
        {
            var last = mob.TakeLast(Judge).ToList();
            if (last.Count < LeastToJudge) continue;
            double Share(string outcome) => (double)last.Count(f => (string?)f["outcome"] == outcome) / last.Count;
            var locks = last.Select(f => (double?)f["firstLock"]).OfType<double>().ToList();
            double onBody = Median(last.Select(f => (double?)f["onBody"] ?? 0));
            double searching = Median(last.Select(f => (double?)f["searching"] ?? 0));
            double losses = last.Average(f => (double?)f["losses"] ?? 0);
            double neverLocked = (double)last.Count(f => f["firstLock"] == null && (string?)f["outcome"] != "switched") / last.Count;
            string n = $"{mob.Key} (last {last.Count} fights)";
            if (neverLocked >= .3) flags.Add($"{n}: no lock at all in {Pct(neverLocked)} of them.");
            if (locks.Count > 0 && Median(locks) > 2) flags.Add($"{n}: slow to lock on, {Median(locks):F1} s typically.");
            if (onBody < .5) flags.Add($"{n}: on the body only {Pct(onBody)} of a fight, typically.");
            if (losses > 4) flags.Add($"{n}: loses the body {losses:F1} times a fight.");
            if (searching > .4) flags.Add($"{n}: searching {Pct(searching)} of a fight: the marks aren't showing (too close, hidden, or off screen).");
            if (Share("no-sight") + Share("no-damage") >= .3) flags.Add($"{n}: {Pct(Share("no-sight") + Share("no-damage"))} ended with no line of sight or no damage.");
            if (Share("unreadable") >= .2) flags.Add($"{n}: {Pct(Share("unreadable"))} ended with your character unreadable (died, or zoned?).");
            double close = (double)last.Count(f => ((double?)f["leastAway"] ?? 999) < 60) / last.Count;
            if (close >= .3) flags.Add($"{n}: got within 60 units in {Pct(close)} of them, faster than backing away.");
        }
        if (fights.TakeLast(Judge * 3).Any(f => (bool?)f["pinRefused"] == true)) flags.Add("The game refused the camera pin: the mouse aimed instead.");
        return flags;
    }

    public static string Write(IReadOnlyList<JsonObject> fights, DateTimeOffset now)
    {
        var text = new StringBuilder();
        string P(double? v) => v is { } x && !double.IsNaN(x) ? Pct(x) : "-";
        string S(double? v) => v is { } x && !double.IsNaN(x) ? x.ToString("F1", CultureInfo.InvariantCulture) + " s" : "-";
        text.AppendLine("# Hunt notes").AppendLine();
        text.AppendLine($"Written by the hunt after every fight ({now:yyyy-MM-dd HH:mm}), from the last {fights.Count} fights. Ask Claude to read these notes to improve the hunt.").AppendLine();
        text.AppendLine("## Needs a look").AppendLine();
        var flags = Flags(fights);
        if (flags.Count == 0) text.AppendLine("Nothing stands out yet.");
        foreach (var flag in flags) text.AppendLine($"- {flag}");
        text.AppendLine().AppendLine("## By mob").AppendLine();
        text.AppendLine("| Mob | Fights | Killed | Lock found in | On the body | Lost it, per fight | Searching | Backing away | Aim height (units over its feet) |");
        text.AppendLine("|---|---|---|---|---|---|---|---|---|");
        foreach (var mob in fights.GroupBy(f => (string?)f["mob"] ?? "?").OrderByDescending(g => g.Count()))
        {
            var all = mob.ToList();
            var body = all.Select(f => (double?)f["bodyHeight"]).OfType<double>().ToList();
            text.AppendLine($"| {mob.Key} | {all.Count} | {all.Count(f => (string?)f["outcome"] == "killed")} | " +
                $"{S(Median(all.Select(f => (double?)f["firstLock"]).OfType<double>()))} | {P(Median(all.Select(f => (double?)f["onBody"] ?? 0)))} | " +
                $"{all.Average(f => (double?)f["losses"] ?? 0):F1} | {P(Median(all.Select(f => (double?)f["searching"] ?? 0)))} | " +
                $"{P(Median(all.Select(f => (double?)f["backing"] ?? 0)))} | {(body.Count > 0 ? Median(body).ToString("F0", CultureInfo.InvariantCulture) : "-")} |");
        }
        text.AppendLine().AppendLine($"## Last {Math.Min(Recent, fights.Count)} fights").AppendLine();
        text.AppendLine("| When | Mob | Ended | Took | Lock at | On the body | Lost it | From | Closest |");
        text.AppendLine("|---|---|---|---|---|---|---|---|---|");
        foreach (var f in fights.TakeLast(Recent).Reverse())
        {
            string when = DateTimeOffset.TryParse((string?)f["at"], CultureInfo.InvariantCulture, DateTimeStyles.None, out var at) ? at.ToLocalTime().ToString("HH:mm:ss") : "?";
            text.AppendLine($"| {when} | {f["mob"]} | {f["outcome"]} | {S((double?)f["seconds"])} | {S((double?)f["firstLock"])} | {P((double?)f["onBody"])} | " +
                $"{f["losses"]} | {f["startAway"]} | {f["leastAway"]} |");
        }
        return text.ToString();
    }
}
