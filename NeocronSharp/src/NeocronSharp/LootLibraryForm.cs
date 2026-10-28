using System.Text.Json;
using NeocronSharp.Core;

namespace NeocronSharp;

internal sealed class LootLibraryForm : Form
{
    private readonly LootCatalog _catalog;
    private readonly DataGridView _npcs = Grid(), _items = Grid();
    private readonly TextBox _search = new() { Dock = DockStyle.Fill, PlaceholderText = "Search NPC, template ID or possible item: warbot, spider, tech part…" };
    private readonly Label _info = new() { Dock = DockStyle.Fill, Padding = new Padding(8) };
    private readonly CheckBox _onlyLoot = new() { Text = "Assigned loot tables only", Checked = true, AutoSize = true };
    private LootTable? _table;
    private LootNpc? _selected;
    private readonly System.Windows.Forms.Timer _debounce = new() { Interval = 250 };

    internal LootLibraryForm(LootCatalog catalog, int? template = null)
    {
        _catalog = catalog; Text = "NeocronSharp — Loot library"; ClientSize = new(1180, 760); MinimumSize = new(950, 600); Font = new("Segoe UI", 10);
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(18), ColumnCount = 1, RowCount = 5 };
        foreach (float h in new[] { 36f, 46f, 44f }) layout.RowStyles.Add(new(SizeType.Absolute, h));
        layout.RowStyles.Add(new(SizeType.Percent, 100)); layout.RowStyles.Add(new(SizeType.Absolute, 130));
        layout.Controls.Add(new Label { Text = "NPC loot library", Dock = DockStyle.Fill, Font = new("Segoe UI", 17, FontStyle.Bold) }, 0, 0);
        layout.Controls.Add(new Label { Text = $"{catalog.Npcs.Count:N0} NPC templates · {catalog.NpcsWithContainer:N0} assigned loot containers · {catalog.ItemCount:N0} named items\nSearch by creature or by an item you want to find. Variant templates retain their own loot rules.", Dock = DockStyle.Fill }, 0, 1);
        var tools = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, RowCount = 1 };
        tools.ColumnStyles.Add(new(SizeType.Percent, 100)); tools.ColumnStyles.Add(new(SizeType.Absolute, 230)); tools.ColumnStyles.Add(new(SizeType.Absolute, 120));
        tools.RowStyles.Add(new(SizeType.Percent, 100)); tools.Controls.Add(_search, 0, 0); tools.Controls.Add(_onlyLoot, 1, 0);
        var export = new SkinButton { Text = "Export table", Dock = DockStyle.Fill }; tools.Controls.Add(export, 2, 0); layout.Controls.Add(tools, 0, 2);
        var split = new SplitContainer { Size = new(1120, 450), Dock = DockStyle.Fill, SplitterDistance = 370, Panel1MinSize = 290, Panel2MinSize = 400 };
        Add(_npcs,"NPC / creature",190,true); Add(_npcs,"Rank",55); Add(_npcs,"Template",75);
        Add(_items,"Definition candidate",280,true); Add(_items,"TL",45); Add(_items,"Rule / group",200); Add(_items,"Chance raw",90); Add(_items,"Quality",70); Add(_items,"Output rule",220);
        split.Panel1.Controls.Add(_npcs); split.Panel2.Controls.Add(_items); layout.Controls.Add(split, 0, 3); layout.Controls.Add(_info, 0, 4); Controls.Add(layout);
        _debounce.Tick += (_, _) => { _debounce.Stop(); Filter(); };
        _search.TextChanged += (_, _) => { _debounce.Stop(); _debounce.Start(); };
        _onlyLoot.CheckedChanged += (_, _) => Filter();
        _npcs.SelectionChanged += (_, _) => { if (_npcs.SelectedRows.Count == 1 && _npcs.SelectedRows[0].Tag is LootNpc npc) Select(npc); };
        export.Click += (_, _) => Export();
        FormClosed += (_, _) => _debounce.Dispose();
        Filter();
        if (template is { } id)
        {
            _onlyLoot.Checked = false; Filter();
            Shown += (_, _) =>
            {
                foreach (DataGridViewRow row in _npcs.Rows) if (row.Tag is LootNpc npc && npc.TemplateId == id)
                { _npcs.ClearSelection(); _npcs.CurrentCell = row.Cells[0]; row.Selected = true; _npcs.FirstDisplayedScrollingRowIndex = row.Index; Select(npc); break; }
            };
        }
        AppTheme.Bind(this);
    }
    private static DataGridView Grid() => new() { Dock = DockStyle.Fill, ReadOnly = true, AllowUserToAddRows = false, AllowUserToDeleteRows = false,
        AllowUserToResizeRows = false, RowHeadersVisible = false, SelectionMode = DataGridViewSelectionMode.FullRowSelect, MultiSelect = false, RowTemplate = { Height = 28 }, EnableHeadersVisualStyles = false };
    private static void Add(DataGridView grid, string name, int width, bool fill = false) => grid.Columns.Add(new DataGridViewTextBoxColumn { HeaderText = name, Width = width,
        AutoSizeMode = fill ? DataGridViewAutoSizeColumnMode.Fill : DataGridViewAutoSizeColumnMode.None, MinimumWidth = fill ? 140 : 40, SortMode = DataGridViewColumnSortMode.NotSortable });
    private void Filter()
    {
        _npcs.Rows.Clear();
        foreach (var npc in _catalog.Search(_search.Text, _onlyLoot.Checked))
        { int row = _npcs.Rows.Add(npc.Name, npc.Rank, npc.TemplateId); _npcs.Rows[row].Tag = npc; }
        if (_npcs.RowCount > 0) { _npcs.Rows[0].Selected = true; Select((LootNpc)_npcs.Rows[0].Tag!); }
        else { _items.Rows.Clear(); _table = null; _info.Text = "No matches. Try a broader creature or item name."; }
    }
    private void Select(LootNpc npc)
    {
        _selected = npc; _table = _catalog.Get(npc.TemplateId); _items.Rows.Clear();
        foreach (var item in _table.Items)
        {
            int row = _items.Rows.Add(item.Name, item.TechLevel, item.RuleSource, item.ChanceRaw, item.QualityFactor.ToString("0.###"), item.OutputRule);
            _items.Rows[row].Cells[0].ToolTipText = $"Item #{item.ItemId}: {item.Name}";
            _items.Rows[row].Cells[3].ToolTipText = "Original signed chance field. This is not a verified per-kill drop percentage.";
        }
        _info.Text = $"{npc.Name} · rank {npc.Rank} · template {npc.TemplateId} · container {npc.ContainerId}\n" +
            $"{_table.Items.Select(i => i.ItemId).Distinct().Count():N0} possible named items across {_table.Rules.Count} rules · configured slots {_table.ItemsAtOnce?.ToString() ?? "—"}\n" +
            (_table.Rules.Count == 0 ? _table.Status : "Local definition candidates; actual corpse contents and per-kill odds are unverified.") +
            "\nNegative-quality rules can generate different outputs (such as parts); a listed base weapon is not proof of a finished-weapon drop.";
    }
    private void Export()
    {
        if (_table == null) return;
        using var dialog = new SaveFileDialog { Filter = "Loot JSON (*.json)|*.json", FileName = $"neocron-loot-{_table.TemplateId}.json" };
        if (dialog.ShowDialog(this) == DialogResult.OK)
            File.WriteAllText(dialog.FileName, JsonSerializer.Serialize(new { npc = _selected, source = LootCatalog.SourceNote, table = _table }, new JsonSerializerOptions { WriteIndented = true }));
    }

    internal void VerifyEvidence()
    {
        if (_selected?.TemplateId != 440) throw new InvalidOperationException("Selected NPC loot shortcut did not survive opening the form.");
        _onlyLoot.Checked = true; _search.Text = "small spider"; _debounce.Stop(); Filter();
        if (_npcs.RowCount == 0 || !_table!.Items.Any(i => i.Name == "Small Limbs"))
            throw new InvalidOperationException("Loot browser did not resolve Small Spider's local loot groups.");
        _search.Text = "warbot"; _debounce.Stop(); Filter();
        foreach (DataGridViewRow row in _npcs.Rows) if (row.Tag is LootNpc { TemplateId: 195 } npc)
        { _npcs.ClearSelection(); _npcs.CurrentCell = row.Cells[0]; row.Selected = true; _npcs.FirstDisplayedScrollingRowIndex = row.Index; Select(npc); break; }
        if (_npcs.RowCount == 0 || !_table!.Items.Any(i => i.QualityFactor < 0))
            throw new InvalidOperationException("Loot browser lost Warbot special generation rules.");
        using var bitmap = new Bitmap(Width, Height); DrawToBitmap(bitmap, new Rectangle(Point.Empty, bitmap.Size));
        bitmap.Save(Path.Combine(ProjectPaths.Root, "logs", "loot-ui.png"));
    }
}
