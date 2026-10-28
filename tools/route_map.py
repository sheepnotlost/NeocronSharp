"""Print the areas learned from walked Nav-Ray routes (routes.json): which areas lead to which."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import routes  # noqa: E402

book = routes.RouteBook()
areas = book.areas()
if not areas:
    print("No routes recorded yet. Walk a Nav-Ray route first.")
for area, info in areas.items():
    print(f"{area}: {info['routes']} routes, reaches {', '.join(info['leads_to']) or 'nothing recorded'}")
for key, entry in book.data["routes"].items():
    print(f"  {key}: {entry['walks']} walks, best {entry['seconds']}s, ends in {entry.get('end')}")
