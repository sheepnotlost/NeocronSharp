using NeocronSharp.Core;

namespace NeocronSharp;

internal sealed class PlayerInspectorForm : Form
{
    private readonly EntityIdentity _identity;
    private readonly int? _sector;
    private readonly string _name;
    private readonly Label _summary = new() { Dock = DockStyle.Fill };
    private readonly Label _coverage = new() { Dock = DockStyle.Fill, Padding = new Padding(0, 8, 0, 0) };
    private readonly DataGridView _gear = new BufferedGrid { Dock = DockStyle.Fill, ReadOnly = true, AllowUserToAddRows = false,
        AllowUserToDeleteRows = false, AllowUserToResizeRows = false, RowHeadersVisible = false, EnableHeadersVisualStyles = false,
        RowTemplate = { Height = 30 }, SelectionMode = DataGridViewSelectionMode.FullRowSelect, MultiSelect = false };
    private bool _lost;
    internal PlayerInspectorForm(WorldEntity entity, EntitySnapshot snapshot)
    {
        _identity = entity.Identity; _name = entity.Name; _sector = snapshot.Sector?.WorldId;
        Text = $"NeocronSharp — Inspect {_name}"; ClientSize = new(1160, 650); MinimumSize = new(900, 500); Font = new("Segoe UI", 10);
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(20), ColumnCount = 1, RowCount = 4 };
        layout.RowStyles.Add(new(SizeType.Absolute, 44)); layout.RowStyles.Add(new(SizeType.Absolute, 95));
        layout.RowStyles.Add(new(SizeType.Percent, 100)); layout.RowStyles.Add(new(SizeType.Absolute, 105));
        layout.Controls.Add(new Label { Text = _name + " · Player inspection", Dock = DockStyle.Fill, Font = new("Segoe UI", 17, FontStyle.Bold) }, 0, 0);
        layout.Controls.Add(_summary, 0, 1);
        foreach (var column in new[] { ("Slot / source",240), ("Published name / model",300), ("ID",70), ("Base TL",75), ("Range",95), ("Magazine",85), ("Shots/burst",100) })
            _gear.Columns.Add(new DataGridViewTextBoxColumn { HeaderText = column.Item1, Width = column.Item2,
                AutoSizeMode = column.Item1 == "Published name / model" ? DataGridViewAutoSizeColumnMode.Fill : DataGridViewAutoSizeColumnMode.None,
                MinimumWidth = column.Item1 == "Published name / model" ? 200 : 60, SortMode = DataGridViewColumnSortMode.NotSortable });
        layout.Controls.Add(_gear, 0, 2); _coverage.Text = PlayerDetails.Coverage +
            "\nWeapon slots are the three published display slots; they do not establish which weapon is currently drawn. Empty means none published. " +
            "Values refresh with the tracker and clear when the player unloads. Base stats are local definitions, not effective combat values.";
        layout.Controls.Add(_coverage, 0, 3); Controls.Add(layout); AppTheme.Bind(this); UpdateSnapshot(snapshot);
    }
    internal void UpdateSnapshot(EntitySnapshot? snapshot)
    {
        if (IsDisposed) return;
        var entity = snapshot != null && snapshot.Sector?.WorldId == _sector ? snapshot.Entities.FirstOrDefault(e => e.Identity == _identity && e.Name == _name) : null;
        if (_lost || entity?.Player is not { } player || snapshot == null)
        {
            _lost = true; _gear.Rows.Clear();
            _summary.Text = "Not currently loaded. The player may have moved out of client range, left the zone or disconnected.\n" +
                "Live gear has been cleared. Select the player again in the tracker when they reappear."; return;
        }
        string state = player.Dead is { } dead ? dead ? "Dead" : "Alive" : "Unknown";
        _summary.Text = $"Live · {snapshot.CapturedAt.LocalDateTime:HH:mm:ss} · HUD rank {player.RankText} · {state} · HP unavailable\n" +
            $"Faction: {player.FactionName ?? player.FactionId?.ToString() ?? "—"} · Soul Light: {player.SoulLight?.ToString() ?? "—"} · Clan ID: {player.ClanId?.ToString() ?? "—"} · Clan rank code: {player.ClanRank?.ToString() ?? "—"}\n" +
            $"Sector {snapshot.Sector?.WorldId} · X {entity.Position.X:N1} · Y {entity.Position.Y:N1} · Z {entity.Position.Z:N1} · Distance {EntityQuery.Describe(entity, snapshot.PlayerPosition, snapshot.PlayerForward).Distance:N1}";
        while (_gear.RowCount > player.Gear.Count) _gear.Rows.RemoveAt(_gear.RowCount - 1);
        while (_gear.RowCount < player.Gear.Count) _gear.Rows.Add();
        for (int row = 0; row < player.Gear.Count; row++)
        {
            var item = player.Gear[row];
            object[] values = { item.Slot, item.Name ?? (item.DefinitionId.HasValue ? "Unresolved definition" : "None published"),
                item.DefinitionId?.ToString() ?? "—", item.TechLevel?.ToString() ?? "—", item.BaseRange?.ToString("N1") ?? "—",
                item.MagazineSize?.ToString() ?? "—", item.ShotsPerBurst?.ToString() ?? "—" };
            for (int col = 0; col < values.Length; col++) if (!Equals(_gear.Rows[row].Cells[col].Value, values[col])) _gear.Rows[row].Cells[col].Value = values[col];
            _gear.Rows[row].Cells[1].ToolTipText = item.Asset ?? "Client-published weapon reference. This is not an inventory-slot inspection.";
        }
    }
    internal void VerifyEvidence(EntitySnapshot snapshot)
    {
        if (_gear.RowCount < 3 || !_summary.Text.Contains("Live")) throw new InvalidOperationException("Player inspection has no live data.");
        using var bitmap = new Bitmap(Width, Height); DrawToBitmap(bitmap, new Rectangle(Point.Empty, bitmap.Size));
        bitmap.Save(Path.Combine(ProjectPaths.Root, "logs", "player-inspector-ui.png"));
        UpdateSnapshot(snapshot with { Entities = Array.Empty<WorldEntity>() });
        if (_gear.RowCount != 0 || !_lost) throw new InvalidOperationException("Unloaded player's gear remained visible.");
        UpdateSnapshot(snapshot);
        if (_gear.RowCount != 0) throw new InvalidOperationException("A returning address silently rebound player inspection.");
    }
}
