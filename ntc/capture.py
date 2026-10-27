"""Full-screen capture via mss -> numpy BGR."""
import mss
import numpy as np

_MSS = getattr(mss, "MSS", None) or mss.mss      # mss.mss is deprecated and will be removed


def grab(monitor_index=1):
    with _MSS() as sct:
        shot = sct.grab(sct.monitors[monitor_index])
        return np.ascontiguousarray(np.array(shot)[:, :, :3])  # BGRA -> BGR


def grab_region(x, y, w, h, monitor_index=1):
    """Grab a screen region (physical px, relative to the monitor) -> numpy BGR."""
    with _MSS() as sct:
        mon = sct.monitors[monitor_index]
        shot = sct.grab({"left": mon["left"] + x, "top": mon["top"] + y, "width": w, "height": h})
        return np.ascontiguousarray(np.array(shot)[:, :, :3])
