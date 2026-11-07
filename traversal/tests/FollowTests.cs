using System.Numerics;
using NavmeshPrototype;
using NeocronSharp;
using NeocronSharp.Core;

/// <summary>Offline tests for following an actor: the distance band, the gap and the replan decision (<see cref="FollowLogic"/>).</summary>
internal static class FollowTests
{
    private static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }

    private static WorldEntity Actor(string name, Vector3 at, EntityKind kind = EntityKind.Player, PlayerDetails? player = null) =>
        new(new EntityIdentity(1, 2, 3, 4, 0, kind), name, at, "test", Player: player);

    public static void Run(Action<string, Action> test)
    {
        test("Position jumps: one or two are the game correcting you, a third close by is not", () =>
        {
            var jumps = new PositionJumps();
            Check(!jumps.TooMany(0) && !jumps.TooMany(4), "two are allowed");
            Check(jumps.TooMany(8), "the third within 10 s stops");
            var spread = new PositionJumps();
            Check(!spread.TooMany(0) && !spread.TooMany(8) && !spread.TooMany(16) && !spread.TooMany(24), "far apart they never add up");
        });

        test("Screen aim: learns where the body is drawn, keeps it as the mob moves, fires only inside the brackets", () =>
        {
            var aim = new ScreenAim();
            const int high = 1080;
            float focal = ScreenAim.Focal * high, across = MathF.Atan(20 / focal), down = MathF.Atan(-60 / focal);
            Check(aim.Error(0, .1f, -.05f, 500) == (.1f, -.05f), "at first, straight at the memory point");
            // Memory says the mob is dead ahead; the game draws its body 60 px below and 20 px right of the crosshair.
            Check(aim.See(0.1, new[] { new TargetMark(-5, 50, 45, 70, true) }, 0, 0, high, 1), "the mark is taken");
            var e = aim.Error(0.1, 0, 0, 500);
            Check(MathF.Abs(e.Yaw - across) < 1e-4 && MathF.Abs(e.Pitch - down) < 1e-4, "turn down and right onto it");
            Check(!aim.Locked(0.1), "not inside the brackets yet: no shots");
            var moved = aim.Error(0.2, .03f, 0, 500);
            Check(MathF.Abs(moved.Yaw - (.03f + across)) < 1e-4, "the mob moves: memory carries the correction along");
            // Turned onto it: now the memory point is up and left of the crosshair, and another mob's mark is off to the side.
            Check(aim.See(0.3, new[] { new TargetMark(150, -200, 190, -180, true), new TargetMark(-25, -5, 25, 15, true) }, -across, -down, high, 1), "seen again");
            Check(aim.Mark is { X: 0 } && aim.Locked(0.3) && aim.Locked(0.8) && !aim.Locked(0.9), "its own mark, crosshair inside: shots for half a second after each look");
        });

        test("Screen aim: with no mark for a moment, it looks round the point in small steps", () =>
        {
            var aim = new ScreenAim();
            Check(aim.Error(1, 0, 0, 3000) == (0, 0), "the point itself first");
            var next = aim.Error(1.3, 0, 0, 3000);
            Check(next.Yaw == 0 && MathF.Abs(next.Pitch - ScreenAim.SearchStep) < 1e-6, "then a step up");
            var near = new ScreenAim();
            near.Error(1, 0, 0, 300);
            Check(MathF.Abs(near.Error(1.3, 0, 0, 300).Pitch - ScreenAim.MostSearchStep) < 1e-6, "close up, bigger steps, but never a swing");
            Check(!aim.See(2, new[] { new TargetMark(900, 0, 950, 20, true) }, 0, 0, 1080, 1), "a mark far off is another mob's");
            Check(aim.See(2, new[] { new TargetMark(-10, -10, 10, 10, true) }, 0, 0, 1080, 1) && aim.Error(2.1, 0, 0, 3000) == (0, 0), "found: the search stops");
        });

        test("Screen aim: point blank, no mark needed: fires at the memory point and does not search", () =>
        {
            var aim = new ScreenAim();
            Check(aim.See(0, new[] { new TargetMark(-5, 50, 45, 70, true) }, 0, 0, 1080, 1), "a correction learned further out");
            Check(!aim.Firing(0, 300), "out there, outside the brackets: no shots");
            Check(aim.Error(3, .02f, -.01f, 40) == (.02f, -.01f) && aim.Error(3.5, .02f, -.01f, 40) == (.02f, -.01f), "40 units, no mark: the point itself, no search steps");
            Check(aim.Firing(3, 40), "and shoots");
        });

        test("Target marks: the label and three bracket corners give the body's box; red floor tiles make none", () =>
        {
            const int size = 648, high = 1080;
            var picture = new byte[size * size * 4];
            void Paint(int x0, int y0, int x1, int y1, byte r, byte g, byte b)
            {
                for (int y = y0; y <= y1; y++)
                    for (int x = x0; x <= x1; x++) { int i = (y * size + x) * 4; picture[i] = b; picture[i + 1] = g; picture[i + 2] = r; picture[i + 3] = 255; }
            }
            Paint(0, 0, size - 1, size - 1, 25, 22, 21);
            for (int y = 0; y < size; y += 16)                      // a red grid floor on the right
                for (int x = 450; x < size - 12; x += 16) Paint(x, y, x + 11, Math.Min(size - 1, y + 11), 169, 73, 83);
            void Label(int x, int y)
            {
                Paint(x, y, x + 38, y + 12, 171, 36, 23);           // the red box
                Paint(x + 3, y + 2, x + 30, y + 10, 219, 216, 216); // "100%", near white as on a live screen
            }
            Label(300, 280);
            byte r = 150, g = 40, b = 35;
            Paint(300, 298, 306, 298, r, g, b); Paint(300, 298, 300, 304, r, g, b);
            Paint(394, 298, 400, 298, r, g, b); Paint(400, 298, 400, 304, r, g, b);
            Paint(300, 360, 306, 360, r, g, b); Paint(300, 354, 300, 360, r, g, b);
            Paint(394, 360, 400, 360, r, g, b); Paint(400, 354, 400, 360, r, g, b);
            Label(486, 100);                                        // a mob on the tiles, its corners lost in them
            var marks = TargetLock.Find(picture, size, high).OrderBy(m => m.Left).ToList();
            Check(marks.Count == 2, $"two labels, found {marks.Count}");
            var body = marks[0];
            Check(body.Measured && body.Left == 300 - 324 && body.Top == 298.5f - 324 && body.Right == 400 - 324 && body.Bottom == 360 - 324,
                $"the brackets' box, from the crosshair: {body}");
            var tiled = marks[1];
            Check(!tiled.Measured && MathF.Abs(tiled.Right - tiled.Left - TargetLock.SmallWidth * high) < .01f, $"on the tiles, a small mob's size: {tiled}");
        });

        test("Screen aim: a mob measured once keeps its size when its corners are lost", () =>
        {
            var aim = new ScreenAim();
            Check(aim.See(0, new[] { new TargetMark(-100, -100, 100, 100, true) }, 0, 0, 1080, 1, 500), "measured at 500");
            Check(aim.See(0.1, new[] { new TargetMark(-50, -50, 4, -23, false) }, 0, 0, 1080, 1, 1000), "corners lost at 1000");
            Check(aim.Mark is { Right: 50, Bottom: 50 }, $"half the size at twice the range: {aim.Mark}");
        });

        test("Track aim: the game easing a turn in, a shove is caught up in a few ticks and not swung past", () =>
        {
            // The view shows each turn spread over 350 ms; the error is the target's angle less what the view shows.
            var aim = new TrackAim();
            var sent = new List<(double At, float Yaw)>();
            float target = .2f, worst = 0;
            double settled = -1;
            for (int tick = 0; tick < 60; tick++)
            {
                double now = tick * .016;
                float shown = sent.Sum(s => s.Yaw * (float)Math.Clamp((now - s.At) / TrackAim.EaseSeconds, 0, 1));
                float error = target - shown;
                if (shown > target) worst = MathF.Max(worst, shown - target);
                if (settled < 0 && MathF.Abs(error) < .01f) settled = now;
                var want = aim.Want(now, error, 0, 500);
                aim.Sent(now, want.Yaw, want.Pitch);
                sent.Add((now, want.Yaw));
            }
            Check(settled >= 0 && settled < .5, $"on it within half a second, not {settled:F2} s");
            Check(worst < .03f, $"no swing past it: {worst:F3} rad over");
        });

        test("Camera pin: the angles as the game keeps them", () =>
        {
            var (pitch, yaw) = CameraWriter.Angles(10, 100, .1f, .05f);
            Check(MathF.Abs(yaw - (100 - .1f * 180 / MathF.PI)) < 1e-3, "yaw the other way round, in degrees");
            Check(MathF.Abs(pitch - (10 + 2 * .05f * 180 / MathF.PI)) < 1e-3, "pitch doubled, in degrees");
            Check(CameraWriter.Angles(80, 0, 0, .5f).Pitch == 86, "never past the 43 degrees the view stops at");
        });

        test("Kite: backs away from a mob too close to see, and holds its ground once backed into a wall", () =>
        {
            var kite = new Kite();
            Check(kite.Step(0, 300, Vector3.Zero) == (false, 0), "far enough: stays");
            Check(kite.Step(1, 100, Vector3.Zero) == (true, 0), "too close: backs away");
            Check(kite.Step(1.7, 120, new Vector3(50, 0, 0)) == (true, 0), "moving back: keeps going");
            Check(kite.Step(3, 230, new Vector3(80, 0, 0)) == (false, 0), "room again: stops");
            Check(kite.Step(4, 100, new Vector3(80, 0, 0)) == (true, 0), "close again: backs away");
            Check(kite.Step(4.7, 90, new Vector3(82, 0, 0)) == (false, 0) && kite.Cornered, "a wall stops it: stands there");
            Check(kite.Step(6, 40, new Vector3(82, 0, 0)) == (false, 0), "and stays, however close the mob");
        });

        test("Read lapse: a fight rides out failed reads of your character, and stops after 3 s of them", () =>
        {
            var lapse = new ReadLapse();
            var good = new PlayerSample(new Vector3(1, 2, 3), 1, 2, 3, Vector3.UnitX);
            PlayerSample Fail() => throw new InvalidOperationException("A verified in-world player is unavailable. Log in and finish zoning.");
            Check(lapse.Read(() => good, 0, "Stopped.") == good, "a good read passes through");
            Check(lapse.Read(Fail, 1, "Stopped.") == null && lapse.Read(Fail, 3.9, "Stopped.") == null, "failing under 3 s: keep going");
            Check(lapse.Read(() => good, 4, "Stopped.") == good, "reads again: carries on");
            lapse.Read(Fail, 5, "Stopped.");
            string? ended = null;
            try { lapse.Read(Fail, 8, "Stopped."); } catch (InvalidOperationException e) { ended = e.Message; }
            Check(ended != null && ended.Contains("could not be read for 3 s (A verified in-world player is unavailable"), $"3 s in a row: stops, saying why: {ended}");
            bool closed = false;
            try { new ReadLapse().Read(() => throw new InvalidOperationException("The game closed."), 0, "Stopped."); } catch (InvalidOperationException) { closed = true; }
            Check(closed, "the game closing stops at once");
        });

        test("Healer place: beside or behind the fighter, never in front", () =>
        {
            var place = new HealerPlace();
            var fighter = Vector3.Zero;
            Check(place.Update(new Vector3(100, 0, 0), fighter, 120, 200) == false, "no front known, within reach: stays");
            // The fighter walks along +X: that is their front.
            for (int i = 0; i <= 10; i++) place.Observe(i * .1, new Vector3(i * 10, 0, 0), null);
            fighter = new Vector3(100, 0, 0);
            var ahead = fighter + new Vector3(90, 0, 10);
            Check(place.Update(ahead, fighter, 120, 200), "in front of them: moves");
            var spot = place.Station(ahead, fighter, 100);
            float bearing = place.Bearing(spot, fighter)!.Value;
            Check(bearing >= HealerPlace.SideAngle - 1e-3 && MathF.Abs(PointNavigation.Distance(spot, fighter) - 100) < .1f, $"to the side, swung round: {bearing * 180 / MathF.PI:F0} deg");
            Check((spot - fighter).Z > 0, "on the side it was already on");
            Check(!place.Update(spot, fighter, 120, 200), "there: stops");
            var behind = fighter + new Vector3(-100, 0, 0);
            Check(Vector3.Distance(place.Station(behind, fighter, 100), fighter + new Vector3(-100, 0, 0)) < .01f, "behind is kept as it is");
            // Standing still, shooting at a mob to the north: the front turns that way.
            var standing = new HealerPlace();
            for (int i = 0; i <= 10; i++) standing.Observe(i * .1, Vector3.Zero, new Vector3(0, 0, 800));
            Check(standing.Front is { } f && MathF.Abs(f.Z - 1) < 1e-3, "front toward the mob being fought");
            Check(standing.Update(new Vector3(0, 0, 100), Vector3.Zero, 120, 200), "between them and the mob: moves");
            Check(standing.Update(new Vector3(500, 0, 0), Vector3.Zero, 120, 200), "fallen behind: moves");
            // Backing away south from a mob close to the north: the front is still the mob, not the way they walk.
            var backing = new HealerPlace();
            for (int i = 0; i <= 10; i++) backing.Observe(i * .1, new Vector3(0, 0, -i * 10), new Vector3(0, 0, 60));
            Check(backing.Front is { } b && b.Z > .99f, "backing away: front toward the mob");
            Check(backing.Bearing(new Vector3(0, 0, -200), new Vector3(0, 0, -100)) > HealerPlace.Clear, "the side away from the mob is behind them");
        });

        test("Hunt notes: each fight is summed up, what looks wrong is flagged, and what was learned is kept", () =>
        {
            string logs = Path.Combine(Path.GetTempPath(), "hunt-notes-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(logs);
            try
            {
                for (int i = 0; i < 4; i++)
                {
                    var fight = new FightNotes("Genotoxic Parasite", $"p{i}", 400, 30);
                    for (int t = 0; t < 10; t++) fight.Tick(t * .1, 400 - t * 40, t >= 8, t < 8, false);
                    fight.Mark(.8, true);
                    foreach (float h in new[] { 6f, 8f, 7f }) fight.Body(h);
                    Check(fight.BodyHeight == 7, "the middle of what was seen");
                    HuntNotes.Add(logs, fight.Line(3, i < 3 ? "Genotoxic Parasite died. Camera follow stopped." : "No line of sight to it."));
                    HuntNotes.Remember(logs, "Genotoxic Parasite", fight.BodyHeight, (8000, 4000));
                }
                var lines = HuntNotes.Read(logs);
                Check(lines.Count == 4 && (string?)lines[0]["outcome"] == "killed" && (string?)lines[3]["outcome"] == "no-sight", "one line a fight, with how it ended");
                string notes = File.ReadAllText(HuntNotes.Digest(logs));
                Check(notes.Contains("on the body only 20%") && notes.Contains("searching 80%") && notes.Contains("got within 60 units"), "the trouble is named: " + notes);
                Check(notes.Contains("| Genotoxic Parasite | 4 | 3 |"), "a row per mob");
                var learned = HuntNotes.Recall(logs, "genotoxic  parasite");
                Check(learned is { BodyHeight: 7, WidthAtRange: 8000, Fights: 4 }, $"learned, whatever the spacing: {learned}");
                Check(HuntNotes.Recall(logs, "Genotoxic Slugger") == null, "nothing yet for another mob");
            }
            finally { Directory.Delete(logs, true); }
        });

        test("Camera angles: the short way round", () =>
        {
            Check(MathF.Abs(CameraAim.Between(3.1f, -3.1f) - (2 * MathF.PI - 6.2f)) < 0.001f, "the short way across the wrap");
        });

        test("Heal from a VM: only the fighter named on the tab", () =>
        {
            Check(CameraAim.IsFighter(" scooter\n", "Scooter", EntityKind.Player), "the fighter, however it was typed");
            Check(!CameraAim.IsFighter("Scooter", "Adam", EntityKind.Player), "any other player");
            Check(!CameraAim.IsFighter(null, "Scooter", EntityKind.Player) && !CameraAim.IsFighter("", "Scooter", EntityKind.Player), "nobody named");
            Check(!CameraAim.IsFighter("Scooter", "Scooter", EntityKind.Npc), "an NPC of that name");
        });

        test("Camera aim: the left button goes down on the target, and only ever on an NPC", () =>
        {
            Check(CameraAim.OnTarget(0.01f, -0.01f), "within 2 degrees both ways");
            Check(!CameraAim.OnTarget(0.1f, 0) && !CameraAim.OnTarget(0, -0.1f), "either axis off is not on the target");
            Check(CameraAim.MayHold(EntityKind.Npc), "NPCs may be held on");
            Check(!CameraAim.MayHold(EntityKind.Player) && !CameraAim.MayHold(EntityKind.UnclassifiedCharacter), "anything else may not");
        });

        test("Camera aim: small steady corrections near the target, a quick swing when far off, nothing on it", () =>
        {
            Check(CameraAim.Turn(0.005f) == 0 && CameraAim.Turn(-0.005f) == 0, "within the deadband nothing moves");
            Check(MathF.Abs(CameraAim.Turn(0.1f) - 0.03f) < 1e-5f, "near it, a share of the error");
            Check(CameraAim.Turn(0.34f) == CameraAim.MaxNearTurn && CameraAim.Turn(-0.34f) == -CameraAim.MaxNearTurn, "capped near it");
            Check(CameraAim.Turn(1f) == CameraAim.FarShare && CameraAim.Turn(-1f) == -CameraAim.FarShare, "far off, a big share");
            Check(CameraAim.Turn(0.005f, 6000) != 0 && CameraAim.Turn(0.005f, 1000) == 0, "the deadband narrows at long range");
            Check(CameraAim.Turn(0.002f, 6000) == 0, "but stays over a pixel, or the aim would shake");
            var cactus = new SectorObjects.Prop("cactus3", new Vector3(500, 0, 0),
                new[] { new Vector2(470, -30), new Vector2(530, -30), new Vector2(530, 30), new Vector2(470, 30) }, 0, 200);
            var shots = new ShotLine(new[] { cactus });
            var eye = new Vector3(0, 100, 0);
            Check(shots.Blocker(eye, new Vector3(1000, 100, 0)) == "cactus3", "a cactus on the line blocks it");
            Check(shots.Blocker(eye, new Vector3(1000, 100, 100)) == null, "one to the side does not");
            Check(shots.Blocker(eye, new Vector3(1000, 900, 0)) == null, "nor does the line passing over it");
            Check(shots.Blocker(eye, new Vector3(300, 100, 0)) == null, "nor one beyond the target");
            Check(shots.Blocker(new Vector3(1000, 100, 0), new Vector3(2000, 100, 0)) == null, "nor one behind you");
            float? side = shots.ClearSide(eye, new Vector3(1000, 100, 0));
            Check(side is { } clear && shots.Blocker(eye + new Vector3(0, 0, -clear), new Vector3(1000, 100, 0)) == null, "a step to the right, looking along +x, is towards -z, and clears it");
            Check(MathF.Abs(side ?? 999) <= 160, "the shortest step does: half way to the target it moves the line half as far");
            var hedge = new ShotLine(Enumerable.Range(-9, 19).Select(i => cactus with { Position = new Vector3(100, 0, i * 50) }));
            Check(hedge.ClearSide(eye, new Vector3(120, 100, 0)) == null, "a wall of them can't be stepped round");

            var ridge = new float[TerrainCell.Samples * TerrainCell.Samples];
            for (int z = 0; z < TerrainCell.Samples; z++)
                for (int x = 256; x < 262; x++) ridge[z * TerrainCell.Samples + x] = 500;
            var cover = new Cover(ridge, new ShotLine(new[] { cactus with { Position = new Vector3(-2000, 0, 3000) } }));
            Check(cover.Hidden(new Vector3(-1000, 0, 0), new Vector3(1000, 0, 0)), "a hill hides a spot");
            Check(!cover.Hidden(new Vector3(-1000, 0, 0), new Vector3(-500, 0, 0)), "open ground does not");
            Check(cover.Hidden(new Vector3(-2500, 0, 3000), new Vector3(-1500, 100, 3000)), "a cactus hides one too");
            var hideout = cover.Spots(new Vector3(-100, 0, 0), new[] { new Vector3(-1000, 0, 0) }, p => p).First();
            Check(hideout.X > 300 && !float.IsNaN(hideout.Z), "it runs over the hill, away from the mob");
            Check(cover.Spots(new Vector3(16300, 0, 0), new[] { new Vector3(15000, 0, 0) }, p => p).All(p => MathF.Abs(p.X) < TerrainCell.Half), "never over the edge into another zone");
            Check(!cover.Spots(default, new[] { new Vector3(100, 0, 0) }, _ => null).Any(), "only on ground it can stand on");

            string saved = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
            Directory.CreateDirectory(saved);
            Travel.SaveObstacle(saved, 2216, new Vector3(4852, 1470, -7700));
            Travel.SaveObstacle(saved, 2216, new Vector3(4900, 1470, -7700));
            Check(Travel.LoadObstacles(saved)[2216].Count == 2, "a blocked spot is remembered for every later walk");
            Directory.Delete(saved, true);

            var sight = new SightWatch();
            Check(!sight.Seen(0), "nothing targeted yet");
            sight.Update(1, true); sight.Update(1.5, false);
            Check(sight.Seen(1.9) && !sight.Showing, "a gap in the target bar is not losing the target");
            Check(!sight.Seen(2.1), "a second without it is");
            Check(sight.ClearToFire(1.3) && !sight.ClearToFire(1.5), "but firing stops much sooner");

            var back = new BackOff(9000);
            back.Update(0, false, false, 1000, default);
            Check(back.Now == BackOff.Phase.Waiting, "no backing until the game targets the mob");
            back.Update(1, true, true, 1000, default);
            Check(back.Now == BackOff.Phase.Backing, "then back away");
            back.Update(2.5, true, true, 1030, new Vector3(30, 0, 0));
            back.Update(5, true, true, 1100, new Vector3(100, 0, 0));
            Check(back.Now == BackOff.Phase.Backing, "still moving, still backing");
            back.Update(6, false, false, 1130, new Vector3(130, 0, 0));
            Check(back.Now == BackOff.Phase.Returning && back.Limit == 1130, "losing it is the target limit");
            back.Update(6.5, false, true, 1120, new Vector3(120, 0, 0));
            Check(back.Now == BackOff.Phase.Done, "forward until it is back");
            var noticed = new BackOff(9000);
            noticed.Update(0, true, true, 1000, default);
            noticed.Update(1, true, true, 900, default);
            Check(noticed.Now == BackOff.Phase.Done && noticed.Limit == null, "a mob coming at you ends the backing");
            var stuck = new BackOff(9000);
            stuck.Update(0, true, true, 1000, default);
            stuck.Update(4, true, true, 1000, default);
            Check(stuck.Now == BackOff.Phase.Done, "so does backing into something");
            var late = new BackOff(9000);
            late.Update(0, true, true, 1000, default);
            late.Update(2, true, true, 1000, new Vector3(60, 0, 0));
            late.Update(181, true, true, 3000, new Vector3(9000, 0, 0));
            Check(late.Now == BackOff.Phase.Done, "and so does the time limit");
            Check(new BackOff(0).Now == BackOff.Phase.Done, "only when asked for");
            var safe = new BackOff(2500);
            safe.Update(0, true, true, 2600, default);
            Check(safe.Now == BackOff.Phase.Done, "a mob already far enough off needs none");
            var near = new BackOff(2500);
            near.Update(0, true, true, 2400, default);
            near.Update(1, true, true, 2430, new Vector3(30, 0, 0));
            Check(near.Now == BackOff.Phase.Backing, "a nearer one does");
            near.Update(4, true, true, 2510, new Vector3(110, 0, 0));
            Check(near.Now == BackOff.Phase.Done && near.Limit == null, "only as far as the safe distance");

            var cycle = new CastCycle();
            var order = new List<(int, bool)>();
            for (var c = cycle.Due(0); c != null; c = cycle.Due(0)) { order.Add((c.Slot, c.OnFighter)); cycle.Done(c, 0); }
            Check(order.SequenceEqual(new[] { (1, true), (1, false), (2, true), (3, true), (2, false), (3, false) }), "every spell on both people, heals first");
            Check(cycle.Due(29) == null, "then nothing for 30 s");
            var heal = cycle.Due(30);
            Check(heal is { Slot: 1, OnFighter: true }, "the heal comes back at 30 s");
            cycle.Done(heal!, 30);
            var selfHeal = cycle.Due(30)!;
            Check(selfHeal is { Slot: 1, OnFighter: false }, "on both");
            cycle.Done(selfHeal, 30);
            Check(cycle.Due(119) == null || cycle.Due(119)!.Slot == 1, "shields wait");
            Check(CastCycle.KeyFor(1, null) == 2 && CastCycle.KeyFor(2, null) == 1, "with nothing known, another slot first");
            Check(CastCycle.KeyFor(1, 2) == 1, "then the slot itself");

            byte[] Picture(Func<int, (byte B, byte G, byte R)> colour, int width, int height)
            {
                var bytes = new byte[width * height * 4];
                for (int i = 0; i < width * height; i++) { var c = colour(i % width); bytes[i * 4] = c.B; bytes[i * 4 + 1] = c.G; bytes[i * 4 + 2] = c.R; }
                return bytes;
            }
            Check(TargetBar.Looks(Picture(_ => (28, 45, 188), 100, 10), 100, 10), "the red bar is seen");
            Check(TargetBar.Looks(Picture(x => x < 74 ? ((byte)10, (byte)10, (byte)10) : ((byte)72, (byte)210, (byte)134), 100, 10), 100, 10), "so is its green end once the red has drained");
            Check(!TargetBar.Looks(Picture(_ => (171, 171, 171), 100, 10), 100, 10), "plain sky is not");

            var snap = new SnapAim();
            Check(snap.Step(0, 2f, -.3f) == (2f, -.3f), "the whole turn at once");
            Check(snap.Step(16, 2f, -.3f) == (0, 0) && snap.Step(32, 2f, -.3f) == (0, 0), "and nothing more while it has not shown: a turn shows late");
            Check(snap.Step(48, .9f, -.1f) == (0, 0) && snap.Step(64, .05f, .02f) == (0, 0), "nor while it is still landing");
            Check(snap.Step(80, .05f, .02f) == (.05f, .02f), "then what is left");
            Check(snap.Step(700, .05f, .02f) == (.05f, .02f), "again if it never showed");
            Check(snap.Step(716, .005f, .001f) == (0, 0) && snap.Step(732, .005f, .001f) == (0, 0) && !snap.Done, "landed there");
            Check(snap.Step(748, .005f, .001f) == (0, 0) && snap.Done, "and it counts once two readings agree");


            var steady = new SteadyAim(1500);
            Check(!steady.Ready(1000, false) && !steady.Ready(2000, false), "no bar yet: keep holding the crosshair there");
            Check(steady.Ready(2500, false), "a crosshair held long enough will do without the bar");
            Check(new SteadyAim(1500).Ready(1000, true), "the bar needs no waiting");

            Check(CameraAim.Pixels(0.0002f, -0.0014f) == -1 && CameraAim.Pixels(0.01f, 0.002f) == 5 && CameraAim.Pixels(0, 0.002f) == 0, "a turn is at least a pixel");
            Check(MathF.Abs(CameraAim.Facing(MathF.PI / 2).Z - 1) < 1e-5f && MathF.Abs(PointNavigation.SignedAngle(CameraAim.Facing(0), CameraAim.Facing(0.5f)) - 0.5f) < 1e-5f, "a heading as a flat direction");
        });

        test("Camera aim: the angle above level, from the eye to the target", () =>
        {
            var eye = new Vector3(0, -CameraAim.EyeHeight, 0);
            Check(MathF.Abs(CameraAim.PitchTo(eye, new Vector3(100, 0, 0))) < 1e-5f, "same height as the eye: level");
            Check(MathF.Abs(CameraAim.PitchTo(eye, new Vector3(200, 100, 0)) - MathF.Atan(0.5f)) < 1e-5f, "half as far up as along");
            Check(CameraAim.PitchTo(eye, new Vector3(10, 900, 0)) == CameraAim.MaxPitch, "no higher than the game lets you look");
            Check(CameraAim.PitchTo(default, new Vector3(10, -900, 0)) == -CameraAim.MaxPitch, "and no lower");
            Check(CameraAim.PitchTo(default, new Vector3(100, 0, 0)) < 0, "an actor on your own floor is below your eye");
            Check(MathF.Abs(CameraAim.PitchTo(eye, eye) ) < 1.6f && float.IsFinite(CameraAim.PitchTo(eye, eye)), "standing on it stays finite");
        });

        test("Target watch: follows the actor, and rides out misses and a registry caught mid-update", () =>
        {
            long now = 0;
            var buddy = Actor("Buddy", new Vector3(1, 0, 1));
            IReadOnlyList<WorldEntity> seen = [buddy with { Position = new Vector3(50, 0, 60) }];
            bool torn = false;
            var watch = new TargetWatch(buddy, () => torn ? throw new InvalidOperationException("mid-update") : seen, () => now, 100, "Stopped.");
            Check(watch.Read() == null && watch.SeenAt.X == 50, "its new position is read");
            seen = [buddy with { Position = new Vector3(70, 0, 60) }];
            now = 50;
            Check(watch.Read() == null && watch.SeenAt.X == 50, "not read again before the interval");
            now = 100;
            torn = true;
            Check(watch.Read() == null, "a torn read is not the end");
            torn = false;
            seen = [];
            for (int i = 0; i < 3; i++) { now += 100; Check(watch.Read() == null, "three misses are not the end"); }
            seen = [buddy];
            now += 100;
            Check(watch.Read() == null, "back again: the misses start over");
            seen = [];
            for (int i = 0; i < 3; i++) { now += 100; watch.Read(); }
            now += 100;
            Check(watch.Read() == "Buddy is gone (out of range, logged off, despawned, or went through a door). Stopped.", "the fourth miss in a row ends it");
        });

        test("Target watch: another actor at a reused address is not the target, a nameless read is", () =>
        {
            long now = 0;
            var buddy = Actor("Buddy", default);
            IReadOnlyList<WorldEntity> seen = [Actor("?", new Vector3(9, 0, 9), EntityKind.UnclassifiedCharacter)];
            var watch = new TargetWatch(buddy, () => seen, () => now, 100, "Stopped.", at => $"crossed from {at.X}");
            Check(watch.Read() == null && watch.SeenAt.X == 9, "a name that failed to read is still them");
            seen = [Actor("Stranger", new Vector3(500, 0, 500))];
            for (int i = 0; i < 3; i++) { now += 100; Check(watch.Read() == null && watch.SeenAt.X == 9, "a stranger never moves the aim"); }
            now += 100;
            Check(watch.Read() == "crossed from 9", "and counts as gone, with the zone-exit reason when there is one");
        });

        test("Sprint: rests when a run goes slow, and runs again after", () =>
        {
            var guard = new SprintGuard();
            Vector3 At(float x) => new(x, 0, 0);
            Check(guard.MayRun(0, At(0), true), "starts running");
            Check(guard.MayRun(1, At(300), true), "300 units/s is a run");
            Check(guard.MayRun(1.5, At(450), true), "still inside the window");
            Check(!guard.MayRun(2, At(335), true), "35 units/s means stamina is out");
            var headquarters = new SprintGuard();
            headquarters.MayRun(0, At(0), true);
            Check(headquarters.MayRun(1, At(85), true), "a headquarters' full run is 85 units/s: no crawl");
            Check(!guard.MayRun(2.1, At(340), false), "rests");
            Check(!guard.MayRun(16.9, At(2000), false), "for the whole rest");
            Check(guard.MayRun(17.1, At(2100), false), "then may run again");
            var turning = new SprintGuard();
            turning.MayRun(0, At(0), true);
            Check(turning.MayRun(0.5, At(10), false) && turning.MayRun(1.1, At(10), true) && turning.MayRun(1.2, At(10), true), "stopping to turn is not a crawl");
            var lift = new SprintGuard();
            lift.MayRun(0, At(0), true);
            Check(lift.MayRun(10, At(0), true), "a lift ride between readings is not a crawl");
        });

        test("Target watch: an NPC is never swapped for an unnamed character at its address", () =>
        {
            long now = 0;
            var rat = Actor("Rat", new Vector3(5, 0, 5), EntityKind.Npc);
            IReadOnlyList<WorldEntity> seen = [rat with { Identity = rat.Identity with { Kind = EntityKind.UnclassifiedCharacter }, Name = "?", Position = new Vector3(900, 0, 900) }];
            var watch = new TargetWatch(rat, () => seen, () => now, 100, "Stopped.");
            for (int i = 0; i < 3; i++) { Check(watch.Read() == null && watch.SeenAt.X == 5, "the aim stays where it was"); now += 100; }
            Check(watch.Read() != null, "and it counts as gone");
        });

        test("Follow band: stops inside the distance and only sets off again past the resume line", () =>
        {
            var band = new FollowBand(150);
            Check(band.Distance == 150 && band.Resume == 200, $"150 stops, 200 resumes (got {band.Distance}, {band.Resume})");
            Check(band.Start(400), "a target 400 away: walk");
            Check(band.Update(300) && band.Update(151), "still walking until within the distance");
            Check(!band.Update(150), "stops at 150");
            Check(!band.Update(170) && !band.Update(200), "a target shuffling inside the band does not restart the walk");
            Check(band.Update(201), "resumes once past 200");
            Check(band.Update(180), "and keeps walking until back within 150");
            Check(!new FollowBand(150).Start(120), "starting already close: wait");
            Check(!new FollowBand(150).Start(150), "starting exactly at the distance: wait");
        });

        test("Follow band: the distance is clamped and the resume margin grows with it", () =>
        {
            Check(new FollowBand(5).Distance == FollowBand.MinDistance, "too close is raised to the minimum");
            Check(new FollowBand(99999).Distance == FollowBand.MaxDistance, "too far is capped");
            Check(new FollowBand(float.NaN).Distance == FollowBand.DefaultDistance, "nonsense falls back to the default");
            Check(new FollowBand(60).Resume == 110, "at least 50 units of margin");
            Check(new FollowBand(600).Resume == 800, "a third of the distance when that is more");
        });

        test("Follow gap: route length, less what no route can cover", () =>
        {
            Check(FollowLogic.Gap(300, null, 0) == 300, "no route: the straight distance");
            Check(FollowLogic.Gap(100, 400, 0) == 400, "a wall between: the walk round it counts");
            Check(FollowLogic.Gap(180, 2, 180) == 2, "target behind a counter 180 off the floor, walker at the route's end: arrived");
            Check(FollowLogic.Gap(300, 50, 100) == 200, "straight distance less the miss when the route is out of date");
            Check(FollowLogic.Gap(50, 10, 200) == 10, "never below zero from the miss");
        });

        test("Follow replan: first plan, off route, target moved, route ending, refresh", () =>
        {
            Check(FollowLogic.Decide(false, 0, 300, 0, 0, 0) == FollowReplan.First, "no route yet: plan one");
            Check(FollowLogic.Decide(true, 0, 300, Simulator.OffRouteLimit + 1, 200, 0.1) == FollowReplan.OffRoute, "off the route: replan at once");
            Check(FollowLogic.Decide(true, 200, 300, 0, 200, 0.2) == FollowReplan.None, "target moved, but the route is brand new: wait a moment");
            Check(FollowLogic.Decide(true, 100, 300, 0, 200, 0.5) == FollowReplan.TargetMoved, "target moved more than a quarter of the gap (75)");
            Check(FollowLogic.Decide(true, 60, 300, 0, 200, 0.5) == FollowReplan.None, "a smaller move keeps the route");
            Check(FollowLogic.Decide(true, 35, 120, 0, 200, 0.5) == FollowReplan.TargetMoved, "close up the threshold bottoms out at 32");
            Check(FollowLogic.Decide(true, 20, 300, 0, 30, 0.5) == FollowReplan.NearRouteEnd, "about to run out of route while the target is elsewhere");
            Check(FollowLogic.Decide(true, 20, 300, 0, 200, 3.5) == FollowReplan.Refresh, "an old route is renewed when the target moved at all");
            Check(FollowLogic.Decide(true, FollowLogic.Jitter, 300, 0, 30, 10) == FollowReplan.None, "position jitter alone never replans");
            Check(FollowLogic.MoveThreshold(10000) == 250, "far away the threshold is capped at 250");
        });

        test("A target that vanished next to an exit is reported as crossing it", () =>
        {
            var exits = new[] { (new Vector3(1000, 0, 0), 2), (new Vector3(0, 0, 3000), 101) };
            Check(FollowLogic.NearestExit(new(800, 0, 100), exits) is { To: 2 }, "last seen 224 from the exit to sector 2");
            Check(FollowLogic.NearestExit(new(0, 0, 0), exits) is null, "far from every exit: just gone");
        });
    }
}
