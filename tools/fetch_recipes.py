"""Fill data/construction_catalog.json with each item's Parts from Tech Haven's Items DB.

Developer tool; the app itself never goes online. Run with the bundled Python:
    runtime\\python.exe tools\\fetch_recipes.py [--limit N]

Pages are cached under analysis/techhaven-cache (git-ignored), so an interrupted run
resumes without re-downloading. Requests are spaced out to stay polite to the site.
"""

import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "construction_catalog.json"
CACHE = ROOT / "analysis" / "techhaven-cache"
DELAY = 0.6
AGENT = "Mozilla/5.0 (neocron-macro-suite catalog builder; personal use)"


def fetch(url, name):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    time.sleep(DELAY)
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8", "replace")
    path.write_text(text, encoding="utf-8")
    return text


def clean(name):
    """Row names can carry the status marker ("Crahn Fire Halo !"); drop it."""
    return re.sub(r"\s*!.*$", "", html.unescape(name).strip())


def listing_slugs(page):
    """{item name: slug} for every row of a category listing."""
    result = {}
    for row in re.split(r"<tr", page):
        link = re.search(r'show-item/([a-z0-9\-_.]+)"', row)
        name = re.search(r'<td class="name">\s*([^<]+?)\s*(?:<|$)', row)
        if link and name:
            result[clean(name.group(1))] = link.group(1)
    return result


def item_parts(page):
    """[(quantity, name)] from the item's Parts block."""
    block = page.split("Parts:", 1)
    if len(block) < 2:
        return []
    block = block[1].split("</tr>", 1)[0]
    parts = []
    for text in re.findall(r'<div class="item-part">.*?<a [^>]*>\s*([^<]+?)\s*</a>', block, re.S):
        match = re.fullmatch(r"(\d+)\s*x\s+(.+)", html.unescape(text).strip())
        if match:
            parts.append((int(match.group(1)), match.group(2).strip()))
    return parts


def main(limit=None):
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    rows = data["recipes"]
    slugs = {}
    for url in sorted({row["source_url"] for row in rows}):
        try:
            slugs[url] = listing_slugs(fetch(url, re.sub(r"\W+", "_", url) + ".html"))
        except Exception as exc:  # noqa: BLE001 - report and continue with other categories
            print("category failed:", url, exc, flush=True)
            slugs[url] = {}
    done = missing = 0
    for index, row in enumerate(rows):
        if limit and index >= limit:
            break
        row["name"] = clean(row["name"])
        slug = slugs.get(row["source_url"], {}).get(row["name"])
        if not slug:
            missing += 1
            continue
        try:
            parts = item_parts(fetch(f"https://db.techhaven.org/en/show-item/{slug}", slug + ".html"))
        except Exception as exc:  # noqa: BLE001
            print("item failed:", row["name"], exc, flush=True)
            continue
        if parts:
            row["parts"] = [{"quantity": q, "name": n} for q, n in parts]
            row["ingredients"] = [f"{q} x {n}" for q, n in parts]
            row["item_url"] = f"https://db.techhaven.org/en/show-item/{slug}"
            done += 1
        if index % 50 == 0:
            print(f"{index}/{len(rows)} items, {done} with parts", flush=True)
    data["parts_retrieved"] = time.strftime("%Y-%m-%d")
    CATALOG.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"done: {done} items with parts, {missing} not matched to a listing row", flush=True)


if __name__ == "__main__":
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    main(limit)
