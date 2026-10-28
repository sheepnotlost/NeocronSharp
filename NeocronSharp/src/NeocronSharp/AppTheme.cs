namespace NeocronSharp;

internal static class AppTheme
{
    internal static NeocronSharp.Core.SkinSpec Current { get; private set; } = NeocronSharp.Core.SkinCatalog.Get(1);
    internal static event Action? Changed;
    internal static Color C(int value) => Color.FromArgb((value >> 16) & 255, (value >> 8) & 255, value & 255);
    internal static Color Window => C(Current.Window);
    internal static Color Surface => C(Current.Surface);
    internal static Color Input => C(Current.Input);
    internal static Color Border => C(Current.Border);
    internal static Color Ink => C(Current.Ink);
    internal static Color Muted => C(Current.Muted);
    internal static Color Selection => C(Current.Selection);
    internal static Color Accent => C(Current.Accent);
    internal static void Set(int id, bool persist = false)
    {
        Current = NeocronSharp.Core.SkinCatalog.Get(id);
        if (persist)
        {
            string directory = Path.Combine(ProjectPaths.Root, "settings"); Directory.CreateDirectory(directory);
            string path = Path.Combine(directory, "appearance.json");
            File.WriteAllText(path, System.Text.Json.JsonSerializer.Serialize(new { skin = Current.Id }));
        }
        Changed?.Invoke();
    }
    internal static void Load()
    {
        try
        {
            using var json = System.Text.Json.JsonDocument.Parse(File.ReadAllText(Path.Combine(ProjectPaths.Root, "settings", "appearance.json")));
            Set(json.RootElement.GetProperty("skin").GetInt32());
        }
        catch (Exception e) when (e is IOException or System.Text.Json.JsonException or KeyNotFoundException or InvalidOperationException) { Set(1); }
    }
    internal static void Bind(Form form)
    {
        void Update() { if (!form.IsDisposed) { Apply(form); form.Invalidate(true); } }
        Changed += Update; form.FormClosed += (_, _) => Changed -= Update; Update();
    }

    internal static void Apply(Control control)
    {
        control.ForeColor = Ink;
        control.BackColor = control is Form or TableLayoutPanel or FlowLayoutPanel or SplitContainer or SplitterPanel ? Window : Surface;
        if (control is Label or CheckBox) control.BackColor = Color.Transparent;
        switch (control)
        {
            case Button button:
                button.FlatStyle = FlatStyle.Flat; button.FlatAppearance.BorderColor = Border;
                button.FlatAppearance.MouseOverBackColor = Selection; button.FlatAppearance.MouseDownBackColor = Border;
                button.BackColor = Input; button.UseVisualStyleBackColor = false;
                break;
            case TextBox text: text.BackColor = Input; text.BorderStyle = BorderStyle.FixedSingle; break;
            case ComboBox combo: combo.BackColor = Input; combo.ForeColor = Ink; combo.FlatStyle = FlatStyle.Flat; break;
            case NumericUpDown number: number.BackColor = Input; number.BorderStyle = BorderStyle.FixedSingle; break;
            case DataGridView grid:
                grid.BackgroundColor = Input; grid.GridColor = Border;
                grid.DefaultCellStyle.BackColor = Input; grid.DefaultCellStyle.ForeColor = Ink;
                grid.DefaultCellStyle.SelectionBackColor = Selection; grid.DefaultCellStyle.SelectionForeColor = Ink;
                grid.AlternatingRowsDefaultCellStyle.BackColor = Surface;
                grid.ColumnHeadersDefaultCellStyle.BackColor = Window; grid.ColumnHeadersDefaultCellStyle.ForeColor = Ink;
                grid.ColumnHeadersDefaultCellStyle.SelectionBackColor = Window;
                break;
        }
        foreach (Control child in control.Controls) Apply(child);
    }
}
