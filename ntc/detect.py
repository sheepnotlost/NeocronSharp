"""Find item windows (cabinet, inventory) on screen with no calibration and for any HUD color (SPEC 14).

A window is a mesh of thin dark grid lines at a fixed pitch. Line contrast differs a lot between HUD themes
(about 5 gray levels in the darkest one), so nothing here thresholds a single pixel:
 1. a soft "dark thin line" evidence map is built for both directions,
 2. every position is scored by how much evidence lines up on a lattice of the right pitch (the background has
    plenty of lines, but not on every line of a regular lattice),
 3. the best few lattices are fitted to sub-pixel accuracy, aligned to the window's known size, and scored by how
    consistently ALL their lines show evidence. Clutter has a few strong lines and gaps; a window has no gaps.
"""
from dataclasses import dataclass

import cv2
import numpy as np

# pitch = slot width/height including the grid line at 1440p; core = smallest lattice (cols, rows) that must be
# present; extent = (columns, rows) of the visible grid. These windows have a fixed size, and the contrast at the
# outermost slots is too faint in dim themes to grow the grid by thresholding, so only its alignment is chosen.
FAMILIES = {
    "cabinet": dict(pitch=(144.2, 72), core=(5, 10), extent=(5, 10)),
    "inventory": dict(pitch=(70, 72), core=(8, 6), extent=(8, 6)),
}
MIN_RATIO = 1.3          # mesh peak vs the 99.9th percentile of the score map (a weak first filter)
MIN_CONSISTENCY = 0.5    # weakest-quartile interior line evidence / median (real windows >= 0.58, clutter <= 0.43)
CANDIDATES = 6
PITCH_SLACK = 0.4        # the pitch is a fixed UI constant; a fitted one may differ from nominal by at most this


@dataclass
class Window:
    kind: str
    x0: float            # grid top-left corner (screen px)
    y0: float
    qx: float            # slot width / height including the grid line
    qy: float
    cols: int
    rows: int
    score: float = 0.0           # mesh peak ratio
    consistency: float = 0.0
    quality: float = 0.0

    def slot_rect(self, r, c):
        return (int(round(self.x0 + c * self.qx)), int(round(self.y0 + r * self.qy)),
                int(round(self.qx)), int(round(self.qy)))

    @property
    def bounds(self):
        return (int(round(self.x0)), int(round(self.y0)),
                int(round(self.cols * self.qx)), int(round(self.rows * self.qy)))


def _gray(img):
    """Luminance with local contrast equalised, so dark HUD themes (navy: lines only ~5 gray levels deep) are as
    readable as bright ones."""
    g8 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.createCLAHE(clipLimit=3.0, tileGridSize=(16, 16)).apply(g8).astype(np.float32)


def _evidence(g, off):
    """Soft evidence of a thin dark line: (horizontal-line map, vertical-line map), relative to local brightness."""
    base = cv2.GaussianBlur(g, (0, 0), 6) + 6
    eh = np.maximum((np.roll(g, off, 0) + np.roll(g, -off, 0)) / 2 - g, 0) / base
    ev = np.maximum((np.roll(g, off, 1) + np.roll(g, -off, 1)) / 2 - g, 0) / base
    return eh, ev


def _wide_evidence(g):
    """Evidence of dark bands up to ~8 px thick, centred on the band (the thin-line map locks onto band edges)."""
    base = cv2.GaussianBlur(g, (0, 0), 9)
    e = np.maximum(base - g, 0) / (base + 6)
    return e, e


def _mesh_score(eh, ev, q, p, C, R):
    H, W = eh.shape
    cs_h = np.cumsum(np.pad(eh, ((0, 0), (1, 0))), axis=1)
    cs_v = np.cumsum(np.pad(ev, ((1, 0), (0, 0))), axis=0)
    Wd, Hd = C * q, R * p
    ny, nx = H - Hd, W - Wd
    if ny <= 0 or nx <= 0:
        return np.zeros((1, 1), np.float32)
    hmean = (cs_h[:, Wd:Wd + nx] - cs_h[:, :nx]) / Wd
    vmean = (cs_v[Hd:Hd + ny, :] - cs_v[:ny, :]) / Hd
    hl = [hmean[j * p:j * p + ny] for j in range(R + 1)]
    vl = [vmean[:, i * q:i * q + nx] for i in range(C + 1)]
    # min of neighbouring lines: a lattice that fits only every other line (e.g. a 72px lattice laid over a
    # 144px window) scores zero; a real window has evidence on all of its lines
    s_h = sum(np.minimum(hl[j], hl[j + 1]) for j in range(R)) / R
    s_v = sum(np.minimum(vl[i], vl[i + 1]) for i in range(C)) / C
    return np.minimum(s_h, s_v)


def _fit_lines(profile, origin, pitch, n_lines, nominal, reach=5):
    """Locate n_lines evenly spaced lines near origin + i*pitch. The pitch stays within PITCH_SLACK of nominal and
    the offset is a median over the lines, so one noisy line cannot pull the fit."""
    pos = []
    for i in range(n_lines):
        e = origin + i * pitch
        lo, hi = int(round(e)) - reach, int(round(e)) + reach + 1
        if lo < 1 or hi > len(profile) - 1:
            continue
        j = lo + int(np.argmax(profile[lo:hi]))
        w = profile[j - 1:j + 2]                              # centroid of the peak: sub-pixel
        c = j + (float(w[2] - w[0]) / float(w.sum()) if w.sum() > 1e-9 else 0.0)
        pos.append((i, c))
    if len(pos) < 3:
        return origin, pitch
    idx = np.array([p[0] for p in pos], float)
    xs = np.array([p[1] for p in pos], float)
    a = float(np.clip(np.polyfit(idx, xs, 1)[0], nominal - PITCH_SLACK, nominal + PITCH_SLACK))
    return float(np.median(xs - idx * a)), a


def _contrast(profile, line_pos, half):
    """Line evidence minus the evidence half a slot away, per line. Scales with the theme's contrast."""
    def val(x):
        lo, hi = max(int(round(x)) - 3, 0), min(int(round(x)) + 4, len(profile))
        return float(profile[lo:hi].max()) if hi > lo else 0.0
    return np.array([val(x) - val(x + half) for x in line_pos])


def _robust_total(c):
    """Sum of line evidence with each line capped at 1.5x the median, so a few strong clutter lines cannot
    outweigh a lattice whose lines are all present (even if faint)."""
    c = np.clip(c, 0, None)
    return float(np.minimum(c, 1.5 * np.median(c)).sum())


def _refine(win, eh_f, ev_f, ew, extent, nominal):
    """Fit the core lattice, align the full extent to the evidence, and score it. Returns the window or None."""
    x0, y0, qx, qy, C, R = win.x0, win.y0, win.qx, win.qy, win.cols, win.rows
    H, W = eh_f.shape
    for _ in range(2):
        ys0, ys1 = int(max(y0, 0)), int(min(y0 + R * qy, H))
        xs0, xs1 = int(max(x0, 0)), int(min(x0 + C * qx, W))
        x0, qx = _fit_lines(ev_f[ys0:ys1, :].mean(axis=0), x0, qx, C + 1, nominal[0])
        y0, qy = _fit_lines(eh_f[:, xs0:xs1].mean(axis=1), y0, qy, R + 1, nominal[1])

    Ce, Re = extent
    best = None
    for a_ in range(-1, Ce - C + 2):                  # where the core lattice sits inside the full extent
        for b_ in range(-1, Re - R + 2):
            X0, Y0 = x0 - a_ * qx, y0 - b_ * qy
            if X0 < 0 or Y0 < 0 or X0 + Ce * qx > W or Y0 + Re * qy > H:
                continue
            rows_y = [Y0 + j * qy for j in range(Re + 1)]
            cols_x = [X0 + i * qx for i in range(Ce + 1)]
            sh = _contrast(ew[:, int(X0):int(X0 + Ce * qx)].mean(axis=1), rows_y, qy / 2)
            sv = _contrast(ew[int(Y0):int(Y0 + Re * qy), :].mean(axis=0), cols_x, qx / 2)
            # ALL lines count: a lattice shifted by one row has as many real interior lines, but its extra
            # outer line falls on empty space, so only the true alignment has evidence on both outer lines
            total = _robust_total(sh) + _robust_total(sv)
            if best is None or total > best[0]:
                best = (total, X0, Y0, sh, sv)
    if best is None:
        return None
    total, X0, Y0, sh, sv = best
    # final alignment: slide the whole lattice a few px so its interior lines sit on the centre of the dark bands
    def sample(profile, pos):
        return float(np.interp(pos, np.arange(len(profile)), profile))
    ph = ew[:, int(X0):int(X0 + Ce * qx)].mean(axis=1)
    pv = ew[int(Y0):int(Y0 + Re * qy), :].mean(axis=0)
    ds = np.arange(-4, 4.01, 0.5)
    X0 += float(ds[int(np.argmax([sum(sample(pv, X0 + d + i * qx) for i in range(1, Ce)) for d in ds]))])
    Y0 += float(ds[int(np.argmax([sum(sample(ph, Y0 + d + j * qy) for j in range(1, Re)) for d in ds]))])
    cons = []
    for line in (sh[1:-1], sv[1:-1]):
        med = float(np.median(line))
        cons.append(float(np.percentile(line, 25)) / med if med > 1e-6 else 0.0)
    win.x0, win.y0, win.qx, win.qy, win.cols, win.rows = X0, Y0, qx, qy, Ce, Re
    win.consistency, win.quality = min(cons), total
    return win


def _overlap(a, b):
    ax, ay, aw, ah = a.bounds
    bx, by, bw, bh = b.bounds
    ix, iy = max(0, min(ax + aw, bx + bw) - max(ax, bx)), max(0, min(ay + ah, by + bh) - max(ay, by))
    return ix * iy > 0.3 * min(aw * ah, bw * bh)


def find_windows(img, families=None, min_ratio=MIN_RATIO, min_consistency=MIN_CONSISTENCY):
    """Return the item windows found in a screenshot, best first. Scales with the screen height (1440p = 1.0)."""
    families = families or FAMILIES
    scale = img.shape[0] / 1440.0
    g = _gray(img)
    gs = cv2.resize(g, (g.shape[1] // 2, g.shape[0] // 2), interpolation=cv2.INTER_AREA)
    eh2, ev2 = _evidence(gs, 2)
    b = cv2.GaussianBlur(gs, (0, 0), 4.5)
    w2 = np.maximum(b - gs, 0) / (b + 6)                 # wide dark bands (thick borders)
    eh_f, ev_f = _evidence(g, 3)
    ew = _wide_evidence(g)[0]
    candidates = []
    for kind, fam in families.items():
        nominal = (fam["pitch"][0] * scale, fam["pitch"][1] * scale)
        q0, p0 = nominal[0] / 2, nominal[1] / 2
        C, R = fam["core"]
        q, p = int(round(q0)), int(round(p0))
        St, Sw = _mesh_score(eh2, ev2, q, p, C, R), _mesh_score(w2, w2, q, p, C, R)
        # each map is normalised by its own robust scale, then added: thin lines suit bright themes, wide
        # bands suit the others; together the true window ranks at or near the top in every theme
        S = St / max(float(np.percentile(St, 99.9)), 1e-6) + Sw / max(float(np.percentile(Sw, 99.9)), 1e-6)
        med, p999 = float(np.median(S)), float(np.percentile(S, 99.9))
        S = S.copy()
        for _ in range(CANDIDATES):
            y, x = np.unravel_index(int(np.argmax(S)), S.shape)
            ratio = (float(S[y, x]) - med) / max(p999 - med, 1e-6)
            S[max(y - p, 0):y + p + 1, max(x - q // 2, 0):x + q // 2 + 1] = 0     # next candidate must be elsewhere
            if ratio < min_ratio:
                break
            win = _refine(Window(kind, x * 2.0, y * 2.0, q * 2.0, p * 2.0, C, R, ratio), eh_f, ev_f, ew,
                          fam["extent"], nominal)
            if win is not None and win.consistency >= min_consistency:
                candidates.append(win)
    candidates.sort(key=lambda w: -w.quality)
    kept = []
    for w in candidates:
        if not any(_overlap(w, k) for k in kept) and sum(k.kind == w.kind for k in kept) < 2:
            kept.append(w)
    return kept
