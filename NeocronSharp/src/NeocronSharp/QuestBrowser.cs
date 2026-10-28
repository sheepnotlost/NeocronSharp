using NeocronSharp.Core;

namespace NeocronSharp;

internal sealed class QuestBrowser : UserControl
{
    private readonly QuestCatalog _catalog = new();
    private readonly TextBox _search = new() { Dock = DockStyle.Fill, PlaceholderText = "Search quest, NPC, item, location, rank or dialogue…" };
    private readonly ComboBox _category = new() { Dock = DockStyle.Fill, DropDownStyle = ComboBoxStyle.DropDownList };
    private readonly Label _status = new() { Dock = DockStyle.Fill, AutoEllipsis = true, TextAlign = ContentAlignment.MiddleLeft };
    private readonly DataGridView _grid = new() { Dock = DockStyle.Fill, ReadOnly = true, AllowUserToAddRows = false,
        AllowUserToDeleteRows = false, AllowUserToResizeRows = false, RowHeadersVisible = false,
        SelectionMode = DataGridViewSelectionMode.FullRowSelect, MultiSelect = false, EnableHeadersVisualStyles = false,
        AutoGenerateColumns = false, RowTemplate = { Height = 28 } };
    private readonly TextBox _overview = Reader(true);
    private readonly TextBox _dialogueHighlights = Reader(true);
    private readonly TextBox _dialogue = Reader(false);
    private readonly Label _selected = new() { Dock = DockStyle.Fill, AutoEllipsis = true, Font = new Font("Segoe UI", 13, FontStyle.Bold) };
    private readonly System.Windows.Forms.Timer _debounce = new() { Interval = 250 };
    private bool _rendering;

    public QuestBrowser()
    {
        Dock = DockStyle.Fill;
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(18), ColumnCount = 1, RowCount = 5 };
        layout.RowStyles.Add(new(SizeType.Absolute, 42));
        layout.RowStyles.Add(new(SizeType.Absolute, 30));
        layout.RowStyles.Add(new(SizeType.Absolute, 42));
        layout.RowStyles.Add(new(SizeType.Absolute, 30));
        layout.RowStyles.Add(new(SizeType.Percent, 100));
        layout.Controls.Add(new Label { Text = "Quest inspector", Dock = DockStyle.Fill, Font = new Font("Segoe UI", 18, FontStyle.Bold) }, 0, 0);
        layout.Controls.Add(new Label { Text = "Search Neocron's mission definitions, NPCs, objectives, items, rewards and dialogue.", Dock = DockStyle.Fill, AutoEllipsis = true }, 0, 1);
        var filters = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1 };
        filters.ColumnStyles.Add(new(SizeType.Percent, 100)); filters.ColumnStyles.Add(new(SizeType.Absolute, 210));
        filters.Controls.Add(_search, 0, 0); filters.Controls.Add(_category, 1, 0);
        _category.Items.AddRange(new object[] { "All quests & dialogue", "Mission guides", "Other quest dialogue" }); _category.SelectedIndex = 0;
        layout.Controls.Add(filters, 0, 2); layout.Controls.Add(_status, 0, 3);

        var split = new SplitContainer { Size = new Size(1350, 550), Dock = DockStyle.Fill, SplitterWidth = 8,
            Panel1MinSize = 300, Panel2MinSize = 400, SplitterDistance = 470 };
        _grid.Columns.Add(new DataGridViewTextBoxColumn { HeaderText = "Quest / dialogue", AutoSizeMode = DataGridViewAutoSizeColumnMode.Fill, MinimumWidth = 160, SortMode = DataGridViewColumnSortMode.NotSortable });
        _grid.Columns.Add(new DataGridViewTextBoxColumn { HeaderText = "Contact", Width = 150, SortMode = DataGridViewColumnSortMode.NotSortable });
        _grid.Columns.Add(new DataGridViewTextBoxColumn { HeaderText = "Source", Width = 110, SortMode = DataGridViewColumnSortMode.NotSortable });
        split.Panel1.Controls.Add(_grid);
        var right = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3 };
        right.RowStyles.Add(new(SizeType.Absolute, 36)); right.RowStyles.Add(new(SizeType.Absolute, 44)); right.RowStyles.Add(new(SizeType.Percent, 100));
        right.Controls.Add(_selected, 0, 0);
        right.Controls.Add(new Label { Text = "From the game files. Your current quest progress is not shown; dialogue can include alternative choices.", Dock = DockStyle.Fill }, 0, 1);
        var views = new TabControl { Dock = DockStyle.Fill };
        var overviewPage = new TabPage("Mission details"); var highlightsPage = new TabPage("Dialogue"); var dialoguePage = new TabPage("Original source");
        overviewPage.Controls.Add(_overview); highlightsPage.Controls.Add(_dialogueHighlights); dialoguePage.Controls.Add(_dialogue);
        views.TabPages.Add(overviewPage); views.TabPages.Add(highlightsPage); views.TabPages.Add(dialoguePage);
        right.Controls.Add(views, 0, 2); split.Panel2.Controls.Add(right); layout.Controls.Add(split, 0, 4); Controls.Add(layout);

        _debounce.Tick += (_, _) => { _debounce.Stop(); Filter(); };
        _search.TextChanged += (_, _) => { _debounce.Stop(); _debounce.Start(); };
        _category.SelectedIndexChanged += (_, _) => Filter();
        _grid.SelectionChanged += (_, _) => { if (!_rendering && _grid.SelectedRows.Count == 1 && _grid.SelectedRows[0].Tag is QuestEntry entry) Select(entry); };
        Filter();
    }

    private static TextBox Reader(bool wrap) => new() { Dock = DockStyle.Fill, ReadOnly = true, Multiline = true, ScrollBars = wrap ? ScrollBars.Vertical : ScrollBars.Both,
        WordWrap = wrap, Font = new Font(wrap ? "Segoe UI" : "Consolas", 10), BorderStyle = BorderStyle.FixedSingle };

    private static string Lines(string text) => text.Replace("\r\n", "\n").Replace("\n", "\r\n");

    private void Filter()
    {
        string? category = _category.SelectedIndex switch { 1 => "Structured mission", 2 => "Lua quest script", _ => null };
        var entries = _catalog.Search(_search.Text, category).ToArray();
        _rendering = true;
        try
        {
            _grid.Rows.Clear();
            foreach (var entry in entries)
            {
                int row = _grid.Rows.Add(entry.Title, entry.Contact, entry.Category == "Structured mission" ? "Mission guide" : "Dialogue");
                _grid.Rows[row].Tag = entry;
            }
            if (entries.Length > 0) { _grid.Rows[0].Selected = true; Select(entries[0]); }
            else { _selected.Text = "No matches"; _overview.Text = "Try another quest, NPC, item or location."; _dialogueHighlights.Clear(); _dialogue.Clear(); }
            _status.Text = $"{entries.Length:N0} shown / {_catalog.Entries.Count:N0} references · " +
                $"{_catalog.Entries.Count(e => e.Category == "Structured mission"):N0} mission guides · {_catalog.Entries.Count(e => e.Category == "Lua quest script"):N0} dialogue sources";
        }
        finally { _rendering = false; }
    }

    private void Select(QuestEntry entry)
    {
        _selected.Text = entry.Title;
        _overview.Text = Lines($"{entry.Description}\n\n{entry.Details}\n\nReference: {entry.Source}:{entry.Line}");
        _overview.SelectionStart = 0;
        _dialogue.Text = Lines(entry.Dialogue.Length == 0 ? "No dialogue section was found in this file." : entry.Dialogue);
        _dialogue.SelectionStart = 0;
        _dialogueHighlights.Text = Lines(entry.Conversation.Length == 0
            ? "No readable dialogue was identified for this entry."
            : "Possible dialogue and responses from the game files. Some lines are alternatives and may depend on your choices or quest progress.\n\n" + entry.Conversation);
        _dialogueHighlights.SelectionStart = 0;
    }

    internal void FindNpc(string name)
    {
        _category.SelectedIndex = 0;
        _search.Text = name;
        _debounce.Stop(); Filter();
    }

    internal void VerifyEvidence()
    {
        _search.Text = "Sorcha Nox"; _debounce.Stop(); Filter();
        if (_grid.Rows.Count == 0 || !_catalog.Search("Sorcha Nox").Any(e => e.Id == "shamantrophy.mission.decontaminate_remains" && e.Details.Contains("Swamp Shaman Remains")))
            throw new InvalidOperationException("Quest browser did not find Sorcha and the trophy mission.");
        _search.Text = "WOC_BIGBADGUN"; _debounce.Stop(); Filter();
        if (!_catalog.Search("WOC_BIGBADGUN").Any(e => e.Dialogue.Contains("GETBASERANK()") && e.Dialogue.Contains("result >=55")))
            throw new InvalidOperationException("Quest browser lost the Big Bad Gun rank branch.");
        _search.Clear(); _debounce.Stop(); Filter();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) _debounce.Dispose();
        base.Dispose(disposing);
    }
}
