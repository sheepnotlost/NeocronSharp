"""An item's picture beside its recipe text, on the Recycling and Catalog tabs. It grows with the window.

Pictures come from Tech Haven on PictureLoader's worker thread (see item_images.py); the app hands each result to
the slot showing that recipe. A slot only asks while its tab is open in a shown window.
"""
from tkinter import ttk

from item_images import fit

WELL_MIN = 136          # px: the slot at the default window size
WELL_MAX = 420          # px: the most it grows to
TEXT_ROOM = 360         # px kept beside the picture for the recipe's text
HEIGHT_SHARE = .55      # of the pane's height, at most
PICTURE_DELAY_MS = 150  # let the selection settle before looking a picture up
RESIZE_MS = 80          # redraw once the window stops changing size
PICTURE_TEXT = {"loading": "Loading\npicture…", "missing": "No picture on\nTech Haven",
                "failed": "No answer from\nTech Haven"}


def well_size(width, height):
    """The slot's side for a details pane of this size: fills the room the text leaves, within its limits."""
    size = min(WELL_MAX, width - TEXT_ROOM, int(height * HEIGHT_SHARE))
    return max(WELL_MIN, size - size % 4)


class PictureSlot:
    """One picture well. ``selected()`` gives the row on show; ``recipe_of(row)`` what PictureLoader looks up."""

    def __init__(self, app, parent, tab, selected, recipe_of=None, pane=None):
        self.app, self.tab, self.selected = app, tab, selected
        self.recipe_of = recipe_of or (lambda row: row)
        self.size = WELL_MIN
        self.well = ttk.Frame(parent, style="Picture.TFrame", width=WELL_MIN, height=WELL_MIN)
        self.well.pack_propagate(False)  # A fixed slot, so nothing moves when the picture loads.
        self.label = ttk.Label(self.well, style="Picture.TLabel", anchor="center", justify="center")
        self.label.pack(fill="both", expand=True, padx=1, pady=1)
        self.shown = None   # (recipe id, PIL image as Tech Haven gave it)
        self.photo = None
        self._after = None
        self._resize = None
        if pane is not None:
            pane.bind("<Configure>", lambda event: self.fit_to(event.width, event.height), add="+")

    def fit_to(self, width, height):
        size = well_size(width, height)
        if size == self.size:
            return
        self.size = size
        self.well.configure(width=size, height=size)
        if self._resize is not None:
            self.app.root.after_cancel(self._resize)
        self._resize = self.app.root.after(RESIZE_MS, self._redraw)

    def _redraw(self):
        self._resize = None
        if self.shown is not None:
            self.set(self.shown, "")

    def visible(self):
        return self.app.pictures_visible(self.tab)

    def queue(self):
        """Ask for the selected row's picture once the selection settles (arrow-key scrolling skips rows)."""
        if self._after is not None:
            self.app.root.after_cancel(self._after)
            self._after = None
        row = self.selected()
        if row is None:
            self.set(None, "")
            return
        if self.shown is not None and self.shown[0] == row["id"]:
            return
        self.set(None, "")
        if self.visible():
            self._after = self.app.root.after(PICTURE_DELAY_MS, lambda: self._request(row["id"]))

    def _request(self, recipe_id):
        self._after = None
        row = self.selected()
        if row is not None and row["id"] == recipe_id and self.visible():
            self.app.picture_loader.request(self.recipe_of(row))

    def show(self, recipe_id, state, image):
        """Take a loader result if it is for this slot's row; False when it belongs elsewhere or is stale."""
        row = self.selected()
        if row is None or row["id"] != recipe_id:
            return False
        if state == "ok" and image is not None:
            self.set((recipe_id, image), "")
        else:
            self.set(None, PICTURE_TEXT.get(state, ""))
        return True

    def set(self, shown, text):
        self.shown = shown
        self.photo = None
        if shown is not None:
            from PIL import Image, ImageTk
            image = fit(shown[1], self.size - 8)
            if image.mode == "RGBA":  # Flatten onto the slot colour so the edges match every skin.
                flat = Image.new("RGB", image.size, self.app.skin_rgb("input"))
                flat.paste(image, mask=image.getchannel("A"))
                image = flat
            self.photo = ImageTk.PhotoImage(image, master=self.app.root)
        self.label.configure(image=self.photo or "", text=text)
