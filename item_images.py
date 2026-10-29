"""Item pictures for the Recycling tab, looked up on Tech Haven's Items DB and cached on disk.

The pictures are game artwork, so they live in the git-ignored ``item-images/`` folder and are
never part of the repository. Lookups are polite: one request at a time on a single worker
thread, only for the recipe the user is looking at, and a missing picture or a failed fetch is
remembered for a while so it is not fetched again on every click.

Cache layout (keyed by recipe id):
    item-images/<recipe id>.png    the picture, as Tech Haven serves it
    item-images/<recipe id>.none   no picture (JSON: reason, time); retried after it expires
    item-images/index.json         Tech Haven recyclable list: item name -> item page URL
"""

import difflib
import html
import io
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "item-images"
USER_AGENT = "NeocronSharp/1.0 (desktop helper; item picture lookup, one request per click)"
TIMEOUT = 8
SITE = "https://db.techhaven.org"
LIST_URL = SITE + "/en/item-lists/recyclable"
ITEM_URL = SITE + "/en/item/"
IMAGE_HOSTS = ("cdn.techhaven.org", "db.techhaven.org")
MISSING_TTL = 24 * 3600   # Tech Haven has no picture for the item.
FAILED_TTL = 3600         # Tech Haven did not answer; try again sooner.
INDEX_TTL = 7 * 24 * 3600
MAX_PAGE = 2_000_000
MAX_IMAGE = 1_000_000
MIN_GAP = 0.5             # seconds between two requests to Tech Haven
FIT = 128                 # longest side of the shown picture


class NotFound(Exception):
    """The page or picture does not exist (HTTP 404/410)."""


def fetch(url, limit=MAX_PAGE):
    """GET ``url`` with an honest User-Agent; returns bytes. Raises NotFound or OSError."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 410):
            raise NotFound(url) from exc
        raise
    if len(data) > limit:
        raise OSError("response too large: " + url)
    return data


def key(name):
    """Compare names by letters and digits only ("Cryton's" == "Crytons", "Electro Shocker" == "Electroshocker")."""
    return re.sub(r"[^a-z0-9]+", "", html.unescape(name).casefold())


def slug(name):
    """Tech Haven's item-page slug for a name: apostrophes dropped, other runs of symbols become '-'."""
    name = re.sub(r"['’]", "", html.unescape(name).casefold())
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-")


def parse_index(page):
    """Recyclable item list -> {name key: item page URL}."""
    index = {}
    for url, cell in re.findall(r'<tr data-url="([^"]+)".*?<td class="name">([^<]*)', page, re.S):
        name = html.unescape(cell).strip()
        item = url.replace("/show-item/", "/item/")
        if name and item.startswith(ITEM_URL):
            index.setdefault(key(name), item)
    return index


def parse_item_page(page, base=SITE):
    """Item page -> (item name or None, picture URL or None).

    The item's own picture is the <img> inside ``<span class="idb-item-image">`` next to the
    ``<h1 class="thn-item">`` title. og:image is a site-wide placeholder and the other images on
    the page are recycle parts, so neither is used.
    """
    title = re.search(r'<h1 class="thn-item">([^<]*)</h1>', page)
    name = html.unescape(title.group(1)).strip() if title else None
    image = re.search(r'<span class="idb-item-image">\s*<img\b[^>]*?\bsrc="([^"]+)"', page)
    if image is None:
        return name, None
    url = urllib.parse.urljoin(base, html.unescape(image.group(1)))
    host = urllib.parse.urlsplit(url)
    if host.scheme != "https" or host.hostname not in IMAGE_HOSTS:
        return name, None
    return name, url


def fit(image, size=FIT):
    """Scale to fit ``size`` keeping the aspect ratio: small icons grow by a whole factor with
    nearest-neighbour (crisp pixels), large pictures shrink smoothly. Returns RGBA."""
    from PIL import Image
    image = image.convert("RGBA")
    w, h = image.size
    if max(w, h) > size:
        scale = size / max(w, h)
        return image.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    factor = max(1, size // max(w, h))
    return image.resize((w * factor, h * factor), Image.NEAREST) if factor > 1 else image


class ItemImages:
    """Find, download and cache item pictures. ``lookup`` blocks; call it from the worker only."""

    def __init__(self, folder=CACHE_DIR, fetcher=fetch, clock=time.time, sleep=time.sleep):
        self.folder = Path(folder)
        self.fetcher = fetcher
        self.clock = clock
        self.sleep = sleep
        self._index = None
        self._last_request = None
        self._memory = {}

    # -- cache -------------------------------------------------------------------------------
    def _path(self, recipe_id, suffix):
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", recipe_id)
        return self.folder / (safe + suffix)

    def cached(self, recipe):
        """Return ('ok', path), ('missing'|'failed', None) for a fresh negative entry, or None."""
        picture = self._path(recipe["id"], ".png")
        if picture.exists():
            return "ok", picture
        marker = self._path(recipe["id"], ".none")
        try:
            note = json.loads(marker.read_text(encoding="utf8"))
            ttl = FAILED_TTL if note.get("reason") == "failed" else MISSING_TTL
            if self.clock() - float(note["time"]) < ttl:
                return note.get("reason", "missing"), None
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def _remember_none(self, recipe, reason):
        self.folder.mkdir(parents=True, exist_ok=True)
        self._path(recipe["id"], ".none").write_text(
            json.dumps({"reason": reason, "time": self.clock(), "name": recipe["name"]}), encoding="utf8")

    # -- network -----------------------------------------------------------------------------
    def _get(self, url, limit=MAX_PAGE):
        if self._last_request is not None:
            wait = MIN_GAP - (self.clock() - self._last_request)
            if wait > 0:
                self.sleep(wait)
        try:
            return self.fetcher(url, limit)
        finally:
            self._last_request = self.clock()

    def index(self):
        """Tech Haven's recyclable list as {name key: item URL}; fetched at most once a week."""
        if self._index is not None:
            return self._index
        path = self.folder / "index.json"
        try:
            saved = json.loads(path.read_text(encoding="utf8"))
            if self.clock() - float(saved["time"]) < INDEX_TTL and saved["items"]:
                self._index = saved["items"]
                return self._index
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self._index = parse_index(self._get(LIST_URL).decode("utf8", "replace"))
        self.folder.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"time": self.clock(), "source": LIST_URL, "items": self._index}), encoding="utf8")
        return self._index

    def item_url(self, recipe):
        """Tech Haven item page for a recipe and whether its title must be checked against the name."""
        source = recipe.get("source_url") or ""
        if source.startswith(ITEM_URL):
            return source, False
        from_tech_haven = source.startswith(SITE)
        name = key(recipe["name"])
        try:
            index = self.index()
        except NotFound:
            index = {}
        if name in index:
            return index[name], False
        if from_tech_haven:  # Small spelling differences ("Metallplate"/"Metalplate") in sourced entries only.
            close = difflib.get_close_matches(name, list(index), n=1, cutoff=0.9)
            if close:
                return index[close[0]], False
        return ITEM_URL + slug(recipe["name"]), True

    def lookup(self, recipe):
        """Blocking: ('ok', PIL image) or ('missing'|'failed', None). Network only on a cache miss."""
        if recipe["id"] in self._memory:
            return self._memory[recipe["id"]]
        hit = self.cached(recipe)
        if hit is None:
            hit = self._download(recipe)
        if hit[0] == "ok":
            from PIL import Image
            try:
                with Image.open(hit[1]) as image:
                    result = ("ok", fit(image))
            except OSError:
                hit[1].unlink(missing_ok=True)
                return "failed", None
        else:
            result = hit
        if result[0] != "failed":
            self._memory[recipe["id"]] = result
        return result

    def _download(self, recipe):
        from PIL import Image
        try:
            page_url, check_name = self.item_url(recipe)
            name, image_url = parse_item_page(self._get(page_url).decode("utf8", "replace"), page_url)
            if image_url is None or (check_name and key(name or "") != key(recipe["name"])):
                self._remember_none(recipe, "missing")
                return "missing", None
            data = self._get(image_url, MAX_IMAGE)
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                picture = image.copy()
        except NotFound:
            self._remember_none(recipe, "missing")
            return "missing", None
        except (OSError, ValueError):  # URLError/timeouts are OSErrors; bad image data is OSError/ValueError.
            self._remember_none(recipe, "failed")
            return "failed", None
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self._path(recipe["id"], ".png")
        partial = path.with_suffix(".part")
        picture.save(partial, "PNG")
        partial.replace(path)
        self._path(recipe["id"], ".none").unlink(missing_ok=True)
        return "ok", path


class PictureLoader:
    """One daemon worker that serves the latest request only (rapid clicks skip stale ones).

    ``report(recipe_id, state, image)`` is called on the worker thread with state 'loading'
    (a network fetch starts), 'ok', 'missing' or 'failed'; hand it to Tk through a queue.
    """

    def __init__(self, images, report):
        self.images = images
        self.report = report
        self._pending = None
        self._wake = threading.Condition()
        self._thread = None

    def request(self, recipe):
        with self._wake:
            self._pending = recipe
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="item-pictures", daemon=True)
                self._thread.start()
            self._wake.notify()

    def _run(self):
        while True:
            with self._wake:
                while self._pending is None:
                    self._wake.wait()
                recipe, self._pending = self._pending, None
            try:
                if recipe["id"] not in self.images._memory and self.images.cached(recipe) is None:
                    self.report(recipe["id"], "loading", None)
                state, image = self.images.lookup(recipe)
            except Exception:  # A picture must never take the app down.
                state, image = "failed", None
            self.report(recipe["id"], state, image)
