using System.Buffers.Binary;
using System.Globalization;
using System.Text;
using System.Text.Json.Nodes;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// Every robot, mutant and animal the game client places, sector by sector, from each sector's spawn file: single spawns
/// (record 1000006, the NPC id at byte 16) and spawn groups (record 1000009, the pak_npcgroupspawns id at byte 14, whose
/// mobs are in pak_npcgroupspawnchildren). Level, health and weapon come from pak_npcs and pak_weapons. A mob with no
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

    public sealed record Mob(string Name, int Level, int Health, string Attack, float? Range, Dictionary<string, int> Where);

    public static List<Mob> Build(string install, Travel travel)
    {
        Dictionary<int, Dictionary<string, string>> Table(string name) =>
            NpcDefinitions.Parse(File.ReadAllBytes(Path.Combine(install, "definitions", $"pak_{name}.csv")));
        var npcs = Table("npcs"); var characters = Table("characters"); var weapons = Table("weapons");
        var groups = new Dictionary<int, List<int>>();
        foreach (var row in NpcDefinitions.ParseRows(File.ReadAllBytes(Path.Combine(install, "definitions", "pak_npcgroupspawnchildren.csv"))))
            if (int.TryParse(row.GetValueOrDefault("EntryId"), out int g) && int.TryParse(row.GetValueOrDefault("NpcId"), out int n))
                (groups.TryGetValue(g, out var list) ? list : groups[g] = new()).Add(n);

        var mobs = new Dictionary<string, Mob>(StringComparer.Ordinal);
        void Add(int id, string sector)
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
            mob.Where[sector] = mob.Where.GetValueOrDefault(sector) + 1;
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
                if (type == NpcSpawn && element.Length >= 20) Add((int)BinaryPrimitives.ReadUInt32LittleEndian(element.AsSpan(16, 4)), sector);
                else if (type == GroupSpawn && element.Length >= 16 && groups.TryGetValue(BinaryPrimitives.ReadUInt16LittleEndian(element.AsSpan(14, 2)), out var members))
                    foreach (int id in members.Distinct()) Add(id, sector);
            }
        }
        return mobs.Values.OrderByDescending(m => m.Level).ThenBy(m => m.Name, StringComparer.Ordinal).ToList();
    }

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
            "The server can spawn differently from these files.").AppendLine();
        text.AppendLine("| Mob | Level | Health | Attack | Melee or ranged | Hit you from | Where (spawn points) |");
        text.AppendLine("|---|---|---|---|---|---|---|");
        foreach (var mob in mobs.Where(m => m.Level >= least))
        {
            seen.TryGetValue(Reach.Key(mob.Name), out var reach);
            string attack = mob.Range is { } r ? $"{mob.Attack} (range {r:F0})" : mob.Attack;
            string hit = reach is { Hits: > 0 } h ? $"{h.Typical:F0} units ({h.Hits} hit{(h.Hits == 1 ? "" : "s")})" : "-";
            string where = string.Join(", ", mob.Where.OrderByDescending(p => p.Value).Take(4).Select(p => $"{p.Key} ({p.Value})"))
                + (mob.Where.Count > 4 ? $", +{mob.Where.Count - 4} more" : "");
            text.AppendLine($"| {mob.Name} | {mob.Level} | {mob.Health} | {attack} | {Kind(mob, reach)} | {hit} | {where} |");
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
