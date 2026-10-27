"""Windowed 1920x1080 frames: heading fonts and window layouts need not share one scale."""
from pathlib import Path
import unittest

import cv2

from vision import Detector


class WindowedSplitScaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Crop of a real windowed 1080p capture (26-27 Oct). Replay only; the
        # live behaviour at this size beyond Processor/Inventory is unverified.
        image=cv2.imread(str(Path(__file__).parent/"fixtures"/"windowed_1080_split_scale.png"))
        cls.frame=cv2.cvtColor(image,cv2.COLOR_BGR2RGB)

    def test_processor_layout_and_start_are_found_at_a_non_reference_scale(self):
        detector=Detector();anchor=detector.processor(self.frame)
        self.assertAlmostEqual(anchor.scale,.80,delta=.03)
        self.assertGreater(anchor.heading,anchor.scale)
        self.assertIsNotNone(anchor.start)
        self.assertTrue(detector.construction_tool(self.frame,anchor))
        self.assertEqual(detector.input_cube_kind(self.frame[anchor.point(49+53.5-20,88-20)[1]:anchor.point(49+53.5+20,88+20)[1],
                                                           anchor.point(49+53.5-20,88-20)[0]:anchor.point(49+53.5+20,88+20)[0]],
                                                  anchor.scale),"empty_datacube")

    def test_inventory_grid_is_fitted_from_its_cells(self):
        detector=Detector();inventory=detector.inventory(self.frame)
        self.assertAlmostEqual(inventory.scale,.78,delta=.02)
        self.assertEqual(detector.current_inventory(self.frame,inventory),inventory)
        self.assertAlmostEqual(detector.inventory_scroll_position(self.frame,inventory),15.4,delta=1.5)
        _,candidates=detector.fast_blueprint_candidates(self.frame)
        self.assertEqual(sorted(c["cell"] for c in candidates),[(0,5),(0,6)])

    def test_inventory_hover_points_land_inside_their_cells(self):
        detector=Detector();_,cells=detector.inventory_cells(self.frame)
        inventory=detector.inventory(self.frame)
        for cell in cells:
            x,y=cell["point"]
            row,col=cell["cell"]
            left,top=inventory.point(39+col*44.6,63+row*45.5);right,bottom=inventory.point(39+(col+1)*44.6,63+(row+1)*45.5)
            self.assertTrue(left<x<right and top<y<bottom,cell)

    def test_cube_colours_classify_at_any_icon_scale(self):
        root=Path(__file__).resolve().parent.parent/"assets"
        for name in ("empty_datacube","loaded_blueprint_red","loaded_blueprint_green"):
            image=cv2.cvtColor(cv2.imread(str(root/(name+".png"))),cv2.COLOR_BGR2RGB)
            for scale in (.75,.8,1,4/3):
                resized=cv2.resize(image,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
                self.assertEqual(Detector.cube_kind_by_color(resized),name,(name,scale))


class WindowedTooltipTests(unittest.TestCase):
    def test_real_windowed_blueprint_tooltip_is_read_at_its_own_text_scale(self):
        # Crop of the user's live windowed capture: layout .79, tooltip text .80,
        # where the shipped prefix only correlates ~.60. Replay, not a live run.
        from recipes import catalog
        image=cv2.imread(str(Path(__file__).parent/"fixtures"/"windowed_1080_tooltip_wp9.png"))
        frame=cv2.cvtColor(image,cv2.COLOR_BGR2RGB)
        detector=Detector();detector.recipes=catalog({})
        self.assertEqual(detector.tooltip_recipe(frame,[337,82],.788),"weaponpart_9")
        wp7_only=catalog({});wp7_only.pop("weaponpart_9")
        other=Detector();other.recipes=wp7_only
        self.assertNotIn(other.tooltip_recipe(frame,[337,82],.788),("weaponpart_9","weaponpart_7"))

    def test_non_blueprint_text_is_not_accepted_as_a_blueprint_line(self):
        import numpy as np
        frame=np.zeros((300,900,3),np.uint8)
        cv2.rectangle(frame,(300,100),(700,118),(200,200,200),1)
        cv2.putText(frame,"Metal D  weight 0.1",(306,114),cv2.FONT_HERSHEY_SIMPLEX,.4,(220,220,220),1,cv2.LINE_AA)
        detector=Detector()
        self.assertNotIn(detector.tooltip_recipe(frame,[330,140],.8),("weaponpart_9","weaponpart_7","holy_heal"))


class LiveHoverFrameTests(unittest.TestCase):
    def test_tooltip_is_read_from_a_real_backend_capture_with_the_ui_scales_known(self):
        # Backend capture of the hovered cell (not a screenshot): with the heading
        # ratio known (as after Processor detection) the box test used to fail at
        # a finer text scale and the tooltip returned None. Replay, not live.
        from recipes import catalog
        frame=cv2.cvtColor(cv2.imread(str(Path(__file__).parent/"fixtures"/"windowed_1080_live_hover_wp9.png")),cv2.COLOR_BGR2RGB)
        detector=Detector();detector.recipes=catalog({});detector.heading_ratio=1.135
        for scale in (.786,.8):
            self.assertEqual(detector.tooltip_recipe(frame,[338,81],scale),"weaponpart_9",scale)


class WindowedQuantityDialogTests(unittest.TestCase):
    def test_dialog_found_at_its_own_scale_when_the_processor_scale_differs(self):
        # Real windowed capture: Processor layout .80, dialog .77 and already
        # showing 1. Replay, not a live run. Only a call that expects a dialog
        # pays for the dense search; later calls reuse the found scale.
        frame=cv2.cvtColor(cv2.imread(str(Path(__file__).parent/"fixtures"/"windowed_1080_quantity_dialog.png")),cv2.COLOR_BGR2RGB)
        detector=Detector();detector.last_scale=.804;detector.heading_ratio=1.135
        self.assertIsNone(detector.quantity(frame))
        dialog=detector.quantity(frame,expected=True)
        self.assertTrue(dialog["one"])
        self.assertAlmostEqual(detector.quantity_scale,.77,delta=.02)
        self.assertEqual(detector.quantity(frame)["ok"],dialog["ok"])
        # An empty frame never produces a dialog, even with the scale remembered.
        import numpy as np
        self.assertIsNone(detector.quantity(np.zeros_like(frame)))


class UniformIntermediateScaleTests(unittest.TestCase):
    def test_processor_is_found_at_scales_between_the_reference_values(self):
        folder=Path(__file__).parent/"fixtures"
        crop=cv2.cvtColor(cv2.imread(str(folder/"construction_ready.png")),cv2.COLOR_BGR2RGB)
        for scale in (.9,1.1,1.4,1.6):
            with self.subTest(scale=scale):
                resized=cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_LINEAR)
                import numpy as np
                frame=np.zeros((1080,1920,3),np.uint8);frame[300:300+resized.shape[0],400:400+resized.shape[1]]=resized
                anchor=Detector().processor(frame)
                self.assertAlmostEqual(anchor.scale,scale,delta=.04)

    def test_dialog_tooltip_and_processor_states_at_intermediate_scales(self):
        # Recorded 1x fixtures resized to scales the reference list never had.
        # With the Processor's scale known (as in a real run) the quantity dialog,
        # its exact-one flag, the WP9 tooltip and ready/busy/done states all hold.
        import numpy as np
        from recipes import catalog
        folder=Path(__file__).parent/"fixtures"
        load=lambda name:cv2.cvtColor(cv2.imread(str(folder/name)),cv2.COLOR_BGR2RGB)
        resize=lambda image,s:cv2.resize(image,None,fx=s,fy=s,interpolation=cv2.INTER_AREA if s<1 else cv2.INTER_LINEAR)
        for scale in (.8,.9,1.1,1.2,1.4,1.6,1.8):
            with self.subTest(scale=scale):
                for name,one in (("construction_quantity_wp7.png",True),("construction_quantity_twentyseven.png",False)):
                    crop=resize(load(name),scale);frame=np.zeros((1080,1920,3),np.uint8)
                    frame[300:300+crop.shape[0],400:400+crop.shape[1]]=crop
                    detector=Detector();detector.last_scale=scale
                    self.assertEqual(detector.quantity(frame)["one"],one,name)
                tip=resize(load("construction_tooltip_wp9.png"),scale);frame=np.zeros((1080,1920,3),np.uint8)
                frame[400:400+tip.shape[0],500:500+tip.shape[1]]=tip
                detector=Detector();detector.recipes=catalog({})
                self.assertEqual(detector.tooltip_recipe(frame,[500+int(196*scale),400-int(17*scale)],scale),"weaponpart_9")
                for name,expected in (("construction_ready.png",(False,False)),("construction_wp7_busy.png",(True,False)),
                                      ("construction_wp7_done.png",(False,True))):
                    crop=resize(load(name),scale);frame=np.zeros((1080,1920,3),np.uint8)
                    frame[300:300+crop.shape[0],400:400+crop.shape[1]]=crop
                    detector=Detector();detector.recipes=catalog({});anchor=detector.processor(frame)
                    state=detector.construction_state(frame,anchor,"weaponpart_7")
                    self.assertEqual((state["busy"],state["result"]),expected,name)


if __name__=="__main__":
    unittest.main()
