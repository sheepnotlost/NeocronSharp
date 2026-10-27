"""Offline cell coverage, tooltip timing and false-match regression checks."""
from pathlib import Path
import unittest

from construction_runner import ConstructionRunner
from macro_core import Control, Interrupted, default_profile
import test_construction as construction_fixtures
from test_macro import FakeClock
from vision import Detector, cv2, np


class InventorySweepTests(unittest.TestCase):
    def test_wheel_stays_inside_inventory_until_the_game_consumes_it(self):
        run=construction_fixtures.ConstructionRunnerTests();run.setup_run(count=1)
        run.backend.page_recipes=[None,"weaponpart_7"]
        scroll=run.backend.scroll;pending=False
        def queue_wheel(notches):
            nonlocal pending
            pending=True
        run.backend.scroll=queue_wheel
        def game_tick():
            nonlocal pending
            if pending:
                pending=False
                if run.backend.position==run.backend.inventory.point(395,310):scroll(-1)
        run.clock.on_sleep=game_tick
        run.runner.run()
        self.assertFalse(run.errors(),run.events)
        self.assertEqual(run.backend.scrolls,[-1])
        self.assertEqual(run.runner.completed,1)

    def test_ignored_wheel_uses_detected_thumb_then_searches_later_rows(self):
        run=construction_fixtures.ConstructionRunnerTests();run.setup_run(count=1)
        run.backend.page_recipes=[None,"weaponpart_7"]
        wheel=[];drags=[];held=None
        def bar(frame,inventory):
            return {"position":frame["page"]*20,"thumb":inventory.point(419,86+frame["page"]*20),
                    "bottom":inventory.point(419,333)[1],"thumb_bottom":inventory.point(419,100+frame["page"]*20)[1]}
        run.runner.detector.inventory_scrollbar=bar
        run.backend.scroll=wheel.append
        original=run.backend.button
        def button(name,down):
            nonlocal held
            thumb=bar({"page":run.backend.page},run.backend.inventory)["thumb"]
            if down and run.backend.position==thumb:
                held=run.backend.position[:];return
            if not down and held is not None:
                drags.append((held,run.backend.position[:]))
                held=None;run.backend.page+=1;return
            original(name,down)
        run.backend.button=button
        run.runner.run()
        self.assertFalse(run.errors(),run.events)
        self.assertEqual(wheel,[-1,-1])
        self.assertEqual(len(drags),1)
        self.assertEqual(drags[0][1][1]-drags[0][0][1],1)
        self.assertEqual(run.runner.completed,1)

    def test_region_capture_keeps_focus_guards_and_reacquires_when_header_is_missing(self):
        crop=cv2.cvtColor(cv2.imread(str(Path(__file__).parent/"fixtures/construction_search_2013.png")),cv2.COLOR_BGR2RGB)
        frame=np.zeros((1080,1920,3),np.uint8);frame[300:665,1120:1630]=crop
        detector=Detector();inventory=detector.inventory(frame)
        class Replay:
            focus=True
            partial=0
            full=0
            def check_focus(self,size):
                if not self.focus:raise Interrupted("Game lost focus")
            def capture_region(self,box):
                self.partial+=1;return np.zeros_like(frame)  # Window left the old ROI.
            def capture(self):self.full+=1;return frame
        replay=Replay();clock=FakeClock();profile=default_profile()
        profile["operation"]="construction";profile["client_size"]=[1920,1080];profile["construction"]["search_mode"]="all_cells"
        runner=ConstructionRunner(profile,replay,Control(),lambda *args:None,clock.clock,clock.sleep,detector=detector)
        result=runner.inventory_frame(inventory,inventory.point(61.3,85.75))
        self.assertIs(result,frame)
        self.assertEqual((replay.partial,replay.full),(1,1))
        replay.focus=False
        with self.assertRaises(Interrupted):runner.inventory_frame(inventory)
        self.assertEqual((replay.partial,replay.full),(1,1))

    def test_focus_loss_during_scrollbar_fallback_releases_the_button(self):
        run=construction_fixtures.ConstructionRunnerTests();run.setup_run(count=1)
        run.backend.page_recipes=[None,"weaponpart_7"]
        run.backend.scroll=lambda notches:None
        run.runner.detector.inventory_scrollbar=lambda frame,inv:{"position":0,"thumb":inv.point(419,86),
                                                                "bottom":inv.point(419,333)[1],"thumb_bottom":inv.point(419,100)[1]}
        held=False;released=False
        original=run.backend.button
        def button(name,down):
            nonlocal held,released
            if down and run.backend.position==run.backend.inventory.point(419,86):held=True;return
            if not down and held:held=False;released=True;return
            original(name,down)
        run.backend.button=button
        run.clock.on_sleep=lambda:setattr(run.backend,"focus",False) if held else None
        run.runner.run()
        self.assertIn("Game lost focus",run.errors()[0])
        self.assertTrue(released);self.assertFalse(held)
        self.assertFalse(run.backend.transfers)

    def test_every_cell_is_visited_in_order_before_scrolling_and_search_continues(self):
        run=construction_fixtures.ConstructionRunnerTests();run.setup_run(count=1)
        run.backend.page_recipes=[None,"weaponpart_7"]
        detector=run.runner.detector
        frame=run.backend.capture();_,cells=detector.inventory_cells(frame)
        wanted=[c["point"] for c in cells]
        scroll=run.backend.scroll
        def checked_scroll(notches):
            moves=[p for kind,p in run.backend.events if kind=="move" and p in wanted]
            self.assertEqual(moves,wanted)
            scroll(notches)
        run.backend.scroll=checked_scroll
        run.runner.run()
        self.assertFalse(run.errors(),run.events)
        self.assertEqual(run.runner.completed,1)
        self.assertEqual(run.backend.scrolls,[-1])

    def test_a_stale_target_tooltip_on_an_unrelated_cell_cannot_authorize_drag(self):
        run=construction_fixtures.ConstructionRunnerTests();run.setup_run(count=1)
        expected_source=run.backend.source()
        detector=run.runner.detector
        read=detector.tooltip_recipe;seen=False
        def stale_once(frame,point,scale):
            nonlocal seen
            if frame["position"]==point and point==frame["inventory"].point(61.3,85.75) and not seen:
                seen=True;return "weaponpart_7"
            return read(frame,point,scale)
        detector.tooltip_recipe=stale_once
        run.runner.run()
        self.assertTrue(seen)
        self.assertFalse(run.errors(),run.events)
        self.assertEqual(run.backend.transfers[0][0],expected_source)
        self.assertEqual(len(run.backend.transfers),1)

    def test_brief_tooltip_delay_is_retried_without_skipping_the_target(self):
        run=construction_fixtures.ConstructionRunnerTests();run.setup_run(count=1)
        detector=run.runner.detector;read=detector.tooltip_recipe
        move=run.backend.move;entered=0
        def track_move(point):
            nonlocal entered
            move(point);entered=run.clock.now
        run.backend.move=track_move
        def delayed(frame,point,scale):
            if run.clock.now-entered<.085:return None
            return read(frame,point,scale)
        detector.tooltip_recipe=delayed
        run.runner.run()
        self.assertFalse(run.errors(),run.events)
        self.assertEqual(len(run.backend.transfers),1)

    def test_recorded_inventory_sweep_covers_blank_and_rejected_icon_cells(self):
        crop=cv2.cvtColor(cv2.imread(str(Path(__file__).parent/"fixtures/construction_search_2013.png")),cv2.COLOR_BGR2RGB)
        frame=np.zeros((1080,1920,3),np.uint8);frame[300:665,1120:1630]=crop
        detector=Detector();inventory,cells=detector.inventory_cells(frame)
        self.assertEqual([c["cell"] for c in cells],[(r,c) for r in range(6) for c in range(8)])
        _,filtered=detector.blueprint_candidates(frame)
        self.assertLess(len(filtered),len(cells))
        self.assertEqual(detector.current_inventory(frame,inventory),inventory)
        class Replay:
            position=None
            visits=[]
            def check_focus(self,size):pass
            def capture(self):return frame
            def move(self,point):
                self.position=list(point)
                if point in [c["point"] for c in cells]:self.visits.append(list(point))
            def scroll(self,notches):raise Interrupted("page visited; stop offline replay")
        replay=Replay();clock=FakeClock();profile=default_profile()
        profile["operation"]="construction";profile["client_size"]=[1920,1080];profile["construction"]["search_mode"]="all_cells"
        runner=ConstructionRunner(profile,replay,Control(),lambda *args:None,clock.clock,clock.sleep,detector=detector)
        with self.assertRaisesRegex(Interrupted,"page visited"):runner.locate_blueprint()
        self.assertEqual(replay.visits,[c["point"] for c in cells])
        self.assertLess(clock.now,6.2)  # UI pacing, excluding real capture/OCR CPU time.

    def test_local_header_verification_relocates_moved_inventory(self):
        crop=cv2.cvtColor(cv2.imread(str(Path(__file__).parent/"fixtures/construction_search_2013.png")),cv2.COLOR_BGR2RGB)
        first=np.zeros((1080,1920,3),np.uint8);first[300:665,1120:1630]=crop
        moved=np.zeros_like(first);moved[200:565,700:1210]=crop
        detector=Detector();old=detector.inventory(first)
        current=detector.current_inventory(moved,old)
        self.assertNotEqual((current.x,current.y),(old.x,old.y))
        self.assertEqual(current,detector.inventory(moved))
