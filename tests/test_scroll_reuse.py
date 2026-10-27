"""Reused Inventory anchors must not turn a small window drift into a false bottom."""
from pathlib import Path
import unittest

import cv2
import numpy as np

from construction_runner import ConstructionRunner
from vision import Detector


class ThumbFallbackBaselineTests(unittest.TestCase):
    def test_thumb_nudge_after_small_drift_still_scrolls(self):
        # Recorded Inventory frame; the wheel is ignored and each thumb drag
        # moves the thumb by one pixel. The window drifts 0-3 px after the
        # anchor was cached, which the cheap header check tolerates. Replay
        # with a fake backend; no desktop input.
        detector=Detector()
        image=cv2.imread(str(Path(__file__).parent/"fixtures"/"construction_search_2013.png"))
        known=detector.inventory(image)

        class IgnoredWheel:
            def __init__(self,frame,dy):self.base=frame;self.dy=dy;self.moved=0
            def capture(self):
                frame=self.base.copy()
                if self.moved:
                    x0=known.x+413;y0=known.y+self.dy+60;y1=known.y+self.dy+340
                    strip=self.base[y0:y1,x0:x0+12].copy()
                    frame[y0+self.moved:y1,x0:x0+12]=strip[:y1-y0-self.moved]
                return frame
            def scroll(self,notches):pass
            def move(self,point):pass
            def button(self,button,down):
                if not down:self.moved+=1

        for dy in (0,1,2,3):
            with self.subTest(drift=dy):
                runner=ConstructionRunner.__new__(ConstructionRunner)
                runner.detector=detector;runner.backend=IgnoredWheel(np.roll(image,dy,axis=0),dy)
                runner.name="Tangent Weaponpart 7";runner.last_frame=None
                runner.guard=lambda:None;runner.wait=lambda seconds:None;runner.move=lambda point:None
                current=runner.scroll_inventory_down(known)
                self.assertEqual(current.y,known.y+dy)
                self.assertEqual(runner.backend.moved,1)


if __name__=="__main__":
    unittest.main()
