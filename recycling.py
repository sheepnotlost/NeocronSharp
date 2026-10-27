"""Offline sourced recycling catalog and one prepared-Processor recycling run."""

import json
from pathlib import Path
from macro_core import Interrupted
from vision_runner import VisualRunner

CATALOG_PATH=Path(__file__).parent/"data/recycling_recipes.json"


def load_catalog(path=CATALOG_PATH):
    data=json.loads(Path(path).read_text(encoding="utf8"))
    recipes=data["recipes"]
    seen=set()
    for row in recipes:
        if row["id"] in seen or not row["name"] or not row["ingredients"]:
            raise ValueError("Invalid recycling catalog entry.")
        seen.add(row["id"])
        for part in row["ingredients"]:
            if type(part["quantity"]) is not int or part["quantity"]<1 or not part["name"]:
                raise ValueError("Invalid recycling ingredient quantity.")
    return data


def filter_recipes(recipes,query="",category="All"):
    query=query.casefold().strip()
    return [r for r in recipes if (category=="All" or r["category"]==category) and
            (not query or query in (r["name"]+" "+" ".join(i["name"] for i in r["ingredients"])).casefold())]


class RecyclingRunner(VisualRunner):
    """Click Start once on user-prepared inputs; never guess material transfers."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        recipe_id=self.profile["recycling"]["recipe"]
        self.recipe=next(r for r in load_catalog()["recipes"] if r["id"]==recipe_id)
        self.detector.recipes={recipe_id:{"name":self.recipe["name"],"aliases":()}}

    def execute(self):
        frame,processor=self.processor_state()
        if self.detector.quantity(frame,checkpoint=self.guard) is not None:
            raise Interrupted("Resolve the quantity dialog and prepare the recycling tool and inputs first.")
        seen_busy=self.detector.progress_busy(frame,processor)
        expected=self.detector.recipes
        self.detector.recipes={"recycling_tool":{"name":"Recycling Tool","aliases":("Recycling Device","Recycle Tool","Recycle Device"),"ignore_numbers":True}}
        verified=False
        try:
            for _ in range(16):
                frame,processor=self.processor_state()
                point=self.detector.input_point(processor,0)
                self.move(point);self.wait(.06)
                frame,current=self.processor_state()
                if (current.x,current.y,current.scale)!=(processor.x,processor.y,processor.scale):continue
                details=self.detector.result_details(frame,point,current.scale)
                if details is not None and details["recipe"]=="recycling_tool":verified=True;break
        finally:self.detector.recipes=expected
        if not verified:raise Interrupted("Recycling Tool name was not verified in Processor slot 1. No recycling was started.")
        frame,processor=self.processor_state()
        seen_busy=seen_busy or self.detector.progress_busy(frame,processor)
        if not seen_busy:
            self.click(processor.start_point())
            self.move((24,80))
        self.emit("status","Recycling prepared inputs; monitoring Processor progress.")
        idle=0
        while True:
            frame,processor=self.processor_state()
            if self.detector.progress_busy(frame,processor):seen_busy=True;idle=0
            elif seen_busy:
                idle+=1
                if idle>=3:break
            self.wait(.05,safe_pause=True)
        # Verify the selected product by name, without a recipe-specific icon.
        for _ in range(16):
            frame,processor=self.processor_state()
            point=processor.point(421,110)
            self.move(point)
            self.wait(.06)
            frame,current=self.processor_state()
            if (current.x,current.y,current.scale)!=(processor.x,processor.y,processor.scale):continue
            details=self.detector.result_details(frame,point,current.scale)
            if details is not None and details["recipe"]==self.recipe["id"]:
                self.completed=1
                self.move((24,80))
                self.emit("done",f"Recycled {self.recipe['name']}. Result remains in the Processor. Prepare inputs before another run.")
                return
        raise Interrupted("Recycling ended but the selected result name could not be verified. Check the Processor.")
