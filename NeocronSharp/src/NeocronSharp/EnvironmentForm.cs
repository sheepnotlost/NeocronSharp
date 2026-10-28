using System.Text.Json;
using NeocronSharp.Core;

namespace NeocronSharp;

internal sealed class EnvironmentForm : Form
{
    private readonly EnvironmentCatalog _catalog;
    private readonly DataGridView _areas = new() { Dock = DockStyle.Fill, ReadOnly = true, AllowUserToAddRows = false,
        RowHeadersVisible = false, MultiSelect = false, SelectionMode = DataGridViewSelectionMode.FullRowSelect, EnableHeadersVisualStyles = false };
    private readonly TextBox _search = new() { Dock = DockStyle.Fill, PlaceholderText = "Search areas…" };
    private readonly Label _status = new() { Dock = DockStyle.Fill, Padding = new Padding(8) };
    private readonly NumericUpDown _from = new() { Minimum = 1, Maximum = 65535, Width = 80 }, _to = new() { Minimum = 1, Maximum = 65535, Value = 2, Width = 80 };
    private readonly CancellationTokenSource _cancel = new();
    private EnvironmentWorld? _world;
    private Task? _running;
    private bool _closing;
    private readonly int _currentSector;
    internal event Action<EnvironmentSummary>? OverlayRequested;

    internal EnvironmentForm(string install, int currentSector)
    {
        _catalog = new(install); _currentSector = currentSector; Text = "NeocronSharp — Environment mapper"; ClientSize = new(1060, 760); MinimumSize = new(850, 590); Font = new("Segoe UI", 10);
        _from.Value = Math.Clamp(currentSector, 1, 65535);
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(18), RowCount = 6, ColumnCount = 1 };
        foreach (int h in new[] { 38, 50, 42 }) layout.RowStyles.Add(new(SizeType.Absolute, h));
        layout.RowStyles.Add(new(SizeType.Percent, 100)); layout.RowStyles.Add(new(SizeType.Absolute, 44)); layout.RowStyles.Add(new(SizeType.Absolute, 135));
        layout.Controls.Add(new Label { Text = "Environment mapper", Dock = DockStyle.Fill, Font = new("Segoe UI", 17, FontStyle.Bold) }, 0, 0);
        layout.Controls.Add(new Label { Text = "Read actual BSP geometry, authored path points and zone transitions.\nGeometry export is navigation input; it is not yet a baked or traversal-validated navigation mesh.", Dock = DockStyle.Fill }, 0, 1);
        var tools = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 5, RowCount = 1 };
        tools.ColumnStyles.Add(new(SizeType.Percent, 100)); foreach (int w in new[] { 110, 125, 130, 145 }) tools.ColumnStyles.Add(new(SizeType.Absolute, w));
        tools.RowStyles.Add(new(SizeType.Percent, 100)); tools.Controls.Add(_search, 0, 0);
        Button Button(string text, int column, Func<Task> action)
        {
            var button = new SkinButton { Text = text, Dock = DockStyle.Fill }; tools.Controls.Add(button, column, 0);
            button.Click += async (_, _) => { if (_running is { IsCompleted: false }) return; _running = action(); await _running; }; return button;
        }
        Button("Load area", 1, LoadSelected); Button("Scan all", 2, ScanAll);
        Button("Map overlay", 3, () => { if (_world != null) OverlayRequested?.Invoke(_world.Summary); return Task.CompletedTask; });
        Button("Export OBJ", 4, Export); layout.Controls.Add(tools, 0, 2);
        foreach (var c in new[] { ("Area", 370), ("ID", 70), ("Ground points", 105), ("Transitions", 100), ("Geometry", 180) })
            _areas.Columns.Add(new DataGridViewTextBoxColumn { HeaderText = c.Item1, Width = c.Item2, AutoSizeMode = c.Item1 == "Area" ? DataGridViewAutoSizeColumnMode.Fill : DataGridViewAutoSizeColumnMode.None, SortMode = DataGridViewColumnSortMode.NotSortable });
        layout.Controls.Add(_areas, 0, 3);
        var route = new FlowLayoutPanel { Dock = DockStyle.Fill };
        route.Controls.Add(new Label { Text = "Sector route  From", AutoSize = true, Padding = new Padding(0, 8, 0, 0) }); route.Controls.Add(_from);
        route.Controls.Add(new Label { Text = "to", AutoSize = true, Padding = new Padding(0, 8, 0, 0) }); route.Controls.Add(_to);
        var plan = new SkinButton { Text = "Find zone links", Width = 145, Height = 31 };
        plan.Click += (_, _) =>
        {
            if (_running is { IsCompleted: false }) return;
            int[] path = _catalog.WorldRoute((int)_from.Value, (int)_to.Value);
            _status.Text = path.Length == 0 ? "No zone route in the scanned data. Scan the relevant areas first." :
                "Authored zone order: " + string.Join(" → ", path) + "\nThis gives sector transitions only. Local walkable routes and door handling still need navmesh validation.";
        };
        route.Controls.Add(plan); layout.Controls.Add(route, 0, 4); layout.Controls.Add(_status, 0, 5); Controls.Add(layout);
        _search.TextChanged += (_, _) => { if (_running is not { IsCompleted: false }) Fill(); }; Fill();
        _status.Text = $"{_catalog.Areas.Count:N0} area definitions available. Load an area or scan the full installation.\nThe macro-suite mapping layer keeps 3D height and transition metadata; map-image pixels are never assumed walkable.";
        FormClosing += async (_, e) =>
        {
            if (_closing) return; _closing = true; _cancel.Cancel();
            if (_running is { IsCompleted: false }) { e.Cancel = true; await _running; Close(); }
        };
        FormClosed += (_, _) => _cancel.Dispose(); AppTheme.Bind(this);
        Shown += (_, _) => SelectArea(_currentSector);
    }
    private void SelectArea(int worldId)
    {
        foreach (DataGridViewRow row in _areas.Rows) if (row.Tag is EnvironmentArea area && area.WorldId == worldId)
        { _areas.ClearSelection(); _areas.CurrentCell = row.Cells[0]; row.Selected = true; _areas.FirstDisplayedScrollingRowIndex = row.Index; break; }
    }
    private void Fill()
    {
        int selected = _areas.SelectedRows.Count == 1 && _areas.SelectedRows[0].Tag is EnvironmentArea chosen ? chosen.WorldId : _currentSector;
        _areas.Rows.Clear(); var summaries = _catalog.Scanned.ToDictionary(x => x.WorldId);
        foreach (var area in _catalog.Areas.Where(a => a.Name.Contains(_search.Text, StringComparison.OrdinalIgnoreCase) || a.WorldId.ToString().Contains(_search.Text)))
        {
            summaries.TryGetValue(area.WorldId, out var s);
            int row = _areas.Rows.Add(area.Name, area.WorldId, s?.GroundPoints.ToString() ?? "—", s?.Transitions.ToString() ?? "—",
                s == null ? "Not scanned" : s.Error != null ? "Unavailable" : $"{s.Faces:N0} faces"); _areas.Rows[row].Tag = area;
        }
        SelectArea(selected);
    }
    private async Task LoadSelected()
    {
        if (_areas.SelectedRows.Count != 1 || _areas.SelectedRows[0].Tag is not EnvironmentArea area) return;
        _search.Enabled = false;
        try
        {
            _status.Text = "Reading " + area.Name + "…";
            _world = null;
            _world = await Task.Run(() => _catalog.Load(area.WorldId));
            if (_closing) return;
            Fill();
            var s = _world.Summary;
            _status.Text = $"{s.Name} · {s.Vertices:N0} vertices · {s.Faces:N0} faces · {s.Models} models\n" +
                $"{s.GroundPoints} ground points · {s.AirPoints} air points · {s.Transitions} world transitions\n" +
                "Map overlay shows authored ground points and exits in the current sector. Export OBJ writes static-world geometry plus entity/transition JSON for the next navmesh stage.";
        }
        catch (Exception error) { if (!_closing) _status.Text = error.Message; }
        finally { if (!_closing) _search.Enabled = true; }
    }
    private async Task ScanAll()
    {
        _search.Enabled = false;
        try
        {
            var progress = new Progress<(int Done, int Total, string Area)>(p => { if (!_closing) _status.Text = $"Mapping {p.Done:N0}/{p.Total:N0}: {p.Area}"; });
            await Task.Run(() => _catalog.ScanAll((i, total, name) => ((IProgress<(int,int,string)>)progress).Report((i,total,name)), _cancel.Token));
            if (_closing) return; Fill();
            _status.Text = $"Mapped {_catalog.Scanned.Count(s => s.Error == null):N0}/{_catalog.Areas.Count:N0} areas. " +
                $"Authored ground points: {_catalog.Scanned.Sum(s => s.GroundPoints):N0}; transitions: {_catalog.Scanned.Sum(s => s.Transitions):N0}.\n" +
                "Use the zone-link planner below the list. A complete collision-aware local navmesh and live traversal tests are still required for seamless macro travel.";
        }
        catch (OperationCanceledException) { }
        catch (Exception error) { if (!_closing) _status.Text = error.Message; }
        finally { if (!_closing) _search.Enabled = true; }
    }
    private Task Export()
    {
        if (_world == null) return Task.CompletedTask;
        using var dialog = new SaveFileDialog { Filter = "Navigation geometry (*.obj)|*.obj", FileName = $"neocron-world-{_world.Summary.WorldId}.obj" };
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            EnvironmentCatalog.ExportObj(_world, dialog.FileName);
            File.WriteAllText(Path.ChangeExtension(dialog.FileName, ".json"), JsonSerializer.Serialize(_world.Summary, new JsonSerializerOptions { WriteIndented = true, IncludeFields = true }));
        }
        return Task.CompletedTask;
    }

    internal async Task VerifyEvidence()
    {
        await LoadSelected();
        if (_world == null || _world.Summary.WorldId != _currentSector || _world.StaticGeometry.Triangles.Length == 0)
            throw new InvalidOperationException($"Environment browser expected sector {_currentSector}, loaded {_world?.Summary.WorldId}: {_status.Text}");
        _search.Text = "PLAZA";
        if (_areas.RowCount == 0) throw new InvalidOperationException("Area filtering failed.");
        using var bitmap = new Bitmap(Width, Height); DrawToBitmap(bitmap, new Rectangle(Point.Empty, bitmap.Size));
        bitmap.Save(Path.Combine(ProjectPaths.Root, "logs", "environment-ui.png"));
    }
}
