using System.Buffers.Binary;
using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.Json.Nodes;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// Every robot, mutant and animal the game client places, sector by sector, from each sector's spawn file: single spawns
/// (record 1000006, the NPC id at byte 16) and spawn groups (record 1000009: the pak_npcgroupspawns id at byte 14, whose
/// mobs are in pak_npcgroupspawnchildren, then how many it keeps up and over what radius: a wasteland sector has one, such as
/// 20 within 3000 units in E 05 Swamp; indoors the radius is 0). Level, health and weapon come from pak_npcs and pak_weapons. A mob with no
/// weapon there attacks with its own body, whose reach only the server knows: logs/mob-reach.json, written by the hunt
/// from where a mob was when your health fell, says what was seen. These are the client's copies: the server can differ.
/// </summary>
internal static class MobMap
{
    private const uint NpcSpawn = 1000006, GroupSpawn = 1000009;
    /// <summary>pak_factions: Robot, Mutant, Wildlife (the hunt's prey).</summary>
    private static readonly HashSet<string> Prey = new() { "16", "17", "18" };
    /// <summary>Weapon range (the game's own measure) at or under which an attack is a melee one: fists and bats are 4.</summary>
    public const float MeleeRange = 10;

    /// <summary>Where: per sector, each spawn point that can put it there, how many of it the point keeps up (its count weighed by
    /// the spawn chances) and over what radius.</summary>
    public sealed record Mob(string Name, int Level, int Health, string Attack, float? Range, Dictionary<string, List<(Vector3 At, float Share, float Radius)>> Where)
    {
        /// <summary>How many of it a full spawn round puts in a sector: its shares summed.</summary>
        public float In(string sector) => Where.TryGetValue(sector, out var points) ? points.Sum(p => p.Share) : 0;
    }

    /// <summary>Units: how far a spot's spawn points may be from its middle (a few seconds' run).</summary>
    public const float SpotRadius = 1500;

    /// <summary>Where to stand for it: the sector, and the place there with the most of it within <see cref="SpotRadius"/>.</summary>
    public static (string Sector, Vector3 At, float Count, float Radius)? Best(Mob mob)
    {
        (string, Vector3, float, float)? best = null;
        foreach (var (sector, points) in mob.Where)
            foreach (var (at, _, _) in points)
            {
                var near = points.Where(p => Vector3.Distance(p.At, at) <= SpotRadius).ToList();
                float count = near.Sum(p => p.Share);
                if (best is not { } b || count > b.Item3 + 1e-3f)
                    best = (sector, near.Aggregate(Vector3.Zero, (sum, p) => sum + p.At) / near.Count, count, Math.Max(near.Max(p => p.Radius), near.Count > 1 ? near.Max(p => Vector3.Distance(p.At, at)) : 0));
            }
        return best;
    }

    public static List<Mob> Build(string install, Travel travel)
    {
        Dictionary<int, Dictionary<string, string>> Table(string name) =>
            NpcDefinitions.Parse(File.ReadAllBytes(Path.Combine(install, "definitions", $"pak_{name}.csv")));
        var npcs = Table("npcs"); var characters = Table("characters"); var weapons = Table("weapons");
        var groups = new Dictionary<int, List<(int Id, float Chance)>>();
        foreach (var row in NpcDefinitions.ParseRows(File.ReadAllBytes(Path.Combine(install, "definitions", "pak_npcgroupspawnchildren.csv"))))
            if (row.GetValueOrDefault("Enabled") == "1" && int.TryParse(row.GetValueOrDefault("EntryId"), out int g) && int.TryParse(row.GetValueOrDefault("NpcId"), out int n))
                (groups.TryGetValue(g, out var list) ? list : groups[g] = new()).Add((n, float.TryParse(row.GetValueOrDefault("SpawnChance"), NumberStyles.Float, CultureInfo.InvariantCulture, out float chance) ? chance : 1));

        var mobs = new Dictionary<string, Mob>(StringComparer.Ordinal);
        void Add(int id, string sector, Vector3 at, float share, float radius)
        {
            if (!npcs.TryGetValue(id, out var npc) || npc.GetValueOrDefault("Enabled") != "1" || !Prey.Contains(npc.GetValueOrDefault("FactionId", ""))) return;
            if (npc.GetValueOrDefault("ModelTargetType") != "1" || !int.TryParse(npc.GetValueOrDefault("ModelTargetValue"), out int c)
                || !characters.TryGetValue(c, out var ch) || ch.GetValueOrDefault("Name") is not { Length: > 0 } raw) return;
            string name = string.Join(' ', raw.Replace("\\n", " ").Replace("\n", " ").Split(' ', StringSplitOptions.RemoveEmptyEntries));   // "Dome of York\nGuardian"
            int level = int.TryParse(npc.GetValueOrDefault("Skill"), out int l) ? l : 0;
            int health = int.TryParse(npc.GetValueOrDefault("Health"), out int h) ? h : 0;
            string attack = "own body"; float? range = null;
            if (int.TryParse(npc.GetValueOrDefault("WeaponId"), out int w) && weapons.TryGetValue(w, out var weapon))
            {
                attack = weapon.GetValueOrDefault("Name", "weapon").Replace("NPC ", "");
                if (float.TryParse(weapon.GetValueOrDefault("Range"), NumberStyles.Float, CultureInfo.InvariantCulture, out float r)) range = r;
            }
            string key = $"{name}|{level}|{attack}";
            if (!mobs.TryGetValue(key, out var mob)) mobs[key] = mob = new Mob(name, level, health, attack, range, new());
            (mob.Where.TryGetValue(sector, out var points) ? points : mob.Where[sector] = new()).Add((at, share, radius));
        }

        foreach (var area in travel.Areas)
        {
            byte[] bytes;
            try
            {
                string file = SectorObjects.SpawnFile(install, area.WorldId, area.AssetPath);
                if (!File.Exists(file)) continue;
                bytes = File.ReadAllBytes(file);
                try { bytes = NpcDefinitions.DecodeBytes(bytes); } catch (InvalidDataException) { }   // stored unpacked
            }
            catch (Exception e) when (e is IOException or ArgumentException or InvalidDataException) { continue; }
            string sector = travel.SectorName(area.WorldId);
            foreach (var (type, element) in WorldObjects.Elements(bytes))
            {
                if (type == NpcSpawn && element.Length >= 20) Add((int)BinaryPrimitives.ReadUInt32LittleEndian(element.AsSpan(16, 4)), sector, Vec(element, 4), 1, 0);
                else if (type == GroupSpawn && element.Length >= 20 && groups.TryGetValue(BinaryPrimitives.ReadUInt16LittleEndian(element.AsSpan(14, 2)), out var members))
                {
                    // One pick per spawn, weighed by SpawnChance: a mob that is one of three equal choices counts a third.
                    float total = members.Sum(m => m.Chance);
                    int count = Math.Max(1, (int)BinaryPrimitives.ReadUInt16LittleEndian(element.AsSpan(16, 2)));
                    float radius = BinaryPrimitives.ReadUInt16LittleEndian(element.AsSpan(18, 2));
                    foreach (var pick in members.GroupBy(m => m.Id)) Add(pick.Key, sector, Vec(element, 0), total > 0 ? count * pick.Sum(m => m.Chance) / total : 0, radius);
                }
            }
        }
        return mobs.Values.OrderByDescending(m => m.Level).ThenBy(m => m.Name, StringComparer.Ordinal).ToList();
    }

    private static Vector3 Vec(byte[] e, int at) => new(BitConverter.ToSingle(e, at), BitConverter.ToSingle(e, at + 4), BitConverter.ToSingle(e, at + 8));

    /// <summary>"melee", "ranged" or "?" from the weapon, else from what the hunt saw.</summary>
    public static string Kind(Mob mob, Reach? seen) =>
        mob.Range is { } r ? (r <= MeleeRange ? "melee" : "ranged")
        : seen is { Hits: >= Reach.Enough } s ? (s.Typical > Reach.MeleeUnits ? "ranged (seen)" : "melee (seen)")
        : "?";

    public static string Write(IReadOnlyList<Mob> mobs, IReadOnlyDictionary<string, Reach> seen, int least)
    {
        var text = new StringBuilder();
        text.AppendLine("# Mob map").AppendLine();
        text.AppendLine($"Every robot, mutant and animal of level {least} and up that the game's own files place, highest first. " +
            "\"Own body\" attacks have no range in the files: \"Hit you from\" is what the hunt saw (units between you and the only mob near when your health fell). " +
            $"Counts are how many of it the game keeps up there, by its spawn counts and chances. \"Best spot\" is the place with the most of it: " +
            "the middle of the spawn zone (x, z) and how far out they roam. " +
            "The server can spawn differently from these files.").AppendLine();
        text.AppendLine("| Mob | Level | Health | Attack | Melee or ranged | Hit you from | Best spot | Where (how many) |");
        text.AppendLine("|---|---|---|---|---|---|---|---|");
        foreach (var mob in mobs.Where(m => m.Level >= least))
        {
            seen.TryGetValue(Reach.Key(mob.Name), out var reach);
            string attack = mob.Range is { } r ? $"{mob.Attack} (range {r:F0})" : mob.Attack;
            string hit = reach is { Hits: > 0 } h ? $"{h.Typical:F0} units ({h.Hits} hit{(h.Hits == 1 ? "" : "s")})" : "-";
            string spot = Best(mob) is { } b ? $"{b.Sector}: {b.Count:0.#} within {b.Radius:F0} of ({b.At.X:F0}, {b.At.Z:F0})" : "-";
            string where = string.Join(", ", mob.Where.Keys.OrderByDescending(mob.In).Take(4).Select(k => $"{k} ({mob.In(k):0.#})"))
                + (mob.Where.Count > 4 ? $", +{mob.Where.Count - 4} more" : "");
            text.AppendLine($"| {mob.Name} | {mob.Level} | {mob.Health} | {attack} | {Kind(mob, reach)} | {hit} | {spot} | {where} |");
        }
        return text.ToString();
    }

    /// <summary>What the hunt saw of one mob's reach: the median distance it hit from, over its last hits.</summary>
    public sealed record Reach(int Hits, float Typical)
    {
        public const int Enough = 3;
        /// <summary>Units: a hit from further than this was not a bite or a punch.</summary>
        public const float MeleeUnits = 150;
        public static string Key(string mob) => string.Join(' ', mob.ToLowerInvariant().Split(' ', StringSplitOptions.RemoveEmptyEntries));

        public static Dictionary<string, Reach> Load(string file)
        {
            var all = new Dictionary<string, Reach>(StringComparer.Ordinal);
            try
            {
                if (JsonNode.Parse(File.ReadAllText(file)) is not JsonObject root) return all;
                foreach (var (name, node) in root)
                {
                    var away = (node?["away"] as JsonArray)?.Select(a => (float?)a).OfType<float>().Order().ToList();
                    if (away is { Count: > 0 }) all[Key(name)] = new Reach(away.Count, away[away.Count / 2]);
                }
            }
            catch (Exception e) when (e is IOException or System.Text.Json.JsonException or InvalidOperationException or FormatException) { }
            return all;
        }
    }
}
