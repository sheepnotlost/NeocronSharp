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

    def template(self, name, scale):
        key = (name, scale)
        if key not in self.scaled:
            src = self.templates[name]
            self.scaled[key] = cv2.resize(src, None, fx=scale, fy=scale,
                                           interpolation=cv2.INTER_LINEAR)
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
        # Retain the thorough search for unusual renderings that yield no coarse proposal.
        return self.processor_full_search(frame, checkpoint)

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
        try:
            title=self.template("inventory_title",inventory.scale)
            patch=self.gray(self.region(frame,inventory,(23,0,29+title.shape[1]/inventory.scale,
                                                           6+title.shape[0]/inventory.scale)))
            if float(cv2.matchTemplate(patch,title,cv2.TM_CCOEFF_NORMED).max())<.86:
                raise NotFound("Inventory moved.")
            for name,box in (("inventory_max_load",(57,37,141,65)),("inventory_free_load",(268,37,361,65))):
                patch=self.gray(self.region(frame,inventory,box))
                reference=self.template(name,inventory.scale)
                if float(cv2.matchTemplate(patch,reference,cv2.TM_CCOEFF_NORMED).max())<.78:
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
                "bottom":inventory.point(419,333)[1],
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
        patch=cv2.resize(patch,None,fx=1/scale,fy=1/scale,interpolation=cv2.INTER_AREA)
        prefix = self.template("tooltip_prefix",1)
        if patch.shape[0]<prefix.shape[0] or patch.shape[1]<prefix.shape[1]:
            return None
        _,score,_,(px,py) = cv2.minMaxLoc(cv2.matchTemplate(patch,prefix,cv2.TM_CCOEFF_NORMED))
        if score < .74:
            return "other" if self.item_tooltip_panel(patch) else None
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
            return fallback
        def tooltip_name(trim):
            text=self.read_text(patch[py+1:bottom-1,px:px+end-trim])
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
        return scores[0][1] if scores[0][0]>=.75 and scores[0][0]-scores[1][0]>=.04 else "unknown"

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
        raise NotFound(f"Inventory window not found: title and load headers could not be verified "
                       f"(best title score {best_title:.3f}).")

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

    def quantity(self, frame, checkpoint=lambda: None):
        # Inventory already establishes the UI scale during construction.
        # Keep exact title verification, avoiding seven full-size scale scans
        # when no dialog is open; retain the raster-jitter fallback.
        hint=self.last_scale or self.inventory_scale
        try:
            anchor=self.locate(frame,"quantity_title",scales=[hint] if hint else None,
                               threshold=.86,checkpoint=checkpoint)
        except NotFound:
            anchor=self.quantity_title_fallback(frame,checkpoint)
            if anchor is None:return None
        self.region(frame, anchor, (-7, -7, 316, 55))
        half = self.region(frame, anchor, (205, 14, 251, 39))
        template = self.template("quantity_half", anchor.scale)
        if half.shape[0] < template.shape[0] or half.shape[1] < template.shape[1]:
            return None
        score = float(cv2.matchTemplate(self.gray(half), template, cv2.TM_CCOEFF_NORMED).max())
        if score < .75:
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
        return {"field": anchor.point(177, 25), "ok": anchor.point(286, 25), "one": bool(is_one)}

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
