using System.Globalization;
using System.Text.RegularExpressions;

namespace NeocronSharp.Core;

public sealed class PlayerDefinitions
{
    private readonly Dictionary<int, Dictionary<string, string>> _weapons, _factions;
    private readonly Dictionary<int, string> _models;
    private PlayerDefinitions(Dictionary<int, Dictionary<string, string>> weapons, Dictionary<int, Dictionary<string, string>> factions,
        Dictionary<int, string> models) { _weapons = weapons; _factions = factions; _models = models; }
    public static PlayerDefinitions Load(string install)
    {
        Dictionary<int, Dictionary<string, string>> Table(string name)
        {
            try { return NpcDefinitions.Parse(File.ReadAllBytes(Path.Combine(install, "definitions", name))); }
            catch (Exception e) when (e is IOException or InvalidDataException or ArgumentException) { return new(); }
        }
        var models = new Dictionary<int, string>();
        try
        {
            string text = NpcDefinitions.DecodeText(File.ReadAllBytes(Path.Combine(install, "models", "pak_models.ini")));
            string section = "";
            foreach (string raw in text.Split('\n'))
            {
                string line = raw.Trim(); if (line.StartsWith('[')) { section = line; continue; }
                if (!section.Equals("[PLAYER]", StringComparison.OrdinalIgnoreCase)) continue;
                var match = Regex.Match(line, "^set\\s+(\\d+)\\s+\"([^\"]+)\"");
                if (match.Success) models[int.Parse(match.Groups[1].Value, CultureInfo.InvariantCulture)] = match.Groups[2].Value.Replace('\\', '/');
            }
        }
        catch (Exception e) when (e is IOException or InvalidDataException or ArgumentException) { }
        return new(Table("pak_weapons.csv"), Table("pak_factions.csv"), models);
    }
    public WorldEntity Enrich(WorldEntity entity)
    {
        if (entity.Player is not { } player) return entity;
        string? Field(Dictionary<string, string>? row, string name) => row?.GetValueOrDefault(name);
        int? Number(Dictionary<string, string>? row, string name) => int.TryParse(Field(row, name), NumberStyles.Integer, CultureInfo.InvariantCulture, out int value) ? value : null;
        float? Real(Dictionary<string, string>? row, string name) => float.TryParse(Field(row, name), NumberStyles.Float, CultureInfo.InvariantCulture, out float value) && float.IsFinite(value) ? value : null;
        var gear = player.Gear.Select(item =>
        {
            if (item.DefinitionId is not { } id) return item;
            if (item.Slot.StartsWith("Visible weapon"))
            {
                _weapons.TryGetValue(id, out var row);
                return item with { Name = Field(row, "Name"), TechLevel = Number(row, "Level"), BaseRange = Real(row, "Range"),
                    MagazineSize = Number(row, "ClipSize"), ShotsPerBurst = Number(row, "ShotCount") };
            }
            if (item.Slot.Contains("texture selector")) return item;
            return _models.TryGetValue(id, out string? asset) ? item with { Asset = asset, Name = Path.GetFileNameWithoutExtension(asset).Replace('_', ' ') } : item;
        }).ToArray();
        _factions.TryGetValue(player.FactionId ?? -1, out var faction);
        return entity with { Player = player with { FactionName = player.FactionId > 0 ? Field(faction, "Name") : null, Gear = gear } };
    }
}
