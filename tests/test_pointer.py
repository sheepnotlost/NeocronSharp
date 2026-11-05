"""The job loop finds the game's own pointer by sight and steers it onto the target before a click (the user's ask, 5 Nov)."""
import unittest

import numpy as np

import job_aim
import mission_runner
import pointer
from macro_core import Control, Interrupted, default_profile
from mission_runner import MissionRunner

job_aim.AIM_FILE = None
GREEN = (80, 220, 130)


def arrow(frame, tip, high=16):
    """The game's pointer: a solid green arrow, its tip at the top left."""
    x, y = tip
    for row in range(high):
        wide = 1+int(row*.7) if row < high*.8 else max(1, int(high*.56)-(row-int(high*.8))*2)
        frame[y+row, x:x+wide] = GREEN


class Game:
    """A client with its own pointer. tracks: it sits where Windows' cursor is, times scale. raw: only mouse motion moves
    it, times speed. hidden: mouse-look, where motion turns the camera; Tab shows it in a conversation."""
    def __init__(self, mode="tracks", scale=1., speed=1., hidden=False, talk=False, decoys=()):
        self.mode, self.scale, self.speed, self.hidden, self.talk, self.decoys = mode, scale, speed, hidden, talk, decoys
        self.cursor = [300., 300.]
        self.raw = [300., 300.]
        self.turned = self.swept = 0
        self.clicks, self.keys = [], []

    def at(self):
        if self.mode == "raw":
            return round(self.raw[0]), round(self.raw[1])
        return round(self.cursor[0]*self.scale), round(self.cursor[1]*self.scale)

    def capture(self):
        frame = np.zeros((1440, 2560, 3), np.uint8)
        if self.talk:
            frame[320:1190, 200:1760] = (41, 105, 62)
        for decoy in self.decoys:
            arrow(frame, decoy)
        if not self.hidden:
            x, y = self.at()
            if 0 <= x < 2530 and 0 <= y < 1420:
                arrow(frame, (x, y))
        return frame

    def move_relative(self, dx, dy):
        if self.hidden:
            self.turned += dx
            self.swept += abs(dx)
            return
        self.cursor = [min(2559/self.scale, max(0, self.cursor[0]+dx)), min(1439/self.scale, max(0, self.cursor[1]+dy))]
        self.raw = [min(2559, max(0, self.raw[0]+dx*self.speed)), min(1439, max(0, self.raw[1]+dy*self.speed))]

    def move(self, point):
        self.cursor = list(point)

    def cursor_client(self):
        return list(self.cursor)

    def button(self, name, down):
        if down:
            self.clicks.append(None if self.hidden else self.at())

    def key(self, name, down):
        if down:
            self.keys.append(name)
            if name == "tab" and self.talk:
                self.hidden = not self.hidden

    def check_focus(self, size):
        pass

    def release_all(self):
        pass


def runner(game):
    run = MissionRunner(default_profile(), game, Control(), lambda *a: None, detector=object(), engine=object(), aim=job_aim.Aim(None))
    run.wait = lambda seconds, safe_pause=False: None
    return run


class PointerTests(unittest.TestCase):
    def land(self, game, target=(1200, 700)):
        runner(game).aim_click(target)
        self.assertEqual(len(game.clicks), 1)
        x, y = game.clicks[0]
        self.assertLessEqual(abs(x-target[0]), mission_runner.STEER_CLOSE, game.clicks)
        self.assertLessEqual(abs(y-target[1]), mission_runner.STEER_CLOSE, game.clicks)

    def test_a_pointer_that_follows_windows_cursor_lands(self):
        self.land(Game())

    def test_a_pointer_scaled_from_windows_cursor_lands(self):
        self.land(Game(scale=1.25))
        self.land(Game(scale=.8))

    def test_a_pointer_only_mouse_motion_moves_lands(self):
        self.land(Game(mode="raw", speed=1.6))
        self.land(Game(mode="raw", speed=.5))

    def test_arrows_painted_on_the_screen_are_not_the_pointer(self):
        self.land(Game(decoys=[(1190, 690), (1215, 705), (320, 300)]))

    def test_with_no_pointer_showing_nothing_is_clicked_and_the_camera_barely_turns(self):
        game = Game(hidden=True)
        with self.assertRaisesRegex(Interrupted, "nowhere on the screen"):
            runner(game).aim_click((1200, 700))
        self.assertEqual(game.clicks, [])
        self.assertEqual(game.turned, 0)            # each nudge that found no pointer was undone by the next
        self.assertLessEqual(game.swept, 8*mission_runner.PROBE)
        self.assertNotIn("esc", game.keys)

    def test_a_conversation_in_mouse_look_gets_one_tab_and_then_the_click(self):
        game = Game(hidden=True, talk=True)
        self.land(game, (600, 500))
        self.assertEqual(game.keys, ["tab"])

    def test_the_arrow_is_found_at_every_size_and_lines_and_blocks_are_not(self):
        for high in (10, 16, 24, 40):
            frame = np.zeros((300, 300, 3), np.uint8)
            arrow(frame, (100, 100), high)
            frame[200, 0:300] = GREEN                    # a one-pixel line
            frame[20:60, 200:240] = GREEN                # a lit button
            self.assertEqual([c[:2] for c in pointer.candidates(frame)], [(100, 100)], high)


if __name__ == "__main__":
    unittest.main()
