"""What the job loop's clicks needed on this PC, learned as it runs and kept in job-aim.json (the user's ask, 5 Nov).

One entry per game client size: the R.N. window's scale, a shift for every click on it in its own 640x480 pixels, and a
nudge for the conversation's options as a share of the chat panel's height. A click the game did not take is tried again a
little to each side; the shift that worked is kept for next time. Never far: a shift past these limits would reach the next
button or line.
"""
import json
from pathlib import Path

AIM_FILE = Path(__file__).parent / "job-aim.json"
RN_MOST = (12, 4)            # R.N. pixels, across and down: its buttons are some 50 wide and 12 high, its rows 15 apart
CHAT_MOST = .012             # of the panel's height: its lines are .0355 apart
RN_TRIES = ((0, 0), (0, 0), (4, 0), (-4, 0), (0, 2), (0, -2), (8, 0), (-8, 0), (4, 2), (-4, -2))   # the usual place twice: a slow game is not a miss
CHAT_TRIES = (0, 0, .006, -.006, .012, -.012)


def size_key(frame):
    high, wide = frame.shape[:2]
    return f"{wide}x{high}"


def clamp(value, most):
    return max(-most, min(most, value))


class Aim:
    def __init__(self, path="saved"):
        path = AIM_FILE if path == "saved" else path
        self.path = Path(path) if path is not None else None      # None keeps it in memory only (the tests)
        self.sizes = {}
        if self.path is not None:
            try:
                self.sizes = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.sizes = {}

    def entry(self, frame):
        return self.sizes.setdefault(size_key(frame), {"rn_scale": None, "rn": [0, 0], "chat": 0.})

    def known(self, frame):
        return size_key(frame) in self.sizes

    def rn(self, frame):
        return tuple(self.entry(frame)["rn"])

    def chat(self, frame):
        return float(self.entry(frame)["chat"])

    def learn_rn(self, frame, shift):
        entry = self.entry(frame)
        entry["rn"] = [clamp(entry["rn"][0]+shift[0], RN_MOST[0]), clamp(entry["rn"][1]+shift[1], RN_MOST[1])]
        self.save()
        return tuple(entry["rn"])

    def learn_chat(self, frame, nudge):
        entry = self.entry(frame)
        entry["chat"] = round(clamp(entry["chat"]+nudge, CHAT_MOST), 4)
        self.save()
        return entry["chat"]

    def learn_scale(self, frame, scale):
        entry = self.entry(frame)
        if entry.get("rn_scale") != scale:
            entry["rn_scale"] = scale
            self.save()

    def save(self):
        if self.path is None:
            return
        try:
            self.path.write_text(json.dumps(self.sizes, indent=2), encoding="utf-8")
        except OSError:
            pass

    def describe(self, frame):
        if not self.known(frame):
            return f"New screen size {size_key(frame)}: it measures the terminal window and its clicks as it goes, and keeps what works."
        entry = self.entry(frame)
        scale = f"terminal window at {entry['rn_scale']:g} times 640x480" if entry.get("rn_scale") else "terminal window not measured yet"
        return (f"Saved aim for {size_key(frame)}: {scale}, terminal clicks shifted {entry['rn'][0]:+d},{entry['rn'][1]:+d}, "
                f"chat clicks nudged {entry['chat']:+.3f} of the panel.")
