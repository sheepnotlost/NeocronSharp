"""Native calls are replaced: these checks never capture the desktop."""
import ctypes
import unittest
from unittest.mock import Mock,call

from windows_backend import WindowsBackend


class RegionCaptureTests(unittest.TestCase):
    def test_cropped_bitblt_preserves_client_coordinates_and_full_size_focus_checks(self):
        backend=object.__new__(WindowsBackend)
        backend.client_size=Mock(return_value=(2560,1440))
        backend.origin=Mock(return_value=(100,200))
        backend.check_focus=Mock()
        backend.user=Mock();backend.user.GetDC.return_value=1
        backend.gdi=Mock()
        for name in ("CreateCompatibleDC","CreateCompatibleBitmap","SelectObject","BitBlt"):
            getattr(backend.gdi,name).return_value=1
        def pixels(dc,bitmap,start,height,buffer,info,mode):
            header=info._obj.header
            ctypes.memset(buffer,255,header.width*height*4)
            return height
        backend.gdi.GetDIBits.side_effect=pixels
        frame=backend.capture_region((1500,400,2100,900))
        self.assertEqual(frame.shape,(1440,2560,3))
        self.assertTrue((frame[400:900,1500:2100]==255).all())
        self.assertFalse(frame[:400].any())
        self.assertEqual(backend.check_focus.call_args_list,[call([2560,1440]),call([2560,1440])])
        self.assertEqual(backend.gdi.BitBlt.call_args.args[3:5],(600,500))
        self.assertEqual(backend.gdi.BitBlt.call_args.args[6:8],(1600,600))
