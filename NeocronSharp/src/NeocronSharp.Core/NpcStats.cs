namespace NeocronSharp.Core;

public sealed record NpcHealth(int RawCurrent, int Maximum)
{
    // RPOS health info (RVA 0x140379) bounds the health pair for display.
    // The client can retain a regeneration accumulator above Maximum.
    public int Current => Math.Clamp(RawCurrent, 0, Maximum);
    public float Percent => 100f * Current / Maximum;
    public bool WasClamped => Current != RawCurrent;
    public static NpcHealth? FromNative(int current, int maximum) =>
        maximum is > 0 and <= 100_000_000 && current is >= -100_000_000 and <= 100_000_000 ? new(current, maximum) : null;
}

public sealed record NpcStats(int TemplateId, NpcHealth? Health, int? Rank, float? RawRank,
    int? FactionId, int WeaponId, int ArmorId, bool? Dead, float? DamageModifier,
    float? DamageFrequency, int FunctionCode, ushort NativeFlags);

/// <summary>Optional reference data from this install's definitions, not observed combat results.</summary>
public sealed record NpcReferenceData(string? FactionName, string? WeaponName, int? WeaponLevel,
    float? BaseWeaponRange, int? BaseRank, int? BaseHealth, string? AiScript, string? DialogScript,
    int? BaseMagazineSize = null, int? ShotsPerBurst = null);
