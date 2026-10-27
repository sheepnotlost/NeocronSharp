"""Row reuse is based on content evidence; these are offline replays."""
from pathlib import Path
import unittest

import test_construction as fixtures
from inventory_tracking import snapshot,overlap,checked_overlap
from vision import Detector,cv2,np
from construction_runner import ConstructionRunner
from macro_core import Control,default_profile
from test_macro import FakeClock


class InventoryTrackingTests(unittest.TestCase):
    def production_replay(self,mode):
        folder=Path(__file__).parent/"fixtures"
        frames=[];detector=Detector()
        processor=cv2.cvtColor(cv2.imread(str(folder/"construction_ready.png")),cv2.COLOR_BGR2RGB)
        for i in range(4):
            crop=cv2.cvtColor(cv2.imread(str(folder/f"construction_overlap_{i}.png")),cv2.COLOR_BGR2RGB)
            frame=np.zeros((1080,1920,3),np.uint8);frame[300:665,1120:1630]=crop
            frame[700:700+processor.shape[0],100:100+processor.shape[1]]=processor
            frames.append(frame)
        inventory=detector.inventory(frames[3]);target=inventory.point(61.3+3*44.6,85.75+2*45.5)
        tooltip=cv2.cvtColor(cv2.imread(str(folder/"construction_tooltip_wp7_latest.png")),cv2.COLOR_BGR2RGB)
        hover=frames[3].copy();x,y=target[0]-180,target[1]+20
        hover[y:y+tooltip.shape[0],x:x+tooltip.shape[1]]=tooltip
        _,grid=detector.inventory_cells(frames[3])
        point_cells={tuple(c["point"]):c["cell"] for c in grid}
        class Replay:
            page=0
            position=None
            visits=[]
            def check_focus(self,size):pass
            def capture(self):
                if self.page==3 and self.position==target:return hover
                base=frames[self.page]
                cell=point_cells.get(tuple(self.position or []))
                # The same target was visible in the previous bottom row but
                # unreadable there. It must remain eligible after scrolling.
                if cell is None or (self.page==2 and cell==(5,3)):return base
                # Model a confirmed unrelated tooltip for other cells. The
                # production pixel detector reads this generated panel.
                result=base.copy();px,py=self.position[0]-120,self.position[1]+20
                cv2.rectangle(result,(px,py),(px+240,py+17),(0,0,0),-1)
                cv2.rectangle(result,(px,py),(px+240,py+17),(200,200,200),1)
                cv2.putText(result,"Other inventory item",(px+4,py+12),cv2.FONT_HERSHEY_SIMPLEX,.4,(220,220,220),1)
                return result
            def move(self,point):self.position=list(point);self.visits.append((self.page,tuple(point)))
            def scroll(self,notches):
                if self.page>=3:raise AssertionError("Verified visible WP7 was skipped")
                self.page+=1
        replay=Replay();clock=FakeClock();profile=default_profile()
        profile["operation"]="construction";profile["client_size"]=[1920,1080];profile["construction"]["search_mode"]=mode
        runner=ConstructionRunner(profile,replay,Control(),lambda *args:None,clock.clock,clock.sleep,detector=detector)
        source,destination=runner.locate_blueprint()
        self.assertEqual(source,target)
        _,cells=detector.inventory_cells(frames[3]);points={tuple(c["point"]) for c in cells}
        visited={i:{p for page,p in replay.visits if page==i and p in points} for i in range(4)}
        if mode=="all_cells":
            self.assertEqual(len(visited[0]),48)
            self.assertLessEqual(len(visited[1]),21)
            self.assertLessEqual(len(visited[2]),25)
            self.assertLess(sum(map(len,visited.values())),130)
        else:
            self.assertLessEqual(len(visited[0]),3)
            self.assertLessEqual(sum(map(len,visited.values())),12)
        # This is replay pacing, excluding the game's actual capture latency.
        self.assertLess(clock.now,8)
        replay.visits=[]
        source,destination=runner.locate_blueprint()
        self.assertEqual(source,target)
        self.assertEqual({p for page,p in replay.visits if p in points},{tuple(target)})

    def test_production_search_replays_new_rows_then_reuses_the_verified_stack(self):
        self.production_replay("all_cells")

    def test_fast_search_checks_only_cube_candidates_and_keeps_tooltip_verification(self):
        self.production_replay("fast")

    def test_two_new_rows_reuse_exactly_the_32_already_checked_cells(self):
        rng=np.random.default_rng(82)
        previous=rng.random((6,8,16,16,4),dtype=np.float32)
        current=np.concatenate((previous[2:],rng.random((2,8,16,16,4),dtype=np.float32)))
        checked={(r,c) for r in range(6) for c in range(8)}
        shift,reused=checked_overlap(previous,current,checked)
        self.assertEqual(shift,2)
        self.assertEqual(reused,{(r,c) for r in range(4) for c in range(8)})
        current[1,3]=rng.random((16,16,4),dtype=np.float32)
        checked.remove((3,4))  # An unreadable old cell was never verified.
        shift,reused=checked_overlap(previous,current,checked)
        self.assertEqual(shift,2)
        self.assertNotIn((1,3),reused);self.assertNotIn((1,4),reused)

    def test_ambiguous_blank_or_upward_views_do_not_skip_cells(self):
        rng=np.random.default_rng(31)
        repeated=np.ones((6,8,16,16,4),np.float32)
        self.assertIsNone(overlap(repeated,repeated))
        self.assertIsNone(overlap(repeated*0,repeated*0))
        previous=rng.random(repeated.shape,dtype=np.float32)
        upward=np.concatenate((rng.random((2,8,16,16,4),dtype=np.float32),previous[:4]))
        self.assertIsNone(overlap(previous,upward))

    def test_latest_recording_recognizes_overlaps_and_leaves_new_rows_unchecked(self):
        detector=Detector();views=[]
        for i in range(4):
            crop=cv2.cvtColor(cv2.imread(str(Path(__file__).parent/f"fixtures/construction_overlap_{i}.png")),cv2.COLOR_BGR2RGB)
            frame=np.zeros((1080,1920,3),np.uint8);frame[300:665,1120:1630]=crop
            views.append(snapshot(detector,frame,detector.inventory(frame)))
        checked={(r,c) for r in range(6) for c in range(8)}
        for i,expected,minimum in ((1,2,28),(2,2,24),(3,3,14)):
            with self.subTest(page=i):
                shift,reused=checked_overlap(views[i-1],views[i],checked)
                self.assertEqual(shift,expected)
                self.assertGreaterEqual(len(reused),minimum)
                self.assertFalse(any(r>=6-shift for r,c in reused))

    def test_next_build_checks_previous_stack_before_the_other_cells(self):
        run=fixtures.ConstructionRunnerTests();run.setup_run(count=2)
        run.runner.locate_blueprint()
        run.backend.events.clear()
        expected=run.backend.source()
        run.runner.locate_blueprint()
        _,cells=run.runner.detector.inventory_cells(run.backend.capture())
        points=[c["point"] for c in cells]
        visited=[p for kind,p in run.backend.events if kind=="move" and p in points]
        self.assertTrue(visited)
        self.assertTrue(all(p==expected for p in visited))

    def test_moved_cached_stack_is_not_dragged_without_new_name_verification(self):
        run=fixtures.ConstructionRunnerTests();run.setup_run(count=1)
        old=run.backend.source()
        run.runner.source_cell=(0,5)
        new_cell=(4,6)
        new_point=run.backend.inventory.point(61.3+6*44.6,85.75+4*45.5)
        run.backend.source=lambda:new_point
        # The fake grid's source location is deliberately moved to a new cell.
        original=run.runner.detector.inventory_cells
        def cells(frame,checkpoint=lambda:None):
            inv,items=original(frame,checkpoint)
            for item in items:
                if item["cell"]==(0,5):item["point"]=old
                if item["cell"]==new_cell:item["point"]=new_point
            return inv,items
        run.runner.detector.inventory_cells=cells
        source,destination=run.runner.locate_blueprint()
        self.assertEqual(source,new_point)
        self.assertEqual(run.runner.source_cell,new_cell)
        self.assertFalse(run.backend.transfers)
