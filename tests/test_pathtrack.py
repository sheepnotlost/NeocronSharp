"""pathtrack: camera model, tracking orbs and the route through them.

The replay fixture tests/fixtures/pathtrack_cal1.json is cut from the 28 Oct cal1 recording (see its "note")."""
import json
from pathlib import Path

import unittest

import numpy as np

import pathtrack
from pathtrack import Camera, PathTracker

FIXTURES = Path(__file__).parent / "fixtures"


def sample(x, z, heading, sector=1):
    return {"sector": sector, "x": x, "z": z, "heading": heading}


def test_heading_convention():
    assert np.allclose(pathtrack.forward(0), [0, -1])            # 0 = -Z
    assert np.allclose(pathtrack.forward(90), [1, 0])            # 90 = +X
    assert np.allclose(pathtrack.right(0), [1, 0])
    assert np.isclose(pathtrack.heading_to(1, 0), 90)
    assert np.isclose(pathtrack.heading_to(0, 1), 180)
    assert np.isclose(pathtrack.wrap(350), -10)


def test_camera_round_trip():
    for cam in (pathtrack.CAMERA, Camera(pitch=.3, height=90, back=200, focal=1100, side=7, yaw=3, rise=12)):
        round_trip(cam)


def round_trip(cam):
    world = np.array([[100.0, 40.0], [300, -120], [-50, 520], [12, 900]])
    for x, z, heading in [(0, 0, 0), (2500, -300, 137.5), (-40, 80, 271)]:
        pts = world + [x, z]
        px = cam.to_image(pts, x, z, heading)
        back = cam.to_world(px, x, z, heading)
        ahead = (pts - [x, z]) @ pathtrack.forward(heading + cam.yaw) > -cam.back + 5
        assert np.allclose(back[ahead], pts[ahead], atol=1e-6)
        # other screen sizes scale with the width (2560x1440 live)
        big = cam.to_image(pts, x, z, heading, size=(2560, 1440))
        assert np.allclose(cam.to_world(big, x, z, heading, size=(2560, 1440))[ahead], pts[ahead], atol=1e-6)


def test_camera_geometry():
    cam = Camera(pitch=.2, height=70, back=150, focal=900)
    centre = cam.to_floor([[960, 540]])[0]
    assert np.isclose(centre[0], -150 + 70/np.tan(.2))       # the view centre hits the floor ahead
    assert np.isclose(centre[1], 0)
    assert np.isnan(cam.to_floor([[960, 540 - 900*np.tan(.2) - 5]])[0, 0])     # above the horizon
    left, right_ = cam.to_floor([[400, 800], [1520, 800]])
    assert left[1] < 0 < right_[1] and np.isclose(left[0], right_[0])


def view(tracker, world, x, z, heading, size=(1920, 1080), noise=0.0, rng=None):
    """Pixels of the world points that are on screen and ahead, as a frame would show them."""
    px = tracker.camera.to_image(world, x, z, heading, size)
    ok = np.isfinite(px).all(1) & (px[:, 0] >= 0) & (px[:, 0] < size[0]) & (px[:, 1] > size[1]*.42) & (px[:, 1] < size[1])
    px = px[ok]
    if noise and rng is not None:
        px = px + rng.normal(0, noise, px.shape)
    return px


def dashes_l():
    """An L-shaped dashed path: north (-Z) 1000 units, then east (+X) 800, a dash every 80."""
    north = [(0.0, -z) for z in np.arange(80, 1001, 80)]
    east = [(x, -1000.0) for x in np.arange(80, 801, 80)]
    return np.array(north + east)


def walk(tracker, world, steps, rng=None, noise=0.0):
    out = []
    for x, z, heading in steps:
        tracker.update(sample(x, z, heading), view(tracker, world, x, z, heading, noise=noise, rng=rng))
        out.append(tracker.steer(sample(x, z, heading)))
    return out


def test_merging_counts_sightings():
    tr = PathTracker()
    world = dashes_l()
    walk(tr, world, [(0, -z, 0) for z in (0, 40, 80, 120)])
    orbs = tr.orbs(1)
    assert orbs and max(o.count for o in orbs) >= 3
    # every orb is one of the dashes (exact camera: no drift)
    for o in orbs:
        assert np.min(np.hypot(*(world - [o.x, o.z]).T)) < 1.0
    # no two orbs for one dash
    pts = np.array([[o.x, o.z] for o in orbs])
    gaps = np.hypot(*(pts[:, None] - pts[None]).transpose(2, 0, 1))
    assert np.min(gaps + np.eye(len(pts))*1e9) > tr.merge


def test_lone_sightings_age_out():
    tr = PathTracker(confirm_after=3)
    tr.update(sample(0, 0, 0), tr.camera.to_image([[300.0, -400]], 0, 0, 0))     # a stray mark, seen once
    assert len(tr.orbs(1)) == 1
    for _ in range(3):
        tr.update(sample(0, 0, 0), np.zeros((0, 2)))
    assert len(tr.orbs(1)) == 1
    tr.update(sample(0, 0, 0), np.zeros((0, 2)))
    assert tr.orbs(1) == []


def test_nothing_added_behind_or_at_the_feet():
    tr = PathTracker()
    behind = tr.camera.to_image([[0.0, 30], [10, -20]], 0, 0, 0)       # 30 behind, 20 ahead (inside `near`)
    tr.update(sample(0, 0, 0), behind)
    assert tr.orbs(1) == []


def test_passed_orbs_leave_the_route():
    tr = PathTracker()
    world = dashes_l()
    walk(tr, world, [(0, -z, 0) for z in range(0, 400, 40)])
    route = tr.route(sample(0, -400, 0))
    assert len(route) and np.all(route[:, 1] < -400 + tr.reach)          # all ahead of the character
    assert all(o.visited for o in tr.orbs(1) if o.z > -400 + tr.reach - 1 and abs(o.x) < 1)


def test_route_order_and_corner():
    tr = PathTracker(max_range=1500)
    world = dashes_l()
    rng = np.random.default_rng(3)
    walk(tr, world, [(0, -z, 0) for z in range(0, 640, 40)], rng=rng, noise=1.0)
    # an outlier pair beside the path, confirmed twice
    stray = tr.camera.to_image([[260.0, -800]], 0, -640, 0)
    tr.update(sample(0, -640, 0), stray)
    tr.update(sample(0, -640, 0), stray)
    here = sample(0, -640, 0)
    route = tr.route(here)
    assert len(route) >= 3
    run = np.hypot(*np.diff(np.vstack([[0, -640], route]), axis=0).T)
    assert np.all(run < tr.link)                                         # nearest first, no jumps
    assert np.all(np.diff(-route[:, 1]) > -5) or route[-1, 0] > 50      # forward, then round the corner
    assert np.min(np.hypot(route[:, 0] - 260, route[:, 1] + 800)) > 100  # the stray is not on it
    steer = tr.steer(here)
    assert abs(steer.error) < 10 and steer.confidence > .5
    # at the corner the way on turns right (east = +90)
    walk(tr, world, [(0, -z, 0) for z in range(680, 1000, 40)], rng=rng, noise=1.0)
    turn = tr.steer(sample(0, -960, 0))
    assert turn is not None and turn.error > 30


def test_route_survives_frames_without_dashes():
    tr = PathTracker()
    world = dashes_l()
    walk(tr, world, [(0, -z, 0) for z in range(0, 320, 40)])
    tr.update(sample(0, -360, 0), np.zeros((0, 2)))                      # dashes hidden for a frame
    steer = tr.steer(sample(0, -360, 0))
    assert steer is not None and abs(steer.error) < 5


def test_sectors_are_separate():
    tr = PathTracker()
    for z in (0, -30):                                   # two views of one dash
        tr.update(sample(0, z, 0, sector=7), tr.camera.to_image([[0.0, -300]], 0, z, 0))
    assert len(tr.route(sample(0, -30, 0, sector=7))) == 1
    assert len(tr.route(sample(0, -30, 0, sector=8))) == 0


def test_same_view_twice_is_not_two_sightings():
    tr = PathTracker()
    px = tr.camera.to_image([[0.0, -300]], 0, 0, 0)
    tr.update(sample(0, 0, 0), px)
    tr.update(sample(0, 0, 0), px)                     # standing still: the same picture again
    assert [o.count for o in tr.orbs(1)] == [1]


def test_turning_frames_are_not_placed():
    tr = PathTracker()
    px = tr.camera.to_image([[0.0, -300]], 0, 0, 0)
    assert tr.update(sample(0, 0, 0), px, before=sample(0, 0, 350)) == 0      # heading moved within the frame
    tr.update(sample(0, -20, 0), np.zeros((0, 2)))
    assert tr.update(sample(0, -40, 40), tr.camera.to_image([[0.0, -300]], 0, -40, 40)) == 0   # jumped 40 deg


def test_misplaced_orb_is_dropped_when_not_seen_again():
    tr = PathTracker()
    world = dashes_l()
    ghost = np.array([[150.0, -350]])                  # beside the path, in plain view
    for z in (0, -30):
        tr.update(sample(0, z, 0), np.vstack([view(tr, world, 0, z, 0), tr.camera.to_image(ghost, 0, z, 0)]))
    assert any(abs(o.x - 150) < 5 for o in tr.orbs(1))
    for z in (-60, -90, -120):
        tr.update(sample(0, z, 0), view(tr, world, 0, z, 0))
    assert not any(abs(o.x - 150) < 5 for o in tr.orbs(1))
    assert any(abs(o.z + 400) < 5 and abs(o.x) < 5 for o in tr.orbs(1))   # the real dashes stay


def test_replay_cal1_excerpt():
    """Twelve walking frames of the 28 Oct cal1 recording (Plaza 3, frames 124-135): the dash points that
    pathvision.find_path chose, with the live telemetry. The tracked route must follow where the character
    then walked."""
    data = json.loads((FIXTURES / "pathtrack_cal1.json").read_text())
    tr = PathTracker()
    held = []
    for row in data["frames"]:
        tr.update(row["sample"], np.array(row["points"], float).reshape(-1, 2), size=tuple(data["size"]))
        held.append((row["sample"], tr.route(row["sample"]), tr.steer(row["sample"])))
    track = np.array([[r["sample"]["x"], r["sample"]["z"]] for r in data["frames"]])
    misses, steered = [], 0
    for i, (s, route, steer) in enumerate(held[:-3]):
        if steer is None:
            continue
        steered += 1
        here = np.array([s["x"], s["z"]])
        poly = np.vstack([here, route])
        for p in track[i + 1:i + 4]:
            a, b = poly[:-1], poly[1:]
            t = np.clip(((p - a)*(b - a)).sum(1)/np.maximum(((b - a)**2).sum(1), 1e-9), 0, 1)
            misses.append(np.min(np.hypot(*(a + t[:, None]*(b - a) - p).T)))
    assert steered >= 6
    assert np.median(misses) < data["max_median_miss"]


class PathTrackTest(unittest.TestCase):
    """The test_* functions above, run by unittest like the rest of the suite."""


for _name, _fn in list(globals().items()):
    if _name.startswith("test_") and callable(_fn):
        setattr(PathTrackTest, _name, lambda self, fn=_fn: fn())
del _name, _fn


if __name__ == "__main__":
    unittest.main()
