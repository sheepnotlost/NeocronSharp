from pathlib import Path
import tempfile
import unittest

from macro_core import default_profile, save_profile, load_profile, validate_profile
from recipes import RECIPES, add_recipe, remove_recipe, catalog, find_recipe, identify_name


class SavedRecipeTests(unittest.TestCase):
    def test_remove_every_recipe_persists_and_restores_builtin_shorthand(self):
        profile=default_profile()
        for key in list(catalog(profile)):remove_recipe(profile,key)
        self.assertIsNone(profile["construction"]["recipe"])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"profile.json";save_profile(path,profile);profile=load_profile(path)
        self.assertEqual(catalog(profile),{})
        profile["operation"]="construction"
        with self.assertRaisesRegex(ValueError,"Choose or add"):validate_profile(profile)
        self.assertEqual(add_recipe(profile,"WP7"),"weaponpart_7")
        self.assertEqual(profile["construction"]["recipe"],"weaponpart_7")
        self.assertEqual(list(catalog(profile)),["weaponpart_7"])
        for hidden in (None,["invented"],["weaponpart_7","weaponpart_7"]):
            profile["hidden_recipes"]=hidden
            with self.assertRaises(ValueError):validate_profile(profile,require_ready=False)

    def test_custom_names_and_aliases_survive_profile_reload(self):
        profile=default_profile()
        key=add_recipe(profile,"Crahn Holy Lightning",["hl","holy lightning"])
        profile["construction"]["recipe"]=key
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"profile.json"
            save_profile(path,profile)
            loaded=load_profile(path)
        self.assertEqual(find_recipe("HL",catalog(loaded)),key)
        self.assertEqual(find_recipe("Crahn Holy Lightning",catalog(loaded)),key)
        self.assertIsNone(catalog(loaded)[key]["result_template"])

    def test_builtin_and_new_weaponpart_shorthand(self):
        profile=default_profile()
        self.assertEqual(add_recipe(profile,"WP7"),"weaponpart_7")
        key=add_recipe(profile,"WP13")
        self.assertEqual(identify_name("Tangent Weaoonoart 13",catalog(profile)),key)
        self.assertEqual(identify_name("Tangent Weaoonoart 7",catalog(profile)),"weaponpart_7")

    def test_different_numbers_are_never_fuzzy_matches(self):
        profile=default_profile();key=add_recipe(profile,"Custom Test Blaster 13")
        self.assertEqual(identify_name("Custom Test Blaster 13",catalog(profile)),key)
        self.assertNotEqual(identify_name("Custom Test Blaster 12",catalog(profile)),key)
        self.assertNotEqual(identify_name("Tangent Weaponpart 9",catalog(profile)),"weaponpart_7")

    def test_alias_collision_and_invalid_saved_names_are_rejected(self):
        profile=default_profile()
        with self.assertRaises(ValueError):add_recipe(profile,"Something Else",["wp7"])
        for entry in ({"name":"","aliases":[]},{"name":"Valid","aliases":"not a list"}):
            profile["custom_recipes"]={"custom_bad":entry}
            with self.assertRaises(ValueError):validate_profile(profile,require_ready=False)

    def test_short_initials_and_ocr_spelling_are_supported(self):
        profile=default_profile();key=add_recipe(profile,"HL")
        self.assertEqual(identify_name("Crahn Holy Lightning",catalog(profile)),key)
        self.assertEqual(identify_name("Tangent Weaoonoart 7",catalog(profile)),"weaponpart_7")
