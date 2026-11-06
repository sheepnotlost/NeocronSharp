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
    def __init__(self, mode="tracks", scale=1., speed=1., hidden=False, talk=False, decoys=(), green=None):
        self.mode, self.scale, self.speed, self.hidden, self.talk, self.decoys = mode, scale, speed, hidden, talk, decoys
        self.green = green          # (left, top, right, bottom): a bright green button, where the arrow can't be seen
        self.nudges = 0
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
            on_green = self.green is not None and self.green[0] <= x < self.green[2] and self.green[1] <= y < self.green[3]
            if 0 <= x < 2530 and 0 <= y < 1420 and not on_green:
                arrow(frame, (x, y))
        return frame

    def move_relative(self, dx, dy):
        self.nudges += 1
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
    def land(self, game, target=(1200, 700), run=None):
        before = len(game.clicks)
        (run or runner(game)).aim_click(target)
        self.assertEqual(len(game.clicks), before+1)
        x, y = game.clicks[-1]
        self.assertLessEqual(abs(x-target[0]), mission_runner.STEER_CLOSE, game.clicks)
        self.assertLessEqual(abs(y-target[1]), mission_runner.STEER_CLOSE, game.clicks)

    def test_a_pointer_that_follows_windows_cursor_lands_with_no_nudging(self):
        game = Game()
        run = runner(game)
        for target in ((1200, 700), (400, 900), (2000, 300)):
            self.land(game, target, run)
        self.assertEqual(game.nudges, 0)

    def test_on_a_green_terminal_button_it_snaps_there_and_clicks_with_no_hovering(self):
        game = Game(green=(1100, 690, 1300, 712))           # a tab bar, the arrow lost in it
        run = runner(game)
        self.land(game, (1200, 700), run)
        self.land(game, (1250, 700), run)
        self.assertEqual(game.nudges, 0, "no looking around for the pointer (the user's word, 5 Nov)")

    def test_in_a_conversation_where_the_pointer_went_it_never_looks_again(self):
        game = Game(talk=True)
        run = runner(game)
        for target in ((600, 500), (900, 520)):
            self.land(game, target, run)
        self.assertEqual(game.nudges, 0)
        self.assertTrue(run.tracks)

    def test_the_far_off_pointer_of_the_other_pc_is_steered_on_every_click(self):
        game = Game(mode="raw", speed=1.3, talk=True)
        run = runner(game)
        for target in ((600, 500), (900, 520), (700, 800)):
            self.land(game, target, run)
        self.assertTrue(run.steering)

    def test_a_pointer_scaled_from_windows_cursor_lands_in_a_conversation(self):
        self.land(Game(scale=1.25, talk=True), (600, 500))
        self.land(Game(scale=.8, talk=True), (600, 500))

    def test_a_pointer_only_mouse_motion_moves_lands_in_a_conversation(self):
        self.land(Game(mode="raw", speed=1.6, talk=True), (600, 500))
        self.land(Game(mode="raw", speed=.5, talk=True), (600, 500))

    def test_arrows_painted_on_the_screen_are_not_the_pointer(self):
        self.land(Game(decoys=[(1190, 690), (1215, 705), (320, 300)]))

    def test_with_no_pointer_showing_the_camera_ends_where_it_was(self):
        game = Game(hidden=True)
        runner(game).aim_click((1200, 700))         # outside a conversation: it clicks as it always did
        self.assertEqual(game.swept, 0)             # and never nudges the camera round
        self.assertNotIn("esc", game.keys)

    def test_a_conversation_in_mouse_look_gets_one_tab_and_then_the_click(self):
        game = Game(hidden=True, talk=True)
        self.land(game, (600, 500))
        self.assertEqual(game.keys, ["tab"])

    def test_a_conversation_whose_pointer_never_shows_is_not_clicked(self):
        game = Game(hidden=True, talk=True)
        game.key = lambda name, down: game.keys.append(name) if down else None      # Tab does nothing
        with self.assertRaisesRegex(Interrupted, "did not show in the conversation"):
            runner(game).aim_click((600, 500))
        self.assertEqual(game.clicks, [])
        self.assertEqual(game.keys, ["tab", "tab"])         # freed once, then put back

    def test_the_arrow_is_found_at_every_size_and_lines_and_blocks_are_not(self):
        for high in (10, 16, 24, 40):
            frame = np.zeros((300, 300, 3), np.uint8)
            arrow(frame, (100, 100), high)
            frame[200, 0:300] = GREEN                    # a one-pixel line
            frame[20:60, 200:240] = GREEN                # a lit button
            self.assertEqual([c[:2] for c in pointer.candidates(frame)], [(100, 100)], high)


if __name__ == "__main__":
    unittest.main()
