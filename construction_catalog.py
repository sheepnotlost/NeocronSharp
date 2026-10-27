"""Offline construction item browser, separate from active recipe recognition."""
import json
from pathlib import Path


def load_construction_catalog():
    data=json.loads((Path(__file__).parent/"data/construction_catalog.json").read_text(encoding="utf8"))
    ids=set()
    for row in data["recipes"]:
        if row["id"] in ids or not row["name"] or row["method"] not in ("verified_example","check_blueprint","rare_parts","recycling_only"):
            raise ValueError("Invalid construction catalog.")
        ids.add(row["id"])
    return data


def filter_construction(rows,query="",category="All"):
    # WP shorthand is useful in both saved recipes and the item browser.
    import re
    query=re.sub(r"\bwp\s*(\d+)\b",r"weaponpart \1",query.casefold()).strip()
    return [r for r in rows if (category=="All" or r["category"]==category) and
            (not query or query in (r["name"]+" "+" ".join(r.get("ingredients") or ())).casefold())]
