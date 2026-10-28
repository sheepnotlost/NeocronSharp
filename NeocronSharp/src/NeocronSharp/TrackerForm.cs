using NeocronSharp.Core;

namespace NeocronSharp;

internal sealed class TrackerForm : Form
{
    private readonly TextBox _search = new() { PlaceholderText = "Search NPC names: copbot, spider…", Dock = DockStyle.Fill };
    private readonly NumericUpDown _radius = new() { Minimum = 0, Maximum = 100000, Increment = 100, ThousandsSeparator = true, Width = 95 };
    private readonly CheckBox _unknown = new() { Text = "Unnamed actors", Dock = DockStyle.Fill };
    private readonly CheckBox _showPlayers = new() { Text = "Players", Checked = true, Dock = DockStyle.Fill };
    private readonly List<PlayerInspectorForm> _inspectors = new();
    private readonly Font _nameFont;
    private readonly CheckBox _pause = new() { Text = "Pause", Dock = DockStyle.Fill };
    private readonly Label _status = new() { Dock = DockStyle.Fill, AutoEllipsis = true, TextAlign = ContentAlignment.MiddleLeft };
    private readonly Label _details = new() { AutoSize = true, Location = new Point(12, 12), MaximumSize = new Size(350, 0) };
    private readonly DataGridView _grid = new BufferedGrid() { Dock = DockStyle.Fill, ReadOnly = true, AllowUserToAddRows = false,
        AllowUserToDeleteRows = false, AllowUserToResizeRows = false, RowHeadersVisible = false,
        SelectionMode = DataGridViewSelectionMode.FullRowSelect, MultiSelect = false, AutoGenerateColumns = false,
        BackgroundColor = Color.White, BorderStyle = BorderStyle.None };
    private readonly SectorMapPanel _map = new() { Dock = DockStyle.Fill, Margin = new Padding(8) };
    private readonly Label _mapTitle = new() { Text = "Sector map", Dock = DockStyle.Fill, Font = new Font("Segoe UI", 13, FontStyle.Bold), TextAlign = ContentAlignment.MiddleLeft };
    private readonly Label _mapLegend = new() { Dock = DockStyle.Fill, Padding = new Padding(8), Font = new Font("Segoe UI", 9) };
    private SectorMapAssets? _mapAssets;
    private string _mapInstall = "", _mapAssetError = "";
    private readonly EntityTracking _tracking = new();
    private readonly System.Windows.Forms.Timer _timer = new() { Interval = 500 };
    private EntitySnapshot? _snapshot;
    private PlayerReader? _reader;
    private Task? _refresh;
    private bool _rendering, _closing;
    private int _processId;
    private MainForm? _navigation;
    private CoordinateRecorderForm? _recorder;
    private readonly SkinHeader _chrome = new();
    private readonly TabControl _mainTabs = new() { Dock = DockStyle.Fill };
    private readonly QuestBrowser _questBrowser = new();
    private readonly PluginHost _pluginHost;
    private PluginBrowser? _pluginBrowser;
    private readonly ComboBox _skins = new() { Dock = DockStyle.Fill, DropDownStyle = ComboBoxStyle.DropDownList };
    private bool _skinEvidence;
    private LootCatalog? _loot;
    private string _lootError = "";
    private EntitySortColumn _sortColumn = EntitySortColumn.Distance;
    private bool _sortDescending, _resetSortScroll;
    private static readonly EntitySortColumn[] SortColumns = { EntitySortColumn.Name, EntitySortColumn.Rank, EntitySortColumn.HitPoints,
        EntitySortColumn.Weapon, EntitySortColumn.HealthPercent, EntitySortColumn.Distance, EntitySortColumn.Faction, EntitySortColumn.Direction, EntitySortColumn.Type };

    public TrackerForm()
    {
        _pluginHost = new PluginHost(ProjectPaths.Root, PluginTelemetry);
        Text = "NeocronSharp — NPC / Player tracker";
        ClientSize = new Size(1500, 870);
        MinimumSize = new Size(1180, 690);
        StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Segoe UI", 10);
        _nameFont = new Font(Font, FontStyle.Bold);
        DoubleBuffered = true;
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(20), ColumnCount = 1, RowCount = 5 };
        var headerHeight = new RowStyle(SizeType.Absolute, AppTheme.Current.Id == 1 ? 56 : 70); layout.RowStyles.Add(headerHeight);
        layout.RowStyles.Add(new(SizeType.Absolute, 32));
        layout.RowStyles.Add(new(SizeType.Absolute, 50));
        layout.RowStyles.Add(new(SizeType.Absolute, 44));
        layout.RowStyles.Add(new(SizeType.Percent, 100));
        var header = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1, Margin = Padding.Empty };
        header.ColumnStyles.Add(new(SizeType.Percent, 100)); header.ColumnStyles.Add(new(SizeType.Absolute, 295));
        header.RowStyles.Add(new(SizeType.Percent, 100)); header.Controls.Add(_chrome, 0, 0);
        var skinField = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2, Padding = new Padding(12,0,0,0) };
        skinField.RowStyles.Add(new(SizeType.Absolute, 17)); skinField.RowStyles.Add(new(SizeType.Percent, 100));
        skinField.Controls.Add(new Label { Text = "SKIN", Dock = DockStyle.Fill, Font = new Font("Segoe UI", 8, FontStyle.Bold) }, 0, 0);
        _skins.Items.AddRange(SkinCatalog.All.Cast<object>().ToArray()); _skins.SelectedIndex = AppTheme.Current.Id - 1; skinField.Controls.Add(_skins, 0, 1);
        _skins.DrawMode = DrawMode.OwnerDrawFixed; _skins.ItemHeight = 22;
        _skins.DrawItem += (_, e) =>
        {
            if (e.Index < 0 || _skins.Items[e.Index] is not SkinSpec item) return;
            using var background = new SolidBrush((e.State & DrawItemState.Selected) != 0 ? AppTheme.Selection : AppTheme.Input);
            e.Graphics.FillRectangle(background, e.Bounds);
            using var chip = new SolidBrush(AppTheme.C(item.Accent)); e.Graphics.FillRectangle(chip, e.Bounds.X + 5, e.Bounds.Y + 5, 13, e.Bounds.Height - 10);
            TextRenderer.DrawText(e.Graphics, item.ToString(), _skins.Font, new Rectangle(e.Bounds.X+24,e.Bounds.Y,e.Bounds.Width-24,e.Bounds.Height), AppTheme.Ink, TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
            e.DrawFocusRectangle();
        };
        header.Controls.Add(skinField, 1, 0); layout.Controls.Add(header, 0, 0);
        _skins.SelectedIndexChanged += (_, _) =>
        {
            if (_skins.SelectedItem is not SkinSpec skin) return;
            AppTheme.Set(skin.Id, !_skinEvidence); headerHeight.Height = skin.Id == 1 ? 56 : 70;
            AppTheme.Apply(this); _chrome.Invalidate(); _map.Invalidate();
            if (_snapshot != null) Render();
        };
        layout.Controls.Add(new Label { Text = "Loaded NPCs and nearby players on the sector map. Double-click a player to inspect published gear.", Dock = DockStyle.Fill }, 0, 1);
        _search.PlaceholderText = "Search NPC or player names…";
        var filters = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 7, RowCount = 1, Padding = new Padding(0, 4, 0, 0) };
        filters.RowStyles.Add(new(SizeType.Percent, 100));
        filters.ColumnStyles.Add(new(SizeType.Percent, 100));
        foreach (float width in new[] { 145f, 105f, 150f, 85f, 135f, 100f }) filters.ColumnStyles.Add(new(SizeType.Absolute, width));
        var searchField = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1, Margin = Padding.Empty };
        searchField.ColumnStyles.Add(new(SizeType.Absolute, 85)); searchField.ColumnStyles.Add(new(SizeType.Percent, 100));
        searchField.RowStyles.Add(new(SizeType.Percent, 100));
        searchField.Controls.Add(new Label { Text = "Search", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft }, 0, 0);
        searchField.Controls.Add(_search, 1, 0); _search.AccessibleName = "Search NPC names";
        filters.Controls.Add(searchField, 0, 0);
        filters.Controls.Add(new Label { Text = "Radius (0 = all)", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleRight }, 1, 0);
        filters.Controls.Add(_radius, 2, 0); filters.Controls.Add(_unknown, 3, 0); filters.Controls.Add(_pause, 4, 0);
        var topmost = new CheckBox { Text = "Stay on top", Dock = DockStyle.Fill };
        filters.Controls.Add(topmost, 5, 0);
        filters.Controls.Add(_showPlayers, 6, 0);
        layout.Controls.Add(filters, 0, 2);
        var statusRow = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 8, RowCount = 1 };
        statusRow.RowStyles.Add(new(SizeType.Percent, 100));
        statusRow.ColumnStyles.Add(new(SizeType.Percent, 100));
        foreach (int width in new[] { 150, 115, 135, 120, 120, 125, 130 }) statusRow.ColumnStyles.Add(new(SizeType.Absolute, width));
        statusRow.Controls.Add(_status, 0, 0);
        var export = new SkinButton { Text = "Export snapshot", Dock = DockStyle.Fill };
        var navigation = new SkinButton { Text = "Navigation…", Dock = DockStyle.Fill };
        var loot = new SkinButton { Text = "Loot library", Dock = DockStyle.Fill };
        var mapping = new SkinButton { Text = "Environment…", Dock = DockStyle.Fill };
        var inspect = new SkinButton { Text = "Inspect player", Dock = DockStyle.Fill };
        inspect.Click += (_, _) => InspectPlayer();
        statusRow.Controls.Add(inspect, 1, 0); statusRow.Controls.Add(loot, 2, 0); statusRow.Controls.Add(mapping, 3, 0); statusRow.Controls.Add(export, 4, 0); statusRow.Controls.Add(navigation, 5, 0);
        var recorder = new SkinButton { Text = "Recorder…", Dock = DockStyle.Fill };
        recorder.Click += (_, _) =>
        {
            if (_recorder == null || _recorder.IsDisposed) { _recorder = new CoordinateRecorderForm(); _recorder.Show(this); }
            else _recorder.Activate();
        };
        statusRow.Controls.Add(recorder, 6, 0);
        var npcQuests = new SkinButton { Text = "NPC quests", Dock = DockStyle.Fill };
        npcQuests.Click += (_, _) =>
        {
            if (_tracking.Lost || _tracking.Tracked is not { Stats: not null } entity)
            { MessageBox.Show(this, "Select a loaded NPC or mob first.", "NPC quests"); return; }
            _questBrowser.FindNpc(entity.Name);
            _mainTabs.SelectedIndex = 1;
        };
        statusRow.Controls.Add(npcQuests, 7, 0);
        loot.Click += (_, _) => OpenLoot();
        mapping.Click += (_, _) => OpenEnvironment();
        layout.Controls.Add(statusRow, 0, 3);
        var content = new SplitContainer { Size = new Size(1450, 660), Dock = DockStyle.Fill, SplitterWidth = 8, Orientation = Orientation.Vertical,
            Panel1MinSize = 460, Panel2MinSize = 360, Margin = new Padding(0, 10, 0, 0), SplitterDistance = 800 };
        var listSide = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 2, ColumnCount = 1 };
        listSide.RowStyles.Add(new(SizeType.Percent, 100)); listSide.RowStyles.Add(new(SizeType.Absolute, 170));
        listSide.Controls.Add(_grid, 0, 0);
        var detailsPanel = new Panel { Dock = DockStyle.Fill, AutoScroll = true };
        detailsPanel.Controls.Add(_details);
        detailsPanel.SizeChanged += (_, _) => _details.MaximumSize = new Size(Math.Max(100, detailsPanel.ClientSize.Width - 32), 0);
        listSide.Controls.Add(detailsPanel, 0, 1); content.Panel1.Controls.Add(listSide);
        var side = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 4, ColumnCount = 1 };
        side.RowStyles.Add(new(SizeType.Absolute, 38));
        var toolbarRow = new RowStyle(SizeType.Absolute, 42); side.RowStyles.Add(toolbarRow);
        side.RowStyles.Add(new(SizeType.Percent, 100)); side.RowStyles.Add(new(SizeType.Absolute, 80));
        side.Controls.Add(_mapTitle, 0, 0);
        var mapTools = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = true, Padding = new Padding(0, 2, 0, 0) };
        mapTools.SizeChanged += (_, _) =>
        {
            float height = mapTools.ClientSize.Width < 520 ? 84 : 42;
            if (toolbarRow.Height != height) toolbarRow.Height = height;
        };
        void MapButton(string text, int width, Action action)
        {
            var button = new SkinButton { Text = text, Width = width, Height = 31, Margin = new Padding(2), AccessibleName = "Map " + text };
            button.Click += (_, _) => action(); mapTools.Controls.Add(button);
        }
        MapButton("Fit", 48, _map.Fit); MapButton("You", 48, _map.CenterPlayer); MapButton("Tracked", 78, _map.CenterSelected);
        MapButton("−", 36, () => _map.Zoom(0.8f)); MapButton("+", 36, () => _map.Zoom(1.25f));
        var labels = new CheckBox { Text = "Names", AutoSize = true, Margin = new Padding(6, 7, 2, 0) };
        labels.CheckedChanged += (_, _) => { _map.ShowLabels = labels.Checked; _map.Invalidate(); };
        mapTools.Controls.Add(labels);
        var height = new CheckBox { Text = "Height ±48", AutoSize = true, Margin = new Padding(6, 7, 2, 0) };
        height.CheckedChanged += (_, _) => { _map.NearHeight = height.Checked; _map.Invalidate(); };
        mapTools.Controls.Add(height);
        side.Controls.Add(mapTools, 0, 1); side.Controls.Add(_map, 0, 2); side.Controls.Add(_mapLegend, 0, 3);
        content.Panel2.Controls.Add(side); layout.Controls.Add(content, 0, 4);
        var trackerTab = new TabPage("Tracker"); var questsTab = new TabPage("Quests");
        trackerTab.Controls.Add(layout); questsTab.Controls.Add(_questBrowser);
        _pluginHost.Discover(); _pluginHost.StartEnabled();
        _pluginBrowser = new PluginBrowser(_pluginHost);
        var pluginsTab = new TabPage("Plugins"); pluginsTab.Controls.Add(_pluginBrowser);
        _mainTabs.TabPages.Add(trackerTab); _mainTabs.TabPages.Add(questsTab); _mainTabs.TabPages.Add(pluginsTab); Controls.Add(_mainTabs);
        AddColumn("Name", 230, fill: true); AddColumn("Rank", 95); AddColumn("HP (client)", 160); AddColumn("Weapon", 300);
        AddColumn("Health %", 80); AddColumn("Distance", 85); AddColumn("Faction", 175); AddColumn("Direction", 90); AddColumn("Type", 80);
        _grid.Columns[0].DefaultCellStyle.Font = _nameFont;
        _grid.Columns[0].HeaderCell.Style.Font = _nameFont;
        _grid.Columns[8].DisplayIndex = 1;
        _grid.Columns[1].HeaderCell.ToolTipText = "Sort by numeric rank; player rank pairs use the first rank, then the second.";
        _grid.Columns[2].HeaderCell.ToolTipText = "Sort by current client HP, then maximum HP. Unavailable values stay last.";
        _grid.Columns[7].HeaderCell.ToolTipText = "Sort by signed bearing: left through ahead to right. Click again to reverse.";
        UpdateSortGlyphs();
        _grid.ColumnHeaderMouseClick += (_, e) => { if (e.Button == MouseButtons.Left) SortByHeader(e.ColumnIndex); };
        _grid.RowTemplate.Height = 30;
        _grid.ColumnHeadersHeight = 34;
        _grid.EnableHeadersVisualStyles = false;
        _grid.ColumnHeadersDefaultCellStyle.BackColor = Color.FromArgb(234, 239, 244);
        _grid.ColumnHeadersDefaultCellStyle.SelectionBackColor = Color.FromArgb(234, 239, 244);
        _grid.AlternatingRowsDefaultCellStyle.BackColor = Color.FromArgb(247, 249, 251);
        _grid.DefaultCellStyle.SelectionBackColor = Color.FromArgb(212, 234, 244);
        _grid.DefaultCellStyle.SelectionForeColor = Color.Black;
        _details.Text = "Select a mob or NPC to track its distance, direction and coordinates.";
        _search.TextChanged += (_, _) => Render(); _radius.ValueChanged += (_, _) => Render(); _unknown.CheckedChanged += (_, _) => Render();
        _showPlayers.CheckedChanged += (_, _) => Render();
        _grid.CellDoubleClick += (_, e) => { if (e.RowIndex >= 0) InspectPlayer(); };
        topmost.CheckedChanged += (_, _) => TopMost = topmost.Checked;
        _pause.CheckedChanged += (_, _) =>
        {
            if (_pause.Checked) { _tracking.Unavailable(); Render(); _status.Text = "PAUSED — displayed data is frozen. Uncheck Pause to resume."; }
            else Tick();
        };
        _grid.SelectionChanged += (_, _) =>
        {
            if (!_rendering && _snapshot != null && _grid.SelectedRows.Count == 1 && _grid.SelectedRows[0].Tag is WorldEntity entity)
            { _tracking.Track(entity); UpdateDetails(); _map.Selected = entity.Identity; _map.Invalidate(); }
        };
        _map.Picked += entity => { _tracking.Track(entity); Render(); };
        export.Click += (_, _) => ExportSnapshot();
        navigation.Click += (_, _) =>
        {
            if (_navigation == null || _navigation.IsDisposed) { _navigation = new MainForm(); _navigation.Show(this); }
            else _navigation.Activate();
        };
        _timer.Tick += (_, _) => Tick();
        Shown += (_, _) => { _timer.Start(); Tick(); };
        FormClosing += async (_, e) =>
        {
            if (_closing) return;
            _closing = true; _timer.Stop();
            if (_refresh is { IsCompleted: false }) { e.Cancel = true; await _refresh; Close(); }
        };
        FormClosed += (_, _) => { _timer.Dispose(); _reader?.Dispose(); _nameFont.Dispose(); _pluginHost.Dispose(); };
        FormClosed += (_, _) => _mapAssets?.Dispose();
        AppTheme.Bind(this);
    }

    private void InspectPlayer()
    {
        if (_snapshot == null || _tracking.Lost || _tracking.Tracked is not { Player: not null } entity)
        { MessageBox.Show(this, "Select a loaded player row or map marker first.", "Player inspection"); return; }
        _inspectors.RemoveAll(f => f.IsDisposed);
        var inspector = new PlayerInspectorForm(entity, _snapshot); _inspectors.Add(inspector); inspector.Show(this);
    }

    internal void VerifyQuestView()
    {
        _mainTabs.SelectedIndex = 1;
        _questBrowser.VerifyEvidence();
        if (_mainTabs.SelectedTab?.Text != "Quests" || !_questBrowser.Visible)
            throw new InvalidOperationException("Quest tab did not open.");
    }
    internal void VerifyPluginView()
    {
        _mainTabs.SelectedIndex = 2;
        _pluginBrowser!.VerifyEvidence();
        if (_mainTabs.SelectedTab?.Text != "Plugins" || !_pluginBrowser.Visible)
            throw new InvalidOperationException("Plugins tab did not open.");
    }
    private PluginTelemetry? PluginTelemetry()
    {
        var snapshot = _snapshot;
        if (_closing || _pause.Checked || snapshot == null || _reader == null ||
            DateTimeOffset.UtcNow - snapshot.CapturedAt > TimeSpan.FromSeconds(2)) return null;
        return new(snapshot.CapturedAt, snapshot.PlayerPosition.X, snapshot.PlayerPosition.Y, snapshot.PlayerPosition.Z,
            snapshot.Entities.Count(e => e.Identity.Kind == EntityKind.Npc), snapshot.Sector?.WorldId, _reader.Window);
    }

    private LootCatalog? Loot()
    {
        if (_loot != null) return _loot;
        try { return _loot = new LootCatalog(string.IsNullOrEmpty(_mapInstall) ? Path.GetDirectoryName(ProjectPaths.Client)! : _mapInstall); }
        catch (Exception error) { _lootError = error.Message; return null; }
    }
    private void OpenLoot()
    {
        var catalog = Loot();
        if (catalog == null) { MessageBox.Show(this, "Loot definitions could not be loaded: " + _lootError); return; }
        new LootLibraryForm(catalog, _tracking.Tracked?.Stats?.TemplateId).Show(this);
    }
    private void OpenEnvironment()
    {
        try
        {
            var form = new EnvironmentForm(string.IsNullOrEmpty(_mapInstall) ? Path.GetDirectoryName(ProjectPaths.Client)! : _mapInstall, _snapshot?.Sector?.WorldId ?? 1);
            form.OverlayRequested += summary => { _map.Environment = summary; _map.Invalidate(); };
            form.Show(this);
        }
        catch (Exception error) { MessageBox.Show(this, error.Message, "Environment data unavailable"); }
    }
    internal void SaveSkinEvidence()
    {
        int selected = _skins.SelectedIndex; _skinEvidence = true;
        string folder = Path.Combine(ProjectPaths.Root, "logs", "skins"); Directory.CreateDirectory(folder);
        try
        {
            foreach (var skin in SkinCatalog.All)
            {
                _skins.SelectedIndex = skin.Id - 1; PerformLayout();
                using var bitmap = new Bitmap(Width, Height); DrawToBitmap(bitmap, new Rectangle(Point.Empty, bitmap.Size));
                bitmap.Save(Path.Combine(folder, $"skin-{skin.Id:00}.png"));
            }
        }
        finally { _skins.SelectedIndex = selected; _skinEvidence = false; }
    }

    internal async Task SaveExpansionEvidence()
    {
        using (var loot = new LootLibraryForm(Loot() ?? throw new InvalidOperationException(_lootError), 440))
        { loot.Show(this); await Task.Delay(100); loot.VerifyEvidence(); loot.Close(); }
        using var environment = new EnvironmentForm(Path.GetDirectoryName(ProjectPaths.Client)!, _snapshot?.Sector?.WorldId ?? 1);
        environment.Show(this); await Task.Delay(100); await environment.VerifyEvidence(); environment.Close();
    }

    private void AddColumn(string title, int width, bool fill = false) => _grid.Columns.Add(new DataGridViewTextBoxColumn
    { HeaderText = title, Width = width, AutoSizeMode = fill ? DataGridViewAutoSizeColumnMode.Fill : DataGridViewAutoSizeColumnMode.None,
        MinimumWidth = fill ? 210 : 60, SortMode = DataGridViewColumnSortMode.Programmatic });

    private void SortByHeader(int index)
    {
        if (index < 0 || index >= SortColumns.Length) return;
        var column = SortColumns[index];
        _sortDescending = column == _sortColumn && !_sortDescending;
        _sortColumn = column; _resetSortScroll = true; UpdateSortGlyphs(); Render();
    }
    private void UpdateSortGlyphs()
    {
        for (int i = 0; i < SortColumns.Length; i++)
            _grid.Columns[i].HeaderCell.SortGlyphDirection = SortColumns[i] == _sortColumn ?
                _sortDescending ? SortOrder.Descending : SortOrder.Ascending : SortOrder.None;
    }

    private async void Tick()
    {
        if (_closing || _pause.Checked || _refresh is { IsCompleted: false }) return;
        _refresh = RefreshSnapshot();
        await _refresh;
    }

    private async Task RefreshSnapshot()
    {
        try
        {
            var snapshot = await Task.Run(() =>
            {
                try
                {
                    _reader ??= new PlayerReader(ProjectPaths.Client);
                    _processId = _reader.Process.Id;
                    return _reader.ReadEntities();
                }
                catch { _reader?.Dispose(); _reader = null; throw; }
            });
            if (_closing) return;
            if (_pause.Checked) { _tracking.Unavailable(); return; }
            string install = Path.GetDirectoryName(_reader!.Executable)!;
            if (_mapInstall != install)
            {
                _mapInstall = install; _mapAssets?.Dispose(); _mapAssets = null;
                try { _mapAssets = new SectorMapAssets(install); _mapAssetError = ""; }
                catch (Exception error) { _mapAssetError = "Map assets unavailable: " + error.Message; }
            }
            _snapshot = snapshot; _tracking.Update(snapshot); Render();
        }
        catch (Exception error)
        {
            if (_closing) return;
            _snapshot = null; _tracking.Unavailable(); Render();
            _status.Text = "Waiting for live data: " + error.Message;
            _status.ForeColor = Color.Firebrick;
        }
    }

    private void Render()
    {
        _rendering = true;
        try
        {
            int scroll = _resetSortScroll ? 0 : Math.Max(0, _grid.FirstDisplayedScrollingRowIndex); _resetSortScroll = false;
            var rows = _snapshot == null ? Array.Empty<NearbyEntity>() : EntityOrdering.Sort(
                EntityQuery.Nearby(_snapshot, _search.Text, (float)_radius.Value, _unknown.Checked)
                    .Where(r => _showPlayers.Checked || r.Entity.Identity.Kind != EntityKind.Player), _sortColumn, _sortDescending);
            while (_grid.Rows.Count > rows.Length) _grid.Rows.RemoveAt(_grid.Rows.Count - 1);
            while (_grid.Rows.Count < rows.Length) _grid.Rows.Add();
            for (int index = 0; index < rows.Length; index++)
            {
                var row = rows[index];
                var stats = row.Entity.Stats;
                string weapon = row.Entity.Player is { } player ? string.IsNullOrEmpty(player.WeaponText) ? "None published" : player.WeaponText :
                    row.Entity.ReferenceData?.WeaponName ?? (stats == null ? "—" : stats.WeaponId == 0 ? "None / unarmed" : $"Weapon #{stats.WeaponId}");
                object[] values = { row.Entity.Name, row.Entity.Player?.RankText ?? stats?.Rank?.ToString() ?? "—", stats?.Health is { } hp ? $"{hp.Current:N0} / {hp.Maximum:N0}" : "—", weapon,
                    stats?.Health is { } percent ? $"{percent.Percent:0.#}%" : "—", row.Distance.ToString("N1"), Faction(row.Entity), Direction(row.Bearing), row.Entity.Identity.Kind == EntityKind.Npc ? "NPC" : row.Entity.Identity.Kind == EntityKind.Player ? "Player" : "Unknown" };
                for (int cell = 0; cell < values.Length; cell++)
                    if (!Equals(_grid.Rows[index].Cells[cell].Value, values[cell])) _grid.Rows[index].Cells[cell].Value = values[cell];
                _grid.Rows[index].Tag = row.Entity;
                _grid.Rows[index].Cells[0].ToolTipText = row.Entity.Name;
                if (stats?.Health is { } health)
                {
                    _grid.Rows[index].Cells[2].ToolTipText = $"Client HP: {health.Current:N0} / {health.Maximum:N0}. Raw current: {health.RawCurrent:N0}. Display bounded like the game HUD.";
                    _grid.Rows[index].Cells[2].Style.ForeColor = health.Percent < 30 ? (AppTheme.Current.Dark ? Color.LightSalmon : Color.Firebrick) : AppTheme.Accent;
                    _grid.Rows[index].Cells[4].Style.ForeColor = _grid.Rows[index].Cells[2].Style.ForeColor;
                }
                else
                {
                    _grid.Rows[index].Cells[2].ToolTipText = row.Entity.Player != null ? "Player hitpoints are not verified in the published appearance data." : "Health unavailable.";
                    _grid.Rows[index].Cells[2].Style.ForeColor = _grid.Rows[index].Cells[4].Style.ForeColor = AppTheme.Ink;
                }
                _grid.Rows[index].Cells[3].ToolTipText = row.Entity.Player != null ? weapon + " · Published display slots; double-click to inspect. Not a complete inventory or proof of the drawn weapon." : $"{weapon} · native weapon ID {stats?.WeaponId.ToString() ?? "unmapped"}";
                _grid.Rows[index].Cells[6].ToolTipText = (row.Entity.Player?.FactionId ?? stats?.FactionId) is { } faction ? $"{Faction(row.Entity)} · faction ID {faction}" : "Faction not mapped for this actor type.";
                _grid.Rows[index].DefaultCellStyle.ForeColor = stats?.Dead == true || row.Entity.Player?.Dead == true ? AppTheme.Muted : AppTheme.Ink;
            }
            foreach (DataGridViewRow row in _grid.Rows)
            {
                bool selected = !_tracking.Lost && _tracking.Tracked != null && row.Tag is WorldEntity entity && entity.Identity == _tracking.Tracked.Identity;
                if (row.Selected != selected) row.Selected = selected;
            }
            if (_grid.RowCount > 0 && _grid.FirstDisplayedScrollingRowIndex != Math.Min(scroll, _grid.RowCount - 1)) _grid.FirstDisplayedScrollingRowIndex = Math.Min(scroll, _grid.RowCount - 1);
            UpdateMap(rows);
            _map.Selected = _tracking.Lost ? null : _tracking.Tracked?.Identity; _map.Invalidate();
            if (_snapshot != null && !_pause.Checked)
            {
                int npcs = _snapshot.Entities.Count(e => e.Identity.Kind == EntityKind.Npc);
                int players = _snapshot.Entities.Count(e => e.Identity.Kind == EntityKind.Player);
                _status.Text = $"Live · {rows.Length} shown · {npcs} NPCs / {players} players loaded · +{_tracking.Appeared} / −{_tracking.Disappeared} · {_snapshot.CapturedAt.LocalDateTime:HH:mm:ss}";
                _status.ForeColor = AppTheme.Accent;
                _chrome.Readout = $"SECTOR {_snapshot.Sector?.WorldId} · NPC {npcs} · PLAYERS {players}"; _chrome.Invalidate();
            }
            UpdateDetails();
            _inspectors.RemoveAll(f => f.IsDisposed);
            foreach (var inspector in _inspectors) inspector.UpdateSnapshot(_snapshot);
        }
        finally { _rendering = false; }
    }

    private void UpdateMap(IReadOnlyList<NearbyEntity> rows)
    {
        SectorMapDefinition? definition = null; Bitmap? image = null;
        string empty = "Waiting for a verified current sector. Log into Neocron and finish zoning.";
        string title = "Sector map";
        if (_snapshot?.Sector is { } sector)
        {
            title = _mapAssets?.Catalog.Name(sector.WorldId) ?? $"Sector {sector.WorldId}";
            if (sector.MapRotationDegrees == null) empty = "The client’s map orientation is unavailable. Finish loading the game HUD.";
            else if (_mapAssets == null) empty = _mapAssetError;
            else
            {
                definition = _mapAssets.Catalog.Find(sector.WorldId);
                if (definition == null) empty = "This sector has no mapped sector image in the local client. NPC data remains available in the list.";
                else
                {
                    try { image = _mapAssets.Image(definition); }
                    catch (Exception error) { empty = "Sector image unavailable: " + error.Message; }
                }
            }
        }
        if (_mapTitle.Text != title) _mapTitle.Text = title;
        _map.SetData(_snapshot, rows, definition, image, empty);
        _mapLegend.Text = _map.HasMap ? "● NPC   ◆ Player   ▲ You   ◎ Tracked   × Dead\nWheel: zoom · Drag: pan · Hollow NPC: height Δ >48" : "Sector maps use the game’s own assets and reference coordinates.";
    }

    private static string Direction(float bearing) => Math.Abs(bearing) < 8 ? "Ahead" :
        Math.Abs(bearing) > 172 ? "Behind" : $"{Math.Abs(bearing):0}° {(bearing > 0 ? "right" : "left")}";

    private static string Faction(WorldEntity entity) => entity.Player is { } player ? player.FactionName ?? (player.FactionId?.ToString() ?? "—") : entity.ReferenceData?.FactionName ??
        (entity.Stats?.FactionId is { } id ? id == 0 ? "Unspecified (0)" : $"Faction #{id}" : "—");

    private void UpdateDetails()
    {
        if (_tracking.Tracked is not { } entity) return;
        if (_tracking.Lost || _snapshot == null)
        { _details.Text = $"{entity.Name}\n\nTracking lost. This actor is no longer verified in live data.\nSelect a row to track again."; return; }
        var row = EntityQuery.Describe(entity, _snapshot.PlayerPosition, _snapshot.PlayerForward);
        if (entity.Player is { } player)
        {
            _details.Text = $"{entity.Name} · PLAYER · HUD rank {player.RankText}\nFaction {Faction(entity)} · Soul Light {player.SoulLight?.ToString() ?? "—"}\n" +
                $"Clan ID {player.ClanId?.ToString() ?? "—"} · Clan rank code {player.ClanRank?.ToString() ?? "—"}\n" +
                $"Visible weapons: {(player.WeaponText.Length > 0 ? player.WeaponText : "None published")}\n" +
                $"Distance {row.Distance:N1} · Direction {Direction(row.Bearing)} · Height Δ {row.Height:+0.0;-0.0;0.0}\n" +
                $"X {entity.Position.X:N1} · Y {entity.Position.Y:N1} · Z {entity.Position.Z:N1}\n" +
                "Double-click the row or choose Inspect player for gear and appearance.\n" + PlayerDetails.Coverage;
            return;
        }
        var stats = entity.Stats;
        string vitals = stats?.Health is { } hp ? $"HP  {hp.Current:N0} / {hp.Maximum:N0} ({hp.Percent:0.#}%)" : "HP  Unavailable";
        string state = stats?.Dead is { } dead ? dead ? "Dead" : "Alive" : "Unknown";
        string weapon = entity.ReferenceData?.WeaponName ?? (stats is { WeaponId: 0 } ? "None (ID 0)" : stats != null ? $"Weapon #{stats.WeaponId}" : "Unmapped");
        string extra = stats == null ? "Extra stats are not mapped for this actor type.\n" :
            $"Rank  {stats.Rank?.ToString() ?? "—"}     State  {state}\nFaction  {Faction(entity)}\n" +
            $"Weapon  {weapon}\nArmor profile  {stats.ArmorId}    Template  {stats.TemplateId}\n" +
            $"Base AI / dialog  {entity.ReferenceData?.AiScript ?? "—"} / {entity.ReferenceData?.DialogScript ?? "—"}\n";
        if (stats != null)
        {
            extra += $"Damage modifier  {stats.DamageModifier?.ToString("0.###") ?? "—"}\nDamage frequency  {stats.DamageFrequency?.ToString("0.###") ?? "—"} (native value)\n";
            if (entity.ReferenceData is { } reference)
                extra += $"Template base HP  {reference.BaseHealth?.ToString("N0") ?? "—"}    Base rank  {reference.BaseRank?.ToString() ?? "—"}\n" +
                    $"Weapon base TL  {reference.WeaponLevel?.ToString() ?? "—"}    Base range  {reference.BaseWeaponRange?.ToString("N1") ?? "—"}\n" +
                    $"Base magazine  {reference.BaseMagazineSize?.ToString() ?? "—"}    Shots / burst  {reference.ShotsPerBurst?.ToString() ?? "—"}\n";
        }
        _details.Text = $"{entity.Name}\n\n{vitals}\n{extra}\nDistance  {row.Distance:N1} units\nDirection  {Direction(row.Bearing)}   Height Δ {row.Height:+0.0;-0.0;0.0}\n" +
            $"X {entity.Position.X:N1}   Y {entity.Position.Y:N1}   Z {entity.Position.Z:N1}\n\n" +
            "HP/state reflect the client's stored readings. Faction/weapon names and AI/dialog labels use local definitions. Base weapon stats can differ from effective combat stats.";
    }

    private void ExportSnapshot()
    {
        var snapshot = _snapshot;
        if (snapshot == null || _pause.Checked) { MessageBox.Show(this, "Resume live tracking before exporting a snapshot."); return; }
        using var dialog = new SaveFileDialog { Filter = "JSON snapshot (*.json)|*.json", FileName = $"neocron-entities-{DateTime.Now:yyyyMMdd-HHmmss}.json" };
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            try { File.WriteAllText(dialog.FileName, EntityExport.Json(snapshot, _processId)); }
            catch (Exception error) { MessageBox.Show(this, error.Message, "Export failed"); }
        }
    }

    internal void VerifyLiveView()
    {
        if (_snapshot == null) throw new InvalidOperationException("Live UI check needs an available in-world snapshot.");
        if (_grid.Columns[0].DefaultCellStyle.Font?.Bold != true) throw new InvalidOperationException("Name column is not bold.");
        _search.Text = "copbot";
        int copbots = _grid.RowCount;
        if (copbots == 0 || _grid.Rows.Cast<DataGridViewRow>().Any(r => !((WorldEntity)r.Tag!).Name.Contains("copbot", StringComparison.OrdinalIgnoreCase)))
            throw new InvalidOperationException("Live COPBOT name filtering failed.");
        _grid.Rows[0].Selected = true;
        if (_tracking.Tracked == null || _tracking.Lost) throw new InvalidOperationException("Live row selection failed.");
        var live = _tracking.Tracked;
        if (live.Stats?.Rank != 120 || live.Stats.Health == null || live.Stats.FactionId != 1 || live.ReferenceData?.FactionName != "City Administration")
            throw new InvalidOperationException("Expanded COPBOT stats or definition lookup failed.");
        _search.Text = "__no_such_npc__";
        if (_grid.RowCount != 0 || _tracking.Lost) throw new InvalidOperationException("Empty filter damaged the tracked selection.");
        _search.Clear();
        int titleChanges = 0; EventHandler changed = (_, _) => titleChanges++;
        _mapTitle.TextChanged += changed; Render(); Render(); Render(); _mapTitle.TextChanged -= changed;
        if (titleChanges != 0) throw new InvalidOperationException("Sector title still toggles during steady refreshes.");
        var npcRow = _grid.Rows.Cast<DataGridViewRow>().First(r => r.Tag is WorldEntity entity && entity.Identity == live.Identity);
        if (!npcRow.Cells[2].Value!.ToString()!.Contains('/') || !npcRow.Cells[3].Value!.ToString()!.Contains("CopBot", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Hitpoints or weapon name are missing from the main table.");
        _map.VerifyProjection();
        Size normalSize = ClientSize;
        ClientSize = new Size(1180, 720); PerformLayout();
        if (_map.Height < 150) throw new InvalidOperationException("Map collapses in the smaller supported window.");
        ClientSize = normalSize; PerformLayout();
        File.WriteAllText(Path.Combine(ProjectPaths.Root, "logs", "tracker-ui-check.json"),
            System.Text.Json.JsonSerializer.Serialize(new { status = "passed", copbots, rows = _grid.RowCount,
                tracked = _tracking.Tracked.Name, _snapshot.CapturedAt, rank = live.Stats.Rank, hp = live.Stats.Health,
                faction = live.ReferenceData.FactionName, weapon = live.ReferenceData.WeaponName,
                sector = _snapshot.Sector, sectorName = _mapTitle.Text, mapMarkers = _map.MarkerCount, availableSectorMaps = _mapAssets?.Catalog.Count,
                checks = new[] { "live refresh", "case-insensitive filter", "selection", "empty filter", "selection preserved outside filter", "live NPC stats", "local definition lookup", "native sector map", "player projection", "zoom anchor", "steady sector title", "main-table numeric HP and weapon" } }));
    }

    internal async Task VerifyPlayers()
    {
        if (_snapshot == null) throw new InvalidOperationException("No live snapshot for player verification.");
        var player = _snapshot.Entities.FirstOrDefault(e => e.Identity.Kind == EntityKind.Player && e.Player != null)
            ?? throw new InvalidOperationException("Live player verification needs at least one nearby player.");
        _search.Text = player.Name;
        if (!_showPlayers.Checked || !_grid.Rows.Cast<DataGridViewRow>().Any(r => r.Tag is WorldEntity e && e.Identity == player.Identity))
            throw new InvalidOperationException("Nearby players are not included by default or cannot be searched.");
        var row = _grid.Rows.Cast<DataGridViewRow>().First(r => r.Tag is WorldEntity e && e.Identity == player.Identity);
        row.Selected = true;
        if (_tracking.Tracked?.Identity != player.Identity) throw new InvalidOperationException("Player selection failed.");
        _showPlayers.Checked = false;
        if (_grid.RowCount != 0) throw new InvalidOperationException("Players toggle did not filter players.");
        _showPlayers.Checked = true; _search.Clear();
        using var inspector = new PlayerInspectorForm(player, _snapshot);
        inspector.Show(this); await Task.Delay(100); inspector.VerifyEvidence(_snapshot); inspector.Close();
        File.WriteAllText(Path.Combine(ProjectPaths.Root, "logs", "player-ui-check.json"),
            System.Text.Json.JsonSerializer.Serialize(new { status = "passed", player.Name, players = _snapshot.Entities.Count(e => e.Player != null),
                checks = new[] { "bold names", "players enabled by default", "player search", "player selection", "player toggle", "live gear inspector", "gear cleared on unload", "no silent rebind" } }));
    }

    internal void VerifyHeaderSorting()
    {
        if (_snapshot == null || _grid.RowCount == 0) throw new InvalidOperationException("Header-sort verification needs live rows.");
        var selected = _tracking.Tracked?.Identity;
        for (int column = 0; column < SortColumns.Length; column++)
        {
            // Start on another header, then exercise the same handler used by a header click.
            SortByHeader((column + 1) % SortColumns.Length); SortByHeader(column);
            foreach (bool descending in new[] { false, true })
            {
                if (descending) SortByHeader(column);
                var expected = EntityOrdering.Sort(EntityQuery.Nearby(_snapshot, _search.Text, (float)_radius.Value, _unknown.Checked)
                    .Where(r => _showPlayers.Checked || r.Entity.Identity.Kind != EntityKind.Player), SortColumns[column], descending);
                Render(); // The user's order must survive the next live redraw.
                var actual = _grid.Rows.Cast<DataGridViewRow>().Select(r => ((WorldEntity)r.Tag!).Identity);
                if (!actual.SequenceEqual(expected.Select(r => r.Entity.Identity)) || _sortDescending != descending ||
                    _grid.Columns[column].HeaderCell.SortGlyphDirection != (descending ? SortOrder.Descending : SortOrder.Ascending) ||
                    _tracking.Tracked?.Identity != selected)
                    throw new InvalidOperationException($"Header sort or preserved selection failed for {_grid.Columns[column].HeaderText}.");
            }
        }
        SortByHeader(5); // Restore nearest-first for the normal opening view.
        File.WriteAllText(Path.Combine(ProjectPaths.Root, "logs", "sorting-ui-check.json"),
            System.Text.Json.JsonSerializer.Serialize(new { status = "passed", headers = _grid.Columns.Cast<DataGridViewColumn>().Select(c => c.HeaderText),
                directionsChecked = 2, preservedSelection = true, liveRedrawPreserved = true }));
    }
}
