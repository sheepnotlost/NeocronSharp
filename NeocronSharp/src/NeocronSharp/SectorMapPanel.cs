using System.Drawing.Drawing2D;
using System.ComponentModel;
using System.Numerics;
using NeocronSharp.Core;

namespace NeocronSharp;

internal sealed class SectorMapPanel : Panel
{
    private readonly MapViewport _view = new();
    private readonly ToolTip _tip = new();
    private EntitySnapshot? _snapshot;
    private IReadOnlyList<NearbyEntity> _rows = Array.Empty<NearbyEntity>();
    private SectorMapDefinition? _definition;
    private Bitmap? _image;
    private string _empty = "Waiting for the current sector…";
    private Point _last, _down;
    private bool _dragging, _moved;
    private string _hover = "";
    private EntityIdentity? _hoverIdentity;
    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    internal EntityIdentity? Selected { get; set; }
    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    internal bool ShowLabels { get; set; }
    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    internal bool NearHeight { get; set; }
    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    internal EnvironmentSummary? Environment { get; set; }
    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    internal IReadOnlyList<CoordinatePoint>? Trail { get; set; }
    internal bool HasMap => _image != null && _definition != null && _snapshot?.Sector?.MapRotationDegrees != null;
    internal int MarkerCount => VisibleRows().Count();
    internal event Action<WorldEntity>? Picked;
    internal SectorMapPanel()
    {
        DoubleBuffered = true; TabStop = true; SetStyle(ControlStyles.Selectable, true);
        AccessibleName = "Sector map with NPC markers";
        Cursor = Cursors.Hand;
    }
    internal void SetData(EntitySnapshot? snapshot, IReadOnlyList<NearbyEntity> rows, SectorMapDefinition? definition, Bitmap? image, string empty)
    {
        bool changed = snapshot?.Sector?.WorldId != _snapshot?.Sector?.WorldId || definition?.BitmapId != _definition?.BitmapId;
        if (changed) _view.Reset();
        _snapshot = snapshot; _rows = rows; _definition = definition; _image = image; _empty = empty;
        _view.ImageSize = image == null ? new(256, 256) : new(image.Width, image.Height);
        if (changed || !HasMap || (_hoverIdentity != null && !_rows.Any(r => r.Entity.Identity == _hoverIdentity)))
        { _tip.SetToolTip(this, ""); _hover = ""; _hoverIdentity = null; }
        Invalidate();
    }
    private void ResizeView() => _view.ViewSize = new(Math.Max(1, ClientSize.Width), Math.Max(1, ClientSize.Height));
    protected override void OnResize(EventArgs eventargs) { base.OnResize(eventargs); ResizeView(); Invalidate(); }
    internal void Fit() { ResizeView(); _view.Reset(); Invalidate(); }
    internal void Zoom(float factor) { ResizeView(); _view.ZoomAt(_view.ViewSize / 2, factor); Invalidate(); }
    internal void CenterPlayer()
    { if (HasMap) { ResizeView(); _view.Center(Pixel(_snapshot!.PlayerPosition)); Invalidate(); } }
    internal void CenterSelected()
    {
        var row = _rows.FirstOrDefault(r => r.Entity.Identity == Selected);
        if (HasMap && row != null) { ResizeView(); _view.Center(Pixel(row.Entity.Position)); Invalidate(); }
    }
    private Vector2 Pixel(Vector3 position) => _definition!.Project(position, _snapshot!.Sector!.MapRotationDegrees!.Value);
    private PointF Screen(Vector3 position) { var p = _view.ToScreen(Pixel(position)); return new(p.X, p.Y); }
    private bool InImage(Vector3 position)
    { var p = Pixel(position); return p.X >= 0 && p.Y >= 0 && p.X < _image!.Width && p.Y < _image.Height; }
    private IEnumerable<NearbyEntity> VisibleRows() => HasMap ? _rows.Where(r => (!NearHeight || Math.Abs(r.Height) <= 48) && InImage(r.Entity.Position)) : Enumerable.Empty<NearbyEntity>();

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e); var g = e.Graphics; ResizeView();
        g.Clear(AppTheme.Surface); g.SmoothingMode = SmoothingMode.AntiAlias;
        if (!HasMap)
        {
            TextRenderer.DrawText(g, _empty, Font, Rectangle.Inflate(ClientRectangle, -30, -30), AppTheme.Muted,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.WordBreak); return;
        }
        var top = _view.ToScreen(Vector2.Zero); var bottom = _view.ToScreen(_view.ImageSize);
        var rect = RectangleF.FromLTRB(top.X, top.Y, bottom.X, bottom.Y);
        g.InterpolationMode = InterpolationMode.HighQualityBicubic;
        var skin = AppTheme.Current;
        Color light = AppTheme.Surface, dark = skin.Dark ? Color.FromArgb(157, 168, 171) : Color.FromArgb(44, 42, 36);
        using (var attributes = new System.Drawing.Imaging.ImageAttributes())
        {
            var matrix = new System.Drawing.Imaging.ColorMatrix(new[]
            {
                new[]{(light.R-dark.R)/255f,(light.G-dark.G)/255f,(light.B-dark.B)/255f,0f,0f},
                new[]{0f,0f,0f,0f,0f}, new[]{0f,0f,0f,0f,0f}, new[]{0f,0f,0f,1f,0f},
                new[]{dark.R/255f,dark.G/255f,dark.B/255f,0f,1f}
            });
            attributes.SetColorMatrix(matrix);
            g.DrawImage(_image!, Rectangle.Round(rect), 0, 0, _image!.Width, _image.Height, GraphicsUnit.Pixel, attributes);
        }
        using var border = new Pen(AppTheme.Border); g.DrawRectangle(border, rect.X, rect.Y, rect.Width, rect.Height);
        var saved = g.Save(); g.SetClip(rect, CombineMode.Intersect);
        if (Trail != null)
        {
            using var trailPen = new Pen(skin.Dark ? Color.LightSkyBlue : Color.FromArgb(33, 103, 152), 2);
            PointF? previous = null; int previousSegment = -1;
            foreach (var point in Trail)
            {
                if (point.SectorId != _snapshot!.Sector!.WorldId || (NearHeight && Math.Abs(point.Y - _snapshot.PlayerPosition.Y) > 48)) { previous = null; continue; }
                PointF screen = Screen(new(point.X, point.Y, point.Z));
                if (previous != null && point.Segment == previousSegment)
                {
                    float distance = Math.Abs(screen.X - previous.Value.X) + Math.Abs(screen.Y - previous.Value.Y);
                    if (distance < 1) continue;
                    g.DrawLine(trailPen, previous.Value, screen);
                }
                previous = screen; previousSegment = point.Segment;
            }
        }
        if (Environment?.WorldId == _snapshot!.Sector!.WorldId)
        {
            using var node = new Pen(skin.Dark ? Color.LightSkyBlue : Color.Teal, 1.5f);
            using var exit = new Pen(skin.Dark ? Color.Gold : Color.DarkRed, 2);
            foreach (var feature in Environment.Features.Where(f => f.Kind is "GroundPathPoint" or "WorldChange"))
            {
                var point = Screen(feature.Position);
                if (feature.Kind == "GroundPathPoint") g.DrawRectangle(node, point.X-3, point.Y-3, 6, 6);
                else g.DrawPolygon(exit, new[] { new PointF(point.X,point.Y-6),new PointF(point.X+6,point.Y),new PointF(point.X,point.Y+6),new PointF(point.X-6,point.Y) });
            }
        }
        PointF player = Screen(_snapshot!.PlayerPosition);
        var selected = VisibleRows().FirstOrDefault(r => r.Entity.Identity == Selected);
        if (selected != null)
        {
            using var line = new Pen(AppTheme.Accent, 1.5f) { DashStyle = DashStyle.Dash };
            g.DrawLine(line, player, Screen(selected.Entity.Position));
        }
        foreach (var row in VisibleRows().OrderBy(r => r.Entity.Identity == Selected ? 1 : 0))
        {
            var point = Screen(row.Entity.Position); bool tracked = row.Entity.Identity == Selected;
            float radius = tracked ? 6 : 4;
            using var halo = new Pen(Color.White, tracked ? 4 : 3);
            g.DrawEllipse(halo, point.X - radius, point.Y - radius, radius * 2, radius * 2);
            using var ink = new Pen(row.Entity.Identity.Kind == EntityKind.Player ? (skin.Dark ? Color.LightSkyBlue : Color.FromArgb(32, 86, 151)) : row.Entity.Identity.Kind == EntityKind.Npc ? Color.FromArgb(146, 78, 24) : AppTheme.Muted, 2);
            if (row.Entity.Stats?.Dead == true || row.Entity.Player?.Dead == true)
            { g.DrawLine(ink, point.X - 4, point.Y - 4, point.X + 4, point.Y + 4); g.DrawLine(ink, point.X + 4, point.Y - 4, point.X - 4, point.Y + 4); }
            else if (row.Entity.Identity.Kind == EntityKind.Player)
            {
                var diamond = new[] { new PointF(point.X, point.Y-radius-2), new PointF(point.X+radius+2, point.Y), new PointF(point.X, point.Y+radius+2), new PointF(point.X-radius-2, point.Y) };
                using var fill = new SolidBrush(ink.Color); g.FillPolygon(fill, diamond); g.DrawPolygon(Pens.White, diamond);
            }
            else if (Math.Abs(row.Height) > 48) g.DrawEllipse(ink, point.X - radius, point.Y - radius, radius * 2, radius * 2);
            else { using var fill = new SolidBrush(ink.Color); g.FillEllipse(fill, point.X - radius, point.Y - radius, radius * 2, radius * 2); }
            if (tracked) g.DrawEllipse(Pens.Black, point.X - 9, point.Y - 9, 18, 18);
            if (ShowLabels || tracked) DrawLabel(g, row.Entity.Name, point);
        }
        if (InImage(_snapshot.PlayerPosition))
        {
            Vector2 direction = Pixel(_snapshot.PlayerPosition + _snapshot.PlayerForward * 10) - Pixel(_snapshot.PlayerPosition);
            if (direction.LengthSquared() > 0) direction = Vector2.Normalize(direction);
            var side = new Vector2(-direction.Y, direction.X);
            PointF P(Vector2 delta) => new(player.X + delta.X, player.Y + delta.Y);
            PointF[] triangle = { P(direction * 11), P(-direction * 7 + side * 6), P(-direction * 7 - side * 6) };
            using var fill = new SolidBrush(Color.FromArgb(37, 78, 101)); g.FillPolygon(fill, triangle);
            using var halo = new Pen(Color.White, 2); g.DrawPolygon(halo, triangle);
        }
        g.Restore(saved);
        TextRenderer.DrawText(g, Trail == null ? $"{_view.Zoom:0.#}×  ·  {MarkerCount} markers" : $"{_view.Zoom:0.#}×  ·  {Trail.Count:N0} recorded samples", Font, new Point(10, Height - 26), AppTheme.Ink, AppTheme.Surface);
    }
    private void DrawLabel(Graphics g, string text, PointF at)
    {
        string name = text.Length > 36 ? text[..33] + "…" : text;
        var size = TextRenderer.MeasureText(name, Font);
        var box = new Rectangle((int)at.X + 11, (int)at.Y - size.Height / 2, size.Width + 6, size.Height + 2);
        using var background = new SolidBrush(Color.FromArgb(240, AppTheme.Input)); g.FillRectangle(background, box);
        TextRenderer.DrawText(g, name, Font, box, AppTheme.Ink, TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix);
    }
    private NearbyEntity? Hit(Point location) => VisibleRows().Select(r => (Row: r, Point: Screen(r.Entity.Position)))
        .Select(x => (x.Row, Distance: MathF.Pow(location.X - x.Point.X, 2) + MathF.Pow(location.Y - x.Point.Y, 2)))
        .Where(x => x.Distance < 144).OrderBy(x => x.Distance).Select(x => x.Row).FirstOrDefault();
    protected override void OnMouseWheel(MouseEventArgs e)
    { base.OnMouseWheel(e); ResizeView(); _view.ZoomAt(new(e.X, e.Y), e.Delta > 0 ? 1.25f : 0.8f); Invalidate(); }
    protected override void OnMouseDown(MouseEventArgs e)
    {
        base.OnMouseDown(e);
        if (e.Button != MouseButtons.Left || !HasMap) return;
        Focus(); _down = _last = e.Location; _dragging = Capture = true; _moved = false;
    }
    protected override void OnMouseMove(MouseEventArgs e)
    {
        base.OnMouseMove(e);
        if (_dragging)
        {
            if (!_moved && Math.Abs(e.X - _down.X) + Math.Abs(e.Y - _down.Y) <= 4) return;
            _moved = true;
            _view.Drag(new(e.X - _last.X, e.Y - _last.Y)); _last = e.Location; Invalidate(); return;
        }
        var row = Hit(e.Location);
        _hoverIdentity = row?.Entity.Identity;
        string text = row == null ? "" : row.Entity.Player is { } player ? $"{row.Entity.Name} · Player\nHUD rank {player.RankText} · {player.FactionName}\n{player.WeaponText}\nDistance {row.Distance:N1} · Height Δ {row.Height:+0.0;-0.0;0.0}" :
            $"{row.Entity.Name}\nRank {row.Entity.Stats?.Rank?.ToString() ?? "—"} · HP {row.Entity.Stats?.Health?.Percent.ToString("0.#") ?? "—"}%\nDistance {row.Distance:N1} · Height Δ {row.Height:+0.0;-0.0;0.0}";
        if (text != _hover) { _tip.SetToolTip(this, text); _hover = text; }
    }
    protected override void OnMouseUp(MouseEventArgs e)
    {
        base.OnMouseUp(e); if (!_dragging) return;
        _dragging = Capture = false;
        if (!_moved && Hit(e.Location) is { } row) Picked?.Invoke(row.Entity);
    }
    protected override void OnKeyDown(KeyEventArgs e)
    {
        base.OnKeyDown(e);
        switch (e.KeyCode)
        {
            case Keys.Home: Fit(); break;
            case Keys.Add: case Keys.Oemplus: Zoom(1.25f); break;
            case Keys.Subtract: case Keys.OemMinus: Zoom(0.8f); break;
            default: return;
        }
        e.Handled = true;
    }
    internal void VerifyProjection()
    {
        if (!HasMap || !InImage(_snapshot!.PlayerPosition) || MarkerCount == 0) throw new InvalidOperationException("Live sector map/marker check failed.");
        Vector2 player = _view.ToScreen(Pixel(_snapshot.PlayerPosition)); var anchor = _view.FromScreen(player);
        _view.ZoomAt(player, 2);
        if (Vector2.Distance(_view.FromScreen(player), anchor) > 0.01f) throw new InvalidOperationException("Map zoom anchor drifted.");
        _view.Reset();
        var marker = VisibleRows().First();
        PointF location = Screen(marker.Entity.Position);
        if (Hit(Point.Round(location)) == null) throw new InvalidOperationException("Projected NPC marker cannot be selected.");
        var snapshot = _snapshot; var rows = _rows; var definition = _definition; var image = _image;
        SetData(null, Array.Empty<NearbyEntity>(), null, null, "Unavailable");
        if (HasMap || MarkerCount != 0) throw new InvalidOperationException("Stale map markers survived disconnect.");
        SetData(snapshot, rows, definition, image, "");
    }
    protected override void Dispose(bool disposing) { if (disposing) _tip.Dispose(); base.Dispose(disposing); }
}
