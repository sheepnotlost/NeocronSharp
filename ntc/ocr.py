import os

import cv2
import pytesseract

from .config import SUITE_ROOT

INSTALL_URL = "https://github.com/UB-Mannheim/tesseract/wiki"


BUNDLED = SUITE_ROOT / "runtime" / "tesseract"


def configure(tesseract_path):
    """Use the Tesseract bundled with the .exe if there is one, else the configured path."""
    bundled = BUNDLED / "tesseract.exe"
    if bundled.exists():
        pytesseract.pytesseract.tesseract_cmd = str(bundled)
        os.environ["TESSDATA_PREFIX"] = str(BUNDLED / "tessdata")
    elif os.path.exists(tesseract_path):
        pytesseract.pytesseract.tesseract_cmd = tesseract_path


def available():
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def require():
    if not available():
        raise RuntimeError(f"Tesseract OCR not found. Install it from {INSTALL_URL} (default path), "
                           "or set tesseract_path in config.json.")


def _prep(gray, scale):
    big = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(big, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)


def read_tooltip_text(crop_bgr):
    """OCR tooltip text (white on black)."""
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    img = 255 - gray
    text = pytesseract.image_to_string(_prep(img, 3), config="--psm 7")
    return " ".join(text.split())
