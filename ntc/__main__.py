"""Entry point.  python -m ntc [app | scan [all|cabinet|inventory] [all|techs] | windows [screenshot.png] | capture]"""
import sys
import time
from pathlib import Path

from . import winapi


def cmd_capture():
    """Ctrl+Alt+S saves a full-screen PNG to tests/fixtures, Ctrl+Alt+Q quits."""
    import cv2
    from .capture import grab

    out = Path("tests/fixtures")
    out.mkdir(parents=True, exist_ok=True)
    quit_flag = []

    def save():
        img = grab()
        name = out / f"shot_{time.strftime('%Y%m%d_%H%M%S')}.png"
        cv2.imwrite(str(name), img)
        print(f"saved {name} {img.shape[1]}x{img.shape[0]}")

    listener = winapi.HotkeyListener({1: ("ctrl+alt+s", save), 2: ("ctrl+alt+q", lambda: quit_flag.append(1))})
    listener.start()
    print("Capture mode: Ctrl+Alt+S = save screenshot, Ctrl+Alt+Q = quit")
    while not quit_flag:
        time.sleep(0.2)
    listener.stop()


def cmd_windows():
    """Show which item windows are detected in a screenshot (or on screen right now)."""
    import cv2
    from . import detect
    from .capture import grab

    img = cv2.imread(sys.argv[2]) if len(sys.argv) > 2 else grab()
    for w in detect.find_windows(img):
        print(f"{w.kind:9s} at ({w.x0:.0f},{w.y0:.0f}) {w.cols}x{w.rows} slots, pitch {w.qx:.1f}x{w.qy:.1f}, "
              f"confidence {w.consistency:.2f}")


def cmd_scan():
    """Headless live scan: 3 s countdown (switch to the game), then print what was found."""
    from . import config, names
    from .scanner import Scanner

    cfg = config.load()
    target = sys.argv[2] if len(sys.argv) > 2 else cfg["scan_target"]
    print(f"Scanning ({target}) in 3s - make sure the window is open in the game...")
    time.sleep(3)
    items = sys.argv[3] if len(sys.argv) > 3 else cfg["log_items"]
    for result in Scanner(cfg, names.Names()).scan(target, lambda msg: print("  " + msg, end="\r"), items=items):
        print(f"\n=== {result.kind} ===")
        for n, q in result.totals.items():
            print(f"{q:4d}  {n}")
        print(f"TOTAL {sum(result.totals.values())} items in {len(result.cells)} slots, {result.duration_s}s")
        for wmsg in result.warnings:
            print("WARNING:", wmsg)
        for c in result.cells:
            if c.flags and "NEW_NAME" not in c.flags:
                print(f"  row {c.row + 1} col {c.col + 1} {c.flags} raw={c.raw_ocr!r}")


def main():
    winapi.set_dpi_aware()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "app"
    if cmd == "app":
        from .app import main as app_main
        return app_main()
    cmds = {"capture": cmd_capture, "scan": cmd_scan, "windows": cmd_windows}
    if cmd not in cmds:
        sys.exit(__doc__)
    cmds[cmd]()


if __name__ == "__main__":
    main()
