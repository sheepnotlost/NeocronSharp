using System.Numerics;
using NeocronSharp.Core;

internal static class OrderingTests
{
    public static void Run(Action<string, Action> test, Action<bool, string> check)
    {
        NearbyEntity Row(int id, string name, int? rank, int hp, int max, float distance, string weapon = "Rifle", string faction = "City Administration", float bearing = 0)
        {
            var stats = new NpcStats(1, NpcHealth.FromNative(hp, max), rank, rank, 1, 1651, 1, false, 1, 15, 0, 0);
            var entity = new WorldEntity(new(1,2,(ulong)id+100,(ulong)id+200,id,EntityKind.Npc), name, Vector3.Zero,"SCRIPTEDPLAYER",stats,
                new(faction,weapon,128,500,120,15168,null,null));
            return new(entity,distance,distance,bearing,0);
        }
        int[] Keys(IEnumerable<NearbyEntity> rows) => rows.Select(r=>r.Entity.Identity.Key).ToArray();
        test("Distance sorting is numeric in both directions rather than sorting formatted strings", () =>
        {
            var rows = new[] { Row(1,"A",1,10,100,1000),Row(2,"B",1,10,100,20),Row(3,"C",1,10,100,100) };
            check(Keys(EntityOrdering.Sort(rows,EntitySortColumn.Distance)).SequenceEqual(new[]{2,3,1}),"Numeric ascending distance failed");
            check(Keys(EntityOrdering.Sort(rows,EntitySortColumn.Distance,true)).SequenceEqual(new[]{1,3,2}),"Numeric descending distance failed");
        });
        test("HP sorts current then maximum while Health sorts the actual percentage", () =>
        {
            var rows = new[] {Row(1,"A",1,20,100,1),Row(2,"B",1,100,1000,1),Row(3,"C",1,20,50,1)};
            check(Keys(EntityOrdering.Sort(rows,EntitySortColumn.HitPoints)).SequenceEqual(new[]{3,1,2}),"HP pair must use current then max");
            check(Keys(EntityOrdering.Sort(rows,EntitySortColumn.HealthPercent)).SequenceEqual(new[]{2,1,3}),"Health percent is a different numeric key");
        });
        test("Missing player HP stays last in ascending and descending order", () =>
        {
            var known=Row(1,"Z",1,10,100,1);var missing=Row(2,"A",null,0,0,1) with{Entity=Row(2,"A",null,0,0,1).Entity with{Stats=null}};
            foreach(bool descending in new[]{false,true})
                check(Keys(EntityOrdering.Sort(new[]{missing,known},EntitySortColumn.HitPoints,descending)).SequenceEqual(new[]{1,2}),"Unknown HP moved before known HP");
        });
        test("Player rank pairs sort numerically by first then second rank alongside NPC ranks", () =>
        {
            var npc=Row(1,"NPC",100,1,1,1);var p1=Row(2,"P1",null,0,0,1);var p2=Row(3,"P2",null,0,0,1);
            PlayerDetails Player(int second)=>new(64,second,1,null,100,null,null,false,Array.Empty<PlayerGear>(),new Dictionary<int,float>());
            p1=p1 with{Entity=p1.Entity with{Stats=null,Player=Player(9)}};p2=p2 with{Entity=p2.Entity with{Stats=null,Player=Player(61)}};
            check(Keys(EntityOrdering.Sort(new[]{npc,p2,p1},EntitySortColumn.Rank)).SequenceEqual(new[]{2,3,1}),"Rank pair order failed");
            check(Keys(EntityOrdering.Sort(new[]{npc,p1,p2},EntitySortColumn.Rank,true)).SequenceEqual(new[]{1,3,2}),"Descending rank pair order failed");
        });
        test("Name, weapon, faction and type headers use case-insensitive text keys", () =>
        {
            var a=Row(1,"zulu",1,1,1,1,"alpha rifle","beta");var b=Row(2,"Alpha",1,1,1,1,"Zulu rifle","Alpha");
            check(Keys(EntityOrdering.Sort(new[]{a,b},EntitySortColumn.Name)).SequenceEqual(new[]{2,1}),"Name order failed");
            check(Keys(EntityOrdering.Sort(new[]{a,b},EntitySortColumn.Weapon)).SequenceEqual(new[]{1,2}),"Weapon order failed");
            check(Keys(EntityOrdering.Sort(new[]{a,b},EntitySortColumn.Faction)).SequenceEqual(new[]{2,1}),"Faction order failed");
            var player=b with{Entity=b.Entity with{Identity=b.Entity.Identity with{Kind=EntityKind.Player}}};
            check(Keys(EntityOrdering.Sort(new[]{player,a},EntitySortColumn.Type)).SequenceEqual(new[]{1,2}),"Type order failed");
        });
        test("Direction sorts signed bearings and equal values have deterministic instance order", () =>
        {
            var rows=new[]{Row(1,"Same",1,1,1,1,bearing:90),Row(2,"Same",1,1,1,1,bearing:-90),Row(3,"Same",1,1,1,1,bearing:0)};
            check(Keys(EntityOrdering.Sort(rows,EntitySortColumn.Direction)).SequenceEqual(new[]{2,3,1}),"Signed direction order failed");
            var tied=rows.Select(r=>r with{Bearing=0}).ToArray();
            check(Keys(EntityOrdering.Sort(tied.Reverse(),EntitySortColumn.Direction)).SequenceEqual(new[]{1,2,3}),"Tied instances must not depend on registry enumeration order");
        });
    }
}
