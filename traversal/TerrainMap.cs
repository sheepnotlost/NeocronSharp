using System.Numerics;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// The whole wasteland as one coarse walking grid, for planning which cells to cross and where.
/// Every cell's heightfield is cut into 128 x 128 squares of 256 units; a square is walkable when
/// at least 12 of its 16 heightfield samples slope less than 55 degrees, and two neighbouring squares
/// connect when the rise between them is under 55 degrees as well. Squares on either side of a cell
/// edge connect when both are walkable (the two heightfields do not meet exactly at the seam).
/// Also kept: every door placed in a cell (its "portals": WorldChanges of the entrance models)
/// and the outposts (pak_outposts: factories, mines, labs, fortresses, uplinks) as landmarks.
/// Built once from the game files (about half a minute) and cached in logs/terrain/.
/// </summary>
internal sealed class TerrainMap
{
    public const int N = 128;
    public const float Step = TerrainCell.Half * 2 / N;   // 256 units
    private const int PerCell = N * N;
    private const float MaxRise = 1.43f;                    // tan 55 degrees, as the cell navmesh (TerrainNav)
    private const int Version = 5;

    /// <summary>A door in a cell: where it is (cell space), where it leads, and its Index/arrival numbers.</summary>
    public sealed record Portal(int Cell, string Name, Vector3 Position, int To, string Index, int Arrival);

    /// <summary>A named place in a cell (an outpost), with the spot to walk to (cell space).</summary>
    public sealed record Landmark(int Cell, string Name, string Kind, Vector3 Position);

    public IReadOnlyList<int> Cells { get; }
    public IReadOnlyList<Portal> Portals { get; }
    public IReadOnlyList<Landmark> Landmarks { get; }
    public TimeSpan LoadTime { get; private set; }
    public bool FromCache { get; private set; }

    private readonly Dictionary<int, int> _slot;
    private readonly byte[] _walk;
    private readonly float[] _height;
    private int[] _componentCache;
    private bool _dirty;
    // Connected areas, recomputed after nodes are blocked.
    private int[] _component { get { if (_dirty) { _componentCache = Components(); _dirty = false; } return _componentCache; } }
    private readonly HashSet<int> _blocked = new();

    private TerrainMap(List<int> cells, byte[] walk, float[] height, List<Portal> portals, List<Landmark> landmarks)
    {
        Cells = cells; _walk = walk; _height = height; Portals = portals; Landmarks = landmarks;
        _slot = cells.Select((c, i) => (c, i)).ToDictionary(p => p.c, p => p.i);
        _componentCache = Components();
    }

    public bool IsCell(int id) => _slot.ContainsKey(id);

    private static readonly Dictionary<string, TerrainMap> Loaded = new(StringComparer.OrdinalIgnoreCase);

    /// <summary>The map for this install: from logs/terrain/ when the cell files are unchanged, else built and saved.</summary>
    public static TerrainMap Get(string install)
    {
        lock (Loaded)
        {
            if (Loaded.TryGetValue(install, out var known)) return known;
            var clock = System.Diagnostics.Stopwatch.StartNew();
            var cells = new List<int>();
            for (int row = 0; row < 12; row++)
                for (int column = 1; column < TerrainCell.Columns; column++)
                    if (TerrainCell.Exists(install, TerrainCell.IdAt(row, column))) cells.Add(TerrainCell.IdAt(row, column));
            string stamp = Stamp(install, cells);
            string file = Path.Combine(TerrainNav.CacheDirectory, $"map-{stamp}.bin");
            var map = File.Exists(file) ? TryRead(file, cells) : null;
            bool cached = map != null;
            if (map == null)
            {
                map = Build(install, cells);
                try { Directory.CreateDirectory(TerrainNav.CacheDirectory); map.Write(file); } catch (IOException) { }
            }
            map.LoadTime = clock.Elapsed; map.FromCache = cached;
            return Loaded[install] = map;
        }
    }

    private static string Stamp(string install, List<int> cells)
    {
        var parts = new List<string> { $"v{Version}" };
        foreach (int id in cells)
            foreach (var ext in new[] { "tfl", "dat" })
            {
                var info = new FileInfo(Path.Combine(install, "terrain", $"pak_{TerrainCell.CodeOf(id)}.{ext}"));
                parts.Add(info.Exists ? $"{id}{ext}{info.Length}:{info.LastWriteTimeUtc.Ticks}" : "-");
            }
        var outposts = new FileInfo(Path.Combine(install, "definitions", "pak_outposts.csv"));
        parts.Add(outposts.Exists ? $"{outposts.Length}:{outposts.LastWriteTimeUtc.Ticks}" : "-");
        return Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(string.Join("|", parts))), 0, 6).ToLowerInvariant();
    }

    private static TerrainMap Build(string install, List<int> cells)
    {
        var walk = new byte[cells.Count * PerCell]; var height = new float[cells.Count * PerCell];
        var portals = new List<Portal>(); var landmarks = new List<Landmark>();
        Dictionary<int, Dictionary<string, string>> outposts = new();
        try { outposts = NpcDefinitions.Parse(File.ReadAllBytes(Path.Combine(install, "definitions", "pak_outposts.csv"))); }
        catch (Exception e) when (e is IOException or InvalidDataException) { }
        var cellData = new TerrainCell?[cells.Count];
        Parallel.For(0, cells.Count, new ParallelOptions { MaxDegreeOfParallelism = Math.Max(1, Environment.ProcessorCount - 1) }, k =>
        {
            TerrainCell cell;
            try { cell = TerrainCell.Load(install, cells[k]); }
            catch (Exception e) when (e is IOException or InvalidDataException) { return; }
            cellData[k] = cell;
            Coarsen(cell.Heights, walk.AsSpan(k * PerCell, PerCell), height.AsSpan(k * PerCell, PerCell));
        });
        string[] kinds = { "Mine", "Factory", "Lab", "Fortress", "Uplink", "Outpost" };
        for (int k = 0; k < cells.Count; k++)
        {
            if (cellData[k] is not { } cell) continue;
            // Outpost GenReps carry a WorldChange to the Fallen Angels HQ: a teleporter you "use", not a door to walk through.
            foreach (var exit in cell.Exits.Where(e => !e.Name.Contains("genrep", StringComparison.OrdinalIgnoreCase)))
                if (int.TryParse(exit.Properties.GetValueOrDefault("NextLevel"), out int to) && to > 0)
                    portals.Add(new(cell.Id, exit.Name, exit.Position, to, exit.Properties.GetValueOrDefault("Index") ?? "",
                        int.TryParse(exit.Properties.GetValueOrDefault("NextLevelStartIndex"), out int arrival) ? arrival : 0));
            if (outposts.TryGetValue(cell.Id, out var row) && row.GetValueOrDefault("Enabled") == "1")
            {
                // The outpost's gate is the way in; else its main building; else any outpost model.
                var models = cell.Placements.Where(p => p.Model.Contains("/outposts/", StringComparison.OrdinalIgnoreCase)).ToList();
                var spot = models.FirstOrDefault(p => p.Model.Contains("_gate", StringComparison.OrdinalIgnoreCase))
                    ?? models.FirstOrDefault(p => p.Model.Contains("_main", StringComparison.OrdinalIgnoreCase)) ?? models.FirstOrDefault();
                var at = spot?.Position ?? Vector3.Zero;
                at.Y = cell.Height(at.X, at.Z);
                string kind = int.TryParse(row.GetValueOrDefault("Type"), out int t) && t >= 0 && t < kinds.Length ? kinds[t] : "Outpost";
                landmarks.Add(new(cell.Id, row.GetValueOrDefault("Name") ?? $"Outpost {cell.Code}", kind, at));
            }
        }
        return new(cells, walk, height, portals, landmarks);
    }

    /// <summary>512 x 512 heightfield -> 128 x 128 squares: mean height, walkable when 12 of 16 samples are not too steep.</summary>
    internal static void Coarsen(float[] fine, Span<byte> walk, Span<float> height)
    {
        const int S = TerrainCell.Samples, F = S / N;
        float limit = MaxRise * TerrainCell.Spacing;
        for (int cj = 0; cj < N; cj++)
            for (int ci = 0; ci < N; ci++)
            {
                int ok = 0; float sum = 0;
                for (int dj = 0; dj < F; dj++)
                    for (int di = 0; di < F; di++)
                    {
                        int i = ci * F + di, j = cj * F + dj;
                        float h = fine[j * S + i]; sum += h;
                        bool flat = (i + 1 >= S || MathF.Abs(fine[j * S + i + 1] - h) <= limit) && (j + 1 >= S || MathF.Abs(fine[(j + 1) * S + i] - h) <= limit)
                            && (i == 0 || MathF.Abs(fine[j * S + i - 1] - h) <= limit) && (j == 0 || MathF.Abs(fine[(j - 1) * S + i] - h) <= limit);
                        if (flat) ok++;
                    }
                walk[cj * N + ci] = (byte)(ok >= F * F * 3 / 4 ? 1 : 0);
                height[cj * N + ci] = sum / (F * F);
            }
    }

    private void Write(string file)
    {
        string temp = file + ".tmp";
        using (var w = new BinaryWriter(File.Create(temp)))
        {
            w.Write(Version); w.Write(Cells.Count);
            foreach (int c in Cells) w.Write(c);
            w.Write(_walk);
            foreach (float h in _height) w.Write((ushort)Math.Clamp(MathF.Round(h * 4), 0, 65535));
            w.Write(Portals.Count);
            foreach (var p in Portals) { w.Write(p.Cell); w.Write(p.Name); w.Write(p.Position.X); w.Write(p.Position.Y); w.Write(p.Position.Z); w.Write(p.To); w.Write(p.Index); w.Write(p.Arrival); }
            w.Write(Landmarks.Count);
            foreach (var l in Landmarks) { w.Write(l.Cell); w.Write(l.Name); w.Write(l.Kind); w.Write(l.Position.X); w.Write(l.Position.Y); w.Write(l.Position.Z); }
        }
        File.Move(temp, file, overwrite: true);
    }

    private static TerrainMap? TryRead(string file, List<int> expected)
    {
        try
        {
            using var r = new BinaryReader(File.OpenRead(file));
            if (r.ReadInt32() != Version) return null;
            int count = r.ReadInt32();
            var cells = Enumerable.Range(0, count).Select(_ => r.ReadInt32()).ToList();
            if (!cells.SequenceEqual(expected)) return null;
            var walk = r.ReadBytes(count * PerCell);
            var height = new float[count * PerCell];
            for (int i = 0; i < height.Length; i++) height[i] = r.ReadUInt16() / 4f;
            var portals = Enumerable.Range(0, r.ReadInt32()).Select(_ => new Portal(r.ReadInt32(), r.ReadString(), new(r.ReadSingle(), r.ReadSingle(), r.ReadSingle()), r.ReadInt32(), r.ReadString(), r.ReadInt32())).ToList();
            var landmarks = Enumerable.Range(0, r.ReadInt32()).Select(_ => new Landmark(r.ReadInt32(), r.ReadString(), r.ReadString(), new(r.ReadSingle(), r.ReadSingle(), r.ReadSingle()))).ToList();
            return new(cells, walk, height, portals, landmarks);
        }
        catch (Exception e) when (e is IOException or EndOfStreamException or InvalidDataException) { return null; }
    }

    // ---- nodes: g = slot * 128 * 128 + cj * 128 + ci ----

    public int CellOf(int g) => Cells[g / PerCell];

    /// <summary>A node's centre in its own cell's space (on the ground).</summary>
    public Vector3 Local(int g)
    {
        int ci = g % N, cj = g / N % N;
        return new(-TerrainCell.Half + Step * (ci + 0.5f), _height[g], -TerrainCell.Half + Step * (cj + 0.5f));
    }

    /// <summary>Where a cell's origin sits on the wasteland plane: column east (+x), row A at the north (+z).</summary>
    public static Vector2 CellOrigin(int cell) => new(TerrainCell.Column(cell) * TerrainCell.Half * 2, -TerrainCell.Row(cell) * TerrainCell.Half * 2);

    public Vector2 Global(int g) { var l = Local(g); return CellOrigin(CellOf(g)) + new Vector2(l.X, l.Z); }

    /// <summary>A point given in one cell's space, expressed in another's (cells are 32768 apart).</summary>
    public static Vector3 Into(int fromCell, Vector3 p, int toCell)
    {
        var shift = CellOrigin(fromCell) - CellOrigin(toCell);
        return new(p.X + shift.X, p.Y, p.Z + shift.Y);
    }

    private bool Walkable(int g) => g >= 0 && _walk[g] != 0 && !_blocked.Contains(g);

    public int Component(int g) => _component[g];

    /// <summary>Never plan through this node again in this run (the navmesh or the game found no way).</summary>
    public void Block(int g) { if (g >= 0 && _blocked.Add(g)) _dirty = true; }

    /// <summary>
    /// Block every walkable node of <paramref name="cell"/> that <paramref name="keep"/> rejects (the cell's
    /// navmesh cannot reach it from where you stand), so the grid plans only where the navmesh can walk.
    /// </summary>
    public int Restrict(int cell, Func<Vector3, bool> keep)
    {
        if (!_slot.TryGetValue(cell, out int slot)) return 0;
        int blocked = 0;
        for (int g = slot * PerCell; g < (slot + 1) * PerCell; g++)
            if (_walk[g] != 0 && !_blocked.Contains(g) && !keep(Local(g))) { _blocked.Add(g); blocked++; }
        if (blocked > 0) _dirty = true;
        return blocked;
    }

    /// <summary>The walkable node nearest a point in a cell (within about 3 km), optionally in one component; -1 if none.</summary>
    public int Nearest(int cell, Vector3 p, int component = -1, int rings = 12)
    {
        if (!_slot.TryGetValue(cell, out int slot)) return -1;
        int ci = Math.Clamp((int)((p.X + TerrainCell.Half) / Step), 0, N - 1), cj = Math.Clamp((int)((p.Z + TerrainCell.Half) / Step), 0, N - 1);
        int best = -1; float bestDistance = float.MaxValue;
        for (int r = 0; r <= rings && (best < 0 || r * Step < bestDistance + Step); r++)
            for (int dj = -r; dj <= r; dj++)
                for (int di = -r; di <= r; di++)
                {
                    if (Math.Max(Math.Abs(di), Math.Abs(dj)) != r) continue;
                    int i = ci + di, j = cj + dj;
                    if (i < 0 || j < 0 || i >= N || j >= N) continue;
                    int g = slot * PerCell + j * N + i;
                    if (!Walkable(g) || (component >= 0 && _component[g] != component)) continue;
                    var at = Local(g); float d = MathF.Sqrt((at.X - p.X) * (at.X - p.X) + (at.Z - p.Z) * (at.Z - p.Z));
                    if (d < bestDistance) { bestDistance = d; best = g; }
                }
        return best;
    }

    private static readonly (int Di, int Dj)[] Directions = { (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1) };

    /// <summary>The node one step from g, crossing into the neighbouring cell at an edge (straight steps only); -1 if none.</summary>
    private int Step8(int g, int di, int dj, out bool seam)
    {
        seam = false;
        int slot = g / PerCell, ci = g % N + di, cj = g / N % N + dj;
        if (ci >= 0 && ci < N && cj >= 0 && cj < N) return slot * PerCell + cj * N + ci;
        if (di != 0 && dj != 0) return -1;
        int cell = Cells[slot];
        int row = TerrainCell.Row(cell) - (cj >= N ? 1 : cj < 0 ? -1 : 0), column = TerrainCell.Column(cell) + (ci >= N ? 1 : ci < 0 ? -1 : 0);
        if (column < 1 || column >= TerrainCell.Columns || row < 0 || !_slot.TryGetValue(TerrainCell.IdAt(row, column), out int next)) return -1;
        seam = true;
        return next * PerCell + ((cj + N) % N) * N + (ci + N) % N;
    }

    private bool Passable(int a, int b, int di, int dj, bool seam)
    {
        if (!Walkable(b)) return false;
        if (seam) return true;
        float run = di != 0 && dj != 0 ? Step * 1.4142f : Step;
        if (MathF.Abs(_height[b] - _height[a]) > run * MaxRise) return false;
        // No cutting a corner past an unwalkable square.
        if (di != 0 && dj != 0 && (!Walkable(Step8(a, di, 0, out _)) || !Walkable(Step8(a, 0, dj, out _)))) return false;
        return true;
    }

    private int[] Components()
    {
        var component = new int[_walk.Length]; Array.Fill(component, -1);
        int next = 0; var stack = new Stack<int>();
        for (int g0 = 0; g0 < _walk.Length; g0++)
        {
            if (!Walkable(g0) || component[g0] >= 0) continue;
            component[g0] = next; stack.Push(g0);
            while (stack.Count > 0)
            {
                int g = stack.Pop();
                foreach (var (di, dj) in Directions)
                {
                    int h = Step8(g, di, dj, out bool seam);
                    if (h < 0 || component[h] >= 0 || !Passable(g, h, di, dj, seam)) continue;
                    component[h] = next; stack.Push(h);
                }
            }
            next++;
        }
        return component;
    }

    /// <summary>A* over the grid from one node to another; the nodes in order, or empty when they do not connect.</summary>
    public List<int> Route(int from, int to)
    {
        if (from < 0 || to < 0 || _component[from] != _component[to] || _component[from] < 0) return new();
        var cost = new float[_walk.Length]; Array.Fill(cost, float.PositiveInfinity); cost[from] = 0;
        var parent = new int[_walk.Length];
        var done = new bool[_walk.Length];
        var open = new PriorityQueue<int, float>();
        var goal = Global(to);
        open.Enqueue(from, Vector2.Distance(Global(from), goal));
        while (open.TryDequeue(out int g, out _))
        {
            if (g == to) break;
            if (done[g]) continue;
            done[g] = true;
            float here = cost[g];
            foreach (var (di, dj) in Directions)
            {
                int h = Step8(g, di, dj, out bool seam);
                if (h < 0 || done[h] || !Passable(g, h, di, dj, seam)) continue;
                float rise = MathF.Abs(_height[h] - _height[g]);
                float step = (di != 0 && dj != 0 ? Step * 1.4142f : Step) + (seam ? 0 : rise);   // climbing costs a little extra
                float total = here + step;
                if (cost[h] <= total) continue;
                cost[h] = total; parent[h] = g;
                open.Enqueue(h, total + Vector2.Distance(Global(h), goal));
            }
        }
        if (float.IsPositiveInfinity(cost[to])) return new();
        var path = new List<int> { to };
        while (path[^1] != from) path.Add(parent[path[^1]]);
        path.Reverse();
        return path;
    }

    /// <summary>Length of a grid route in world units.</summary>
    public float Length(List<int> route)
    {
        float total = 0;
        for (int i = 1; i < route.Count; i++) total += Vector2.Distance(Global(route[i - 1]), Global(route[i]));
        return total;
    }

    /// <summary>The cells a grid route passes through, in order.</summary>
    public List<int> CellsAlong(List<int> route)
    {
        var cells = new List<int>();
        foreach (int g in route) if (cells.Count == 0 || cells[^1] != CellOf(g)) cells.Add(CellOf(g));
        return cells;
    }

    /// <summary>
    /// Where a route leaves its first cell: the last node inside and the first beyond (both in the
    /// first cell's space). Null when it never leaves.
    /// </summary>
    public (int Inside, int Beyond, Vector3 Walk, Vector3 Push)? FirstCrossing(List<int> route)
    {
        if (route.Count == 0) return null;
        int cell = CellOf(route[0]);
        for (int i = 1; i < route.Count; i++)
            if (CellOf(route[i]) != cell)
            {
                var (walk, push) = CrossingPoints(route[i - 1], route[i]);
                return (route[i - 1], route[i], walk, push);
            }
        return null;
    }

    /// <summary>
    /// For a step across a cell edge: the spot to walk to (the inside node, moved to 96 units from the
    /// edge) and the spot to press on toward (900 units past the edge, straight out), in the inside cell's space.
    /// </summary>
    public (Vector3 Walk, Vector3 Push) CrossingPoints(int inside, int beyond)
    {
        int cell = CellOf(inside);
        var a = Local(inside); var b = Into(CellOf(beyond), Local(beyond), cell);
        var across = MathF.Abs(b.X - a.X) > MathF.Abs(b.Z - a.Z) ? new Vector3(MathF.Sign(b.X - a.X), 0, 0) : new Vector3(0, 0, MathF.Sign(b.Z - a.Z));
        const float margin = TerrainCell.Half - 96;
        var walk = across.X != 0 ? a with { X = across.X * margin } : a with { Z = across.Z * margin };
        return (walk, walk + across * 900);
    }

    /// <summary>Other walkable nodes along the same cell edge as <paramref name="inside"/>, nearest first, that still cross (for when the navmesh cannot reach the planned one).</summary>
    public IEnumerable<(int Inside, int Beyond)> AlongEdge(int inside, int beyond)
    {
        int slot = inside / PerCell, ci = inside % N, cj = inside / N % N;
        int bi = beyond % N, bj = beyond / N % N, bslot = beyond / PerCell;
        bool vertical = ci == 0 || ci == N - 1 ? bi != ci : false;   // crossing east/west
        var list = new List<(int, int, int)>();
        for (int k = 0; k < N; k++)
        {
            int a = vertical ? slot * PerCell + k * N + ci : slot * PerCell + cj * N + k;
            int b = vertical ? bslot * PerCell + k * N + bi : bslot * PerCell + bj * N + k;
            if (a == inside || !Walkable(a) || !Walkable(b) || _component[a] != _component[inside]) continue;
            list.Add((Math.Abs(k - (vertical ? cj : ci)), a, b));
        }
        return list.OrderBy(t => t.Item1).Select(t => (t.Item2, t.Item3));
    }

    /// <summary>The door in a cell that people coming from <paramref name="from"/> through an exit with this arrival number appear at.</summary>
    public Portal? ArrivalFrom(int cell, int from, int arrival) =>
        Portals.Where(p => p.Cell == cell && p.Index == arrival.ToString(System.Globalization.CultureInfo.InvariantCulture)).OrderBy(p => p.To == from ? 0 : 1).FirstOrDefault()
        ?? Portals.FirstOrDefault(p => p.Cell == cell && p.To == from);

    /// <summary>Squares in a cell, walkable, and in a given component.</summary>
    public int CountIn(int cell, int component)
    {
        if (!_slot.TryGetValue(cell, out int slot)) return 0;
        int n = 0;
        for (int g = slot * PerCell; g < (slot + 1) * PerCell; g++) if (_component[g] == component && _walk[g] != 0) n++;
        return n;
    }

    /// <summary>The cells a component has walkable squares in.</summary>
    public IEnumerable<int> CellsOf(int component)
    {
        for (int slot = 0; slot < Cells.Count; slot++)
            for (int g = slot * PerCell; g < (slot + 1) * PerCell; g++)
                if (_component[g] == component) { yield return Cells[slot]; break; }
    }

    /// <summary>The biggest walkable area of a cell (when no position is known).</summary>
    public int MainComponent(int cell)
    {
        if (!_slot.TryGetValue(cell, out int slot)) return -1;
        return Enumerable.Range(slot * PerCell, PerCell).Where(g => _component[g] >= 0).GroupBy(g => _component[g])
            .OrderByDescending(group => group.Count()).Select(group => group.Key).DefaultIfEmpty(-1).First();
    }

    /// <summary>Share of the cell that is walkable, for reports.</summary>
    public float WalkableShare(int cell) => _slot.TryGetValue(cell, out int slot) ? _walk.Skip(slot * PerCell).Take(PerCell).Count(w => w != 0) / (float)PerCell : 0;
}
