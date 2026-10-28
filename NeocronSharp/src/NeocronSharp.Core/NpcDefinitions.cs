using System.Buffers.Binary;
using System.Globalization;
using System.IO.Compression;
using System.Text;
using Microsoft.VisualBasic.FileIO;

namespace NeocronSharp.Core;

/// <summary>Loads optional local references; native readings remain authoritative.</summary>
public sealed class NpcDefinitions
{
    public const int MaxDefinitionBytes = 32 * 1024 * 1024;
    private static readonly byte[] Magic = { 0x0a, 0xf7, 0x3d, 0x88, 0x84, 0x75, 0x84, 0x93, 0xbd, 0xef, 0xfd, 0xab };
    private readonly Dictionary<int, Dictionary<string, string>> _npcs, _factions, _weapons;
    public IReadOnlyList<string> Issues { get; }

    private NpcDefinitions(Dictionary<int, Dictionary<string, string>> npcs,
        Dictionary<int, Dictionary<string, string>> factions, Dictionary<int, Dictionary<string, string>> weapons, IReadOnlyList<string> issues)
    { _npcs = npcs; _factions = factions; _weapons = weapons; Issues = issues; }

    public static NpcDefinitions Load(string installDirectory)
    {
        var issues = new List<string>();
        Dictionary<int, Dictionary<string, string>> LoadTable(string name)
        {
            try
            {
                var path = Path.Combine(installDirectory, "definitions", name);
                var info = new FileInfo(path);
                if (!info.Exists || info.Length > MaxDefinitionBytes) throw new InvalidDataException("missing or oversized file");
                return Parse(File.ReadAllBytes(path));
            }
            catch (Exception error) when (error is IOException or InvalidDataException or UnauthorizedAccessException or DecoderFallbackException or MalformedLineException)
            { issues.Add($"{name}: {error.Message}"); return new(); }
        }
        return new(LoadTable("pak_npcs.csv"), LoadTable("pak_factions.csv"), LoadTable("pak_weapons.csv"), issues);
    }

    public WorldEntity Enrich(WorldEntity entity)
    {
        if (entity.Stats is not { } stats) return entity;
        _npcs.TryGetValue(stats.TemplateId, out var npc);
        Dictionary<string, string>? faction = null;
        // Entry zero in this table is Soul Light, not a verified faction label
        // for NPCs whose faction field is zero.
        if (stats.FactionId is { } factionId && factionId > 0) _factions.TryGetValue(factionId, out faction);
        _weapons.TryGetValue(stats.WeaponId, out var weapon);
        string? Field(Dictionary<string, string>? row, string name) => row != null && row.TryGetValue(name, out var value) && !string.IsNullOrWhiteSpace(value) ? value : null;
        int? Number(Dictionary<string, string>? row, string name) => int.TryParse(Field(row, name), NumberStyles.Integer, CultureInfo.InvariantCulture, out int value) ? value : null;
        float? Real(Dictionary<string, string>? row, string name) => float.TryParse(Field(row, name), NumberStyles.Float, CultureInfo.InvariantCulture, out float value) && float.IsFinite(value) ? value : null;
        return entity with { ReferenceData = new(Field(faction, "Name"), Field(weapon, "Name"), Number(weapon, "Level"), Real(weapon, "Range"),
            Number(npc, "Skill"), Number(npc, "Health"), Field(npc, "AIScript"), Field(npc, "DialogScript"), Number(weapon, "ClipSize"), Number(weapon, "ShotCount")) };
    }

    public static Dictionary<int, Dictionary<string, string>> Parse(byte[] file)
    {
        var result = new Dictionary<int, Dictionary<string, string>>();
        foreach (var row in ParseRows(file))
            if (!result.TryAdd(int.Parse(row["EntryId"], CultureInfo.InvariantCulture), row)) throw new InvalidDataException("Duplicate definition ID.");
        return result;
    }

    public static IReadOnlyList<Dictionary<string, string>> ParseRows(byte[] file)
    {
        string decoded = DecodeText(file);
        using var parser = new TextFieldParser(new StringReader(decoded))
        { TextFieldType = FieldType.Delimited, HasFieldsEnclosedInQuotes = true, TrimWhiteSpace = false };
        parser.SetDelimiters(",");
        string[] headers = parser.ReadFields() ?? throw new InvalidDataException("Missing definition columns.");
        if (headers.Length > 128 || headers.Distinct(StringComparer.Ordinal).Count() != headers.Length || !headers.Contains("EntryId") || !headers.Contains("Enabled"))
            throw new InvalidDataException("Invalid definition columns.");
        var rows = new List<Dictionary<string, string>>();
        int rowCount = 0;
        while (!parser.EndOfData)
        {
            if (++rowCount > 100000) throw new InvalidDataException("Too many definition rows.");
            string[] values = parser.ReadFields() ?? throw new InvalidDataException("Empty definition row.");
            if (values.Length != headers.Length || values.Any(v => v.Length > 4096)) throw new InvalidDataException("Invalid definition row.");
            var row = headers.Zip(values).ToDictionary(x => x.First, x => x.Second, StringComparer.Ordinal);
            if (!int.TryParse(row["EntryId"], NumberStyles.Integer, CultureInfo.InvariantCulture, out int id)) throw new InvalidDataException("Invalid definition ID.");
            if (row["Enabled"] != "1") continue;
            rows.Add(row);
        }
        return rows;
    }

    public static string DecodeText(byte[] file) => new UTF8Encoding(false, true).GetString(DecodeBytes(file));

    public static byte[] DecodeBytes(byte[] file)
    {
        if (file.Length < 18 || file.Length > MaxDefinitionBytes || !file.AsSpan(0, 12).SequenceEqual(Magic))
            throw new InvalidDataException("Unrecognized definition header.");
        int expected = BinaryPrimitives.ReadInt32LittleEndian(file.AsSpan(12, 4));
        if (expected is <= 0 or > MaxDefinitionBytes) throw new InvalidDataException("Definition size exceeds the read limit.");
        using var source = new MemoryStream(file, 16, file.Length - 16, writable: false);
        using var compressed = new ZLibStream(source, CompressionMode.Decompress);
        byte[] text = new byte[expected];
        compressed.ReadExactly(text);
        if (compressed.ReadByte() != -1) throw new InvalidDataException("Definition length does not match its header.");
        return text;
    }
}
