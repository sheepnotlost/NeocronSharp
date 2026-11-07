using System.Numerics;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// A healer's team mode for the follow loop (7 Nov): who is on the team, where they stand (read from memory), what the team
/// panel on screen says about their buffs, and so which cast is next and where to be for it. The decision is pure
/// (<see cref="Decide"/>); the panel is read on a throttle and corrects the clocks (<see cref="TeamRounds.Seen"/>).
/// </summary>
internal sealed class TeamHeal
{
    /// <summary>Slot 1 heals every 30 s, slots 2 to 4 buff for 180 s, slot 5 for 600 s.</summary>
    public static readonly TeamRounds.Spell[] Spells =
        [new(1, 30, true), new(2, 180, false), new(3, 180, false), new(4, 180, false), new(5, 600, false)];

    /// <summary>A buff just cast may not show in the panel for a moment: a reading without it is not trusted this long.</summary>
    public const double ShowsWithin = 4;

    public sealed record Move(TeamRounds.Due? Due, string? Who, Vector3? Goal, float Stop);

    private readonly string[] _names;
    private readonly Dictionary<string, Vector3> _at = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<(string, int), double> _castAt = [];
    private readonly TeamPanel? _panel;
    private readonly nint _window;
    private double _panelAt = double.NegativeInfinity;

    public TeamHeal(IEnumerable<string> names, nint window = 0, TeamPanel? panel = null)
    {
        _names = names.Select(n => n.Trim()).Where(n => n.Length > 0).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        _window = window;
        _panel = panel;
        Rounds = new TeamRounds(_names, Spells);
    }

    public TeamRounds Rounds { get; }
    public IReadOnlyList<string> Names => _names;

    /// <summary>Where each ally stands now (those in the actor list and alive).</summary>
    public void Observe(IEnumerable<WorldEntity> entities)
    {
        _at.Clear();
        foreach (var e in entities)
            if (e.Identity.Kind == EntityKind.Player && !FollowCommand.Dead(e) && _names.FirstOrDefault(n => string.Equals(n, e.Name, StringComparison.OrdinalIgnoreCase)) is { } name)
                _at[name] = e.Position;
    }

    public Vector3? Position(string who) => _at.TryGetValue(who, out var p) ? p : null;

    public IReadOnlyList<Vector3> Positions => _at.Values.ToList();

    /// <summary>The panel's readings applied to the clocks: a buff showing puts its clock right, a buff gone (not just cast) makes it due.</summary>
    public void Apply(IEnumerable<PanelMember> members, double now)
    {
        foreach (var member in members)
        {
            if (_names.FirstOrDefault(n => string.Equals(n, member.Name, StringComparison.OrdinalIgnoreCase)) is not { } who) continue;
            foreach (var spell in Spells)
            {
                if (member.Buffs.TryGetValue(spell.Slot, out var seconds))
                {
                    if (seconds is { } left) Rounds.Seen(who, spell, left, now);   // shown, timer unread: leave the clock
                }
                else if (!_castAt.TryGetValue((who, spell.Slot), out var at) || now - at > ShowsWithin)
                    Rounds.Seen(who, spell, null, now);
            }
        }
    }

    /// <summary>Reads the team panel on the left of the screen if it is time (<paramref name="every"/> seconds); returns whether it did.</summary>
    public bool ReadPanel(double now, double every)
    {
        if (_panel == null || _window == 0 || now - _panelAt < every) return false;
        _panelAt = now;
        var grab = TargetBar.Grab(_window, (w, h) => (0, (int)(h * .06f), (int)(w * .4f), (int)(h * .88f)));
        if (grab is not { } g) return false;
        Apply(_panel.Read(g.Pixels, g.Width, g.Height), now);
        return true;
    }

    public void Cast(string who, TeamRounds.Spell spell, double now)
    {
        Rounds.Cast(who, spell, now);
        _castAt[(who, spell.Slot)] = now;
    }

    /// <summary>
    /// What to do now: cast where standing (the due ally within <paramref name="reach"/>, or the healer's own), walk to a due ally out
    /// of reach, or with nothing due be at the team's station. Goal null: stay put.
    /// </summary>
    public Move Decide(double now, Vector3 self, Vector3? mob, float reach)
    {
        var due = Rounds.Next(now);
        if (due != null && due.Who == TeamRounds.Self) return new Move(due, null, null, 0);
        if (due != null && Position(due.Who) is { } at)
        {
            if (PointNavigation.Distance(self, at) <= reach) return new Move(due, due.Who, null, 0);
            return new Move(due, due.Who, at, reach * .8f);
        }
        var allies = Positions;
        return new Move(null, null, allies.Count == 0 ? null : TeamStation.Spot(self, allies, mob), 40);
    }
}
