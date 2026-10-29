import unittest

from macro_core import default_profile, validate_profile


class NavRayProfileTests(unittest.TestCase):
    def test_default_profile_and_validation(self):
        profile = default_profile()
        self.assertEqual(profile["navray"], {"destination": ""})
        profile["operation"] = "navray"
        with self.assertRaises(ValueError):
            validate_profile(profile)                      # needs Category > Destination
        profile["navray"]["destination"] = "Faction HQs > Black Dragon"
        validate_profile(profile)
        profile["navray"]["destination"] = ""
        profile["navray"]["scan"] = True                   # reading the lists needs no destination
        validate_profile(profile)
        profile["navray"]["scan"] = False
        profile["navray"]["destination"] = "x" * 200 + " > y"
        with self.assertRaises(ValueError):
            validate_profile(profile)


if __name__ == "__main__":
    unittest.main()
