"""Blueprint-only construction input; all ingredients are handled by Neocron."""

from macro_core import Interrupted
from recipes import RECIPES, catalog
import re
import gogo
from vision import Ambiguous, NotFound, cv2
from vision_runner import VisualRunner
from inventory_tracking import snapshot,checked_overlap


class OutOfMaterials(Interrupted):
    """Start was refused for missing materials, or GoGuardian could not supply them."""


class ConstructionRunner(VisualRunner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.recipes=catalog(self.profile)
        self.detector.recipes=self.recipes
        self.recipe = self.profile["construction"]["recipe"]
        self.name = self.recipes[self.recipe]["name"]
        # Queued jobs (recipe, count) run one after another through the same single-job flow.
        self.queue=list(self.profile["construction"].get("queue") or [])
        self.job_label=None
        self.job_built=0
        self.job_target=0
        self.job_row=0  # This job's row in the saved queue: finished rows leave it, skipped ones stay.
        self.loaded_index=1
        emit=self.emit
        def labelled(kind,payload=None):
            # While a queue runs, every status line says where it is: "Item 3 of 10: Holy Heal, 2 of 5 built · ...".
            if kind=="status" and self.job_label and not payload.startswith("Item "):
                payload=f"{self.job_progress()} · {payload.removeprefix(self.name+': ')}"
            emit(kind,payload)
        self.emit=labelled
        self.stop_at_slots=self.profile["construction"].get("stop_at_slots")
        self.count_slots=self.profile["construction"].get("count_slots",False) or self.stop_at_slots is not None
        self.slot_counts={i:0 for i in range(6)}
        self.slot_unread=0
        self.slot_na=0
        self.output_details=None
        self.source_cell=None
        self.search_mode=self.profile["construction"].get("search_mode","fast")
        self.last_inventory=None

    def job_progress(self):
        return f"{self.job_label}, {self.job_built}{f' of {self.job_target}' if self.job_target else ''} built"

    @staticmethod
    def same_window(a,b):
        return (a.x,a.y,a.scale)==(b.x,b.y,b.scale)

    def inventory_frame(self, inventory, point=None):
        # The game capture is the costly part of each hover. Read the Inventory
        # header/grid and nearby tooltip pixels only; final Processor/quantity
        # verification still uses a fresh full client capture.
        if not hasattr(self.backend,"capture_region"):return self.frame()
        self.guard()
        left,top=inventory.point(-24,-4);right,bottom=inventory.point(481,356)
        if point is not None:
            x,y=point;s=inventory.scale
            left=min(left,round(x-800*s));right=max(right,round(x+800*s))
            top=min(top,round(y-70*s));bottom=max(bottom,round(y+100*s))
        frame=self.backend.capture_region((left,top,right,bottom))
        self.guard()
        # A partial frame is never the only evidence used to relocate a window.
        # If its fresh header check fails, recapture the full bound client.
        try:self.detector.current_inventory(frame,inventory,checkpoint=self.guard)
        except NotFound:return self.frame()
        self.last_frame=frame
        return frame

    def scroll_inventory_down(self, known=None):
        # Clear hover text before measuring the scrollbar, then reacquire the
        # window immediately before directing a single wheel notch into it.
        self.move((24,80))
        self.wait(.04)
        frame=self.frame()
        # A known window needs only the cheap header check; failure relocates fully.
        inventory=(self.detector.current_inventory(frame,known,checkpoint=self.guard) if known is not None
                   else self.detector.inventory(frame,checkpoint=self.guard))
        before=self.detector.inventory_scroll_position(frame,inventory)
        start_window=inventory
        for _ in range(2):
            self.move(inventory.point(395,310))
            self.wait(.05)
            self.guard();self.backend.scroll(-1)
            # Keep the pointer inside while Neocron consumes its wheel event.
            for _ in range(3):
                self.wait(.06)
                frame=self.inventory_frame(inventory)
                current=self.detector.current_inventory(frame,inventory,checkpoint=self.guard)
                after=self.detector.inventory_scroll_position(frame,current)
                if after > before+.5:return current
                if after < before-.5:
                    raise Interrupted("Inventory scrolled unexpectedly upward. Check it before restarting.")
                inventory=current
        # Some RPOS setups ignore wheel input. Move the detected scrollbar
        # thumb by tiny, bounded steps and stop as soon as it actually advances.
        # Small steps retain overlapping rows rather than jumping whole pages.
        if hasattr(self.detector,"inventory_scrollbar"):
            for step in (1,2,3):
                frame=self.frame();inventory=self.detector.inventory(frame,checkpoint=self.guard)
                bar=self.detector.inventory_scrollbar(frame,inventory)
                if step==1 and known is not None and not self.same_window(inventory,start_window):
                    # 'before' was read against the reused anchor, which the
                    # header check tolerates up to ~3 px off. The wheel phase
                    # showed no movement on that consistent anchor, so
                    # re-baseline on this fresh one before nudging the thumb.
                    before=bar["position"]
                if bar["thumb_bottom"]>=bar["bottom"]-2:break
                start=bar["thumb"];end=[start[0],start[1]+step]
                self.move(start);self.guard();self.backend.button("left",True)
                try:
                    self.wait(.04);self.move(end);self.wait(.08)
                finally:self.backend.button("left",False)
                self.wait(.06)
                frame=self.inventory_frame(inventory)
                current=self.detector.current_inventory(frame,inventory,checkpoint=self.guard)
                after=self.detector.inventory_scroll_position(frame,current)
                if after>before+.5:return current
                # At the true bottom a thumb nudge can read as a small upward
                # shift; that is the end of Inventory, not a scrolling fault.
                if after<before-.5:break
        raise Interrupted(f"No verified {self.name} blueprint found in the remaining Inventory rows. "
                          "Inventory reached the bottom or did not respond to scrolling.")

    def scroll_inventory_to_top(self):
        """Wheel Inventory up until it stops moving, so a queued job searches all of it (search runs downward)."""
        self.move((24,80))
        self.wait(.04)
        frame=self.frame()
        inventory=self.detector.inventory(frame,checkpoint=self.guard)
        position=self.detector.inventory_scroll_position(frame,inventory)
        for _ in range(128):
            self.move(inventory.point(395,310))
            self.wait(.05)
            self.guard();self.backend.scroll(1)
            moved=False
            for _ in range(3):
                self.wait(.06)
                frame=self.inventory_frame(inventory)
                current=self.detector.current_inventory(frame,inventory,checkpoint=self.guard)
                after=self.detector.inventory_scroll_position(frame,current)
                inventory=current
                if after<position-.5:
                    position=after;moved=True;break
                if after>position+.5:
                    raise Interrupted("Inventory scrolled down while scrolling to the top. Check it before restarting.")
            if not moved:break
        # At the top, or the game ignores the wheel: drag a thumb that is not at the top of its rail up to it.
        if hasattr(self.detector,"inventory_scrollbar"):
            self.move((24,80));self.wait(.04)
            frame=self.frame();inventory=self.detector.inventory(frame,checkpoint=self.guard)
            bar=self.detector.inventory_scrollbar(frame,inventory)
            # The thumb rests a little inside its rail (2 px at scale 1, 3-5 px at 1.3-1.8).
            inset=4*inventory.scale
            if bar["thumb_top"]>bar["top"]+inset:
                start=bar["thumb"];end=[start[0],start[1]-(bar["thumb_top"]-bar["top"])]
                self.move(start);self.guard();self.backend.button("left",True)
                try:
                    self.wait(.04);self.move(end);self.wait(.08)
                finally:self.backend.button("left",False)
                self.move((24,80));self.wait(.06)
                frame=self.frame();inventory=self.detector.inventory(frame,checkpoint=self.guard)
                bar=self.detector.inventory_scrollbar(frame,inventory)
                if bar["thumb_top"]>bar["top"]+inset:
                    self.emit("status",f"{self.name}: Inventory did not scroll to the top; searching down from here.")
        self.move((24,80))

    def locate_blueprint(self):
        self.emit("status", f"{self.name}: {'fast datacube search' if self.search_mode=='fast' else 'thorough every-cell search'}.")
        relocations=0
        unreadable=0
        previous=None
        checked=set()
        reuse=getattr(self.detector,"known_inventory_reuse",False)
        known=self.last_inventory if reuse else None
        for page in range(128):
            frame=self.frame()
            extra={"known":known} if known is not None else {}
            if self.search_mode=="fast":
                proposal=getattr(self.detector,"fast_blueprint_candidates",self.detector.blueprint_candidates)
                inventory,candidates=proposal(frame,checkpoint=self.guard,**extra)
                if self.source_cell is not None:
                    _,grid=self.detector.inventory_cells(frame,checkpoint=self.guard,**({"known":inventory} if reuse else {}))
                    cached=next((c for c in grid if c["cell"]==self.source_cell),None)
                    if cached is not None and cached not in candidates:candidates.insert(0,cached)
            else:inventory,candidates=self.detector.inventory_cells(frame,checkpoint=self.guard,**extra)
            if reuse:known=self.last_inventory=inventory
            if page==0 and self.detector.quantity(frame,checkpoint=self.guard) is not None:
                raise Interrupted("A quantity dialog is already open. Resolve it before starting construction.")
            current_snapshot=snapshot(self.detector,frame,inventory) if hasattr(frame,"shape") else None
            reused=set()
            if previous is not None and current_snapshot is not None:
                shift,reused=checked_overlap(previous,current_snapshot,checked)
                if reused:
                    self.emit("status",f"{self.name}: reusing {len(reused)} checked cells after scrolling; scanning newly exposed/changed cells.")
            checked=set(reused)
            candidates=[c for c in candidates if c["cell"] not in reused]
            if self.search_mode=="fast":
                self.emit("status",f"{self.name}: checking {len(candidates)} possible datacube stacks in this view; other cells need no hover.")
            if page==0 and self.source_cell is not None:
                candidates.sort(key=lambda c:c["cell"]!=self.source_cell)
                self.emit("status",f"{self.name}: verifying the previous stack first in the freshly detected Inventory.")
            match=None
            relocated=False
            clear_hover=True
            for candidate in candidates:
                # Each cell is visited. Icon color/shape never decides whether
                # a cell deserves a tooltip check. A match is cleared/re-hovered
                # below, so a delayed tooltip cannot authorize the wrong cell.
                if clear_hover:
                    self.move((24,80));self.wait(.02)
                self.move(candidate["point"])
                identity=None
                for attempt in range(4):
                    self.wait((.10 if self.search_mode=="fast" else .035) if attempt==0 else .05 if attempt==1 else .035)
                    hover=self.inventory_frame(inventory,candidate["point"])
                    if not self.same_window(self.detector.current_inventory(hover,inventory,checkpoint=self.guard),inventory):
                        relocated=True
                        break
                    identity=self.detector.tooltip_recipe(hover,candidate["point"],inventory.scale)
                    if identity not in (None,"unknown"):
                        break
                    if self.search_mode!="fast" and identity is None and attempt==0 and current_snapshot is not None:
                        # All cells receive a hover. Only extra delayed-read
                        # attempts may be omitted for a visually empty cell.
                        if not (current_snapshot[candidate["cell"]]>.08).any():break
                    if identity is None and attempt>=1 and self.search_mode!="fast":break
                clear_hover=identity is not None
                if relocated:
                    break
                if identity==self.recipe:
                    # Do not inherit a previous cell's tooltip. Observe its
                    # disappearance outside Inventory before confirming this
                    # exact cell again from a newly displayed tooltip.
                    self.move((24,80))
                    for _ in range(8):
                        self.wait(.025)
                        cleared=self.frame()
                        if self.detector.tooltip_recipe(cleared,candidate["point"],inventory.scale) is None:break
                    else:
                        raise Interrupted("Previous blueprint tooltip did not clear. No transfer was attempted.")
                    current=self.detector.current_inventory(cleared,inventory,checkpoint=self.guard)
                    if not self.same_window(current,inventory):
                        relocated=True;break
                    self.move(candidate["point"])
                    for attempt in range(6):
                        self.wait(.065 if attempt==0 else .035)
                        hover=self.frame()
                        if not self.same_window(self.detector.current_inventory(hover,inventory,checkpoint=self.guard),inventory):
                            relocated=True;break
                        verified=self.detector.tooltip_recipe(hover,candidate["point"],inventory.scale)
                        if verified==self.recipe:match=candidate;break
                        if verified not in (None,"unknown"):break
                    if relocated or match:break
                elif identity=="unknown":
                    unreadable+=1
                empty=current_snapshot is not None and float((current_snapshot[candidate["cell"]]**2).sum())<.5
                # An occupied cell with no readable tooltip is still unresolved.
                # Do not let overlap reuse permanently hide that item later.
                if identity not in (None,"unknown") or empty:checked.add(candidate["cell"])
                if candidate["cell"][1]==7:
                    self.emit("status",f"{self.name}: searched row {candidate['cell'][0]+1}/6 on Inventory page {page+1}.")
            if relocated:
                relocations+=1
                previous=None;checked=set();known=None
                if relocations>=8:
                    raise Interrupted("Inventory kept moving during blueprint identification. No stale coordinates were used.")
                continue
            if match is None:
                # Snapshot after clearing hover so tooltip/cursor pixels do not
                # masquerade as changed item content in the overlapping rows.
                self.move((24,80));self.wait(.02)
                clean=self.inventory_frame(inventory)
                current=self.detector.current_inventory(clean,inventory,checkpoint=self.guard)
                if not self.same_window(current,inventory):
                    previous=None;checked=set();relocations+=1;known=None
                    if relocations>=8:raise Interrupted("Inventory kept moving during blueprint identification. No stale coordinates were used.")
                    continue
                previous=snapshot(self.detector,clean,current) if hasattr(clean,"shape") else None
                self.emit("status", f"{self.name}: not in these rows; scrolling Inventory down.")
                try:
                    scrolled=self.scroll_inventory_down(inventory if reuse else None)
                    if reuse and scrolled is not None:known=self.last_inventory=scrolled
                except Interrupted as exc:
                    if self.search_mode=="fast" and "reached the bottom" in str(exc):
                        raise Interrupted(f"{exc} If the blueprint uses an unrecognized icon, select Thorough every cell under Inventory search.") from exc
                    if unreadable:
                        raise Interrupted(f"{exc} {unreadable} unreadable blueprint observations were skipped; none authorized a transfer.") from exc
                    raise
                continue
            self.move((24,80))
            frame=self.frame()
            current=self.detector.current_inventory(frame,inventory,checkpoint=self.guard)
            if not self.same_window(current,inventory):
                relocations+=1
                previous=None;checked=set();known=None
                if relocations>=8:
                    raise Interrupted("Inventory kept moving during blueprint identification. No stale coordinates were used.")
                continue
            processor=self.detector.processor(frame,checkpoint=self.guard)
            if self.detector.quantity(frame,checkpoint=self.guard) is not None:
                raise Interrupted("A quantity dialog appeared during inventory search. No transfer was attempted.")
            if self.detector.construction_state(frame,processor,self.recipe)["busy"]:
                raise Interrupted("Processor is already working. Finish the current job before starting a construction batch.")
            index=self.loaded_index=self.detector.construction_input(frame,processor)
            self.emit("detected", {"processor":[processor.x,processor.y],"scale":processor.scale,"stacks":{}})
            self.source_cell=match["cell"]
            return match["point"],self.detector.input_point(processor,index)
        raise Interrupted("Inventory search limit reached. No verified blueprint was transferred.")

    def confirm_one(self, available):
        elapsed=0
        dialog=None
        while elapsed<self.settings["dialog_timeout"]:
            frame=self.frame()
            dialog=self.detector.quantity(frame,checkpoint=self.guard,**({"expected":True} if hasattr(self.detector,"quantity_dense") else {}))
            if dialog is not None:
                break
            if available in (1,None):
                processor=self.detector.processor(frame,checkpoint=self.guard)
                if self.detector.has_loaded_blueprint(frame,processor):
                    return
            self.wait(.1)
            elapsed+=.1
        if dialog is None:
            if available is not None and available>1:
                raise Interrupted("Expected blueprint quantity dialog was not detected. No construction was started.")
            return
        if not dialog.get("one"):
            self.click(dialog["field"])
            self.type_one()
            self.move((24,80))
            self.wait(self.settings["settle_seconds"])
        dialog=self.detector.quantity(self.frame(),checkpoint=self.guard)
        if dialog is None or not dialog.get("one"):
            raise Interrupted("Could not verify blueprint quantity 1. No construction was started.")
        self.click(dialog["ok"])
        self.move((24,80))
        self.wait(self.settings["settle_seconds"])
        if self.detector.quantity(self.frame(),checkpoint=self.guard) is not None:
            raise Interrupted("Blueprint quantity dialog did not close. No construction was started.")

    def gogo_enabled(self):
        return bool(self.profile["construction"].get("gogo_refill"))

    def inventory_destination(self, frame, inventory, code):
        """Point to drop an ingredient: its existing stack (merges) or the first empty cell."""
        gray=self.detector.gray(frame)
        left,top=inventory.point(39,63);right,bottom=inventory.point(39+8*44.6,63+6*45.5)
        words=self.detector.text_reader().read_words(gray[top:bottom,left:right])
        occupied=set()
        for text,x,y,w,h in words:
            col=int(x//(44.6*inventory.scale));row=int(y//(45.5*inventory.scale))
            if 0<=col<8 and 0<=row<6:
                occupied.add((row,col))
                if re.fullmatch(r"[A-Za-z]{3}",text.strip()) and text.strip().upper()==code:
                    return inventory.point(39+col*44.6+22.3,63+row*45.5+22.75)
        snapshot=self.detector.inventory_occupancy(frame,inventory) if hasattr(self.detector,"inventory_occupancy") else None
        for row in range(6):
            for col in range(8):
                busy=(row,col) in occupied or (snapshot is not None and snapshot[(row,col)])
                if not busy:return inventory.point(39+col*44.6+22.3,63+row*45.5+22.75)
        return None

    def enter_quantity(self, amount):
        """Open dialog from a GoGuardian drag: type the amount, confirm by reading it, press Ok."""
        elapsed=0.
        dialog=None
        while elapsed<self.settings["dialog_timeout"]:
            dialog=self.detector.quantity(self.frame(),checkpoint=self.guard,expected=True)
            if dialog is not None:break
            self.wait(.1);elapsed+=.1
        if dialog is None:
            raise Interrupted("Expected quantity dialog was not detected after the GoGuardian drag. Nothing was confirmed.")
        def field_number(frame,dialog):
            scale=dialog.get("scale") or 1.
            x,y=dialog["field"];r=max(8,round(9*scale));wide=round(22*scale)
            crop=self.detector.gray(frame[y-r:y+r,x-wide:x+wide])
            digits=re.sub(r"\D","",self.detector.read_text(cv2.resize(crop,None,fx=4,fy=4,interpolation=cv2.INTER_CUBIC)))
            return int(digits) if digits else (1 if dialog.get("one") else None)
        # The dialog opens at the last quantity entered (live: 1 left over from the blueprint
        # drag), not at the full stack. Always type the wanted amount and read it back; a
        # smaller shown number means the game clamped it to a smaller stack.
        if field_number(self.frame(),dialog)!=amount:
            for attempt in range(2):
                self.click(dialog["field"]);self.type_number(amount)
                self.move((24,80));self.wait(self.settings["settle_seconds"])
                frame=self.frame()
                dialog=self.detector.quantity(frame,checkpoint=self.guard)
                if dialog is None:raise Interrupted("Quantity dialog disappeared before confirmation.")
                shown=field_number(frame,dialog)
                # Small digits sometimes cannot be read at all; the typed amount was sent, and a
                # wrong amount here only changes how much moves into Inventory. A readable but
                # different number is still refused.
                if shown is not None and shown>amount:
                    raise Interrupted(f"Could not verify quantity {amount}. The dialog was left open; nothing was confirmed.")
                if shown is None or shown>1 or amount==1:break
        self.click(dialog["ok"]);self.move((24,80));self.wait(self.settings["settle_seconds"])
        if self.detector.quantity(self.frame(),checkpoint=self.guard) is not None:
            raise Interrupted("Quantity dialog did not close after the GoGuardian transfer.")

    def learn_gogo_labels(self,reader,window,cells,missing):
        """{ingredient: label} found by hovering GoGuardian stacks and reading the tooltip name."""
        learned={};todo=list(missing)
        for _,info in gogo.hover_order(cells,todo)[:gogo.MAX_HOVERS]:
            if not todo:break
            # The game hides a tooltip when the cursor leaves, so a stale one is never read.
            self.move((24,80));self.wait(.1)
            self.move(info["point"])
            last=None
            for attempt in range(4):
                self.wait(.3 if attempt==0 else .2)
                texts=gogo.tooltip_texts(reader,self.detector.gray(self.frame()),info["point"],window.scale)
                name=gogo.match_name(texts,todo)
                if name:
                    learned[name]=info["code"];todo.remove(name)
                    self.emit("status",f"GoGuardian: {name} is labelled {info['code']}.")
                    break
                if texts and texts==last:break
                last=texts
        self.move((24,80))
        return learned

    def refill_from_gogo(self):
        """Pull at most BATCH of each needed ingredient from an open GoGuardian into Inventory."""
        self.emit("status",f"{self.name}: materials ran out; refilling from GoGuardian.")
        frame=self.frame();gray=self.detector.gray(frame)
        reader=self.detector.text_reader()
        window=gogo.find_gogo(reader,gray,checkpoint=self.guard)
        if window is None:
            raise Interrupted("GoGuardian window not found. Open it with its Take All / Sort / Stack buttons visible, or turn off More Materials in GoGo.")
        codes=gogo.ingredients_for(self.recipe,self.profile)
        wanted=set((codes or {}).values())
        cells=gogo.read_cells(reader,gray,window,wanted)
        if codes:
            # A label may be a wrong guess. Learn it from the stacks' own tooltips instead of
            # relying on what the window happens to hold.
            seen={info["code"] for info in cells.values()}
            missing=[name for name,code in codes.items() if code not in seen]
            if missing and cells:
                learned=self.learn_gogo_labels(reader,window,cells,missing)
                if learned:
                    codes={**codes,**learned}
                    self.profile.setdefault("materials",{})[self.recipe]=dict(codes)
                    self.emit("materials",{"recipe":self.recipe,"codes":dict(codes)})
        try:plan=gogo.plan_refill(self.recipe,cells,codes)
        except LookupError as exc:raise OutOfMaterials(str(exc)) from None
        inventory=self.detector.inventory(frame,checkpoint=self.guard)
        for name,code,point,amount in plan:
            destination=self.inventory_destination(self.frame(),inventory,code)
            if destination is None:
                raise Interrupted("No free Inventory slot for the GoGuardian materials. Make room and restart.")
            self.emit("status",f"GoGuardian: moving {amount} {name} to Inventory.")
            self.drag(point,destination);self.move((24,80))
            self.enter_quantity(amount)
        return len(plan)

    def await_construction(self):
        self.output_details=None
        seen_busy=False
        idle=0
        polls=0
        started=self.clock()
        while True:
            frame,processor=self.processor_state()
            polls+=1
            # The dialog search is the costliest check (~150 ms) and a dialog
            # cannot appear by itself mid-build, so sample it periodically and
            # always before accepting completion. Faster polling sees the end
            # of a build sooner.
            state=self.detector.construction_state(frame,processor,self.recipe)
            if polls%4==1 or (seen_busy and not state["busy"] and idle>=2):
                if self.detector.quantity(frame,checkpoint=self.guard) is not None:
                    raise Interrupted("Unexpected quantity dialog during construction.")
            # A queue needs to know a refused Start too, to skip that job even without GoGuardian refills.
            if ((self.gogo_enabled() or getattr(self,"queue",None)) and not seen_busy and not state["busy"]
                    and self.clock()-started>=self.settings.get("refused_start_seconds",5.0)
                    and self.detector.has_loaded_blueprint(frame,processor)):
                return "refused"
            if state["busy"]:
                seen_busy=True
                idle=0
            elif seen_busy:
                idle+=1
                if idle>=3:
                    if self.recipes[self.recipe].get("result_template") is None:
                        self.output_details=self.inspect_result()
                        if self.output_details is None:
                            raise Interrupted(f"Construction ended but the result name could not be verified as {self.name}. Check the Processor.")
                        return
                    if not state["result"]:
                        raise Interrupted(f"Construction ended without a visible {self.name} result. Check supplies and the Processor.")
                    if self.count_slots:
                        self.output_details=self.inspect_result()
                    return
            self.wait(.05,safe_pause=True)

    def inspect_result(self):
        # Unknown items need no captured icon/template. Read the result's name
        # after observed progress and stable idle, before starting another job.
        for _ in range(16):
            frame,processor=self.processor_state()
            point=processor.point(421,110)
            self.move(point)
            self.wait(.06)
            frame,current=self.processor_state()
            if not self.same_window(current,processor):continue
            details=self.detector.result_details(frame,point,current.scale)
            if details is not None and details["recipe"]==self.recipe:
                self.move((24,80))
                return details
        self.move((24,80))
        return None

    def return_blueprint(self):
        """Drag a blueprint whose Start was refused back to a free Inventory cell, so the next job can load its own."""
        self.move((24,80))
        frame,processor=self.processor_state()
        if not self.detector.has_loaded_blueprint(frame,processor):return
        inventory=self.detector.inventory(frame,checkpoint=self.guard)
        destination=self.inventory_destination(frame,inventory,None)
        if destination is None:
            raise Interrupted(f"No free Inventory cell for the unbuilt {self.name} blueprint. Make room and restart.")
        self.emit("status",f"{self.name}: taking the unbuilt blueprint back to Inventory.")
        self.drag(self.detector.input_point(processor,self.loaded_index),destination)
        self.move((24,80))
        frame,processor=self.processor_state()
        if self.detector.quantity(frame,checkpoint=self.guard) is not None or self.detector.has_loaded_blueprint(frame,processor):
            raise Interrupted(f"The unbuilt {self.name} blueprint could not be taken back from the Processor. Check it before restarting.")

    def start_job(self, recipe):
        """Point the single-job flow at a queued recipe: its own name, blueprint stack and slot totals."""
        self.recipe=recipe
        self.name=self.recipes[recipe]["name"]
        self.source_cell=None
        self.slot_counts={i:0 for i in range(6)};self.slot_unread=0;self.slot_na=0

    def build_job(self, target, stack_unknown):
        """Build up to `target` of the current recipe. Returns (built, "finished" / "out_of_blueprints" / slots reached)."""
        config=self.profile["construction"]
        self.job_built=0
        for _ in range(target):
            try:source,destination=self.locate_blueprint()
            except Interrupted as exc:
                # With no stack size entered, running out of blueprints is how a batch ends.
                # A queued job that runs out is reported and the queue goes on.
                if str(exc).startswith("No verified") and (self.queue or stack_unknown and self.job_built>0):
                    return self.job_built,"out_of_blueprints"
                raise
            self.emit("status", f"{self.name}: transferring one blueprint; ingredients stay untouched.")
            self.drag(source,destination)
            self.move((24,80))
            self.confirm_one(None if stack_unknown else config["available"])
            frame,processor=self.processor_state()
            if self.detector.quantity(frame,checkpoint=self.guard) is not None:
                raise Interrupted("Quantity dialog is still open. No construction was started.")
            if not self.detector.has_loaded_blueprint(frame,processor):
                raise Interrupted("No loaded blueprint was recognized. No construction was started.")
            self.click(processor.start_point())
            self.move((24,80))
            self.emit("status", f"{self.name}: building; following Processor progress.")
            refills=0
            while self.await_construction()=="refused":
                if not self.gogo_enabled():
                    raise OutOfMaterials(f"Start was refused for {self.name}; its materials ran out.")
                refills+=1
                if refills>2:
                    raise OutOfMaterials("Start was refused again after refilling from GoGuardian. Check the recipe's materials.")
                self.refill_from_gogo()
                frame,processor=self.processor_state()
                self.click(processor.start_point());self.move((24,80))
                self.emit("status", f"{self.name}: building; following Processor progress.")
            self.completed+=1
            self.job_built+=1
            if not self.queue:config["available"]-=1
            event={"completed":self.job_built,"available":config["available"],
                   "remaining":target-self.job_built,"recipe":self.recipe}
            if self.job_label:
                event.update(job=self.job_number,jobs=len(self.queue),target=self.job_target)
            slots=None
            if self.count_slots:
                slots=self.output_details.get("slots") if self.output_details else None
                if slots is not None:self.slot_counts[slots]+=1
                elif self.recipes[self.recipe]["category"]=="Weapon parts":self.slot_na+=1
                else:self.slot_unread+=1
                event.update(slot_counts=self.slot_counts.copy(),slot_unread=self.slot_unread,slot_na=self.slot_na)
            self.emit("construction_cycle", event)
            if self.job_label and self.job_target:
                self.emit("queue_update",{"index":self.job_row,"count":target-self.job_built or None})
            if self.stop_at_slots is not None and slots is not None and slots>=self.stop_at_slots:
                return self.job_built,slots
        return self.job_built,"finished"

    def run_queue(self):
        """Each queued (recipe, count) runs as its own job; one short of blueprints or materials is reported and skipped.

        queue_update events keep the saved queue to what is left, so Start after a stop picks up where this one ended.
        """
        skipped=[]
        for number,row in enumerate(self.queue,1):
            self.start_job(row["recipe"])
            self.job_number,self.job_target,self.job_built=number,row["count"],0
            self.job_label=f"Item {number} of {len(self.queue)}: {self.name}"
            self.emit("queue_job",{"index":self.job_row,"recipe":self.recipe})
            self.emit("status","Scrolling Inventory to the top.")
            try:
                try:self.scroll_inventory_to_top()
                # No readable scrollbar proves nothing about the rows on show; the search decides.
                except NotFound as exc:self.emit("status",f"{exc} Searching down from here.")
                built,reason=self.build_job(row["count"] or 10000,True)
            except OutOfMaterials as exc:
                skipped.append(f"{self.name} (out of materials, {self.job_progress().rsplit(', ',1)[1]})")
                self.emit("status",f"{self.job_progress()}: skipped, out of materials. {exc}")
                self.return_blueprint()
                self.job_row+=1
                continue
            except RuntimeError as exc:  # Stops from the detector too (NotFound, Ambiguous) say where the queue was.
                raise Interrupted(f"{self.job_progress()}: {exc}") from None
            if reason=="out_of_blueprints" and (row["count"] or not built):
                skipped.append(f"{self.name} (out of blueprints, {self.job_progress().rsplit(', ',1)[1]})")
                hint=" If its icon is unusual, choose Thorough under Inventory search." if self.search_mode=="fast" else ""
                self.emit("status",f"{self.job_progress()}: skipped, out of blueprints.{hint}")
                self.job_row+=1
                continue
            if type(reason) is int:
                self.emit("status",f"{self.job_progress()}: stopped at {reason} slots; going on.")
            # A counted row that ran its full count has already left the queue.
            if not row["count"] or built<row["count"]:
                self.emit("queue_update",{"index":self.job_row,"count":None})
        self.job_label=None
        complete=len(self.queue)-len(skipped)
        self.emit("done",f"Queue finished: {complete} of {len(self.queue)} jobs complete, {self.completed} builds."
                  +(" Skipped, still queued: "+"; ".join(skipped)+"." if skipped else "")+" Final result remains in the Processor.")

    def execute(self):
        config=self.profile["construction"]
        # Fail before any inventory scan when a previous interrupted transfer
        # left an unprocessed item behind. Do not spend a whole search finding
        # the same stack only to discover that the Processor cannot accept it.
        frame,processor=self.processor_state()
        if self.detector.quantity(frame,checkpoint=self.guard) is not None:
            raise Interrupted("A quantity dialog is already open. Resolve it before starting construction.")
        if self.detector.construction_state(frame,processor,self.recipe)["busy"]:
            raise Interrupted("Processor is already working. Finish the current job before starting construction.")
        self.detector.construction_input(frame,processor)
        if self.queue:return self.run_queue()
        built,reason=self.build_job(config["count"] or config["available"],config["available"]>=10000)
        if reason=="out_of_blueprints":
            self.emit("done",f"Out of {self.name} blueprints after {built} builds. Final result remains in the Processor.")
        elif type(reason) is int:
            self.emit("done",f"Stopped on {self.name} with {reason} slots after {built} builds. "
                      "The matching result remains in the Processor.")
        else:
            self.emit("done", f"Finished {built} builds of {self.name}. Final result remains in the Processor.")
