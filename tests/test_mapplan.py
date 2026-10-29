"""mapplan: sector-map projection, walkable mask, exits and A* planning.

Fixtures tests/fixtures/mapplan_<world>.png are crops of the game's own sector maps (Plaza 1, Pepper Park 1)
written by `tools/mapplan_render.py --fixtures tests/fixtures`; mapplan_maps.json holds each crop's origin
and the pak_maps.csv reference values. The anchor numbers come from the C# MapTests.cs.
"""
import io
import json
import math
import os
import statistics
import struct
import tempfile
import time
import unittest
import zlib
from pathlib import Path

import cv2
import numpy as np

import mapplan

FIXTURES = Path(__file__).parent / "fixtures"
COPBOT = (-1469.0, 1069.0)           # Plaza 1 COPBOT from the C# test; projects to (145.188, 96.592) at 270
LIVE_PLAZA1 = (-1023.0, 3072.05)     # live position read in Plaza 1 on 2026-10-28
ENVELOPE = bytes([0x0A, 0xF7, 0x3D, 0x88, 0x84, 0x75, 0x84, 0x93, 0xBD, 0xEF, 0xFD, 0xAB])


def plaza_projection(rotation=270):
    return mapplan.Projection((195, 204), (-3248, -2767), 0.028, rotation)


_PLANNERS = {}


def fixture_planner(world_id, rotation=270):
    """SectorPlanner on a fixture crop, with BitmapRef shifted by the crop origin so world coords are exact."""
    key = (world_id, rotation)
    if key not in _PLANNERS:
        meta = json.loads((FIXTURES / "mapplan_maps.json").read_text())[str(world_id)]
        gray = cv2.imread(str(FIXTURES / meta["image"]), cv2.IMREAD_GRAYSCALE)
        ox, oy = meta["crop_origin"]
        proj = mapplan.Projection((meta["bitmap_ref"][0] - ox, meta["bitmap_ref"][1] - oy),
                                  tuple(meta["world_ref"]), meta["scale"], rotation)
        _PLANNERS[key] = mapplan.SectorPlanner(gray, proj)
    return _PLANNERS[key]


def pack(data: bytes) -> bytes:
    return ENVELOPE + struct.pack("<i", len(data)) + zlib.compress(data)


class ProjectionTests(unittest.TestCase):
    def test_reference_maps_to_bitmap_anchor_at_every_rotation(self):
        for rotation in (0, 90, 180, 270):
            u, v = plaza_projection(rotation).to_pixel(-3248, -2767)
            self.assertAlmostEqual(u, 195, places=6)
            self.assertAlmostEqual(v, 204, places=6)

    def test_copbot_and_quarter_turn_match_the_csharp_anchors(self):
        u, v = plaza_projection(270).to_pixel(*COPBOT)
        self.assertAlmostEqual(u, 145.188, places=3)
        self.assertAlmostEqual(v, 96.592, places=3)
        u, v = plaza_projection(90).to_pixel(-2248, -2767)
        self.assertAlmostEqual(u, 223, places=4)
        self.assertAlmostEqual(v, 204, places=4)

    def test_round_trip(self):
        rng = np.random.default_rng(3)
        for rotation in (0, 37.5, 90, 270, 333):
            p = plaza_projection(rotation)
            for x, z in rng.uniform(-6000, 6000, (20, 2)):
                x2, z2 = p.to_world(*p.to_pixel(x, z))
                self.assertAlmostEqual(x, x2, places=6)
                self.assertAlmostEqual(z, z2, places=6)

    def test_invalid_scale_or_coordinates_are_rejected(self):
        with self.assertRaises(ValueError):
            mapplan.Projection((0, 0), (0, 0), float("nan"))
        with self.assertRaises(ValueError):
            mapplan.Projection((0, 0), (0, 0), 0.0)
        with self.assertRaises(ValueError):
            plaza_projection().to_pixel(float("inf"), 0)

    def test_bearing_of_live_forward_vector(self):
        self.assertAlmostEqual(mapplan.bearing_from_forward(0.887, -0.462), 117.5, delta=0.1)
        self.assertAlmostEqual(mapplan.bearing_of(0, 1), 0)
        self.assertAlmostEqual(mapplan.bearing_of(1, 0), 90)
        self.assertAlmostEqual(mapplan.angle_diff(350, 10), 20)


class FileFormatTests(unittest.TestCase):
    def test_catalog_joins_map_bitmaps_only(self):
        with tempfile.TemporaryDirectory() as folder:
            os.makedirs(os.path.join(folder, "definitions"))
            os.makedirs(os.path.join(folder, "gfx"))
            Path(folder, "definitions", "pak_worldinfo.csv").write_bytes(
                pack(b"EntryId,Enabled,Name\n1,1,PLAZA SEC-1\n2,1,PLAZA SEC-2\n"))
            Path(folder, "definitions", "pak_maps.csv").write_bytes(pack(
                b"EntryId,Enabled,WorldId,BitmapId,BitmapRefX,BitmapRefY,WorldRefX,WorldRefZ,Scale\n"
                b"1,1,1,2001,195,204,-3248,-2767,0.028\n2,1,2,2002,0,0,0,0,0.05\n"))
            Path(folder, "gfx", "pak_gfx.ini").write_bytes(pack(
                b'set 2001 "gfx\\modeltextures\\unrelated.dds";\n'
                b'set 2001 "gfx\\maps\\plaza_p1_sm.bmp", "gfx\\maps\\plaza_p1_sm_a.bmp", 0;\n'))
            catalog = mapplan.SectorMapCatalog(folder)
            self.assertEqual(catalog.find(1).asset_path, "gfx/maps/plaza_p1_sm.bmp")
            self.assertEqual(catalog.find(1).bitmap_ref, (195, 204))
            self.assertIsNone(catalog.find(2))
            self.assertEqual(catalog.name(2), "PLAZA SEC-2")

    def test_pak_archive_and_local_override(self):
        with tempfile.TemporaryDirectory() as folder:
            payload = b"BM" + bytes(range(100))
            name = b"maps\\plaza_p1_sm.bmp\0"
            comp = zlib.compress(payload)
            with open(os.path.join(folder, "gfx.pak"), "wb") as f:
                f.write(struct.pack("<II", 0x3D458CDE, 1))
                f.write(struct.pack("<iIiii", 20 + len(name), 8 + 20 + len(name), len(comp), len(payload), len(name)))
                f.write(name + comp)
            archive = mapplan.PakArchive(os.path.join(folder, "gfx.pak"))
            self.assertEqual(archive.read("gfx/MAPS/PLAZA_P1_SM.BMP"), payload)
            self.assertEqual(mapplan.read_map_file(folder, "gfx/maps/plaza_p1_sm.bmp", archive), payload)
            os.makedirs(os.path.join(folder, "gfx", "maps"))
            local = b"BM" + bytes(80)
            Path(folder, "gfx", "maps", "pak_plaza_p1_sm.bmp").write_bytes(pack(local))
            self.assertEqual(mapplan.read_map_file(folder, "gfx/maps/plaza_p1_sm.bmp", archive), local)
            with self.assertRaises(ValueError):
                mapplan.read_map_file(folder, "../outside.bmp", archive)


class MaskAndExitTests(unittest.TestCase):
    def test_known_points_are_on_the_floor(self):
        p = fixture_planner(1)
        self.assertTrue(p.is_floor(*COPBOT))
        self.assertTrue(p.is_floor(*LIVE_PLAZA1))
        u, v = p.projection.to_pixel(*LIVE_PLAZA1)          # top corridor of Plaza 1, next to exit 2
        self.assertTrue(p.wall_distance[int(round(v)), int(round(u))] >= 2)
        self.assertFalse(p.walk[0, 0])

    def test_area_separators_open_but_background_stays_closed(self):
        p = fixture_planner(1)
        self.assertGreater(int(p.bridges.sum()), 50)
        self.assertFalse((p.walk & (p.gray == 247) & ~p.bridges).any())
        # a single 4-connected floor network joins every exit
        comps = {int(p.component[int(e.pixel[1]), int(e.pixel[0])]) for e in p.exits}
        self.assertEqual(len(comps), 1)

    def test_plaza1_exits_and_landmarks(self):
        p = fixture_planner(1)
        self.assertEqual(sorted(e.label for e in p.exits), ["1", "1", "2", "3", "4"])
        self.assertEqual(sorted(l.label for l in p.landmarks), ["A", "B"])
        dirs = {e.label: e.direction for e in p.exits}
        self.assertEqual(dirs["4"], (0.0, -1.0))
        self.assertEqual(dirs["3"], (0.0, 1.0))
        self.assertEqual(dirs["2"], (-1.0, 0.0))
        # at 270 degrees map-left is +X (bearing 90) and map-down is -Z (bearing 180)
        bear = {e.label: e.bearing for e in p.exits}
        self.assertAlmostEqual(bear["1"], 90, delta=0.5)
        self.assertAlmostEqual(bear["3"], 180, delta=0.5)
        self.assertAlmostEqual(bear["4"], 0, delta=0.5)

    def test_pepper_park1_exits(self):
        p = fixture_planner(5)
        self.assertEqual(sorted(e.label for e in p.exits), ["1", "1", "2", "3"])
        self.assertEqual(sorted(l.label for l in p.landmarks), ["A", "A", "A", "B", "C"])


class PlanningTests(unittest.TestCase):
    def assert_on_floor(self, p, path):
        for a, b in zip(path, path[1:]):
            for t in np.linspace(0, 1, 25):
                u, v = p.projection.to_pixel(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                self.assertTrue(p.walk[int(round(v)), int(round(u))], (a, b, t))

    def test_paths_to_every_exit_stay_on_floor_and_arrive(self):
        for wid, start in ((1, COPBOT), (1, LIVE_PLAZA1), (5, None)):
            p = fixture_planner(wid)
            if start is None:
                start = next(l.world for l in p.landmarks if l.label == "B")
            for ex in p.exits:
                path = p.plan(start, ex)
                self.assertIsNotNone(path, (wid, ex.label))
                self.assert_on_floor(p, path)
                end = p.projection.to_pixel(*path[-1])
                self.assertLess(math.dist(end, ex.pixel), 1.0)
                legs = [math.dist(a, b) for a, b in zip(path, path[1:])]
                self.assertLessEqual(max(legs), 160.0 + 1e-6)

    def test_astar_matches_exit_field_and_keeps_off_walls(self):
        p = fixture_planner(1)
        ex = next(e for e in p.exits if e.label == "3")
        a = p.plan(COPBOT, ex.world)
        b = p.plan(COPBOT, ex)
        self.assertAlmostEqual(mapplan.path_length(a), mapplan.path_length(b), delta=150)
        pixels = p.plan_pixels(COPBOT, ex.world)
        clear = [p.wall_distance[v, u] for u, v in pixels[3:-3]]
        self.assertGreater(statistics.median(clear), 2.0)

    def test_unreachable_or_off_map_returns_none(self):
        p = fixture_planner(1)
        self.assertIsNone(p.plan((99999.0, 99999.0), COPBOT))
        far_off_floor = p.projection.to_world(2, 2)
        self.assertIsNone(p.plan(far_off_floor, COPBOT))

    def test_plan_to_exit_follows_the_bearing_hint(self):
        p = fixture_planner(1)
        # from the COPBOT point in the middle of Plaza 1: north (+Z) is exit 2, south (-Z) exit 3, +X the west exits
        self.assertEqual(p.plan_to_exit(COPBOT, 0)[0].label, "2")
        self.assertEqual(p.plan_to_exit(COPBOT, 180)[0].label, "3")
        self.assertIn(p.plan_to_exit(COPBOT, 90)[0].label, {"1", "4"})
        ex, path = p.plan_to_exit(COPBOT, 180)
        self.assertLess(math.dist(p.projection.to_pixel(*path[-1]), ex.pixel), 1.0)
        # no hint: the nearest exit; labels restrict the choice
        self.assertIsNotNone(p.plan_to_exit(COPBOT))
        self.assertEqual(p.plan_to_exit(COPBOT, 180, labels={"1"})[0].label, "1")

    def test_planning_is_fast(self):
        p = fixture_planner(5)
        ys, xs = np.nonzero(p.walk & ~p.bridges & ~p.soft)
        rng = np.random.default_rng(7)
        astar, exits = [], []
        for _ in range(15):
            i, j = rng.integers(len(xs), size=2)
            a, b = p.projection.to_world(xs[i], ys[i]), p.projection.to_world(xs[j], ys[j])
            t = time.perf_counter()
            p.plan(a, b)
            astar.append(time.perf_counter() - t)
            t = time.perf_counter()
            p.plan_to_exit(a, float(rng.uniform(0, 360)))
            exits.append(time.perf_counter() - t)
        self.assertLess(statistics.median(astar), .05)
        self.assertLess(max(exits), .05)


class SteeringTests(unittest.TestCase):
    PATH = [(0.0, 0.0), (0.0, 100.0), (100.0, 100.0)]

    def test_cross_track_error_sign_and_size(self):
        self.assertAlmostEqual(mapplan.cross_track_error((10, 50), self.PATH), 10)    # +X side of a +Z leg
        self.assertAlmostEqual(mapplan.cross_track_error((-7, 50), self.PATH), -7)
        self.assertAlmostEqual(mapplan.cross_track_error((50, 90), self.PATH), 10)    # leg towards +X: bearing+90 is -Z
        self.assertAlmostEqual(mapplan.cross_track_error((50, 104), self.PATH), -4)
        self.assertAlmostEqual(mapplan.cross_track_error((0, 0), self.PATH), 0)

    def test_next_waypoint(self):
        self.assertEqual(mapplan.next_waypoint((0, 10), self.PATH), (1, (0.0, 100.0)))
        self.assertEqual(mapplan.next_waypoint((0, 70), self.PATH), (2, (100.0, 100.0)))   # corner within reach
        self.assertEqual(mapplan.next_waypoint((95, 100), self.PATH), (2, (100.0, 100.0)))
        i, pt = mapplan.next_waypoint((0, 80), self.PATH, lookahead=50)
        self.assertEqual(i, 2)
        self.assertAlmostEqual(pt[0], 30)
        self.assertAlmostEqual(pt[1], 100)


@unittest.skipUnless(os.path.isfile(os.path.join(mapplan.DEFAULT_INSTALL, "gfx.pak")), "game install not present")
class LiveInstallTests(unittest.TestCase):
    def test_catalog_and_fixture_agree_with_the_install(self):
        catalog = mapplan.SectorMapCatalog()
        sector = catalog.find(1)
        self.assertEqual(sector.asset_path, "gfx/maps/plaza_p1_sm.bmp")
        self.assertEqual((sector.bitmap_ref, sector.world_ref, sector.scale), ((195, 204), (-3248, -2767), 0.028))
        meta = json.loads((FIXTURES / "mapplan_maps.json").read_text())["1"]
        crop = cv2.imread(str(FIXTURES / meta["image"]), cv2.IMREAD_GRAYSCALE)
        ox, oy = meta["crop_origin"]
        image = catalog.image(sector)
        self.assertTrue(np.array_equal(image[oy:oy + crop.shape[0], ox:ox + crop.shape[1]], crop))


if __name__ == "__main__":
    unittest.main()
