"""Recycling item pictures: Tech Haven page parsing, the on-disk cache, and the Tk hand-off. No network."""

import io
import json
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from PIL import Image

import item_images
import app as app_module
from item_images import ItemImages, NotFound, PictureLoader, fit, key, parse_index, parse_item_page, slug

FIXTURES = Path(__file__).parent / "fixtures"
LIST = item_images.LIST_URL


def fixture(name):
    return (FIXTURES / ("item_images_" + name + ".html")).read_text(encoding="utf8")


def png(size=(32, 32), colour=(200, 40, 40, 255)):
    out = io.BytesIO()
    Image.new("RGBA", size, colour).save(out, "PNG")
    return out.getvalue()


class FakeFetcher:
    """Serves saved pages and pictures by URL; records every request and the thread it ran on."""
    def __init__(self, pages=None, fail=()):
        self.pages = dict(pages or {})
        self.fail = set(fail)
        self.calls = []
        self.threads = []

    def __call__(self, url, limit):
        self.calls.append(url)
        self.threads.append(threading.current_thread())
        if url in self.fail:
            raise OSError("timed out")
        if url not in self.pages:
            raise NotFound(url)
        data = self.pages[url]
        return data.encode("utf8") if isinstance(data, str) else data


RIFLE = {"id": "recycle_rifle", "name": "Lazar Rifle", "source_url": LIST}
BONE = {"id": "recycle_bone", "name": "Cryton's Restored Head Bone", "source_url": LIST}
ANTIDOTE = {"id": "legacy_antidote", "name": "Antidote", "source_url": "https://neocron.fandom.com/wiki/Recycling_Recipes"}
RIFLE_PNG = "https://cdn.techhaven.org/items-db/assets/item-images/8f8656-street-mode-rifle.png?d3e857"
BONE_PNG = "https://cdn.techhaven.org/items-db/assets/item-images/b5d52d-advanced-headbone.png?d3e857"
ANTIDOTE_PNG = "https://cdn.techhaven.org/items-db/assets/item-images/69703e-green-drugs.png?d3e857"


def site(**extra):
    pages = {LIST: fixture("recyclable_list"),
             "https://db.techhaven.org/en/item/lazar-rifle": fixture("lazar_rifle"),
             "https://db.techhaven.org/en/item/crytons-restored-head-bone": fixture("crytons_head_bone"),
             "https://db.techhaven.org/en/item/antidote": fixture("antidote"),
             RIFLE_PNG: png((128, 64)), BONE_PNG: png(), ANTIDOTE_PNG: png()}
    pages.update(extra)
    return pages


class ParsingTests(unittest.TestCase):
    def test_item_picture_is_the_idb_item_image_not_og_image_or_recycle_parts(self):
        self.assertEqual(parse_item_page(fixture("lazar_rifle")), ("Lazar Rifle", RIFLE_PNG))
        self.assertEqual(parse_item_page(fixture("crytons_head_bone")), ("Cryton's Restored Head Bone", BONE_PNG))
        self.assertEqual(parse_item_page(fixture("antidote")), ("Antidote", ANTIDOTE_PNG))

    def test_page_without_item_picture_or_with_foreign_host_gives_none(self):
        self.assertEqual(parse_item_page("<h1>404 - Not Found</h1>"), (None, None))
        foreign = '<h1 class="thn-item">X</h1><span class="idb-item-image"><img src="https://evil.example/x.png"/></span>'
        self.assertEqual(parse_item_page(foreign), ("X", None))
        relative = '<span class="idb-item-image"><img src="/items-db/a.png"/></span>'
        self.assertEqual(parse_item_page(relative)[1], "https://db.techhaven.org/items-db/a.png")

    def test_recyclable_list_maps_names_to_item_pages(self):
        index = parse_index(fixture("recyclable_list"))
        self.assertEqual(index[key("Lazar Rifle")], "https://db.techhaven.org/en/item/lazar-rifle")
        # The "!" status marker after a name is not part of it; duplicates keep Tech Haven's own slug.
        self.assertEqual(index[key("Tangent Armorpart 5")], "https://db.techhaven.org/en/item/tangent-armorpart-5")
        self.assertEqual(index[key("Recycled Special Alloy Knife")],
                         "https://db.techhaven.org/en/item/recycled-special-alloy-knife-1")
        self.assertEqual(index[key("Beggar Electroshocker")], "https://db.techhaven.org/en/item/beggar-electro-shocker")

    def test_slug_matches_tech_haven(self):
        self.assertEqual(slug("Cryton's Restored Head Bone"), "crytons-restored-head-bone")
        self.assertEqual(slug("Viper King Vest"), "viper-king-vest")

    def test_fit_keeps_aspect_and_scales_small_icons_by_whole_pixels(self):
        self.assertEqual(fit(Image.new("RGBA", (32, 32))).size, (128, 128))
        self.assertEqual(fit(Image.new("RGBA", (64, 64))).size, (128, 128))
        self.assertEqual(fit(Image.new("RGBA", (128, 64))).size, (128, 64))
        self.assertEqual(fit(Image.new("RGBA", (400, 200))).size, (128, 64))
        tiny = Image.new("RGBA", (2, 1), (0, 0, 0, 255)); tiny.putpixel((1, 0), (255, 255, 255, 255))
        big = fit(tiny)
        self.assertEqual({c for _, c in big.getcolors()}, {(0, 0, 0, 255), (255, 255, 255, 255)})  # nearest-neighbour: no blur


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name) / "item-images"
        self.now = [1_000_000.0]

    def tearDown(self):
        self.temp.cleanup()

    def images(self, fetcher):
        return ItemImages(self.folder, fetcher, clock=lambda: self.now[0], sleep=lambda s: None)

    def test_miss_downloads_once_then_disk_hit_needs_no_network(self):
        fetcher = FakeFetcher(site())
        state, image = self.images(fetcher).lookup(RIFLE)
        self.assertEqual((state, image.size), ("ok", (128, 64)))
        self.assertEqual(fetcher.calls, [LIST, "https://db.techhaven.org/en/item/lazar-rifle", RIFLE_PNG])
        self.assertTrue((self.folder / "recycle_rifle.png").exists())
        self.assertTrue((self.folder / "index.json").exists())
        again = FakeFetcher({})
        fresh = self.images(again)  # a new session reads the disk cache
        self.assertEqual(fresh.lookup(RIFLE)[0], "ok")
        self.assertEqual(again.calls, [])

    def test_index_is_reused_for_other_recipes(self):
        fetcher = FakeFetcher(site())
        images = self.images(fetcher)
        images.lookup(RIFLE); images.lookup(BONE)
        self.assertEqual(fetcher.calls.count(LIST), 1)

    def test_community_entry_uses_the_item_page_for_its_name(self):
        fetcher = FakeFetcher(site())
        self.assertEqual(self.images(fetcher).lookup(ANTIDOTE)[0], "ok")
        self.assertIn("https://db.techhaven.org/en/item/antidote", fetcher.calls)

    def test_missing_picture_is_cached_for_a_day(self):
        fetcher = FakeFetcher(site())
        nothing = {"id": "legacy_x", "name": "Delicious crab soup", "source_url": ANTIDOTE["source_url"]}
        self.assertEqual(self.images(fetcher).lookup(nothing), ("missing", None))
        marker = json.loads((self.folder / "legacy_x.none").read_text(encoding="utf8"))
        self.assertEqual(marker["reason"], "missing")
        calls = len(fetcher.calls)
        self.now[0] += 23 * 3600
        self.assertEqual(self.images(fetcher).lookup(nothing), ("missing", None))
        self.assertEqual(len(fetcher.calls), calls)  # still remembered: no request
        self.now[0] += 2 * 3600
        self.images(fetcher).lookup(nothing)
        self.assertGreater(len(fetcher.calls), calls)  # expired: asked again

    def test_failed_fetch_is_cached_then_retried_and_recovers(self):
        broken = FakeFetcher(site(), fail={"https://db.techhaven.org/en/item/lazar-rifle"})
        self.assertEqual(self.images(broken).lookup(RIFLE), ("failed", None))
        self.assertEqual(self.images(broken).lookup(RIFLE), ("failed", None))
        self.assertEqual(broken.calls.count("https://db.techhaven.org/en/item/lazar-rifle"), 1)
        self.now[0] += item_images.FAILED_TTL + 1
        working = FakeFetcher(site())
        self.assertEqual(self.images(working).lookup(RIFLE)[0], "ok")
        self.assertFalse((self.folder / "recycle_rifle.none").exists())

    def test_wrong_page_for_a_guessed_name_is_not_used(self):
        other = {"id": "legacy_vest", "name": "Viper King Vest", "source_url": ANTIDOTE["source_url"]}
        fetcher = FakeFetcher(site(**{"https://db.techhaven.org/en/item/viper-king-vest": fixture("antidote")}))
        self.assertEqual(self.images(fetcher).lookup(other), ("missing", None))

    def test_bad_image_data_is_a_failure_not_a_crash(self):
        fetcher = FakeFetcher(site(**{RIFLE_PNG: b"<html>oops</html>"}))
        self.assertEqual(self.images(fetcher).lookup(RIFLE), ("failed", None))
        self.assertFalse((self.folder / "recycle_rifle.png").exists())

    def test_requests_are_spaced_out(self):
        waits = []
        images = ItemImages(self.folder, FakeFetcher(site()), clock=lambda: self.now[0], sleep=waits.append)
        images.lookup(RIFLE)
        self.assertEqual(len(waits), 2)
        self.assertTrue(all(0 < w <= item_images.MIN_GAP for w in waits))


class LoaderTests(unittest.TestCase):
    def test_worker_serves_only_the_latest_request(self):
        release = threading.Event()
        seen = []
        class Slow:
            _memory = {}
            def cached(self, recipe): return ("ok", None)
            def lookup(self, recipe):
                release.wait(5); seen.append(recipe["id"]); return "ok", None
        reports = []
        done = threading.Event()
        loader = PictureLoader(Slow(), lambda rid, state, image: (reports.append((rid, state)), done.set() if rid == "c" else None))
        loader.request({"id": "a"}); time.sleep(.05)
        loader.request({"id": "b"}); loader.request({"id": "c"})
        release.set()
        self.assertTrue(done.wait(5))
        self.assertEqual(seen, ["a", "c"])


class NoInput:
    def release_all(self):
        pass


class AppPictureTests(unittest.TestCase):
    def setUp(self):
        from app import App
        self.temp = tempfile.TemporaryDirectory()
        self.release = threading.Event()
        pages = site()
        self.fetcher = FakeFetcher(pages)
        outer = self
        class Blocking(FakeFetcher):
            def __call__(self, url, limit):
                outer.release.wait(5)
                return outer.fetcher(url, limit)
        self.images = ItemImages(Path(self.temp.name) / "item-images", Blocking(), sleep=lambda s: None)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root, Path(self.temp.name) / "profile.json", NoInput(), item_images=self.images)

    def tearDown(self):
        self.release.set()
        self.app.close()
        self.temp.cleanup()

    def pump(self, until, seconds=5):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            if until():
                return True
            time.sleep(.01)
        return False

    def select(self, name):
        app = self.app
        rid = next(r["id"] for r in app.recycle_data["recipes"] if r["name"] == name)
        app.recycle_tree.selection_set(rid)
        return rid

    def test_selecting_never_fetches_on_the_tk_thread_and_the_picture_arrives(self):
        app = self.app
        with patch.object(type(app), "pictures_visible", return_value=True):
            app.tabs.select(app.recycling_tab)
            started = time.perf_counter()
            self.select("Lazar Rifle"); self.root.update()
            self.assertLess(time.perf_counter() - started, 1.0)  # the fetcher is still blocked; Tk was not
            self.assertTrue(self.pump(lambda: app.picture_label.cget("text") == app_module.PICTURE_TEXT["loading"]))
            self.release.set()
            self.assertTrue(self.pump(lambda: app._picture_shown is not None))
        self.assertEqual(app._picture_shown[1].size, (128, 64))
        self.assertTrue(self.fetcher.threads)
        self.assertNotIn(threading.main_thread(), self.fetcher.threads)
        self.assertTrue(str(app.picture_label.cget("image")))

    def test_hidden_window_or_other_tab_does_not_look_pictures_up(self):
        app = self.app
        app.tabs.select(app.recycling_tab)
        self.select("Lazar Rifle")
        self.release.set()
        self.pump(lambda: False, .4)
        self.assertEqual(self.fetcher.calls, [])  # withdrawn window: nobody can see it
        with patch.object(type(app), "pictures_visible", return_value=False):
            self.select("Mendicant Rifle")
            self.pump(lambda: False, .4)
        self.assertEqual(self.fetcher.calls, [])

    def test_missing_picture_says_so_and_all_skins_restyle_the_slot(self):
        from appearance import SKINS
        app = self.app
        rid = self.select("Lazar Rifle")
        app.show_item_picture(rid, "missing", None)
        self.assertEqual(app.picture_label.cget("text"), app_module.PICTURE_TEXT["missing"])
        app.show_item_picture(rid, "ok", Image.new("RGBA", (32, 32), (10, 20, 30, 0)))
        with patch("app.save_profile"):
            for skin in SKINS.values():
                app.skin_var.set(skin["name"]); app.save_preferences()
                style = ttk.Style(self.root)
                self.assertEqual(style.lookup("Picture.TLabel", "background"), skin["input"])
                self.assertEqual(style.lookup("Picture.TFrame", "background"), skin["edge"])
                self.assertIsNotNone(app._picture_photo)
        app.show_item_picture("someone_else", "missing", None)  # stale result for another recipe is ignored
        self.assertIsNotNone(app._picture_shown)


if __name__ == "__main__":
    unittest.main()
