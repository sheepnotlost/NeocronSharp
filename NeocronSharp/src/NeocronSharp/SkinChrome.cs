using System.Drawing.Drawing2D;

namespace NeocronSharp;

internal sealed class SkinButton : Button
{
    private bool _hover, _pressed;
    protected override void OnMouseEnter(EventArgs e) { base.OnMouseEnter(e); _hover = true; Invalidate(); }
    protected override void OnMouseLeave(EventArgs e) { base.OnMouseLeave(e); _hover = _pressed = false; Invalidate(); }
    protected override void OnMouseDown(MouseEventArgs e) { base.OnMouseDown(e); _pressed = true; Invalidate(); }
    protected override void OnMouseUp(MouseEventArgs e) { base.OnMouseUp(e); _pressed = false; Invalidate(); }
    protected override void OnPaint(PaintEventArgs e)
    {
        if (AppTheme.Current.Id == 1) { base.OnPaint(e); return; }
        var g = e.Graphics; var bounds = new Rectangle(0, 0, Math.Max(1, Width - 1), Math.Max(1, Height - 1));
        Color face = _hover ? AppTheme.Selection : AppTheme.Surface;
        using var fill = new LinearGradientBrush(bounds, ControlPaint.Light(face, .15f), ControlPaint.Dark(face, .1f), LinearGradientMode.Vertical);
        g.FillRectangle(fill, bounds); using var border = new Pen(AppTheme.Border); g.DrawRectangle(border, bounds);
        using var light = new Pen(Color.FromArgb(100, _pressed ? Color.Black : Color.White));
        g.DrawLine(light, 1, 1, Width - 2, 1); g.DrawLine(light, 1, 1, 1, Height - 2);
        var text = Rectangle.Inflate(bounds, -4, -2); if (_pressed) text.Offset(1, 1);
        TextRenderer.DrawText(g, Text, Font, text, Enabled ? AppTheme.Ink : AppTheme.Muted,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
        if (Focused) ControlPaint.DrawFocusRectangle(g, Rectangle.Inflate(bounds, -4, -4), AppTheme.Ink, face);
    }
}

internal sealed class SkinHeader : Control
{
    internal string Readout = "Waiting for Neocron";
    internal SkinHeader() { DoubleBuffered = true; Dock = DockStyle.Fill; }
    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e); var g = e.Graphics; var skin = AppTheme.Current;
        if (skin.Id == 1)
        {
            using var font = new Font("Segoe UI", 20, FontStyle.Bold);
            TextRenderer.DrawText(g, "NPC / Player tracker", font, ClientRectangle, AppTheme.Ink, TextFormatFlags.VerticalCenter); return;
        }
        var box = new Rectangle(0, 0, Math.Max(1, Width - 1), Math.Max(1, Height - 1));
        using var metal = new LinearGradientBrush(box, ControlPaint.Light(AppTheme.Surface, .3f), AppTheme.Window, LinearGradientMode.Vertical);
        g.FillRectangle(metal, box);
        if (skin.Material is "Brushed" or "Titanium" or "HiFi" or "Classic")
        {
            using var line = new Pen(Color.FromArgb(24, Color.White));
            for (int y = 2; y < Height; y += 3) g.DrawLine(line, 1, y, Width - 2, y);
        }
        if (skin.Material == "Leather")
        {
            using var grain = new Pen(Color.FromArgb(35, Color.Black));
            for (int y = 3; y < Height; y += 5) for (int x = (y % 10); x < Width; x += 8) g.DrawArc(grain, x, y, 4, 3, 20, 150);
            using var stitch = new Pen(AppTheme.C(skin.Accent)) { DashStyle = DashStyle.Dash };
            g.DrawRectangle(stitch, 5, 5, Width - 11, Height - 11);
        }
        if (skin.Material is "XP" or "Aqua")
        {
            using var gloss = new LinearGradientBrush(new Rectangle(1, 1, Width - 2, Height / 2), Color.FromArgb(170, Color.White), Color.FromArgb(0, Color.White), LinearGradientMode.Vertical);
            g.FillRectangle(gloss, 1, 1, Width - 2, Height / 2);
        }
        using var edge = new Pen(AppTheme.Border); g.DrawRectangle(edge, box);
        int lcdWidth = Math.Min(330, Width / 2);
        var lcd = new Rectangle(Width - lcdWidth - 12, 12, lcdWidth, Height - 24);
        using var dark = new SolidBrush(AppTheme.C(skin.LcdBack)); g.FillRectangle(dark, lcd);
        g.DrawRectangle(edge, lcd);
        if (skin.Material is "CRT" or "OEL" or "Classic")
        {
            using var scan = new Pen(Color.FromArgb(30, Color.Black));
            for (int y = lcd.Top + 1; y < lcd.Bottom; y += 3) g.DrawLine(scan, lcd.Left, y, lcd.Right, y);
        }
        using var titleFont = new Font("Segoe UI", 14, FontStyle.Bold);
        TextRenderer.DrawText(g, "NEOCRONSHARP", titleFont, new Rectangle(15, 4, Width - lcdWidth - 35, Height - 8), AppTheme.Ink, TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
        using var lcdFont = new Font("Consolas", 10, FontStyle.Bold);
        TextRenderer.DrawText(g, Readout, lcdFont, Rectangle.Inflate(lcd, -8, -3), AppTheme.C(skin.LcdInk), TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
    }
}
