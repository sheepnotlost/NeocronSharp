"""Locate Neocron controls in fresh RGB screenshots using shipped UI artwork."""

from dataclasses import dataclass
import math
import re
from pathlib import Path
import sys
from recipes import RECIPES, identify_name, normalized, item_name_score

ROOT = Path(__file__).resolve().parent
if Path(sys.executable).resolve().parent != (ROOT / "runtime").resolve() and (ROOT / ".deps").is_dir():
    sys.path.insert(0, str(ROOT / ".deps"))
try:
    import cv2
    import numpy as np
except ImportError as exc:
    raise RuntimeError("Bundled visual dependencies could not be loaded. Use Launch.cmd and keep the complete runtime folder.") from exc


class NotFound(RuntimeError):
    pass


class Ambiguous(RuntimeError):
    pass


@dataclass(frozen=True)
class Anchor:
    x: int
    y: int
    scale: float
    score: float
    start: tuple | None = None
    # Windows are laid out at `scale`, but heading fonts snap to whole pixel
    # sizes and can render larger (live 1080p windowed: layout .80, titles .91).
    heading: float | None = None

    def point(self, x, y):
        # Half-up rounding keeps translated grid cells the same pixel size.
        # Python's round-to-even changes a 45.5px cell with its screen position.
        return [math.floor(self.x + x * self.scale + 0.5),
                math.floor(self.y + y * self.scale + 0.5)]

    def start_point(self):
        return list(self.start) if self.start is not None else self.point(421, 174)


class Detector:
    def __init__(self):
        self.templates = {}
        for name in ("processor", "processor_title", "inventory", "inventory_title", "inventory_max_load", "inventory_free_load",
                     "quantity", "quantity_title", "quantity_half", "start", "start_busy", "progress_percent", "blueprint_cube",
                     "constructed_weaponpart", "constructed_holy_heal", "construction_tool", "empty_datacube",
                     "loaded_blueprint_red", "loaded_blueprint_green", "tooltip_prefix",
                     "tooltip_weaponpart_7", "tooltip_weaponpart_9", "tooltip_holy_heal"):
            data = cv2.imread(str(ROOT / "assets" / f"{name}.png"), cv2.IMREAD_GRAYSCALE)
            if data is None:
                raise RuntimeError(f"Missing visual template: {name}.")
            self.templates[name] = data
        self.labels = {}
        self.gray_labels = {}
        for name in "TEAL":
            data = cv2.imread(str(ROOT / "assets" / f"label_{name}.png"), cv2.IMREAD_GRAYSCALE)
            if data is None:
                raise RuntimeError(f"Missing stack-label template: {name}.")
            self.labels[name] = self.normalize_glyph(data > 127)
            gray = cv2.imread(str(ROOT / "assets" / f"glyph_{name}.png"), cv2.IMREAD_GRAYSCALE)
            if gray is None:
                raise RuntimeError(f"Missing grayscale stack-label template: {name}.")
            self.gray_labels[name] = gray.astype(np.float32)
        self.last_scale = None
        self.inventory_scale = None
        self.heading_ratio = None
        self.quantity_scale = None
        self.quantity_misses = 0
        self.tooltip_text_scale = None
        self.last_tooltip_raw = ""
        self.last_start_score = 0.
        self.recipes=RECIPES
        self.reader=None
        self.last_tooltip_text=""
        self.ocr_cache={}
        self.scaled = {}
        one = cv2.imread(str(ROOT / "assets" / "quantity_one.png"), cv2.IMREAD_GRAYSCALE)
        if one is None:
            raise RuntimeError("Missing quantity-one reference.")
        self.quantity_one = self.normalize_glyph(one > 127)

    @staticmethod
    def gray(frame):
        return cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

    # The game's UI scale is a free setting and windowed clients have any size,
    # so the rendered scale is not limited to the seven reference values. Text
    # peaks are narrow (about 3% off drops a match from .87 to .59), hence 2% steps.
    DENSE_SCALES = tuple(round(.6*1.02**i, 3) for i in range(0, 65) if .6*1.02**i <= 2.2)

    def dense_scales(self, first=()):
        hints = [s for s in first if s]
        return list(dict.fromkeys(hints + list(self.DENSE_SCALES)))

    def template(self, name, scale):
        key = (name, scale)
        if key not in self.scaled:
            src = self.templates[name]
            self.scaled[key] = cv2.resize(src, None, fx=scale, fy=scale,
                                           interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        return self.scaled[key]

    def matching_template(self, name, scale, dx=0, dy=0, blur=0):
        key = (name, scale, dx, dy, blur)
        if key not in self.scaled:
            src = self.template(name, scale)
            if dx or dy:
                src = cv2.resize(src, (src.shape[1]+dx, src.shape[0]+dy), interpolation=cv2.INTER_LINEAR)
            self.scaled[key] = cv2.GaussianBlur(src, (0, 0), blur) if blur else src
        return self.scaled[key]

    def locate(self, frame, name, scales=None, threshold=0.86, checkpoint=lambda: None, verify=None,
               blur=0, variants=((0, 0),)):
        gray = self.gray(frame)
        if blur:
            gray = cv2.GaussianBlur(gray, (0, 0), blur)
        candidates = []
        if scales is None:
            scales = [self.last_scale] if self.last_scale else [1.0, 0.75, 1.25, 4/3, 1.5, 1.7, 2.0]
        for scale in scales:
            for dx, dy in variants:
                checkpoint()
                tpl = self.matching_template(name, scale, dx, dy, blur)
                h, w = tpl.shape
                if gray.shape[0] < h or gray.shape[1] < w:
                    continue
                scores = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
                for _ in range(4 if verify is not None else 2):
                    _, score, _, (x, y) = cv2.minMaxLoc(scores)
                    if score < threshold:
                        break
                    candidate = Anchor(x, y, scale, score)
                    if verify is None or verify(candidate):
                        candidates.append(candidate)
                    scores[max(0, y-h):y+h, max(0, x-w):x+w] = -1
        candidates.sort(key=lambda a: a.score, reverse=True)
        if not candidates:
            raise NotFound(f"{name.capitalize()} window not found.")
        best = candidates[0]
        if any(abs(other.x-best.x) > 20 * best.scale or abs(other.y-best.y) > 20 * best.scale
               for other in candidates[1:]):
            raise Ambiguous(f"Multiple possible {name} windows found; no position selected.")
        return best

    @staticmethod
    def region(frame, anchor, box):
        x1, y1 = anchor.point(box[0], box[1])
        x2, y2 = anchor.point(box[2], box[3])
        if x1 < 0 or y1 < 0 or x2 > frame.shape[1] or y2 > frame.shape[0]:
            raise NotFound("Window controls extend beyond the visible game client.")
        return frame[y1:y2, x1:x2]

    def processor(self, frame, checkpoint=lambda: None):
        """Propose titles at half resolution, then verify original pixels and Start."""
        gray = self.gray(frame)
        small = cv2.resize(gray, None, fx=.5, fy=.5, interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (0, 0), .5)
        common = [1.0, .75, 1.25, 4/3, 1.5, 1.7, 2.0]
        preferred = self.last_scale or min(common, key=lambda s: abs(s-frame.shape[1]/1920))
        scales = [preferred] + [s for s in common if s != preferred]
        if self.heading_ratio and self.last_scale:
            found = self.processor_dense(frame, gray, small, checkpoint,
                                         [round(self.last_scale*self.heading_ratio, 3)], self.last_scale)
            if found is not None:
                return found
        for scale in scales:
            checkpoint()
            key = ("processor_coarse", scale)
            if key not in self.scaled:
                title = self.template("processor_title", scale)
                title = cv2.resize(title, None, fx=.5, fy=.5, interpolation=cv2.INTER_AREA)
                self.scaled[key] = cv2.GaussianBlur(title, (0, 0), .5)
            title = self.scaled[key]
            h, w = title.shape
            if h > small.shape[0] or w > small.shape[1]:
                continue
            scores = cv2.matchTemplate(small, title, cv2.TM_CCOEFF_NORMED)
            verified = []
            for _ in range(8):
                checkpoint()
                _, score, _, (x, y) = cv2.minMaxLoc(scores)
                if score < .60:
                    break
                scores[max(0,y-h):y+h, max(0,x-w):x+w] = -1
                try:
                    anchor = self.refine_processor(frame, gray, x*2, y*2, scale, checkpoint)
                    if not any(abs(a.x-anchor.x) < 20*scale and abs(a.y-anchor.y) < 20*scale for a in verified):
                        verified.append(anchor)
                except NotFound:
                    continue
            if len(verified) > 1:
                raise Ambiguous("Multiple possible Processor windows found; no position selected.")
            if verified:
                self.last_scale = scale
                return verified[0]
        found = self.processor_dense(frame, gray, small, checkpoint)
        if found is not None:
            return found
        # Retain the thorough search for unusual renderings that yield no coarse proposal.
        return self.processor_full_search(frame, checkpoint)

    def processor_dense(self, frame, gray, small, checkpoint, scales=None, layout_hint=None):
        """Find the Processor at any UI scale (0.6x-2.2x) from a dense half-resolution scan."""
        proposals = []
        for scale in (scales or self.dense_scales()):
            checkpoint()
            key = ("processor_coarse", scale)
            if key not in self.scaled:
                title = cv2.resize(self.template("processor_title", scale), None, fx=.5, fy=.5, interpolation=cv2.INTER_AREA)
                self.scaled[key] = cv2.GaussianBlur(title, (0, 0), .5)
            title = self.scaled[key]
            h, w = title.shape
            if min(h, w) < 4 or h > small.shape[0] or w > small.shape[1]:
                continue
            result = cv2.matchTemplate(small, title, cv2.TM_CCOEFF_NORMED)
            for _ in range(3):
                _, score, _, (x, y) = cv2.minMaxLoc(result)
                if score < (.60 if scales else .50):
                    break
                proposals.append((float(score), scale, x, y))
                result[max(0, y-h):y+h, max(0, x-w):x+w] = -1
        proposals.sort(reverse=True)
        verified = []
        for score, scale, x, y in proposals[:8]:
            anchor = None
            for factor in (1, .99, 1.01, .98, 1.02):
                try:
                    anchor = self.refine_processor(frame, gray, x*2, y*2, round(scale*factor, 3), checkpoint)
                    break
                except NotFound:
                    continue
            if anchor is None:
                try:
                    anchor = self.refine_processor_split(frame, gray, x*2, y*2, scale, checkpoint, layout_hint)
                except NotFound:
                    continue
            if not any(abs(a.x-anchor.x) < 20*anchor.scale and abs(a.y-anchor.y) < 20*anchor.scale for a in verified):
                verified.append(anchor)
            break
        if len(verified) > 1:
            raise Ambiguous("Multiple possible Processor windows found; no position selected.")
        if verified:
            found = verified[0]
            self.last_scale = found.scale
            if found.heading:
                self.heading_ratio = found.heading/found.scale
            return found
        return None

    def refine_processor_split(self, frame, gray, x, y, heading, checkpoint, layout_hint=None):
        """Title font at `heading`, window layout at an independent scale found from Start."""
        template = self.template("processor_title", heading)
        pad = max(5, math.ceil(4*heading))
        left, top = max(0, x-pad), max(0, y-pad)
        patch = gray[top:min(gray.shape[0], y+template.shape[0]+pad), left:min(gray.shape[1], x+template.shape[1]+pad)]
        best_title = None
        for blur in (0, .8):
            image = cv2.GaussianBlur(patch, (0, 0), blur) if blur else patch
            reference = self.matching_template("processor_title", heading, 0, 0, blur)
            if reference.shape[0] > image.shape[0] or reference.shape[1] > image.shape[1]:
                continue
            _, score, _, (px, py) = cv2.minMaxLoc(cv2.matchTemplate(image, reference, cv2.TM_CCOEFF_NORMED))
            if best_title is None or score > best_title[0]:
                best_title = (float(score), left+px, top+py)
        if best_title is None or best_title[0] < .80:
            raise NotFound("Processor title could not be verified at the proposed location.")
        score, tx, ty = best_title
        best = None
        if layout_hint:
            candidates = [round(layout_hint+d/100, 3) for d in range(-3, 4)]
        else:
            candidates = [round(heading*1.05-i*.01, 3) for i in range(int(heading*.45/.01))]
        for layout in candidates:
            checkpoint()
            if layout < .5:
                continue
            anchor = Anchor(tx-math.floor(18*layout+.5), ty-math.floor(3*layout+.5), layout, score)
            try:
                self.region(frame, anchor, (-26, 0, 490, 208))
                start = self.processor_start(frame, anchor, checkpoint)
            except NotFound:
                continue
            if best is None or self.last_start_score > best[0]:
                best = (self.last_start_score, anchor, start)
        if best is None:
            raise NotFound("Processor Start control is hidden or unrecognized.")
        anchor = best[1]
        return Anchor(anchor.x, anchor.y, anchor.scale, score, tuple(best[2]), heading)

    def refine_processor(self, frame, gray, x, y, scale, checkpoint):
        template = self.template("processor_title", scale)
        pad = max(5, math.ceil(4*scale))
        left, top = max(0,x-pad), max(0,y-pad)
        patch = gray[top:min(gray.shape[0],y+template.shape[0]+pad),
                     left:min(gray.shape[1],x+template.shape[1]+pad)]
        for blur, variants, threshold in ((0, ((0, 0),), .88),
                (.8, tuple((dx,dy) for dx in (-1,0,1) for dy in (-1,0,1)), .86)):
            image = cv2.GaussianBlur(patch, (0,0), blur) if blur else patch
            best = None
            for dx, dy in variants:
                checkpoint()
                reference = self.matching_template("processor_title", scale, dx, dy, blur)
                if reference.shape[0] > image.shape[0] or reference.shape[1] > image.shape[1]:
                    continue
                _, score, _, (px,py) = cv2.minMaxLoc(cv2.matchTemplate(image, reference, cv2.TM_CCOEFF_NORMED))
                if best is None or score > best[0]:
                    best = (score, left+px, top+py)
            if best is None or best[0] < threshold:
                continue
            anchor = Anchor(best[1]-math.floor(18*scale+.5), best[2]-math.floor(3*scale+.5), scale, best[0])
            self.region(frame, anchor, (-26,0,490,208))
            start = self.processor_start(frame, anchor, checkpoint)
            return Anchor(anchor.x, anchor.y, scale, anchor.score, tuple(start))
        raise NotFound("Processor title could not be verified at the proposed location.")

    def processor_full_search(self, frame, checkpoint=lambda: None):
        # The old whole title plate includes translucent trim and changes with
        # the room behind it. Match only the opaque lettering, preserving the
        # existing plate-relative geometry for slots and controls.
        starts = {}

        def plate(title):
            return Anchor(title.x - math.floor(18 * title.scale + .5),
                          title.y - math.floor(3 * title.scale + .5), title.scale, title.score,
                          starts.get((title.x, title.y, title.scale)))

        def verified(title):
            checkpoint()
            anchor = plate(title)
            try:
                self.region(frame, anchor, (-26, 0, 490, 208))
                start = self.processor_start(frame, anchor, checkpoint)
                starts[(title.x, title.y, title.scale)] = tuple(start)
                return True
            except NotFound:
                return False

        common_scales = [1.0, .75, 1.25, 4/3, 1.5, 1.7, 2.0]
        preferred = self.last_scale or 1.0
        groups = ([preferred], [s for s in common_scales if s != preferred])
        for scales in groups:
            # Moving a game window can alter glyph rasterization by a pixel.
            # Compare exact and normalized text with +/-1px glyph dimensions.
            # Both require independent Start proof and agree on one window.
            found = []
            for blur, variants, threshold in ((0, ((0, 0),), .88),
                    (.8, tuple((dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)), .86)):
                try:
                    title = self.locate(frame, "processor_title", scales=scales, threshold=threshold,
                                        checkpoint=checkpoint, verify=verified, blur=blur, variants=variants)
                except NotFound:
                    continue
                except Ambiguous:
                    raise Ambiguous("Multiple possible Processor windows found; no position selected.") from None
                found.append(plate(title))
            if found:
                anchor = found[0]
                if any(abs(other.x-anchor.x) > 20*anchor.scale or abs(other.y-anchor.y) > 20*anchor.scale
                       for other in found[1:]):
                    raise Ambiguous("Multiple possible Processor windows found; no position selected.")
                self.last_scale = anchor.scale
                return anchor
        raise NotFound("Processor window not found: title and Start control could not be verified.")

    def processor_start(self, frame, anchor, checkpoint=lambda: None):
        patch = self.gray(self.region(frame, anchor, (380, 160, 464, 187)))
        for blur, variants, threshold in ((0, ((0, 0),), .80),
                (.8, tuple((dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)), .88)):
            image = cv2.GaussianBlur(patch, (0, 0), blur) if blur else patch
            best = None
            for name in ("start", "start_busy"):
                for dx, dy in variants:
                    checkpoint()
                    template = self.matching_template(name, anchor.scale, dx, dy, blur)
                    h, w = template.shape
                    if h > image.shape[0] or w > image.shape[1]:
                        continue
                    _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED))
                    if best is None or score > best[0]:
                        left, top = anchor.point(380, 160)
                        best = (score, [math.floor(left+x+w/2+.5), math.floor(top+y+h/2+.5)])
            if best is not None and best[0] >= threshold:
                self.last_start_score = float(best[0])
                return best[1]
        raise NotFound("Processor Start control is hidden or unrecognized.")

    @staticmethod
    def input_point(anchor, index):
        return anchor.point(49 + (index % 6) * 53.5, 88 + (index // 6) * 54)

    def occupied(self, frame, anchor, index):
        # Tech-part and tool pixels are neutral/brown against the green slot.
        point = self.input_point(anchor, index)
        radius = max(8, round(16 * anchor.scale))
        x, y = point
        patch = frame[y-radius:y+radius, x-radius:x+radius].astype(np.float32)
        if patch.size == 0:
            raise NotFound("Processor input is outside the visible client.")
        r, g, b = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
        icon = (r > g * 0.90) & (g > b * 1.15) & (r > 45)
        return float(icon.mean()) >= 0.025

    def empty_input(self, frame, anchor):
        if not self.occupied(frame, anchor, 0):
            raise NotFound("Research tool not recognized in the first Processor slot.")
        # Require an idle, clear input area; never silently select a second slot
        # when a previous attempt still has an item loaded.
        if any(self.occupied(frame, anchor, i) for i in range(1, 12)):
            raise Ambiguous("Processor already contains a part. Clear or finish that attempt before starting.")
        return 1

    def blueprint_state(self, frame, anchor):
        """Read progress and the color-independent datacube shape, for any item."""
        if not self.occupied(frame, anchor, 0):
            raise NotFound("Research tool not recognized in the first Processor slot.")
        busy = self.progress_busy(frame, anchor)
        output = self.gray(self.region(frame, anchor, (390, 70, 450, 140)))
        key = ("blueprint_cube_edges", anchor.scale)
        if key not in self.scaled:
            self.scaled[key] = self.icon_edges(self.template("blueprint_cube", anchor.scale))
        reference = self.scaled[key]
        score = float(cv2.matchTemplate(self.icon_edges(output), reference, cv2.TM_CCOEFF_NORMED).max())
        return {"busy": busy, "result": score >= .60}

    def progress_busy(self, frame, anchor):
        progress = self.gray(self.region(frame, anchor, (300, 176, 340, 193)))
        percent = self.template("progress_percent", anchor.scale)
        percent_score = float(cv2.matchTemplate(progress, percent, cv2.TM_CCOEFF_NORMED).max())
        bar = self.region(frame, anchor, (40, 178, 350, 184)).astype(np.float32)
        r, g, b = bar[:, :, 0], bar[:, :, 1], bar[:, :, 2]
        filled = (g > 135) & (g > r * 1.2) & (g > b * 1.05)
        return percent_score >= .80 or float(filled.mean()) > .04

    @staticmethod
    def colorful_icon(patch, threshold=.06):
        r,g,b = patch.astype(np.float32).transpose(2,0,1)
        pixels = ((r>70)&(r>g*1.5)&(r>b*1.5)) | ((g>100)&(g>r*1.8)&(g>b*2.8)) | ((b>100)&(b>r*1.5)&(b>g*1.5))
        return float(pixels.mean()) > threshold

    def blueprint_candidates(self, frame, checkpoint=lambda: None):
        inventory = self.inventory(frame, checkpoint)
        candidates = []
        for row in range(6):
            checkpoint()
            for col in range(8):
                x,y = 39+col*44.6, 63+row*45.5
                if self.blueprint_icon_candidate(self.region(frame, inventory, (x+4,y+4,x+41,y+41)), inventory.scale):
                    candidates.append({"cell": (row,col), "point": inventory.point(x+22.3,y+22.75)})
        return inventory, candidates

    # Runners may pass the last known Inventory so a page needs only the cheap
    # local header check; a failed check still falls back to full localization.
    known_inventory_reuse=True

    def inventory_cells(self, frame, checkpoint=lambda: None, known=None):
        """Every visible cell, including empty and non-cube-looking cells."""
        inventory=self.current_inventory(frame,known,checkpoint) if known is not None else self.inventory(frame,checkpoint)
        return inventory,[{"cell":(row,col),"point":inventory.point(61.3+col*44.6,85.75+row*45.5)}
                          for row in range(6) for col in range(8)]

    def fast_blueprint_candidates(self,frame,checkpoint=lambda:None,known=None):
        inventory,cells=self.inventory_cells(frame,checkpoint,known)
        candidates=[]
        references=[self.icon_edges(self.template("blueprint_cube",s)) for s in (.5,.6,.85,1)]
        for cell in cells:
            checkpoint()
            row,col=cell["cell"];x,y=39+col*44.6,63+row*45.5
            patch=self.region(frame,inventory,(x+2,y+2,x+43,y+44))
            colored=self.blueprint_icon_candidate(patch,inventory.scale)
            normalized=cv2.resize(self.gray(patch),(46,46),interpolation=cv2.INTER_AREA)
            edges=self.icon_edges(normalized)
            score=max(float(cv2.matchTemplate(edges,reference,cv2.TM_CCOEFF_NORMED).max()) for reference in references)
            # Color is only one proposal path. Edge shape also admits neutral
            # or unusually colored cubes; no proposal authorizes a transfer.
            if colored or score>=.44:candidates.append(cell)
        return inventory,candidates

    def current_inventory(self, frame, inventory, checkpoint=lambda: None):
        # Verify the current title/load labels in small fresh crops instead of
        # doing a whole-screen template search for every rapid hover. A failed
        # local check triggers full localization; the old anchor is never used
        # unchecked after a move, resize, or covered header.
        checkpoint()
        if inventory.heading:
            try:
                self.region(frame,inventory,(-22,0,479,354))
                cx,cy=self.grid_contrast(self.gray(frame),inventory)
                if cx>=10 and cy>=8:return inventory
            except NotFound:pass
            return self.inventory(frame,checkpoint)
        try:
            split=False
            title=self.template("inventory_title",inventory.heading or inventory.scale)
            patch=self.gray(self.region(frame,inventory,(23,0,29+title.shape[1]/inventory.scale,
                                                           6+title.shape[0]/inventory.scale)))
            if float(cv2.matchTemplate(patch,title,cv2.TM_CCOEFF_NORMED).max())<(.66 if split else .86):
                raise NotFound("Inventory moved.")
            for name,box in (("inventory_max_load",(57,37,141,65)),("inventory_free_load",(268,37,361,65))):
                patch=self.gray(self.region(frame,inventory,box))
                reference=self.template(name,inventory.scale)
                if float(cv2.matchTemplate(patch,reference,cv2.TM_CCOEFF_NORMED).max())<(.56 if split else .78):
                    raise NotFound("Inventory header changed.")
            self.region(frame,inventory,(-22,0,479,354))
            return inventory
        except (NotFound,cv2.error):
            return self.inventory(frame,checkpoint)

    @staticmethod
    def blueprint_icon_candidate(patch, scale):
        # Candidate proposal only: a tooltip must still verify the recipe.
        # A spell spans two cells. Its red edges used to nominate both halves
        # as cubes and cause long, fruitless hover scans after missing a cube.
        r,g,b = patch.astype(np.float32).transpose(2,0,1)
        mask = (((r>70)&(r>g*1.5)&(r>b*1.5)) |
                ((g>100)&(g>r*1.8)&(g>b*2.8)) |
                ((b>100)&(b>r*1.5)&(b>g*1.5))).astype(np.uint8)
        _,_,stats,_ = cv2.connectedComponentsWithStats(mask)
        return any(w>=12*scale and h>=12*scale and .65<=w/h<=1.5 and area>=100*scale*scale and area/(w*h)>=.32
                   for x,y,w,h,area in stats[1:])

    def inventory_scroll_position(self, frame, inventory):
        """Read the opaque scrollbar thumb, excluding the translucent items/scene.

        Return coordinates relative to Inventory so window movement cannot look
        like scrolling. Tooltips must be cleared before using this observation.
        """
        return self.inventory_scrollbar(frame,inventory)["position"]

    def inventory_scrollbar(self,frame,inventory):
        strip = self.region(frame, inventory, (415, 66, 423, 333)).astype(np.float32)
        r,g,b = strip.transpose(2,0,1)
        rows = ((g>150)&(g>r*1.4)&(g>b*1.2)).mean(axis=1) >= .65
        edges = np.diff(np.r_[False, rows, False].astype(np.int8))
        runs = [(a,b) for a,b in zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1))
                if b-a >= 7*inventory.scale]
        if len(runs)!=1:
            raise NotFound("Inventory scrollbar is hidden or unrecognized. Keep its right edge unobstructed.")
        a,b = runs[0]
        return {"position":(a+b)/(2*inventory.scale),
                "thumb":inventory.point(419,66+(a+b)/(2*inventory.scale)),
                "top":inventory.point(419,66)[1],"bottom":inventory.point(419,333)[1],
                "thumb_top":inventory.point(419,66+a/inventory.scale)[1],
                "thumb_bottom":inventory.point(419,66+b/inventory.scale)[1]}

    def tooltip_recipe(self, frame, point, scale):
        # Tooltips reposition to stay on screen, so search around the current
        # cursor rather than assuming one tooltip location or inventory cell.
        x,y = point
        left,top = max(0,round(x-800*scale)),max(0,round(y-70*scale))
        patch = self.gray(frame[top:min(frame.shape[0],round(y+100*scale)),
                                left:min(frame.shape[1],round(x+800*scale))])
        # Read at the reference font size. Resizing old video text up to the
        # native UI size loses different glyph pixels than normalizing the
        # actual native screenshot down; that caused the repeated WP7 miss.
        prefix = self.template("tooltip_prefix",1)
        raw = patch
        # Text pixels only match the shipped prefix well at the reference sizes
        # (live windowed 1080p: the correct scale .80 scores .60, a wrong one
        # .50). So: try the remembered/likely scales first; if none reaches .74
        # but a tooltip panel is present, scan text scales finely and accept the
        # sharp peak (>= .52) provisionally; the OCR text must then still read
        # as a BLUEPRINT line before any name is trusted.
        def prefix_at(text_scale):
            candidate=cv2.resize(raw,None,fx=1/text_scale,fy=1/text_scale,interpolation=cv2.INTER_AREA)
            if candidate.shape[0]<prefix.shape[0] or candidate.shape[1]<prefix.shape[1]:
                return None
            _,found,_,(fx,fy)=cv2.minMaxLoc(cv2.matchTemplate(candidate,prefix,cv2.TM_CCOEFF_NORMED))
            return (float(found),candidate,fx,fy,text_scale)
        options=[getattr(self,"tooltip_text_scale",None),scale]
        if self.heading_ratio:options+=[round(scale*r,3) for r in (1.1,1.14,1.2,.92,1.28)]
        best=None
        for text_scale in dict.fromkeys(o for o in options if o):
            found=prefix_at(text_scale)
            if found and (best is None or found[0]>best[0]):best=found
            if found and found[0]>=.74:break
        if best is None:
            return None
        provisional=False
        if best[0]<.74:
            nominal=best[1]
            # Weak match: scan text scales finely (live: the right scale scores only ~.60).
            fine=[f for f in (prefix_at(round(float(t),3)) for t in np.arange(.6,1.5,.02)) if f]
            if fine:
                top=max(fine,key=lambda f:f[0])
                if top[0]>best[0]:best=top
            if best[0]>=.52:
                # A visible panel is only recognized when sized near the reference font, so
                # test several normalizations before trusting a weak prefix match.
                for size in dict.fromkeys([scale,1.0,best[4],round(scale*1.14,3)]):
                    if self.item_tooltip_panel(cv2.resize(raw,None,fx=1/size,fy=1/size,interpolation=cv2.INTER_AREA)):
                        provisional=True;break
            if not provisional:
                # No blueprint line: a clean "other" for a real item panel, otherwise nothing.
                # (Returning "other" for UI boxes broke the "tooltip has cleared" check.)
                return "other" if self.item_tooltip_panel(nominal) else None
        score,patch,px,py,text_scale = best
        self.tooltip_text_scale=text_scale
        fallback=self.known_tooltip_recipe(patch,px,py,prefix.shape[0])
        # The tooltip's continuous bottom border supplies its actual width.
        # Excluding it prevents OCR from appending a false "1" to part 7.
        ends=[]
        for row in range(py+10,min(patch.shape[0],py+20)):
            bright=patch[row,px:]>=90
            end=next((i for i in range(20,len(bright)) if not bright[i]),len(bright))
            ends.append((end,row))
        end,bottom=max(ends)
        import re
        if fallback not in self.recipes:fallback="unknown"
        if end<100:
            return "other" if provisional else fallback
        def tooltip_name(trim):
            text=self.read_text(patch[py+1:bottom-1,px:px+end-trim])
            self.last_tooltip_raw=text
            self.last_tooltip_text=text
            tb=re.search(r"T[B8]",text,re.I)
            if tb:
                name=text[tb.end():]
                if ":" in name:name=name.split(":",1)[1]
            else:
                # A merged OCR line may lose spaces or read "30 TB" as "BO".
                # Its known BLUEPRINT prefix is already verified from pixels.
                nums=list(re.finditer(r"\d+",text))
                name=text[nums[0].end():] if len(nums)>1 else text
            return name.strip(" :.-|")
        name=tooltip_name(4)
        if provisional and not re.search(r"BLUE|LUEP|UEPR|PRINT",self.last_tooltip_raw.upper()):
            return "other"
        self.last_tooltip_text=name
        identity=identify_name(name,self.recipes)
        if identity in ("unknown","other") and not re.search(r"\d",name):
            # A 4 px trim can clip a wide final digit (live: Weaponpart 9 read
            # as "Weaponpart"). When the words match a numbered recipe, re-read
            # with a shorter trim. The exact part number is still required, so
            # a wrong or extra digit ("91") remains rejected.
            strip=lambda t:re.sub(r"\d+","",t)
            if any(re.search(r"\d",r["name"]) and item_name_score(strip(r["name"]),strip(name))>=.8
                   for r in self.recipes.values()):
                for trim in (3,2):
                    retry=tooltip_name(trim)
                    again=identify_name(retry,self.recipes)
                    if again not in ("unknown","other"):
                        name,identity=retry,again
                        break
                self.last_tooltip_text=name
        # The template's digit was verified on its own (known_tooltip_recipe).
        # If OCR clearly read a different number, neither source authorizes.
        seen=re.findall(r"\d+",normalized(name))
        if (fallback!="unknown" and identity in ("unknown","other") and seen
                and seen!=re.findall(r"\d+",normalized(RECIPES[fallback]["name"]))):
            return "unknown"
        if identity in ("unknown","other") and fallback!="unknown":return fallback
        if identity not in ("unknown","other") and fallback not in ("unknown",identity):
            # A shipped short title can be a substring of a valid custom title
            # (Holy Heal / Holy Heal Sanctum). Trust the complete OCR name when
            # that is the relationship; retain exact-number conflict rejection.
            target=normalized(self.recipes[identity]["name"])
            short_names=[normalized(n) for n in (RECIPES[fallback]["name"],*RECIPES[fallback].get("aliases",()))]
            same_numbers=re.findall(r"\d+",target)==re.findall(r"\d+",normalized(RECIPES[fallback]["name"]))
            if same_numbers and any(target.startswith(n) and len(target)>len(n)+2 for n in short_names):return identity
            return "unknown"
        return identity

    @staticmethod
    def item_tooltip_panel(gray):
        # A visible non-blueprint tooltip is already a decisive rejection.
        # Verify its black interior plus neutral bright top/bottom border;
        # green scene/UI rectangles alone do not satisfy this check.
        mask=(gray<42).astype(np.uint8)
        _,_,stats,_=cv2.connectedComponentsWithStats(mask)
        for x,y,w,h,area in stats[1:]:
            if w<50 or not 7<=h<=26 or area/(w*h)<.45:continue
            if y==0 or y+h>=gray.shape[0]:continue
            if (gray[y-1,x:x+w]>90).mean()>.8 and (gray[y+h,x:x+w]>90).mean()>.8:return True
        return False

    def known_tooltip_recipe(self,patch,px,py,height):
        # Pixel verification remains a fallback for the three shipped names.
        # Custom names use OCR and do not require any captured artwork.
        line=patch[max(0,py-3):min(patch.shape[0],py+height+3),px+65:min(patch.shape[1],px+460)]
        if not line.size:return "unknown"
        smooth=cv2.GaussianBlur(line,(0,0),.6)
        scores=[]
        for recipe in RECIPES:
            best=(0.,None,0,0)
            for dx in (-1,0,1):
                for dy in (-1,0,1):
                    reference=self.matching_template("tooltip_"+recipe,1,dx,dy,.6)
                    if reference.shape[0]<=line.shape[0] and reference.shape[1]<=line.shape[1]:
                        _,score,_,(x,y)=cv2.minMaxLoc(cv2.matchTemplate(smooth,reference,cv2.TM_CCOEFF_NORMED))
                        if score>best[0]:best=(float(score),reference,x,y)
            scores.append((best[0],recipe,best[1:]))
        scores.sort(key=lambda s:s[0],reverse=True)
        if scores[0][0]<.78 or scores[0][0]-scores[1][0]<.05:return "unknown"
        recipe=scores[0][1]
        if re.search(r"\d",RECIPES[recipe]["name"]):
            # The whole-line score is dominated by the shared word "Weaponpart"
            # (a '3' still scored .97 against WP9). Verify the final digit alone:
            # recorded 7/9 digits score >= .92, other digits <= .63, blank ~0.
            reference,x,y=scores[0][2];w=reference.shape[1]
            glyph=reference[1:-2,w-10:w-1]
            window=smooth[max(0,y-1):y+reference.shape[0]+1,max(0,x+w-12):min(smooth.shape[1],x+w+1)]
            if (window.shape[0]<glyph.shape[0] or window.shape[1]<glyph.shape[1]
                    or float(cv2.matchTemplate(window,glyph,cv2.TM_CCOEFF_NORMED).max())<.80):
                return "unknown"
        return recipe

    def text_reader(self):
        if self.reader is None:
            from text_reader import TextReader
            self.reader = TextReader()
        return self.reader

    def read_text(self, gray):
        key=(gray.shape,gray.tobytes())
        if key not in self.ocr_cache:
            from text_reader import TextReader
            if self.reader is None:self.reader=TextReader()
            if len(self.ocr_cache)>=32:self.ocr_cache.clear()
            self.ocr_cache[key]=self.reader.read(gray)
        return self.ocr_cache[key]

    def result_details(self, frame, point, scale):
        """Read a constructed item's hover label, allowing quality prefixes."""
        x,y=point
        left,top=max(0,round(x-800*scale)),max(0,round(y-55*scale))
        gray=self.gray(frame[top:min(frame.shape[0],round(y+85*scale)),
                             left:min(frame.shape[1],round(x+800*scale))])
        gray=cv2.resize(gray,None,fx=1/scale,fy=1/scale,interpolation=cv2.INTER_AREA)
        # Black tooltip panels are outlined in light gray, unlike the green UI.
        mask=(gray<38).astype(np.uint8)
        count,labels,stats,_=cv2.connectedComponentsWithStats(mask)
        for x,y,w,h,area in sorted(stats[1:].tolist(),key=lambda s:s[2],reverse=True):
            if w<70 or not 9<=h<=25 or area/(w*h)<.35:continue
            text=self.read_text(gray[y:y+h,x:x+w])
            import re
            slot=re.search(r"\bFree\s*Slots\s*[:;.,]?\s*([0-5Oo])\b",text,re.I)
            slots=int(slot.group(1).lower().replace("o","0")) if slot else None
            name=re.split(r",?\s*(?:Free\s*Slots|Constructed\b)",text,flags=re.I)[0].strip()
            identity=identify_name(name,self.recipes)
            if identity not in ("unknown","other"):
                self.last_tooltip_text=text
                return {"recipe":identity,"slots":slots,"text":text}
        return None

    def result_name(self, frame, point, scale):
        details=self.result_details(frame,point,scale)
        return details["recipe"] if details else None

    def construction_input(self, frame, anchor):
        if not self.construction_tool(frame,anchor):
            raise NotFound("Construction tool not recognized in Processor slot 1.")
        empty=[]
        for index in range(1,12):
            px,py=self.input_point(anchor,index)
            radius=round(24*anchor.scale)
            patch=frame[py-radius:py+radius,px-radius:px+radius]
            present=self.occupied(frame,anchor,index) or self.colorful_icon(patch,.025)
            if not present:
                empty.append(index)
                continue
            if self.input_cube_kind(patch,anchor.scale)!="empty_datacube":
                raise Ambiguous("Processor contains a pending item. Finish or clear it before starting construction.")
        if not empty:
            raise Ambiguous("No free Processor input slot is visible.")
        return empty[0]

    def construction_state(self, frame, anchor, recipe):
        if not self.construction_tool(frame,anchor):
            raise NotFound("Construction tool not recognized in Processor slot 1.")
        patch=self.gray(self.region(frame,anchor,(374,45,473,160)))
        result_template=self.recipes[recipe].get("result_template")
        if result_template is None:
            return {"busy":self.progress_busy(frame,anchor),"result":False}
        reference=self.template(result_template,anchor.scale)
        score=float(cv2.matchTemplate(self.icon_edges(patch),self.icon_edges(reference),cv2.TM_CCOEFF_NORMED).max())
        return {"busy":self.progress_busy(frame,anchor),"result":score>=.60}

    def construction_tool(self, frame, anchor):
        patch=self.gray(self.region(frame,anchor,(24,62,76,114)))
        template=self.template("construction_tool",anchor.scale)
        return float(cv2.matchTemplate(patch,template,cv2.TM_CCOEFF_NORMED).max())>=.60

    def has_loaded_blueprint(self, frame, anchor):
        # A used cube has a different gray top; at least one non-empty cube
        # must be present before Start. Material slots are never moved here.
        for index in range(1,12):
            x,y=self.input_point(anchor,index)
            r=round(24*anchor.scale)
            patch=frame[y-r:y+r,x-r:x+r]
            if self.colorful_icon(patch,.025):
                if self.input_cube_kind(patch,anchor.scale) in ("loaded_blueprint_red","loaded_blueprint_green"):
                    return True
        return False

    def input_cube_kind(self, patch, scale):
        gray=self.gray(patch)
        scores=[]
        for name in ("empty_datacube","loaded_blueprint_red","loaded_blueprint_green"):
            reference=self.template(name,scale)
            scores.append((float(cv2.matchTemplate(gray,reference,cv2.TM_CCOEFF_NORMED).max()),name))
        scores.sort(reverse=True)
        if scores[0][0]>=.75 and scores[0][0]-scores[1][0]>=.04:return scores[0][1]
        return self.cube_kind_by_color(patch)

    @staticmethod
    def cube_kind_by_color(patch):
        """Scale-independent cube classification for UI scales whose icons do not
        match the shipped bitmaps: a used cube has a gray top, a loaded blueprint
        is solid red or bright green. Uncertain colours stay "unknown"."""
        rgb=patch.astype(np.float32);r,g,b=rgb[:,:,0],rgb[:,:,1],rgb[:,:,2]
        height,width=r.shape
        border=np.concatenate((rgb[:3].reshape(-1,3),rgb[:,:3].reshape(-1,3),rgb[:,-3:].reshape(-1,3)))
        background=np.median(border,axis=0)
        icon=np.abs(rgb-background).sum(axis=2)>70
        if icon.sum()<.15*height*width:return "unknown"
        gray_top=icon&((rgb.max(axis=2)-rgb.min(axis=2))<38)&(rgb.max(axis=2)<170)&(rgb.max(axis=2)>35)
        red=icon&(r>g*1.6)&(r>b*1.6)&(r>40)
        green=icon&(g>100)&(g>r*1.7)&(b<g*.75)
        n=float(icon.sum())
        if green.sum()/n>=.30 and gray_top.sum()/n<.12:return "loaded_blueprint_green"
        if red.sum()/n>=.60 and gray_top.sum()/n<.15:return "loaded_blueprint_red"
        if gray_top.sum()/n>=.25:return "empty_datacube"
        return "unknown"

    @staticmethod
    def icon_edges(gray):
        gray = cv2.GaussianBlur(gray, (3,3), .6)
        return cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))

    @staticmethod
    def normalize_glyph(mask):
        ys, xs = np.nonzero(mask)
        if not len(xs):
            return np.zeros((16, 16), dtype=np.uint8)
        crop = mask[ys.min():ys.max()+1, xs.min():xs.max()+1].astype(np.uint8)
        return cv2.resize(crop, (16, 16), interpolation=cv2.INTER_NEAREST)

    @staticmethod
    def label_mask(label, minimum):
        low, high = label.min(axis=2), label.max(axis=2)
        mask = ((low > minimum) & ((high.astype(int)-low) < (90 if minimum == 125 else 110))).astype(np.uint8)
        count, components, stats, _ = cv2.connectedComponentsWithStats(mask)
        clean = np.zeros_like(mask)
        for i in range(1, count):
            x, y, w, h, area = stats[i]
            if h >= 6 and area >= 6:
                clean[components == i] = 1
        return clean

    def read_label(self, cell):
        cell = cv2.resize(cell, (45, 46), interpolation=cv2.INTER_LINEAR)
        label = cell[2:17, 2:41]
        clean = self.label_mask(label, 125)
        ys, xs = np.nonzero(clean)
        candidates = []
        if len(xs) and xs.max()-xs.min()+1 <= 11:
            glyph = self.normalize_glyph(clean)
            scores = []
            for name, template in self.labels.items():
                union = np.logical_or(glyph, template).sum()
                score = np.logical_and(glyph, template).sum() / max(1, union)
                scores.append((float(score), name))
            scores.sort(reverse=True)
            if scores[0][0] >= .64 and scores[0][0]-scores[1][0] >= .12:
                candidates.append(scores[0])
        # Preserve antialiased strokes when the UI is rendered at another scale.
        # Correlation uses the game's own grayscale letter shapes, not a generic OCR font.
        clean = self.label_mask(label, 85)
        ys, xs = np.nonzero(clean)
        if len(xs) and xs.max()-xs.min()+1 <= 11:
            gray = self.gray(label)[ys.min():ys.max()+1, xs.min():xs.max()+1]
            glyph = cv2.resize(gray, (16, 16)).astype(np.float32)
            scores = sorted((float(cv2.matchTemplate(glyph, template, cv2.TM_CCOEFF_NORMED)[0, 0]), name)
                            for name, template in self.gray_labels.items())
            if scores[-1][0] >= .50 and scores[-1][0]-scores[-2][0] >= .20:
                candidates.append(scores[-1])
        candidates.sort(reverse=True)
        if (len(candidates) == 2 and candidates[0][1] != candidates[1][1]
                and candidates[0][0]-candidates[1][0] < .12):
            return None
        # Antialiasing can erase half of a T's top stroke at a strict threshold,
        # making it resemble E. Compare the complete grayscale glyph as well.
        return candidates[0][1] if candidates else None

    def inventory(self, frame, checkpoint=lambda: None):
        gray = self.gray(frame)
        # Text is opaque; window trim includes the changing 3D scene behind it.
        # Verify the load labels before accepting a title, because the game's
        # top navigation bar also says INVENTORY.
        scales = list(dict.fromkeys(s for s in
                      (self.inventory_scale, self.last_scale, 1.0, .75, 1.25, 4/3, 1.5, 1.7, 2.0)
                      if s is not None))
        best_title = 0.0
        if self.heading_ratio and self.inventory_scale:
            # Windows are scaled independently (live: Processor .80, Inventory .78),
            # so only the Inventory's own previous scale is a valid hint.
            layout = self.inventory_scale
            found = self.inventory_split(frame, gray, [round(layout*self.heading_ratio, 3)], layout, checkpoint)
            if found is not None:
                return found
        for scale in scales:
            checkpoint()
            title = self.template("inventory_title", scale)
            h, w = title.shape
            if gray.shape[0] < h or gray.shape[1] < w:
                continue
            scores = cv2.matchTemplate(gray, title, cv2.TM_CCOEFF_NORMED)
            verified = []
            for _ in range(4):
                _, score, _, (x, y) = cv2.minMaxLoc(scores)
                best_title = max(best_title, score)
                if score < .86:
                    break
                scores[max(0, y-h):y+h, max(0, x-w):x+w] = -1
                anchor = Anchor(math.floor(x-26*scale+.5), math.floor(y-3*scale+.5), scale, score)
                try:
                    self.region(frame, anchor, (-22, 0, 479, 354))
                    for name, box in (
                        ("inventory_max_load", (57, 37, 141, 65)),
                        ("inventory_free_load", (268, 37, 361, 65)),
                    ):
                        patch = self.region(frame, anchor, box)
                        expected = self.template(name, scale)
                        if patch.shape[0] < expected.shape[0] or patch.shape[1] < expected.shape[1]:
                            raise NotFound("Inventory load headers are clipped.")
                        confidence = float(cv2.matchTemplate(self.gray(patch), expected,
                                                              cv2.TM_CCOEFF_NORMED).max())
                        if confidence < .78:
                            raise NotFound("Inventory load headers are hidden or unrecognized.")
                    verified.append(anchor)
                except NotFound:
                    continue
            if len(verified) > 1:
                raise Ambiguous("Multiple Inventory windows found; no position selected.")
            if verified:
                self.inventory_scale = scale
                return verified[0]
        found = self.inventory_split(frame, gray, self.dense_scales(), None, checkpoint)
        if found is not None:
            return found
        raise NotFound(f"Inventory window not found: title and load headers could not be verified "
                       f"(best title score {best_title:.3f}).")

    @staticmethod
    def _lerp(profile, pos):
        i = np.floor(pos).astype(int); fraction = pos-i
        i = np.clip(i, 0, len(profile)-2)
        return profile[i]*(1-fraction)+profile[i+1]*fraction

    def grid_contrast(self, gray, anchor):
        """Cell centres minus cell borders along both axes (gray levels). A correctly
        placed 8x6 grid scores high; a shift of a couple of pixels does not."""
        scale = anchor.scale
        x1, x2 = max(0, anchor.x+20), min(gray.shape[1], int(anchor.x+420*scale+20))
        y1, y2 = max(0, anchor.y+40), min(gray.shape[0], int(anchor.y+360*scale+20))
        if x2-x1 < 60 or y2-y1 < 60:
            return 0., 0.
        sub = gray[y1:y2, x1:x2].astype(np.float32)
        columns, rows = sub.mean(axis=0), sub.mean(axis=1)
        cx = (self._lerp(columns, anchor.x+(39+22.3+np.arange(8)*44.6)*scale-x1).mean()
              - self._lerp(columns, anchor.x+(39+np.arange(9)*44.6)*scale-x1).mean())
        cy = (self._lerp(rows, anchor.y+(63+22.75+np.arange(6)*45.5)*scale-y1).mean()
              - self._lerp(rows, anchor.y+(63+np.arange(7)*45.5)*scale-y1).mean())
        return float(cx), float(cy)

    def fit_inventory_grid(self, gray, anchor, shift=(16, 8), span=.05):
        """Refine a title-derived Inventory anchor from the cell grid itself. Heading
        fonts do not scale with the layout, so the title is only a first guess."""
        x1, x2 = max(0, anchor.x+20), min(gray.shape[1], int(anchor.x+420*anchor.scale*(1+span)+30))
        y1, y2 = max(0, anchor.y+40), min(gray.shape[0], int(anchor.y+360*anchor.scale*(1+span)+30))
        if x2-x1 < 60 or y2-y1 < 60:
            return None
        sub = gray[y1:y2, x1:x2].astype(np.float32)
        columns, rows = sub.mean(axis=0), sub.mean(axis=1)
        best = None
        for scale in np.arange(anchor.scale*(1-span), anchor.scale*(1+span)+1e-9, .002):
            bx = by = None
            for ax in np.arange(anchor.x-shift[0], anchor.x+shift[0]+.1, .5):
                value = (self._lerp(columns, ax+(39+22.3+np.arange(8)*44.6)*scale-x1).mean()
                         - self._lerp(columns, ax+(39+np.arange(9)*44.6)*scale-x1).mean())
                if bx is None or value > bx[0]:
                    bx = (value, ax)
            for ay in np.arange(anchor.y-shift[1], anchor.y+shift[1]+.1, .5):
                value = (self._lerp(rows, ay+(63+22.75+np.arange(6)*45.5)*scale-y1).mean()
                         - self._lerp(rows, ay+(63+np.arange(7)*45.5)*scale-y1).mean())
                if by is None or value > by[0]:
                    by = (value, ay)
            if best is None or bx[0]+by[0] > best[0]:
                best = (bx[0]+by[0], float(scale), bx[1], by[1], bx[0], by[0])
        _, scale, ax, ay, cx, cy = best
        if cx < 10 or cy < 8:
            return None
        return Anchor(int(math.floor(ax+.5)), int(math.floor(ay+.5)), round(scale, 3), anchor.score, None, anchor.heading)

    def inventory_split(self, frame, gray, heading_scales, layout_hint, checkpoint):
        """Resolve a title font scale and an independent layout scale from the load labels.

        Heading and label fonts snap to whole pixel sizes, so they correlate only
        weakly with resized templates (live: title .75, labels .64-.70). Accept that
        only when the title and BOTH load labels agree on one layout position.
        A layout hint (from the Processor, which shares the UI layout) is tried first.
        """
        small = cv2.GaussianBlur(cv2.resize(gray, None, fx=.5, fy=.5, interpolation=cv2.INTER_AREA), (0, 0), .5)
        proposals = []
        for heading in heading_scales:
            checkpoint()
            key = ("inventory_coarse", heading)
            if key not in self.scaled:
                title = cv2.resize(self.template("inventory_title", heading), None, fx=.5, fy=.5, interpolation=cv2.INTER_AREA)
                self.scaled[key] = cv2.GaussianBlur(title, (0, 0), .5)
            title = self.scaled[key]
            h, w = title.shape
            if min(h, w) < 4 or small.shape[0] < h or small.shape[1] < w:
                continue
            scores = cv2.matchTemplate(small, title, cv2.TM_CCOEFF_NORMED)
            for _ in range(3):
                _, score, _, (x, y) = cv2.minMaxLoc(scores)
                if score < .55:
                    break
                proposals.append((float(score), heading, x*2, y*2))
                scores[max(0, y-h):y+h, max(0, x-w):x+w] = -1
        proposals.sort(reverse=True)
        results = []
        for _, coarse_heading, cx, cy in proposals[:6]:
            # Refine the title font scale and exact pixel in a small patch.
            best_title = None
            for factor in (1, .98, 1.02, .96, 1.04):
                heading = round(coarse_heading*factor, 3)
                title = self.template("inventory_title", heading)
                pad = max(4, math.ceil(4*heading))
                left, top = max(0, cx-pad), max(0, cy-pad)
                patch = gray[top:cy+title.shape[0]+pad, left:cx+title.shape[1]+pad]
                if patch.shape[0] < title.shape[0] or patch.shape[1] < title.shape[1]:
                    continue
                _, score, _, (px, py) = cv2.minMaxLoc(cv2.matchTemplate(patch, title, cv2.TM_CCOEFF_NORMED))
                if best_title is None or score > best_title[0]:
                    best_title = (float(score), heading, left+px, top+py)
            if best_title is None or best_title[0] < .66:
                continue
            score, heading, x, y = best_title
            if layout_hint:
                layouts = [layout_hint] + [round(layout_hint+d/100, 3) for d in (-1, 1, -2, 2, -3, 3)]
            else:
                layouts = [round(heading*1.05-i*.01, 3) for i in range(int(heading*.45/.01))]
            best = None
            for layout in layouts:
                checkpoint()
                if layout < .5:
                    continue
                anchor = Anchor(math.floor(x-26*layout+.5), math.floor(y-3*layout+.5), layout, score, None, heading)
                try:
                    self.region(frame, anchor, (-22, 0, 479, 354))
                    confidences = []
                    for name, box in (("inventory_max_load", (57, 37, 141, 65)), ("inventory_free_load", (268, 37, 361, 65))):
                        patch = self.region(frame, anchor, box)
                        expected = self.template(name, layout)
                        if patch.shape[0] < expected.shape[0] or patch.shape[1] < expected.shape[1]:
                            raise NotFound("Inventory load headers are clipped.")
                        confidences.append(float(cv2.matchTemplate(self.gray(patch), expected, cv2.TM_CCOEFF_NORMED).max()))
                except NotFound:
                    continue
                if min(confidences) < .45:
                    continue
                if best is None or sum(confidences) > best[0]:
                    best = (sum(confidences), anchor)
            if best is not None:
                # The 8x6 cell grid must sit where the fitted layout says it does;
                # this also rejects the top navigation bar's own INVENTORY label.
                fitted = self.fit_inventory_grid(gray, best[1])
                if fitted is not None:
                    results.append(fitted)
                    if layout_hint or len(results) >= 2:
                        break
        if not results:
            return None
        anchor = results[0]
        if any(abs(o.x-anchor.x) > 20*anchor.scale or abs(o.y-anchor.y) > 20*anchor.scale for o in results[1:]):
            raise Ambiguous("Multiple Inventory windows found; no position selected.")
        self.inventory_scale = anchor.scale
        split = abs(anchor.heading-anchor.scale) > .02
        if split:
            self.heading_ratio = anchor.heading/anchor.scale
        # Any window found by the grid fit keeps its grid-based hot-path check, uniform
        # or not: at scales without shipped bitmaps the title/label correlation is too
        # weak for the cheap re-check and would report "moved" on every hover.
        return Anchor(anchor.x, anchor.y, anchor.scale, anchor.score, None, anchor.heading)

    def stacks(self, frame, checkpoint=lambda: None):
        anchor = self.inventory(frame, checkpoint=checkpoint)
        found = {name: [] for name in "TEAL"}
        for row in range(6):
            checkpoint()
            for col in range(8):
                x = 39 + col * 44.6
                y = 63 + row * 45.5
                cell = self.region(frame, anchor, (x, y, x+44.6, y+45.5))
                label = self.read_label(cell)
                if label:
                    # Reject single letters on a different kind of inventory icon.
                    icon = cv2.resize(cell, (45, 46))[14:33, 8:38].astype(float)
                    r, g, b = icon[:, :, 0], icon[:, :, 1], icon[:, :, 2]
                    if ((r > g*.9) & (g > b*1.15) & (r > 45)).mean() >= .06:
                        found[label].append(anchor.point(x+22.3, y+22.75))
        return found

    def quantity(self, frame, checkpoint=lambda: None, expected=False):
        # Inventory already establishes the UI scale during construction.
        # Keep exact title verification, avoiding seven full-size scale scans
        # when no dialog is open; retain the raster-jitter fallback.
        hint=self.last_scale or self.inventory_scale
        # The dialog is its own window with its own scale (live windowed: Processor
        # .80, dialog .77), so remember the scale where it was last found.
        try:
            if self.quantity_scale:
                anchor=self.locate(frame,"quantity_title",scales=[self.quantity_scale],threshold=.62,checkpoint=checkpoint)
            else:
                anchor=self.locate(frame,"quantity_title",scales=[hint] if hint else None,
                                   threshold=.86,checkpoint=checkpoint)
        except NotFound:
            anchor=None if self.quantity_scale else self.quantity_title_fallback(frame,checkpoint)
            if anchor is None and expected:
                # A remembered scale that keeps missing an expected dialog is stale
                # (window resized); drop it and search again. Otherwise stay cheap.
                if self.quantity_scale:
                    self.quantity_misses+=1
                    if self.quantity_misses>=6:self.quantity_scale=None;self.quantity_misses=0
                if not self.quantity_scale:
                    anchor=self.quantity_dense(frame,checkpoint)
            if anchor is None:return None
        self.quantity_misses=0
        self.region(frame, anchor, (-7, -7, 316, 55))
        half = self.region(frame, anchor, (205, 14, 251, 39))
        template = self.template("quantity_half", anchor.scale)
        if half.shape[0] < template.shape[0] or half.shape[1] < template.shape[1]:
            return None
        score = float(cv2.matchTemplate(self.gray(half), template, cv2.TM_CCOEFF_NORMED).max())
        if score < (.60 if self.quantity_scale else .75):
            return None
        field = self.region(frame, anchor, (156, 16, 198, 36))
        # Frame antialiasing may leave a bright vertical border in this crop.
        # Digits are inset; exclude the border before counting numeric glyphs.
        inset=max(1,round(2*anchor.scale))
        field=field[inset:-inset,inset:-inset]
        confirmations=0
        multiple=False
        for minimum in (75,95,115):
            light = ((field.min(axis=2) > minimum)
                     & ((field.max(axis=2).astype(int)-field.min(axis=2)) < 100)).astype(np.uint8)
            n, labels, stats, _ = cv2.connectedComponentsWithStats(light)
            digits = [i for i in range(1, n) if stats[i][3] >= 5*anchor.scale
                      and stats[i][4] >= 5*anchor.scale*anchor.scale]
            if len(digits)>1:
                multiple=True
                break
            if len(digits)==1:
                glyph = self.normalize_glyph(labels == digits[0])
                union = np.logical_or(glyph, self.quantity_one).sum()
                confirmations+=np.logical_and(glyph, self.quantity_one).sum()/max(1,union)>=.65
        is_one=not multiple and confirmations>=2
        return {"field": anchor.point(177, 25), "ok": anchor.point(286, 25), "one": bool(is_one), "scale": anchor.scale}

    def quantity_dense(self, frame, checkpoint):
        """Find the Number of Units dialog at any UI scale: title proposes, Half confirms."""
        gray = self.gray(frame)
        proposals = []
        # The dialog shares the UI's overall size, so only scan near the known
        # window scales (full range when none is known yet).
        known = [v for v in (self.last_scale, self.inventory_scale) if v]
        scales = [v for v in self.dense_scales() if not known or min(known)*.8 <= v <= max(known)*1.2]
        small = cv2.GaussianBlur(cv2.resize(gray, None, fx=.5, fy=.5, interpolation=cv2.INTER_AREA), (0, 0), .5)
        for scale in scales:
            checkpoint()
            title = cv2.GaussianBlur(cv2.resize(self.template("quantity_title", scale), None, fx=.5, fy=.5,
                                                interpolation=cv2.INTER_AREA), (0, 0), .5)
            if min(title.shape) < 4 or small.shape[0] < title.shape[0] or small.shape[1] < title.shape[1]:
                continue
            _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(small, title, cv2.TM_CCOEFF_NORMED))
            if score >= .45:
                proposals.append((float(score), scale, x*2, y*2))
        proposals.sort(reverse=True)
        for _, coarse, cx, cy in proposals[:4]:
            best = None
            for factor in (1, .99, 1.01, .98, 1.02, .97, 1.03):
                scale = round(coarse*factor, 3)
                title = self.template("quantity_title", scale)
                pad = max(4, math.ceil(4*scale))
                left, top = max(0, cx-pad), max(0, cy-pad)
                patch = gray[top:cy+title.shape[0]+pad, left:cx+title.shape[1]+pad]
                if patch.shape[0] < title.shape[0] or patch.shape[1] < title.shape[1]:
                    continue
                _, score, _, (px, py) = cv2.minMaxLoc(cv2.matchTemplate(patch, title, cv2.TM_CCOEFF_NORMED))
                anchor = Anchor(left+px, top+py, scale, float(score))
                try:
                    half = self.region(frame, anchor, (205, 14, 251, 39))
                except NotFound:
                    continue
                reference = self.template("quantity_half", scale)
                if half.shape[0] < reference.shape[0] or half.shape[1] < reference.shape[1]:
                    continue
                confirm = float(cv2.matchTemplate(self.gray(half), reference, cv2.TM_CCOEFF_NORMED).max())
                if confirm >= .60 and score >= .60 and (best is None or confirm+score > best[0]):
                    best = (confirm+score, anchor)
            if best is not None:
                self.quantity_scale = best[1].scale
                return best[1]
        return None

    def quantity_title_fallback(self, frame, checkpoint):
        # A coarse proposal avoids nine full-screen normalized searches when
        # no dialog is open, while handling the same glyph jitter as Processor.
        gray=self.gray(frame)
        small=cv2.GaussianBlur(cv2.resize(gray,None,fx=.5,fy=.5,interpolation=cv2.INTER_AREA),(0,0),.5)
        scales=[self.last_scale] if self.last_scale else [self.inventory_scale] if self.inventory_scale else [1,.75,1.25,4/3,1.5,1.7,2]
        for scale in scales:
            checkpoint()
            template=self.template("quantity_title",scale)
            key=("quantity_coarse",scale)
            if key not in self.scaled:
                self.scaled[key]=cv2.GaussianBlur(cv2.resize(template,None,fx=.5,fy=.5,interpolation=cv2.INTER_AREA),(0,0),.5)
            coarse=self.scaled[key]
            if coarse.shape[0]>small.shape[0] or coarse.shape[1]>small.shape[1]:
                continue
            scores=cv2.matchTemplate(small,coarse,cv2.TM_CCOEFF_NORMED)
            verified=[]
            for _ in range(4):
                _,score,_,(x,y)=cv2.minMaxLoc(scores)
                if score<.60:break
                h,w=coarse.shape
                scores[max(0,y-h):y+h,max(0,x-w):x+w]=-1
                pad=max(5,round(4*scale));left,top=max(0,x*2-pad),max(0,y*2-pad)
                patch=gray[top:min(gray.shape[0],y*2+template.shape[0]+pad),
                           left:min(gray.shape[1],x*2+template.shape[1]+pad)]
                patch=cv2.GaussianBlur(patch,(0,0),.8)
                best=None
                for dx in (-1,0,1):
                    for dy in (-1,0,1):
                        checkpoint()
                        reference=self.matching_template("quantity_title",scale,dx,dy,.8)
                        if reference.shape[0]>patch.shape[0] or reference.shape[1]>patch.shape[1]:continue
                        _,value,_,(px,py)=cv2.minMaxLoc(cv2.matchTemplate(patch,reference,cv2.TM_CCOEFF_NORMED))
                        if best is None or value>best.score:best=Anchor(left+px,top+py,scale,value)
                if best and best.score>=.86:verified.append(best)
            if len(verified)>1:raise Ambiguous("Multiple quantity dialogs found.")
            if verified:return verified[0]
        return None
