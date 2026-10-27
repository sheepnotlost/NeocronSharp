# Third-party software

The Tech Counter integrated into Neocron Macro Suite uses:
- **Tesseract OCR** (Apache License 2.0), https://github.com/tesseract-ocr/tesseract, with its English model, and the
  libraries it loads (Leptonica, libpng, libjpeg, libtiff, libwebp, zlib, zstd, OpenSSL and others) under their own licenses.
- **Python**, **NumPy**, **OpenCV**, **Pillow**, **pytesseract**, **mss** and **packaging**, under their own licenses (retained in runtime package metadata).
- The **Blinker** font (SIL Open Font License), https://fonts.google.com/specimen/Blinker.

Neocron is a trademark of its owners. This project is an unofficial fan tool and is not affiliated with them.

The suite's Tesseract executable, required DLLs and English model are in
`runtime/tesseract/`; the Tesseract license is included there. See UPSTREAM.md
for the imported counter's source revision and integration changes.
