from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from construction_runner import ConstructionRunner
from macro_core import Control, Interrupted, default_profile, load_profile, save_profile, validate_profile
from recipes import RECIPES, add_recipe, catalog, find_recipe, identify_name
from test_macro import FakeClock
from vision import Ambiguous, Anchor, Detector, cv2, np


class ConstructionBackend:
    def __init__(self, clock, recipe, available):
        self.clock=clock
        self.recipe=recipe
        self.available=available
        self.inventory=Anchor(1000,300,1,1)
        self.processor=Anchor(100,200,1,1)
        self.captures=0
        self.focus=True
        self.dialog=False
        self.quantity=available
        self.loaded=False
        self.used=False
        self.output=False
        self.finish_at=None
        self.starts=[]
        self.transfers=[]
        self.events=[]
        self.position=None
        self.held={}
        self.keys=set()
        self.duplicate=False
        self.ignore_quantity=False
        self.produce_result=True
        self.field=[600,100]
        self.ok=[700,100]
        self.page=0
        self.page_recipes=None
        self.scrolls=[]
        self.scrollbar_hidden=False
        self.settle_result=False
        self.result_slots=None

    def source(self):
        return self.inventory.point(284,86) if self.page==0 else self.inventory.point(150,178)

    def scroll(self, notches):
        self.check_focus(None)
        assert self.position==self.inventory.point(395,310), "Scroll targeted stale Inventory coordinates"
        self.scrolls.append(notches)
        if self.page_recipes is not None and self.page<len(self.page_recipes)-1:
            self.page+=1
            self.inventory=Anchor(self.inventory.x+15,self.inventory.y+10,1,1)

    def check_focus(self, size):
        if not self.focus:
            raise Interrupted("Game lost focus")

    def capture(self):
        if self.finish_at is not None and self.clock.now>=self.finish_at:
            self.finish_at=None
            self.loaded=False
            self.used=True
            self.output=self.produce_result
            self.inventory=Anchor(self.inventory.x+30,self.inventory.y+20,1,1)
        self.captures+=1
        self.processor=Anchor(80+(self.captures%4)*140,150+(self.captures%3)*90,1,1)
        if self.settle_result and self.used and self.finish_at is None:
            self.processor=Anchor(100,200,1,1)
        return {"backend":self,"processor":self.processor,"inventory":self.inventory,
                "dialog":self.dialog,"busy":self.finish_at is not None,"result":self.output,
                "loaded":self.loaded,"used":self.used,"position":self.position,
                "page":self.page,"source":self.source(),
                "recipe":self.recipe if self.page_recipes is None else self.page_recipes[self.page],
                "available":self.available,"quantity":self.quantity,"field":self.field[:],"ok":self.ok[:]}

    def move(self, point):
        self.position=list(point)
        self.events.append(("move",self.position[:]))

    def button(self, name, down):
        self.events.append((name,down))
        if down:
            self.held[name]=self.position[:]
            return
        source=self.held.pop(name,None)
        if source is None:
            return
        if source!=self.position:
            if source!=self.source():
                raise AssertionError("An ingredient or empty cube was dragged")
            expected=Detector.input_point(self.processor,2 if self.used else 1)
            assert self.position==expected, "Stale Processor destination"
            self.transfers.append((source,self.position[:]))
            self.dialog=self.available>1
            self.loaded=not self.dialog
            self.quantity=self.available
            if self.loaded:self.available-=1
        elif self.dialog and self.position==self.ok:
            assert self.quantity==1,"Unverified quantity was confirmed"
            self.dialog=False
            self.loaded=True
            self.available-=1
        elif self.position==self.processor.start_point():
            assert self.loaded and not self.dialog and self.finish_at is None
            self.starts.append(self.position[:])
            self.output=False
            self.finish_at=self.clock.now+(1,3,20)[(len(self.starts)-1)%3]

    def key(self, name, down):
        self.events.append((name,down))
        if down:self.keys.add(name)
        else:self.keys.discard(name)
        if name=="1" and down and not self.ignore_quantity:
            self.quantity=1
            self.field=[650,140]
            self.ok=[750,140]

    def release_all(self):
        for name in list(self.held):self.button(name,False)
        for name in list(self.keys):self.key(name,False)


class ConstructionDetector:
    def processor(self, frame, checkpoint=lambda:None):
        checkpoint()
        return frame["processor"]

    def inventory(self, frame, checkpoint=lambda:None):
        checkpoint()
        return frame["inventory"]

    def current_inventory(self,frame,inventory,checkpoint=lambda:None):
        return self.inventory(frame,checkpoint)

    def inventory_cells(self,frame,checkpoint=lambda:None):
        inv=self.inventory(frame,checkpoint)
        source_cell=(0,5) if frame["page"]==0 else (2,2)
        cells=[{"cell":(r,c),"point":frame["source"] if (r,c)==source_cell else inv.point(61.3+c*44.6,85.75+r*45.5)}
               for r in range(6) for c in range(8)]
        return inv,cells

    def blueprint_candidates(self, frame, checkpoint=lambda:None):
        checkpoint()
        inv=frame["inventory"]
        candidates=[{"cell":(0,5) if frame["page"]==0 else (2,2),"point":frame["source"]}] if frame["recipe"] else []
        if frame["used"] or frame["backend"].duplicate:
            candidates.append({"cell":(1,5),"point":inv.point(284,132)})
        return inv,candidates

    def tooltip_recipe(self, frame, point, scale):
        inv=frame["inventory"]
        if frame["position"]!=point:return None
        if point==frame["source"] or (frame["backend"].duplicate and point==inv.point(284,132)):
            return frame["recipe"]
        return None  # Used empty datacubes are ignored.

    def inventory_scroll_position(self, frame, inventory):
        if frame["backend"].scrollbar_hidden:
            raise Interrupted("Inventory scrollbar is hidden")
        return frame["page"]*20

    def quantity(self, frame, checkpoint=lambda:None):
        checkpoint()
        return {"field":frame["field"],"ok":frame["ok"],"one":frame["quantity"]==1} if frame["dialog"] else None

    def construction_state(self, frame, anchor, recipe):
        return {"busy":frame["busy"],"result":frame["result"]}

    def construction_input(self, frame, anchor):
        if frame["loaded"]:
            raise Ambiguous("Pending blueprint")
        return 2 if frame["used"] else 1

    input_point=staticmethod(Detector.input_point)

    def has_loaded_blueprint(self, frame, anchor):
        return frame["loaded"] and not frame["dialog"]

    def result_details(self,frame,point,scale):
        backend=frame["backend"]
        if not frame["result"] or point!=frame["processor"].point(421,110):return None
        slots=backend.result_slots
        if isinstance(slots,list):slots=slots[len(backend.starts)-1]
        return {"recipe":backend.recipe,"slots":slots,"text":"simulated result tooltip"}


class ConstructionRunnerTests(unittest.TestCase):
    def setup_run(self, recipe="weaponpart_7", available=3, count=0, search_mode="all_cells"):
        self.profile=default_profile()
        self.profile["operation"]="construction"
        self.profile["client_size"]=[1920,1080]
        self.profile["construction"]={"recipe":recipe,"available":available,"count":count,"search_mode":search_mode}
        self.clock=FakeClock()
        self.control=Control()
        self.backend=ConstructionBackend(self.clock,recipe,available)
        self.events=[]
        self.runner=ConstructionRunner(self.profile,self.backend,self.control,
                                       lambda k,v:self.events.append((k,v)),
                                       self.clock.clock,self.clock.sleep,detector=ConstructionDetector())

    def errors(self):
        return [v for k,v in self.events if k=="error"]

    def test_all_recipes_build_repeatedly_with_relocation_and_no_ingredient_gestures(self):
        for recipe in RECIPES:
            with self.subTest(recipe=recipe):
                self.setup_run(recipe)
                original=deepcopy(self.profile)
                self.runner.run()
                self.assertFalse(self.errors(),self.events)
                self.assertEqual(self.runner.completed,3)
                self.assertEqual(len(self.backend.transfers),3)
                self.assertEqual(len(self.backend.starts),3)
                self.assertEqual(self.backend.available,0)
                self.assertTrue(self.backend.output)
                self.assertTrue(self.backend.used)
                self.assertEqual(self.profile,original)
                self.assertGreater(len({tuple(p) for p in self.backend.starts}),1)
                self.assertFalse(self.backend.scrolls)

    def test_scrolls_to_lower_blueprints_for_every_recipe_and_repeated_builds(self):
        for recipe in RECIPES:
            with self.subTest(recipe=recipe):
                self.setup_run(recipe)
                wrong=next(r for r in RECIPES if r!=recipe)
                self.backend.page_recipes=[wrong,None,recipe]
                self.runner.run()
                self.assertFalse(self.errors(),self.events)
                self.assertEqual(self.backend.scrolls,[-1,-1])
                self.assertEqual(self.runner.completed,3)
                self.assertEqual(len(self.backend.transfers),3)
                self.assertEqual(self.backend.transfers[0][0],Anchor(1030,320,1,1).point(150,178))

    def test_missing_blueprint_stops_when_scrollbar_no_longer_moves(self):
        self.setup_run()
        self.backend.page_recipes=[None,"holy_heal",None]
        self.runner.run()
        self.assertEqual(self.backend.scrolls,[-1,-1,-1,-1])
        self.assertIn("reached the bottom",self.errors()[0])
        self.assertFalse(self.backend.transfers)
        self.assertFalse(self.backend.starts)

    def test_focus_loss_before_wheel_prevents_scroll(self):
        self.setup_run()
        self.backend.page_recipes=[None,"weaponpart_7"]
        move=self.backend.move
        def lose_focus(point):
            move(point)
            if point==self.backend.inventory.point(395,310):
                self.backend.focus=False
        self.backend.move=lose_focus
        self.runner.run()
        self.assertIn("Game lost focus",self.errors()[0])
        self.assertFalse(self.backend.scrolls)
        self.assertFalse(self.backend.transfers)

    def test_focus_loss_after_wheel_prevents_any_transfer(self):
        self.setup_run()
        self.backend.page_recipes=[None,"weaponpart_7"]
        self.clock.on_sleep=lambda:setattr(self.backend,"focus",False) if self.backend.scrolls else None
        self.runner.run()
        self.assertIn("Game lost focus",self.errors()[0])
        self.assertEqual(self.backend.scrolls,[-1])
        self.assertFalse(self.backend.transfers)

    def test_hidden_scrollbar_prevents_unverified_scrolling(self):
        self.setup_run()
        self.backend.page_recipes=[None,"weaponpart_7"]
        self.backend.scrollbar_hidden=True
        self.runner.run()
        self.assertIn("scrollbar is hidden",self.errors()[0])
        self.assertFalse(self.backend.scrolls)

    def test_unreadable_blueprint_does_not_block_search_of_later_rows(self):
        self.setup_run()
        self.backend.page_recipes=["unknown","weaponpart_7"]
        self.runner.run()
        self.assertFalse(self.errors(),self.events)
        self.assertEqual(self.backend.scrolls,[-1])
        self.assertEqual(self.runner.completed,3)

    def test_inventory_search_has_a_hard_limit_even_if_scroll_keeps_moving(self):
        self.setup_run()
        self.backend.page_recipes=[None]*200
        self.runner.run()
        self.assertIn("search limit",self.errors()[0])
        self.assertEqual(len(self.backend.scrolls),128)
        self.assertFalse(self.backend.transfers)

    def test_finite_count_leaves_unused_blueprints_and_last_product_in_processor(self):
        self.setup_run(available=5,count=2)
        self.runner.run()
        self.assertFalse(self.errors())
        self.assertEqual(self.runner.completed,2)
        self.assertEqual(self.backend.available,3)
        self.assertTrue(self.backend.output)

    def test_wrong_recipe_prevents_transfers(self):
        self.setup_run()
        self.backend.recipe="holy_heal"
        self.runner.run()
        self.assertTrue(self.errors())
        self.assertFalse(self.backend.transfers)
        self.assertFalse(self.backend.starts)

    def test_first_verified_stack_is_used_without_hovering_over_other_stacks(self):
        self.setup_run()
        self.backend.duplicate=True
        self.runner.run()
        self.assertFalse(self.errors())
        self.assertEqual(self.runner.completed,3)
        self.assertNotIn(("move",Anchor(1000,300,1,1).point(284,132)),self.backend.events)

    def test_custom_recipe_repeats_only_after_matching_result_tooltip(self):
        for output in (True,False):
            with self.subTest(output=output):
                self.setup_run()
                key=add_recipe(self.profile,"Custom Test Blaster 13",["ctb13"])
                self.profile["construction"]["recipe"]=key
                self.backend.recipe=key
                self.backend.produce_result=output
                capture=self.backend.capture
                def settled_result():
                    frame=capture()
                    if frame["used"] and not frame["busy"]:
                        self.backend.processor=frame["processor"]=Anchor(100,200,1,1)
                    return frame
                self.backend.capture=settled_result
                detector=ConstructionDetector()
                self.runner=ConstructionRunner(self.profile,self.backend,self.control,
                                               lambda k,v:self.events.append((k,v)),
                                               self.clock.clock,self.clock.sleep,detector=detector)
                self.runner.run()
                if output:
                    self.assertFalse(self.errors(),self.events)
                    self.assertEqual(self.runner.completed,3)
                else:
                    self.assertIn("result name could not be verified",self.errors()[0])
                    self.assertEqual(len(self.backend.transfers),1)

    def test_optional_slot_counter_counts_zero_through_five(self):
        self.setup_run("holy_heal",available=6)
        self.profile["construction"]["count_slots"]=True
        self.backend.settle_result=True
        self.backend.result_slots=list(range(6))
        self.runner=ConstructionRunner(self.profile,self.backend,self.control,
                                       lambda k,v:self.events.append((k,v)),self.clock.clock,self.clock.sleep,
                                       detector=ConstructionDetector())
        self.runner.run()
        self.assertFalse(self.errors(),self.events)
        self.assertEqual(self.runner.slot_counts,{i:1 for i in range(6)})
        self.assertEqual(self.runner.slot_unread,0)
        event=[v for k,v in self.events if k=="construction_cycle"][-1]
        self.assertEqual(event["slot_counts"],{i:1 for i in range(6)})

    def test_unread_slot_counts_do_not_become_zero(self):
        self.setup_run("holy_heal")
        self.profile["construction"]["count_slots"]=True
        self.backend.settle_result=True
        self.runner=ConstructionRunner(self.profile,self.backend,self.control,
                                       lambda k,v:self.events.append((k,v)),self.clock.clock,self.clock.sleep,
                                       detector=ConstructionDetector())
        self.runner.run()
        self.assertFalse(self.errors())
        self.assertEqual(self.runner.completed,3)
        self.assertEqual(self.runner.slot_counts[0],0)
        self.assertEqual(self.runner.slot_unread,3)


    def test_quantity_must_be_verified_after_edit_and_dialog_movement(self):
        self.setup_run()
        self.backend.ignore_quantity=True
        self.runner.run()
        self.assertIn("quantity 1",self.errors()[0])
        self.assertFalse(self.backend.starts)

    def test_missing_result_stops_without_another_blueprint_transfer(self):
        self.setup_run()
        self.backend.produce_result=False
        self.runner.run()
        self.assertIn("without a visible",self.errors()[0])
        self.assertEqual(len(self.backend.transfers),1)
        self.assertEqual(self.runner.completed,0)

    def test_focus_loss_during_transfer_releases_input_and_does_not_start(self):
        self.setup_run()
        self.clock.on_sleep=lambda:setattr(self.backend,"focus",False) if self.backend.held else None
        self.runner.run()
        self.assertIn("Game lost focus",self.errors()[0])
        self.assertFalse(self.backend.held)
        self.assertFalse(self.backend.keys)
        self.assertFalse(self.backend.starts)

    def test_focus_loss_while_building_never_starts_next_run(self):
        self.setup_run()
        self.clock.on_sleep=lambda:setattr(self.backend,"focus",False) if self.backend.starts else None
        self.runner.run()
        self.assertIn("Game lost focus",self.errors()[0])
        self.assertEqual(len(self.backend.starts),1)
        self.assertEqual(self.runner.completed,0)


class ConstructionVisionTests(unittest.TestCase):
    def test_production_search_finds_the_blueprint_after_moving_it_to_other_cells(self):
        folder=Path(__file__).parent/"fixtures"
        inventory_image=cv2.cvtColor(cv2.imread(str(folder/"construction_scan_idle.png")),cv2.COLOR_BGR2RGB)
        tooltip=cv2.cvtColor(cv2.imread(str(folder/"construction_tooltip_wp7_latest.png")),cv2.COLOR_BGR2RGB)
        d=Detector();anchor=d.inventory(inventory_image)
        cube=d.region(inventory_image,anchor,(39+5*44.6+1,64,39+5*44.6+43,107)).copy()
        blank=d.region(inventory_image,anchor,(40,63+5*45.5+1,82,63+5*45.5+44)).copy()
        for row,col in ((0,0),(0,7),(2,3),(3,6),(5,0),(5,7)):
            with self.subTest(cell=(row,col)):
                idle=self.scan_frame("idle",1)
                detector=Detector();inv=detector.inventory(idle)
                for old_row in (0,1):
                    p=inv.point(39+5*44.6+1,63+old_row*45.5+1)
                    idle[p[1]:p[1]+blank.shape[0],p[0]:p[0]+blank.shape[1]]=blank
                p=inv.point(39+col*44.6+1,63+row*45.5+1)
                idle[p[1]:p[1]+cube.shape[0],p[0]:p[0]+cube.shape[1]]=cube
                point=inv.point(39+col*44.6+22.3,63+row*45.5+22.75)
                hover=idle.copy();x,y=point[0]-100,point[1]+22
                hover[y:y+tooltip.shape[0],x:x+tooltip.shape[1]]=tooltip
                scale=4/3
                idle=cv2.resize(idle,None,fx=scale,fy=scale)
                hover=cv2.resize(hover,None,fx=scale,fy=scale)
                detector=Detector();detector.inventory_scale=scale
                inv,candidates=detector.blueprint_candidates(idle)
                target=next(c["point"] for c in candidates if c["cell"]==(row,col))
                class Replay:
                    position=None
                    def check_focus(self,size):pass
                    def move(self,point):self.position=point
                    def capture(self):return hover if self.position==target else idle
                    def scroll(self,notches):raise AssertionError("Moved blueprint was skipped")
                profile=default_profile();profile["operation"]="construction"
                profile["client_size"]=list(idle.shape[:2][::-1])
                clock=FakeClock()
                runner=ConstructionRunner(profile,Replay(),Control(),lambda *args:None,clock.clock,clock.sleep,detector=detector)
                source,destination=runner.locate_blueprint()
                self.assertEqual(source,target)
                self.assertLess(clock.now,(row*8+col+1)*.13+.3,"Rapid cell scan waited unnecessarily")

    def test_native_inventory_excludes_finished_holy_heals(self):
        crop=cv2.cvtColor(cv2.imread(str(Path(__file__).parent/"fixtures/construction_native_inventory.png")),cv2.COLOR_BGR2RGB)
        frame=np.zeros((1440,2560,3),np.uint8)
        frame[150:150+crop.shape[0],600:600+crop.shape[1]]=crop
        d=Detector();d.inventory_scale=4/3
        inventory,candidates=d.blueprint_candidates(frame)
        self.assertEqual({c["cell"] for c in candidates},{(0,5),(1,5)})
        self.assertEqual(d.result_name(frame,inventory.point(105,268),inventory.scale),"holy_heal")
        self.assertEqual(d.result_details(frame,inventory.point(105,268),inventory.scale)["slots"],2)

    def test_ocr_identifies_a_new_custom_name_without_a_template(self):
        profile=default_profile();key=add_recipe(profile,"Custom Test Blaster 13",["ctb13"])
        d=Detector();d.recipes=catalog(profile)
        label=np.zeros((17,650),np.uint8)
        label[1:16,1:79]=d.templates["tooltip_prefix"]
        cv2.putText(label,"30 TB Capacity: Custom Test Blaster 13",(84,13),cv2.FONT_HERSHEY_SIMPLEX,.45,220,1,cv2.LINE_AA)
        cv2.rectangle(label,(0,0),(649,16),220,1)
        original=np.zeros((900,1600,3),np.uint8)
        original[400:417,500:1150]=cv2.cvtColor(label,cv2.COLOR_GRAY2RGB)
        for scale in (1,4/3,1.7):
            with self.subTest(scale=scale):
                frame=cv2.resize(original,None,fx=scale,fy=scale)
                self.assertEqual(d.tooltip_recipe(frame,[round(700*scale),round(380*scale)],scale),key)

    def scan_frame(self, name, scale):
        folder=Path(__file__).parent/"fixtures"
        inventory=cv2.cvtColor(cv2.imread(str(folder/f"construction_scan_{name}.png")),cv2.COLOR_BGR2RGB)
        processor=cv2.cvtColor(cv2.imread(str(folder/"construction_ready.png")),cv2.COLOR_BGR2RGB)
        frame=np.zeros((1080,1920,3),np.uint8)
        frame[100:100+inventory.shape[0],850:850+inventory.shape[1]]=inventory
        frame[550:550+processor.shape[0],100:100+processor.shape[1]]=processor
        return cv2.resize(frame,None,fx=scale,fy=scale)

    def test_failure_recording_excludes_finished_spells_and_reads_both_blueprint_recipes(self):
        for scale in (1,4/3,1.7):
            for name,recipe,cell in (("wp7","weaponpart_7",(0,5)),("hh","holy_heal",(1,5))):
                with self.subTest(scale=scale,name=name):
                    d=Detector();d.inventory_scale=scale
                    frame=self.scan_frame(name,scale)
                    inventory,candidates=d.blueprint_candidates(frame)
                    self.assertEqual({c["cell"] for c in candidates},{(0,5),(1,5)})
                    source=next(c for c in candidates if c["cell"]==cell)
                    self.assertEqual(d.tooltip_recipe(frame,source["point"],scale),recipe)
            d=Detector();d.inventory_scale=scale
            _,candidates=d.blueprint_candidates(self.scan_frame("lower_spells",scale))
            self.assertFalse(candidates,"Finished Holy Heals must not nominate either of their two cells as blueprint cubes")

    def test_real_detector_hover_replay_selects_wp7_without_scrolling_past_it(self):
        # Only screenshots are replayed. No Windows input adapter is involved.
        for scale in (1,4/3,1.7):
            with self.subTest(scale=scale):
                frames={name:self.scan_frame(name,scale) for name in ("idle","wp7","hh")}
                d=Detector();d.inventory_scale=scale
                inventory,candidates=d.blueprint_candidates(frames["idle"])
                sources={tuple(c["point"]):"wp7" if c["cell"]==(0,5) else "hh" for c in candidates}
                class Replay:
                    position=None
                    def check_focus(self,size):pass
                    def capture(self):return frames[sources.get(tuple(self.position or []),"idle")]
                    def move(self,point):self.position=point
                    def scroll(self,notches):raise AssertionError("Visible verified WP7 was skipped")
                profile=default_profile();profile["operation"]="construction"
                profile["client_size"]=list(frames["idle"].shape[:2][::-1])
                profile["construction"]={"recipe":"weaponpart_7","available":55,"count":55}
                clock=FakeClock();replay=Replay()
                runner=ConstructionRunner(profile,replay,Control(),lambda *args:None,clock.clock,clock.sleep,detector=d)
                source,destination=runner.locate_blueprint()
                self.assertEqual(source,next(list(p) for p,name in sources.items() if name=="wp7"))
                processor=d.processor(frames["idle"])
                self.assertEqual(destination,d.input_point(processor,d.construction_input(frames["idle"],processor)))

    def test_scrollbar_position_on_recorded_inventory_at_different_scales(self):
        folder=Path(__file__).parent/"fixtures"
        for name in ("wp7","hh"):
            crop=cv2.cvtColor(cv2.imread(str(folder/f"construction_inventory_{name}.png")),cv2.COLOR_BGR2RGB)
            for scale in (1,4/3,1.7):
                with self.subTest(name=name,scale=scale):
                    image=cv2.resize(crop,None,fx=scale,fy=scale)
                    frame=np.zeros((900,1600,3),np.uint8)
                    frame[200:200+image.shape[0],300:300+image.shape[1]]=image
                    d=Detector();d.inventory_scale=scale
                    inventory=d.inventory(frame)
                    self.assertAlmostEqual(d.inventory_scroll_position(frame,inventory),20,delta=.7)
                    # Move just the recorded opaque thumb down the rail.
                    patch=d.region(frame,inventory,(415,66,423,333))
                    mask=(patch[:,:,1]>150)&(patch[:,:,1]>patch[:,:,0].astype(float)*1.4)
                    thumb=patch.copy()
                    patch[mask]=[25,70,40]
                    shift=round(160*scale)
                    patch[shift:][mask[:-shift]]=thumb[:-shift][mask[:-shift]]
                    self.assertAlmostEqual(d.inventory_scroll_position(frame,inventory),180,delta=1)
                    patch[:]=0
                    with self.assertRaisesRegex(Exception,"scrollbar"):
                        d.inventory_scroll_position(frame,inventory)

    def test_windows_wheel_event_encodes_negative_notch_without_sending_input(self):
        import os
        if os.name!="nt":
            self.skipTest("Windows input structures")
        from windows_backend import WindowsBackend
        backend=WindowsBackend()
        events=[]
        backend.send=events.append
        backend.scroll(-1)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0].mi.dwFlags,0x0800)
        self.assertEqual(events[0].mi.mouseData,(-120)&0xFFFFFFFF)

    def test_actual_movable_quantity_dialogs_require_exactly_one(self):
        folder=Path(__file__).parent/"fixtures"
        for name,one in (("wp7",True),("holy_heal",True),("twentyseven",False)):
            for scale in (1,4/3,1.7):
                with self.subTest(name=name,scale=scale):
                    crop=cv2.cvtColor(cv2.imread(str(folder/f"construction_quantity_{name}.png")),cv2.COLOR_BGR2RGB)
                    crop=cv2.resize(crop,None,fx=scale,fy=scale)
                    frame=np.zeros((900,1600,3),np.uint8)
                    frame[200:200+crop.shape[0],300:300+crop.shape[1]]=crop
                    d=Detector();d.last_scale=scale
                    dialog=d.quantity(frame)
                    self.assertIsNotNone(dialog)
                    self.assertEqual(dialog["one"],one)

    def test_actual_weaponpart_nine_tooltip_is_distinguished_from_seven(self):
        image=cv2.cvtColor(cv2.imread(str(Path(__file__).parent/"fixtures"/"construction_tooltip_wp9.png")),cv2.COLOR_BGR2RGB)
        for scale in (1,4/3,1.7):
            frame=np.zeros((900,1600,3),np.uint8)
            frame[400:427,500:880]=image
            frame=cv2.resize(frame,None,fx=scale,fy=scale)
            d=Detector()
            self.assertEqual(d.tooltip_recipe(frame,[round(696*scale),round(383*scale)],scale),"weaponpart_9")

    def test_recorded_ready_busy_and_done_after_moves_and_scaling(self):
        folder=Path(__file__).parent/"fixtures"
        for scale in (1,4/3,1.7):
            for name,recipe,busy,result in (("construction_ready","weaponpart_7",False,False),
                                          ("construction_wp7_busy","weaponpart_7",True,False),
                                          ("construction_wp7_done","weaponpart_7",False,True),
                                          ("construction_hh_busy","holy_heal",True,False),
                                          ("construction_hh_done","holy_heal",False,True)):
                with self.subTest(scale=scale,name=name):
                    crop=cv2.cvtColor(cv2.imread(str(folder/(name+".png"))),cv2.COLOR_BGR2RGB)
                    crop=cv2.resize(crop,None,fx=scale,fy=scale)
                    frame=np.zeros((1440,2560,3),np.uint8)
                    frame[600:600+crop.shape[0],900:900+crop.shape[1]]=crop
                    d=Detector();a=d.processor(frame)
                    self.assertEqual(d.construction_state(frame,a,recipe),{"busy":busy,"result":result})
                    if not busy:
                        self.assertEqual(d.construction_input(frame,a),2 if result else 1)
                        self.assertFalse(d.has_loaded_blueprint(frame,a))

    def test_recorded_inventory_and_blueprint_tooltips_identify_selected_recipes(self):
        folder=Path(__file__).parent/"fixtures"
        for name,recipe,cell in (("construction_inventory_wp7","weaponpart_7",(0,5)),
                                ("construction_inventory_hh","holy_heal",(1,5))):
            for scale in (1,4/3,1.7):
                with self.subTest(name=name,scale=scale):
                    crop=cv2.cvtColor(cv2.imread(str(folder/(name+".png"))),cv2.COLOR_BGR2RGB)
                    crop=cv2.resize(crop,None,fx=scale,fy=scale)
                    frame=np.zeros((1440,2560,3),np.uint8)
                    frame[100:100+crop.shape[0],200:200+crop.shape[1]]=crop
                    d=Detector();d.last_scale=scale
                    inventory,candidates=d.blueprint_candidates(frame)
                    candidate=next(c for c in candidates if c["cell"]==cell)
                    self.assertEqual(d.tooltip_recipe(frame,candidate["point"],scale),recipe)


class ConstructionConfigurationTests(unittest.TestCase):
    def test_profiles_save_and_validate_each_recipe_without_research_counts(self):
        for recipe in RECIPES:
            p=default_profile();p["operation"]="construction"
            p["construction"]={"recipe":recipe,"available":5,"count":0}
            validate_profile(p)
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/"profile.json";save_profile(path,p)
                self.assertEqual(load_profile(path),p)

    def test_invalid_blueprint_limits_and_recipe_are_rejected(self):
        for job in ({"recipe":"weaponpart_7","available":0,"count":0},
                    {"recipe":"weaponpart_9","available":2,"count":3},
                    {"recipe":"missing","available":2,"count":1},
                    {"recipe":"holy_heal","available":2,"count":-1}):
            p=default_profile();p["operation"]="construction";p["construction"]=job
            with self.assertRaises(ValueError):validate_profile(p)


if __name__=="__main__":
    unittest.main()
