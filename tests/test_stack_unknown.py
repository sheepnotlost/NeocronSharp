"""No stack size is asked for: a batch runs until the blueprints are gone."""
import unittest

import test_construction as fixtures
from construction_runner import ConstructionRunner
from macro_core import Interrupted


class StackUnknownTests(fixtures.ConstructionRunnerTests):
    def test_batch_ends_cleanly_when_the_blueprints_run_out(self):
        self.setup_run("weaponpart_9",available=3)
        self.profile["construction"]["available"]=10000   # what the UI now saves
        self.runner=ConstructionRunner(self.profile,self.backend,self.control,
                                       lambda k,v:self.events.append((k,v)),
                                       self.clock.clock,self.clock.sleep,detector=fixtures.ConstructionDetector())
        original=self.runner.locate_blueprint
        calls={"n":0}
        def locate():
            calls["n"]+=1
            if calls["n"]>3:raise Interrupted("No verified Tangent Weaponpart 9 blueprint found in the remaining Inventory rows.")
            return original()
        self.runner.locate_blueprint=locate
        self.runner.run()
        self.assertFalse(self.errors(),self.events)
        self.assertEqual(self.runner.completed,3)
        done=[v for k,v in self.events if k=="done"]
        self.assertTrue(done and "Out of" in done[-1],done)

    def test_a_search_failure_before_any_build_is_still_an_error(self):
        self.setup_run("weaponpart_9",available=3)
        self.profile["construction"]["available"]=10000
        self.runner=ConstructionRunner(self.profile,self.backend,self.control,
                                       lambda k,v:self.events.append((k,v)),
                                       self.clock.clock,self.clock.sleep,detector=fixtures.ConstructionDetector())
        def locate():raise Interrupted("No verified Tangent Weaponpart 9 blueprint found in the remaining Inventory rows.")
        self.runner.locate_blueprint=locate
        self.runner.run()
        self.assertTrue(self.errors())


for inherited in [n for n in dir(fixtures.ConstructionRunnerTests) if n.startswith("test_") and n not in ("test_batch_ends_cleanly_when_the_blueprints_run_out","test_a_search_failure_before_any_build_is_still_an_error")]:
    setattr(StackUnknownTests,inherited,None)


if __name__=="__main__":
    unittest.main()
