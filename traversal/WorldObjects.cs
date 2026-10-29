using System.Buffers.Binary;
using System.Numerics;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// Named places inside a sector, from the game client's own spawn file for it (the world's
/// .dat, next to its .bsp): placed objects (GenRep, CityCom, GoGuardian, Venture Warp,
/// apartment and sewer doors, Hacknet logins...) and NPC spawns (traders, quest NPCs).
/// Names come from definitions\pak_worldmodels, pak_npcs and pak_characters.
/// These are the client's copy: the server can spawn differently.
/// </summary>
internal sealed class WorldObjects(string install, Travel travel)
{
    /// <summary>One place: Kind is what it is ("GenRep", "Trader"...), Labels the names of the spawns it groups.</summary>
    public sealed record Place(int World, string Kind, string Name, Vector3 Position, IReadOnlyList<string> Labels);

    // pak_worldmodels Type -> kind. Types not listed (doors, lifts, lights, furniture) are skipped.
    private static readonly Dictionary<int, string> ObjectKinds = new()
    {
        [6] = "GenRep", [2] = "CityCom", [31] = "Venture Warp", [3] = "Outfitter", [7] = "GoGuardian",
        [9] = "Apartment", [10] = "Apartment", [24] = "Apartment", [18] = "Sewer entrance", [20] = "Entrance",
        [28] = "Vehicle depot", [33] = "Hacknet login", [17] = "Recreation unit", [14] = "Holomatch",
        [23] = "Paid entrance", [12] = "Access door", [13] = "Access door",
    };

    // Background NPCs a player would not walk to.
    private static readonly HashSet<string> Background = new(StringComparer.Ordinal)
    {
        "Furniture", "Jailhouse Guard", "Pest Controller", "Tmp", "NEMA Papergirl", "Street Hawker", "COPBOT", "Inquisitor",
        "Grand Inquisitor", "Dancer", "Bum", "Aggressor", "Barvisitor", "S.T.O.R.M. BOT", "Service", "Cleaning Bot",
        "Mutant Soldier", "Mutant Warrior", "Employee", "Pimp", "Novice", "Contact", "Contact Person",
    };

    private const uint PlacedObject = 1000003, NpcSpawn = 1000006;
    private Dictionary<int, Dictionary<string, string>>? _models, _npcs, _characters;

    private Dictionary<int, Dictionary<string, string>> Table(string name) =>
        NpcDefinitions.Parse(File.ReadAllBytes(Path.Combine(install, "definitions", $"pak_{name}.csv")));

    /// <summary>The named places in one sector, grouped (a shop's several counters are one place).</summary>
    public List<Place> In(int world)
    {
        _models ??= Table("worldmodels"); _npcs ??= Table("npcs"); _characters ??= Table("characters");
        var raw = new List<(string Kind, string Label, Vector3 At)>();
        foreach (var (type, element) in Elements(Read(world)))
        {
            if (type == PlacedObject && element.Length >= 46)
            {
                int id = BinaryPrimitives.ReadUInt16LittleEndian(element.AsSpan(44, 2));
                if (_models.TryGetValue(id, out var model) && int.TryParse(model.GetValueOrDefault("Type"), out int t) && ObjectKinds.TryGetValue(t, out var kind))
                    raw.Add((kind, Clean(model.GetValueOrDefault("Name", kind)), Vec(element, 0)));
            }
            else if (type == NpcSpawn && element.Length >= 20)
            {
                int id = (int)BinaryPrimitives.ReadUInt32LittleEndian(element.AsSpan(16, 4));
                if (!_npcs.TryGetValue(id, out var npc)) continue;
                string name = npc.GetValueOrDefault("ModelTargetType") == "1" && int.TryParse(npc.GetValueOrDefault("ModelTargetValue"), out int c)
                    && _characters.TryGetValue(c, out var ch) ? Clean(ch.GetValueOrDefault("Name", "")) : "";
                if (name.Length == 0 || Background.Contains(name)) continue;
                string? kind = name.StartsWith("Venture Warp", StringComparison.Ordinal) ? "Venture Warp"
                    : npc.GetValueOrDefault("NpcFunctionType") switch { "1" => "Trader", "2" => "NPC", _ => null };
                if (kind != null) raw.Add((kind, name, Vec(element, 4)));
            }
        }
        // Group same-kind places (traders and apartments by brand, the text before " / ") within 400 units.
        var groups = new List<(string Kind, string Key, List<(string Label, Vector3 At)> Members)>();
        foreach (var (kind, label, at) in raw)
        {
            string key = kind is "Trader" or "Apartment" ? label.Split(" / ")[0] : kind is "GenRep" or "CityCom" or "GoGuardian" or "Venture Warp" or "Outfitter" ? "" : label;
            var group = groups.FirstOrDefault(g => g.Kind == kind && g.Key == key && g.Members.Any(m => Vector3.Distance(m.At, at) < 400));
            if (group.Members != null) group.Members.Add((label, at)); else groups.Add((kind, key, new() { (label, at) }));
        }
        return groups.Select(g =>
        {
            var labels = g.Members.Select(m => m.Label).Distinct().ToList();
            string name = g.Kind == "Trader" && labels.Count > 1
                ? $"{g.Key} ({string.Join(", ", labels.Take(3).Select(l => l.Contains(" / ") ? l[(l.IndexOf(" / ") + 3)..] : l))}{(labels.Count > 3 ? ", ..." : "")})"
                : g.Key.Length > 0 && g.Kind != "Trader" ? g.Key : labels[0];
            return new Place(world, g.Kind, name, g.Members[0].At, labels);
        }).ToList();
    }

    /// <summary>Every placed object in a sector's spawn file: its record number (0 = first), pak_worldmodels id and position.</summary>
    public IEnumerable<(int Record, int Model, Vector3 At)> Placed(int world)
    {
        int record = 0;
        foreach (var (type, element) in Elements(Read(world)))
        {
            if (type != PlacedObject) continue;
            if (element.Length >= 46) yield return (record, BinaryPrimitives.ReadUInt16LittleEndian(element.AsSpan(44, 2)), Vec(element, 0));
            record++;
        }
    }

    // "Archer & Wesson\nBasic Armor" -> "Archer & Wesson / Basic Armor"; "---LOW SEC LOGIN--- Plaza1" -> "LOW SEC LOGIN Plaza1".
    private static string Clean(string name) => string.Join(' ', name.Replace("\\n", " / ").Replace("\n", " / ").Replace("---", " ")
        .Split(' ', StringSplitOptions.RemoveEmptyEntries));

    private static Vector3 Vec(byte[] e, int at) => new(BitConverter.ToSingle(e, at), BitConverter.ToSingle(e, at + 4), BitConverter.ToSingle(e, at + 8));

    /// <summary>The sector's decoded .dat: same folder and name as its world asset, "pak_" in front.</summary>
    private byte[] Read(int world)
    {
        var area = travel.Areas.FirstOrDefault(a => a.WorldId == world) ?? throw new InvalidDataException($"No world asset for sector {world}.");
        string rel = Path.ChangeExtension(area.AssetPath, ".dat").Replace('/', Path.DirectorySeparatorChar);
        string full = Path.Combine(install, Path.GetDirectoryName(rel) ?? "", "pak_" + Path.GetFileName(rel));
        if (!File.Exists(full)) throw new FileNotFoundException($"No spawn file for {travel.SectorName(world)}.", full);
        byte[] bytes = File.ReadAllBytes(full);
        try { return NpcDefinitions.DecodeBytes(bytes); }
        catch (InvalidDataException) { return bytes; }   // stored unpacked
    }

    /// <summary>Section 2 of a .dat is a list of typed records: (type, bytes). Stops at the first malformed header.</summary>
    internal static IEnumerable<(uint Type, byte[] Data)> Elements(byte[] file)
    {
        if (file.Length < 4) yield break;
        long p = 4L + BinaryPrimitives.ReadUInt32LittleEndian(file);
        while (p + 16 <= file.Length)
        {
            // Each header is u32 header size (12: the three fields after it), u32, u32 type, u32 size.
            uint header = BinaryPrimitives.ReadUInt32LittleEndian(file.AsSpan((int)p));
            uint section = BinaryPrimitives.ReadUInt32LittleEndian(file.AsSpan((int)p + 8));
            uint size = BinaryPrimitives.ReadUInt32LittleEndian(file.AsSpan((int)p + 12));
            if (header < 12) yield break;
            p += 4L + header;
            if (p + size > file.Length) yield break;
            if (section == 2)
            {
                long q = p, end = p + size;
                while (q + 16 <= end)
                {
                    uint h = BinaryPrimitives.ReadUInt32LittleEndian(file.AsSpan((int)q));
                    uint type = BinaryPrimitives.ReadUInt32LittleEndian(file.AsSpan((int)q + 8));
                    uint length = BinaryPrimitives.ReadUInt32LittleEndian(file.AsSpan((int)q + 12));
                    if (h < 12) break;
                    q += 4L + h;
                    if (q + length > end) break;
                    yield return (type, file.AsSpan((int)q, (int)length).ToArray());
                    q += length;
                }
            }
            p += size;
        }
    }
}
