namespace NeocronSharp.Core;

public sealed record SkinSpec(int Id, string Name, string Reference, int Window, int Surface, int Input, int Border,
    int Ink, int Muted, int Selection, int Accent, int LcdBack, int LcdInk, string Material, bool Dark)
{
    public override string ToString() => $"{Id}. {Name}";
}

public static class SkinCatalog
{
    // Original desktop adaptations of period references; not imported Winamp packages.
    public static IReadOnlyList<SkinSpec> All { get; } = new[]
    {
        new SkinSpec(1,"Basic · Matte Cream","Existing basic layout",0xE5DFD2,0xEBE6DA,0xF0EBDF,0xB7AE9B,0x343129,0x625B4E,0xD2D7C6,0x405A4B,0xE4DFD2,0x343129,"Matte",false),
        new SkinSpec(2,"Classic 2.x","Winamp Classic",0x252639,0x303248,0x181C24,0x7D8096,0xE2E4EF,0xBBC0D2,0x464B62,0xA7D75A,0x101B12,0xB2F566,"Classic",true),
        new SkinSpec(3,"MMD3 · Titanium","MMD3",0x333A40,0x424B52,0x1E292E,0x94A2AB,0xEEF3F5,0xDEE7EB,0x536B73,0xB1F2FA,0x142C32,0x9BF5FA,"Titanium",true),
        new SkinSpec(4,"Bento · Amber","Winamp Bento",0x222222,0x303030,0x171717,0x737373,0xECEAE5,0xC5C1B7,0x574627,0xF3BA59,0x18150E,0xFFD17C,"Bento",true),
        new SkinSpec(5,"Sputnik · Steel","Sputnik",0xBEC6CA,0xD3DADD,0xE5EBED,0x6E7C85,0x202C32,0x404E58,0xA8C0CA,0x254E69,0x182A32,0xB6E8F0,"Brushed",false),
        new SkinSpec(6,"Leather Box","Leather Box",0x35291F,0x49382A,0x221B17,0xA17D57,0xF6E8D1,0xDBC9AD,0x6C4E31,0xF2C16F,0x191B10,0xDBEC9E,"Leather",true),
        new SkinSpec(7,"XP Metallic","Winamp XP Metallic",0xB9C6D5,0xD3DDE7,0xE8EEF5,0x6D819B,0x172B43,0x3A4C62,0xA2BEDA,0x204B7D,0x19273E,0xB9DDFF,"XP",false),
        new SkinSpec(8,"Pioneer · OEL","Pioneer OEL",0x171E29,0x253144,0x101722,0x57728E,0xDCEFFF,0xABC8E2,0x304F6E,0x61CBFF,0x07172A,0x7AE5FF,"OEL",true),
        new SkinSpec(9,"Matrix Xtream","Matrix Xtream",0x101A15,0x1C2C22,0x0A120E,0x426F50,0xC4F7D1,0xA0D8AE,0x2B4C34,0x8DE5A1,0x051008,0x92FFA8,"CRT",true),
        new SkinSpec(10,"iBDE · HiFi","iBDE HiFi",0x27282B,0x383A3F,0x17191D,0x82868E,0xF3EDEA,0xD4CAC6,0x61413A,0xFFB09A,0x1D1010,0xFFB5A1,"HiFi",true),
        new SkinSpec(11,"WinAqua","WinAquaAmp",0xCADDE5,0xE0EBEF,0xEFF6F9,0x6C96AC,0x153B51,0x385767,0xA4CDD9,0x1C5369,0xC0DFEB,0x123D52,"Aqua",false)
    };
    public static SkinSpec Get(int id) => All.FirstOrDefault(s => s.Id == id) ?? All[0];
    public static double Contrast(int foreground, int background)
    {
        double L(int rgb)
        {
            double C(int c) { double v = c / 255d; return v <= .04045 ? v / 12.92 : Math.Pow((v + .055) / 1.055, 2.4); }
            return .2126 * C((rgb >> 16) & 255) + .7152 * C((rgb >> 8) & 255) + .0722 * C(rgb & 255);
        }
        double a = L(foreground), b = L(background); return (Math.Max(a, b) + .05) / (Math.Min(a, b) + .05);
    }
}
