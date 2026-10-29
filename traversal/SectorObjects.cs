using System.Buffers.Binary;
using System.Numerics;
using System.Text;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// What a sector's spawn file (<c>pak_&lt;world&gt;.dat</c>) places that its level geometry does not have:
/// solid props (barrels, crates, benches, desks, invisible walls...) cut out of the navmesh, and the
/// doors inside the sector (opened with one right click when one stops a walk).
/// <list type="bullet">
/// <item>Record 1000003, a placed object (76 bytes): position at 0, rotation in degrees at 12
/// (pitch, yaw, roll), scale at 24 (the box below already has it), the 3D model (models\pak_models.ini [STATIC]) at 32, the
/// pak_worldmodels id (u16) at 44, its bounding box about the position, unturned (min xyz, max xyz), at 52.</item>
/// <item>Record 1000005, a door: position at 4, its id (u16) at 20, then text such as
/// "DDOOR2,78,3,1" (78 is the other half of a split door). Elevators ("ELEVATOR") and buttons
/// share the record and are not doors.</item>
/// </list>
/// These are the client's copy; the server can spawn differently.
/// </summary>
internal static class SectorObjects
{
    /// <summary>A solid prop: its footprint (four x,z corners, padded) and the heights it spans.</summary>
    public sealed record Prop(string Name, Vector3 Position, Vector2[] Footprint, float Bottom, float Top);

    /// <summary>A door inside the sector (both halves of a split door are one door).</summary>
    public sealed record Door(string Name, Vector3 Position);

    public sealed record Contents(IReadOnlyList<Prop> Props, IReadOnlyList<Door> Doors);

    private const uint PlacedObject = 1000003, DoorRecord = 1000005;

    /// <summary>Padding round a prop's box, for the character's body (Recast does not shrink cut-out areas by the agent radius).</summary>
    public const float Pad = 12;

    /// <summary>Lower than this a prop is stepped over (the navmesh climbs 24); wider than this it is a structure, maybe walked on.</summary>
    public const float MinHeight = 24, MaxSide = 400;
    /// <summary>Smaller than this across both ways (a bottle, a can) it does not stop you.</summary>
    public const float MinSide = 20;
    /// <summary>A tilted prop is bounded by a sphere; past this size that bound is too coarse to use.</summary>
    public const float MaxTilted = 160;
    /// <summary>A tree's box holds its crown: only the trunk, this wide, is cut out.</summary>
    public const float Trunk = 32;
    private static readonly string[] Trees = { "baum", "tanne", "tree", "palm", "pine", "fichte", "birke" };

    // pak_worldmodels types that are ways in or out, or that the walker is sent to stand at: never cut out.
    // 9/10/24 apartment lifts, 12/13 access doors, 18 sewer entrances, 20 entrances, 21 apartment door
    // numbers, 23 paid entrances, 29 underground exits.
    private static readonly HashSet<int> PassTypes = new() { 9, 10, 12, 13, 18, 20, 21, 23, 24, 29 };
    // Names (worldmodel or model file) that are not solid, or are doors and lifts.
    private static readonly string[] PassNames = { "DOOR", "LIFT", "AIRLOCK", "SHUTTER", "ELEVATOR", "ENTRANCE", "EXIT", "GATE", "HOLO", "LIGHT", "DECAL", "GRAV", "WATER", "PARTICLE" };

    private static readonly Dictionary<string, (Dictionary<int, Dictionary<string, string>> Worldmodels, Dictionary<int, string> Models)> Tables = new();

    private static (Dictionary<int, Dictionary<string, string>> Worldmodels, Dictionary<int, string> Models) TablesFor(string install)
    {
        lock (Tables)
        {
            if (Tables.TryGetValue(install, out var t)) return t;
            var worldmodels = NpcDefinitions.Parse(File.ReadAllBytes(Path.Combine(install, "definitions", "pak_worldmodels.csv")));
            var models = new Dictionary<int, string>();
            string ini = Path.Combine(install, "models", "pak_models.ini");
            if (File.Exists(ini))
            {
                bool inStatic = false;
                foreach (var raw in NpcDefinitions.DecodeText(File.ReadAllBytes(ini)).Split('\n'))
                {
                    string line = raw.Trim();
                    if (line.StartsWith('[')) { inStatic = line.Equals("[STATIC]", StringComparison.OrdinalIgnoreCase); continue; }
                    if (!inStatic || !line.StartsWith("set ", StringComparison.Ordinal)) continue;
                    var parts = line[4..].Split(new[] { ' ', '\t' }, 2, StringSplitOptions.RemoveEmptyEntries);
                    if (parts.Length == 2 && int.TryParse(parts[0], out int id)) models[id] = parts[1].Split('"').ElementAtOrDefault(1) ?? parts[1];
                }
            }
            return Tables[install] = (worldmodels, models);
        }
    }

    /// <summary>The spawn file next to a world asset ("worlds/plaza/plaza_p1.bsp" -> "worlds/plaza/pak_plaza_p1.dat").</summary>
    public static string DatPath(string install, string assetPath)
    {
        string rel = Path.ChangeExtension(assetPath, ".dat").Replace('/', Path.DirectorySeparatorChar);
        return Path.Combine(install, Path.GetDirectoryName(rel) ?? "", "pak_" + Path.GetFileName(rel));
    }

    /// <summary>The props and doors of the sector whose level is <paramref name="assetPath"/>; empty when it has no spawn file.</summary>
    public static Contents Read(string install, string assetPath) => ReadDat(install, DatPath(install, assetPath));

    public static Contents ReadDat(string install, string datPath)
    {
        if (!File.Exists(datPath)) return new(Array.Empty<Prop>(), Array.Empty<Door>());
        byte[] bytes = File.ReadAllBytes(datPath);
        try { bytes = NpcDefinitions.DecodeBytes(bytes); } catch (InvalidDataException) { }
        var (worldmodels, models) = TablesFor(install);
        var props = new List<Prop>();
        var halves = new List<(string Name, Vector3 At)>();
        foreach (var (type, e) in WorldObjects.Elements(bytes))
        {
            if (type == PlacedObject && e.Length >= 76)
            {
                int wm = BinaryPrimitives.ReadUInt16LittleEndian(e.AsSpan(44, 2));
                int model = BinaryPrimitives.ReadInt32LittleEndian(e.AsSpan(32, 4));
                string name;
                if (wm != 0)
                {
                    if (!worldmodels.TryGetValue(wm, out var row)) continue;   // disabled row: the game does not place it
                    name = (row.GetValueOrDefault("Name") ?? "").Replace("\n", " / ");
                    // Doors that are worldmodels (DOOR, LIFT DOOR, AIRLOCK, SHUTTERS: type 0) are doors, not props.
                    if (int.TryParse(row.GetValueOrDefault("Type"), out int t) && t == 0 && IsDoorName(name)) { halves.Add((name, F3(e, 0))); continue; }
                    if (int.TryParse(row.GetValueOrDefault("Type"), out t) && PassTypes.Contains(t)) continue;
                }
                else name = models.GetValueOrDefault(model) is { } path ? Path.GetFileNameWithoutExtension(path) : $"model {model}";
                if (PassNames.Any(p => name.Contains(p, StringComparison.OrdinalIgnoreCase))) continue;
                if (Solid(name, e) is { } prop) props.Add(prop);
            }
            else if (type == DoorRecord && e.Length > 25)
            {
                string text = Encoding.Latin1.GetString(e, 24, e.Length - 24);
                string label = string.Join(' ', text.Split(',')[0].Split(new[] { '\0', ' ' }, StringSplitOptions.RemoveEmptyEntries));
                // The first letter is a kind ('D', 'S', 'T'); "DOOR" or "RIGDD"/"RIGDOOR" (rig doors) follow it.
                if (!label.Contains("DOOR", StringComparison.OrdinalIgnoreCase) && !label.Contains("RIGDD", StringComparison.OrdinalIgnoreCase)) continue;
                halves.Add((label.Length > 1 ? label[1..].Trim() : label, F3(e, 4)));
            }
        }
        // The two halves of a split door stand side by side: one door at their middle.
        var doors = new List<(string Name, List<Vector3> At)>();
        foreach (var (name, at) in halves)
        {
            var group = doors.FirstOrDefault(d => d.At.Any(p => Vector3.Distance(p, at) < 160));
            if (group.At != null) group.At.Add(at); else doors.Add((name, new() { at }));
        }
        return new(props, doors.Select(d => new Door(d.Name, d.At.Aggregate(Vector3.Zero, (a, b) => a + b) / d.At.Count)).ToList());
    }

    public static bool IsDoorName(string name) =>
        name.Contains("DOOR", StringComparison.OrdinalIgnoreCase) || name.Contains("AIRLOCK", StringComparison.OrdinalIgnoreCase) || name.Contains("SHUTTER", StringComparison.OrdinalIgnoreCase);

    /// <summary>The prop's footprint from its bounding box, turned by its yaw; null when it is walked over, through or under.</summary>
    private static Prop? Solid(string name, byte[] e)
    {
        var at = F3(e, 0);
        float pitch = F(e, 12), yaw = F(e, 16), roll = F(e, 20);
        // The box is already scaled (invisible WALL boxes at scale 0.02 are 4 units; a Hacknet login at 3.4 is 112).
        var min = F3(e, 52); var max = F3(e, 64);
        if (!IsFinite(at) || !IsFinite(min) || !IsFinite(max) || max.X <= min.X || max.Y <= min.Y || max.Z <= min.Z) return null;
        if (max.X - min.X > MaxSide || max.Z - min.Z > MaxSide) return null;
        if (max.X - min.X < MinSide && max.Z - min.Z < MinSide) return null;
        if (Trees.Any(t => name.Contains(t, StringComparison.OrdinalIgnoreCase)))
        {
            float h = Trunk / 2;
            if (max.Y - min.Y < MinHeight) return null;
            var trunk = new[] { new Vector2(at.X - h, at.Z - h), new Vector2(at.X + h, at.Z - h), new Vector2(at.X + h, at.Z + h), new Vector2(at.X - h, at.Z + h) };
            return new(name, at, Grow(trunk, Pad), at.Y + min.Y, at.Y + max.Y);
        }
        float bottom, top;
        Vector2[] corners;
        if (MathF.Abs(Wrap(pitch)) > 1 || MathF.Abs(Wrap(roll)) > 1)
        {
            // Tilted (a sign on a wall, a toppled barrel): a square round its bounding sphere.
            float r = Math.Max(Math.Max(MathF.Abs(min.X), MathF.Abs(max.X)), Math.Max(Math.Max(MathF.Abs(min.Y), MathF.Abs(max.Y)), Math.Max(MathF.Abs(min.Z), MathF.Abs(max.Z))));
            if (r * 2 > MaxTilted) return null;
            bottom = at.Y - r; top = at.Y + r;
            corners = new[] { new Vector2(-r, -r), new Vector2(r, -r), new Vector2(r, r), new Vector2(-r, r) }.Select(c => new Vector2(at.X, at.Z) + c).ToArray();
        }
        else
        {
            bottom = at.Y + min.Y; top = at.Y + max.Y;
            corners = new[] { new Vector3(min.X, 0, min.Z), new Vector3(max.X, 0, min.Z), new Vector3(max.X, 0, max.Z), new Vector3(min.X, 0, max.Z) }
                .Select(c => TerrainCell.Place(c, at, yaw)).Select(c => new Vector2(c.X, c.Z)).ToArray();
        }
        if (top - bottom < MinHeight) return null;
        return new(name, at, Grow(corners, Pad), bottom, top);
    }

    /// <summary>Push each corner of a convex quad out from its centre by <paramref name="pad"/> along both edges.</summary>
    private static Vector2[] Grow(Vector2[] quad, float pad)
    {
        var centre = (quad[0] + quad[1] + quad[2] + quad[3]) / 4;
        return quad.Select((c, i) =>
        {
            Vector2 a = c - quad[(i + 3) % 4], b = c - quad[(i + 1) % 4];
            Vector2 push = (a.LengthSquared() > 1e-4f ? Vector2.Normalize(a) : Vector2.Zero) + (b.LengthSquared() > 1e-4f ? Vector2.Normalize(b) : Vector2.Zero);
            if (push.LengthSquared() < 1e-4f) push = c - centre;
            return push.LengthSquared() < 1e-4f ? c : c + Vector2.Normalize(push) * pad * 1.4142f;
        }).ToArray();
    }

    private static float F(byte[] e, int at) => BitConverter.ToSingle(e, at);
    private static Vector3 F3(byte[] e, int at) => new(F(e, at), F(e, at + 4), F(e, at + 8));
    private static bool IsFinite(Vector3 v) => float.IsFinite(v.X) && float.IsFinite(v.Y) && float.IsFinite(v.Z) && MathF.Abs(v.X) < 1e6f && MathF.Abs(v.Y) < 1e6f && MathF.Abs(v.Z) < 1e6f;
    private static float Wrap(float degrees) => float.IsFinite(degrees) ? MathF.IEEERemainder(degrees, 360) : 0;

    /// <summary>The convex-volume outline Recast takes: x, y, z per corner.</summary>
    public static float[] Outline(Prop p) => p.Footprint.SelectMany(c => new[] { c.X, p.Bottom, c.Y }).ToArray();
}
