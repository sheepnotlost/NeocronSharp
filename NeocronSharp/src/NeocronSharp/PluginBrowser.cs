using NeocronSharp.Core;

namespace NeocronSharp;

internal sealed class PluginBrowser : UserControl
{
    private readonly PluginHost _host;
    private readonly DataGridView _list = new() { Dock = DockStyle.Fill, ReadOnly = true, AllowUserToAddRows = false,
        AllowUserToDeleteRows = false, AllowUserToResizeRows = false, RowHeadersVisible = false, MultiSelect = false,
        SelectionMode = DataGridViewSelectionMode.FullRowSelect, EnableHeadersVisualStyles = false, RowTemplate = { Height = 29 } };
    private readonly Label _selected = new() { Dock = DockStyle.Fill, Font = new Font("Segoe UI", 13, FontStyle.Bold), AutoEllipsis = true };
    private readonly Label _description = new() { Dock = DockStyle.Fill, AutoEllipsis = true };
    private readonly Label _status = new() { Dock = DockStyle.Fill, AutoEllipsis = true };
    private readonly TextBox _settings = new() { Dock = DockStyle.Fill, Multiline = true, ScrollBars = ScrollBars.Both, WordWrap = false, Font = new Font("Consolas", 10) };
    private readonly TextBox _log = new() { Dock = DockStyle.Fill, ReadOnly = true, Multiline = true, ScrollBars = ScrollBars.Both, WordWrap = false, Font = new Font("Consolas", 9) };
    private readonly Button _enable = new SkinButton { Text = "Enable", Width = 105, Height = 34 };
    private readonly Button _disable = new SkinButton { Text = "Disable", Width = 105, Height = 34 };
    private readonly Button _save = new SkinButton { Text = "Save settings", Width = 140, Height = 34 };
    private PluginEntry? _entry;
    private bool _rendering;

    public PluginBrowser(PluginHost host)
    {
        _host = host; Dock = DockStyle.Fill;
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(18), ColumnCount = 1, RowCount = 4 };
        layout.RowStyles.Add(new(SizeType.Absolute, 40)); layout.RowStyles.Add(new(SizeType.Absolute, 30));
        layout.RowStyles.Add(new(SizeType.Absolute, 45)); layout.RowStyles.Add(new(SizeType.Percent, 100));
        layout.Controls.Add(new Label { Text = "Plugins", Dock = DockStyle.Fill, Font = new Font("Segoe UI", 18, FontStyle.Bold) }, 0, 0);
        layout.Controls.Add(new Label { Text = "Enable trusted C# modules and manage their settings and logs.", Dock = DockStyle.Fill }, 0, 1);
        var toolbar = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false };
        var refresh = new SkinButton { Text = "Refresh list", Width = 115, Height = 34 };
        toolbar.Controls.AddRange(new Control[] { refresh, _enable, _disable, _save }); layout.Controls.Add(toolbar, 0, 2);
        var split = new SplitContainer { Dock = DockStyle.Fill, Size = new Size(1350, 550), SplitterDistance = 420, Panel1MinSize = 300, Panel2MinSize = 400 };
        _list.Columns.Add(new DataGridViewTextBoxColumn { HeaderText = "Plugin", AutoSizeMode = DataGridViewAutoSizeColumnMode.Fill, MinimumWidth = 150, SortMode = DataGridViewColumnSortMode.NotSortable });
        _list.Columns.Add(new DataGridViewTextBoxColumn { HeaderText = "Status", Width = 95, SortMode = DataGridViewColumnSortMode.NotSortable });
        split.Panel1.Controls.Add(_list);
        var right = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 5 };
        right.RowStyles.Add(new(SizeType.Absolute, 35)); right.RowStyles.Add(new(SizeType.Absolute, 50)); right.RowStyles.Add(new(SizeType.Absolute, 38));
        right.RowStyles.Add(new(SizeType.Percent, 50)); right.RowStyles.Add(new(SizeType.Percent, 50));
        right.Controls.Add(_selected, 0, 0); right.Controls.Add(_description, 0, 1); right.Controls.Add(_status, 0, 2);
        var settingsPanel = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 2, ColumnCount = 1 };
        settingsPanel.RowStyles.Add(new(SizeType.Absolute, 27)); settingsPanel.RowStyles.Add(new(SizeType.Percent, 100));
        settingsPanel.Controls.Add(new Label { Text = "Settings (JSON) · changes apply on next start", Dock = DockStyle.Fill }, 0, 0); settingsPanel.Controls.Add(_settings, 0, 1);
        var logPanel = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 2, ColumnCount = 1 };
        logPanel.RowStyles.Add(new(SizeType.Absolute, 27)); logPanel.RowStyles.Add(new(SizeType.Percent, 100));
        logPanel.Controls.Add(new Label { Text = "Recent log · refresh to update", Dock = DockStyle.Fill }, 0, 0); logPanel.Controls.Add(_log, 0, 1);
        right.Controls.Add(settingsPanel, 0, 3); right.Controls.Add(logPanel, 0, 4); split.Panel2.Controls.Add(right);
        layout.Controls.Add(split, 0, 3); Controls.Add(layout);
        _list.SelectionChanged += (_, _) => { if (!_rendering && _list.SelectedRows.Count == 1) ShowEntry(_list.SelectedRows[0].Tag as PluginEntry); };
        refresh.Click += (_, _) => { try { _host.Discover(); _host.StartEnabled(); RefreshList(); } catch (Exception e) { ShowError(e); } };
        _enable.Click += (_, _) => Act(e => _host.Enable(e));
        _disable.Click += (_, _) => Act(e => _host.Disable(e));
        _save.Click += (_, _) => Act(e => _host.WriteSettings(e, _settings.Text));
        RefreshList();
    }

    private void Act(Action<PluginEntry> action)
    {
        if (_entry?.Manifest == null) return;
        try { action(_entry); RefreshList(_entry.Manifest.Id); }
        catch (Exception e) { ShowError(e); }
    }
    private void ShowError(Exception error) => MessageBox.Show(this, error.Message, "Plugin manager", MessageBoxButtons.OK, MessageBoxIcon.Warning);
    private void RefreshList(string? keep = null)
    {
        _rendering = true;
        try
        {
            _list.Rows.Clear(); int selected = 0;
            foreach (var entry in _host.Entries)
            {
                int row = _list.Rows.Add(entry.Manifest?.Name ?? Path.GetFileName(entry.Folder), entry.Status);
                _list.Rows[row].Tag = entry;
                if (keep != null && entry.Manifest?.Id == keep) selected = row;
            }
            if (_list.RowCount > 0) { _list.ClearSelection(); _list.CurrentCell = _list.Rows[selected].Cells[0]; _list.Rows[selected].Selected = true; ShowEntry((PluginEntry)_list.Rows[selected].Tag!); }
            else { ShowEntry(null); }
        }
        finally { _rendering = false; }
    }
    private void ShowEntry(PluginEntry? entry)
    {
        _entry = entry; bool valid = entry?.Manifest != null;
        _enable.Enabled = valid && !entry!.Running; _disable.Enabled = valid && (entry!.Enabled || entry.Running); _save.Enabled = valid;
        _settings.ReadOnly = !valid;
        if (entry == null)
        {
            _selected.Text = "No plugins found";
            _description.Text = "Put a plugin.json and its DLL inside a folder under NeocronSharp\\plugins, then choose Refresh list.";
            _status.Text = _host.DiscoveryError; _settings.Clear(); _log.Clear(); return;
        }
        if (!valid)
        {
            _selected.Text = Path.GetFileName(entry.Folder); _description.Text = "This plugin could not be loaded.";
            _status.Text = entry.Error; _settings.Clear(); _log.Clear(); return;
        }
        var manifest = entry.Manifest!;
        _selected.Text = manifest.Name + "  ·  " + manifest.Version;
        _description.Text = manifest.Description;
        _status.Text = entry.Error.Length > 0 ? entry.Error : $"{entry.Status}  ·  {manifest.Id}";
        try { _settings.Text = _host.ReadSettings(entry); _log.Text = _host.ReadRecentLog(entry); _log.SelectionStart = _log.TextLength; _log.ScrollToCaret(); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException) { _status.Text = error.Message; }
    }
    internal void VerifyEvidence()
    {
        if (!_host.Entries.Any(e => e.Manifest?.Id == "neocronsharp.example")) throw new InvalidOperationException("Example plugin not discovered.");
        RefreshList("neocronsharp.example");
        if (_entry?.Manifest?.Id != "neocronsharp.example") throw new InvalidOperationException("Plugin selection failed.");
        _settings.Text = "{\"greeting\":\"Plugin UI test\"}"; _save.PerformClick(); _enable.PerformClick();
        if (_entry?.Running != true || !_log.Text.Contains("Plugin UI test")) throw new InvalidOperationException("Plugin UI did not start the module or show its log.");
        _disable.PerformClick();
        if (_entry?.Running != false || _entry.Enabled) throw new InvalidOperationException("Plugin UI did not disable the module.");
    }
}
