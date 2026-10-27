"""A live Weaponpart 9 tooltip lost its final digit to the right-edge trim."""
import unittest
from pathlib import Path

import cv2

from recipes import catalog
from vision import Detector


class TooltipDigitTests(unittest.TestCase):
    def test_live_weaponpart_9_tooltip_keeps_its_number(self):
        # Crop of a real 2560x1440 capture (Inventory scale 4/3); the cursor
        # sat on the blueprint at (900,120) inside this crop. This replays a
        # recorded frame, not a live game run.
        frame=cv2.imread(str(Path(__file__).parent/"fixtures"/"live_wp9_tooltip_2560.png"))
        detector=Detector();detector.recipes=catalog({})
        self.assertEqual(detector.tooltip_recipe(frame,(900,120),4/3),"weaponpart_9")

    def test_part_number_is_still_exact(self):
        frame=cv2.imread(str(Path(__file__).parent/"fixtures"/"live_wp9_tooltip_2560.png"))
        detector=Detector();recipes=catalog({});recipes.pop("weaponpart_9");detector.recipes=recipes
        self.assertNotEqual(detector.tooltip_recipe(frame,(900,120),4/3),"weaponpart_7")


def synthetic_tooltip(detector):
    # Real prefix pixels plus a bordered panel; read_text is stubbed per test
    # so the decision logic is exercised deterministically (replay, not live).
    import numpy as np
    label=np.zeros((17,650),np.uint8)
    label[1:16,1:79]=detector.templates["tooltip_prefix"]
    cv2.rectangle(label,(0,0),(649,16),220,1)
    frame=np.zeros((900,1600,3),np.uint8);frame[400:417,500:1150]=cv2.cvtColor(label,cv2.COLOR_GRAY2RGB)
    return frame


class TemplateNeverDecidesNumberTests(unittest.TestCase):
    def read(self,text,template,recipes=None):
        detector=Detector();detector.recipes=recipes or catalog({})
        detector.read_text=lambda gray:text
        detector.known_tooltip_recipe=lambda *args:template
        return detector.tooltip_recipe(synthetic_tooltip(detector),[700,380],1)

    def test_wp9_template_cannot_accept_a_read_weaponpart_3(self):
        for digit in ("3","1","0","19","91"):
            result=self.read(f"BLUEPRINT- 30 TB Capacity: Tangent Weaponpart {digit}","weaponpart_9")
            self.assertNotIn(result,("weaponpart_9","weaponpart_7"),digit)

    def test_digit_verified_template_rescues_an_unread_number(self):
        # Recorded WP7 tooltips at 4/3 sometimes OCR without their "7"; the
        # template (whose final digit is checked separately) supplies it.
        self.assertEqual(self.read("BLUEPRINT- 30 TB Capacity: Tangent Weaponpart","weaponpart_9"),"weaponpart_9")

    def test_template_rescues_garbled_words_when_number_agrees(self):
        self.assertEqual(self.read("BLUEPRINT- 30 TB Capacity: Tqnqxnt Wxqqqnqart 9","weaponpart_9"),"weaponpart_9")



def wp9_fixture_with_digit(glyph):
    """Recorded WP9 tooltip with its final 9 replaced by the same tooltip's own
    '3' or '0' glyph (from "30 TB"), or blanked. Replay data, not live."""
    import numpy as np
    image=cv2.cvtColor(cv2.imread(str(Path(__file__).parent/"fixtures"/"construction_tooltip_wp9.png")),cv2.COLOR_BGR2RGB)
    if glyph!="9":
        background=image[12,120].copy();image[5:21,365:374]=background
        columns={"3":(96,104),"0":(104,113)}.get(glyph)
        if columns:image[5:21,366:366+columns[1]-columns[0]]=image[5:21,columns[0]:columns[1]]
    return image


class DigitVerifiedTemplateTests(unittest.TestCase):
    def read(self,glyph,scale,text=None,recipes=None):
        import numpy as np
        frame=np.zeros((900,1600,3),np.uint8);frame[400:427,500:880]=wp9_fixture_with_digit(glyph)
        frame=cv2.resize(frame,None,fx=scale,fy=scale)
        detector=Detector();detector.recipes=recipes or catalog({})
        if text is not None:detector.read_text=lambda gray:text
        return detector.tooltip_recipe(frame,[round(696*scale),round(383*scale)],scale)

    def test_template_alone_accepts_only_its_own_digit(self):
        unread="BLUEPRINT- 30 TB Capacity: Tangent Weaponpart"
        for scale in (1,4/3,1.7):
            self.assertEqual(self.read("9",scale,unread),"weaponpart_9",scale)
            for glyph in ("3","0","blank"):
                self.assertNotIn(self.read(glyph,scale,unread),("weaponpart_9","weaponpart_7"),(glyph,scale))

    def test_custom_numbered_weaponpart_is_not_vetoed_by_shipped_templates(self):
        from macro_core import default_profile
        from recipes import add_recipe
        profile=default_profile();key=add_recipe(profile,"Tangent Weaponpart 3")
        for scale in (1,4/3):
            self.assertEqual(self.read("3",scale,"BLUEPRINT- 30 TB Capacity: Tangent Weaponpart 3",catalog(profile)),key,scale)


class ShorthandUpdateTests(unittest.TestCase):
    def test_update_by_alias_keeps_full_item_name(self):
        from macro_core import default_profile
        from recipes import add_recipe,identify_name
        profile=default_profile()
        key=add_recipe(profile,"Tangent Armorpart 1",["ap1"])
        self.assertEqual(add_recipe(profile,"ap1",[]),key)
        entry=catalog(profile)[key]
        self.assertEqual(entry["name"],"Tangent Armorpart 1");self.assertIn("ap1",entry["aliases"])
        self.assertEqual(identify_name("Tangent Armorpart 1",catalog(profile)),key)


if __name__=="__main__":
    unittest.main()
