"""Local Windows OCR for game tooltip crops; no network or game input."""

import asyncio
import threading


class TextReader:
    def __init__(self):
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        self.engine=OcrEngine.try_create_from_language(Language("en-US"))
        if self.engine is None:
            raise RuntimeError("Windows English text recognition is unavailable. Enable English OCR in Windows language features.")
        self.owner=threading.get_ident()

    def read_words(self, gray, up=3):
        """[(text, x, y, w, h)] in the input's own pixel coordinates (light-on-dark text)."""
        from winrt.windows.graphics.imaging import SoftwareBitmap,BitmapPixelFormat,BitmapAlphaMode
        from winrt.windows.storage.streams import DataWriter
        from vision import cv2
        if threading.get_ident()!=self.owner:
            raise RuntimeError("Text reader must stay on its construction worker thread.")
        pad=10
        image=cv2.copyMakeBorder(cv2.resize(255-gray,None,fx=up,fy=up,interpolation=cv2.INTER_CUBIC),pad,pad,pad,pad,
                                cv2.BORDER_CONSTANT,value=255)
        writer=DataWriter()
        writer.write_bytes(cv2.cvtColor(image,cv2.COLOR_GRAY2BGRA).tobytes())
        bitmap=SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(),BitmapPixelFormat.BGRA8,
                                                       image.shape[1],image.shape[0],BitmapAlphaMode.IGNORE)
        async def recognize():
            return await self.engine.recognize_async(bitmap)
        try:
            result=asyncio.run(recognize())
            words=[]
            for line in result.lines:
                for word in line.words:
                    box=word.bounding_rect
                    words.append((word.text,round((box.x-pad)/up),round((box.y-pad)/up),round(box.width/up),round(box.height/up)))
            return words
        finally:
            bitmap.close()
            writer.close()

    def read(self, gray):
        from winrt.windows.graphics.imaging import SoftwareBitmap,BitmapPixelFormat,BitmapAlphaMode
        from winrt.windows.storage.streams import DataWriter
        from vision import cv2
        if threading.get_ident()!=self.owner:
            raise RuntimeError("Text reader must stay on its construction worker thread.")
        # Tooltip text is white on black. Remove its frame before this call;
        # an inverted, enlarged crop gives Windows clearer character shapes.
        image=cv2.copyMakeBorder(cv2.resize(255-gray,None,fx=3,fy=3),10,10,10,10,
                                cv2.BORDER_CONSTANT,value=255)
        writer=DataWriter()
        writer.write_bytes(cv2.cvtColor(image,cv2.COLOR_GRAY2BGRA).tobytes())
        bitmap=SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(),BitmapPixelFormat.BGRA8,
                                                       image.shape[1],image.shape[0],BitmapAlphaMode.IGNORE)
        async def recognize():
            return (await self.engine.recognize_async(bitmap)).text
        try:
            return asyncio.run(recognize())
        finally:
            bitmap.close()
            writer.close()
