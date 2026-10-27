import json
from pathlib import Path

import sys

FROZEN = getattr(sys, "frozen", False)                 # running as the packaged .exe
# ROOT: where the user's own files live (config, lists, known items, exports): next to the .exe, or the project folder.
# RES: read-only files bundled with the program (assets, data).
SUITE_ROOT = Path(__file__).resolve().parent.parent
ROOT = SUITE_ROOT / "tech-counter"
RES = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"

# Seeded from the measured layout of the cabinet window at 2560x1440 (see SPEC section 4).
DEFAULTS = {
    "game_window_title_contains": "Neocron Evolution",   # NOT just "Neocron": that also matches this app's own window
    "tesseract_path": r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    "hotkey_scan": "ctrl+alt+s",
    "hotkey_abort": "ctrl+alt+x",
    "log_items": "all",                   # "all" = every item | "techs" = only "<Part> Part Of <weapon>" items
    "scan_target": "all",                  # "all" | "cabinet" | "inventory"
    "mouse_mode": "absolute",
    "scroll_notches": 2,                  # mouse-wheel notches per scroll step (2 rows each)
    "scroll_settle_ms": 200,
    "scroll_park_ms": 150,
    "max_scroll_frames": 60,
    "tooltip_probe_ms": 500,              # how long to wait for a tooltip on a weak (probably empty) candidate
    "hover_settle_ms": 30,
    "tooltip_timeout_ms": 1500,
    "tooltip_stable_frames": 2,
}


def load(path=CONFIG_PATH):
    cfg = dict(DEFAULTS)
    if path.exists():
        stored = json.loads(path.read_text(encoding="utf-8"))
        cfg.update({k: v for k, v in stored.items() if k in DEFAULTS})
    return cfg


def save(cfg, path=CONFIG_PATH):
    """Write only the values that differ from DEFAULTS, so improved defaults reach existing installs."""
    diff = {k: v for k, v in cfg.items() if k in DEFAULTS and v != DEFAULTS[k]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(diff, indent=2), encoding="utf-8")


def path(cfg, key):
    return ROOT / cfg[key]
