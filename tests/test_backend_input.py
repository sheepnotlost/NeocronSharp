"""New backend input: relative mouse motion and the W / Tab keys (SendInput is captured, not sent)."""
import os
import unittest

from windows_backend import WindowsBackend


@unittest.skipUnless(os.name == "nt", "Windows only")
class BackendInputTests(unittest.TestCase):
    def setUp(self):
        self.backend = WindowsBackend()
        self.sent = []
        self.backend.send = self.sent.append

    def test_relative_move_sends_a_move_event_with_the_deltas(self):
        self.backend.move_relative(-37, 5)
        event = self.sent[0]
        self.assertEqual(event.type, 0)
        self.assertEqual((event.mi.dx, event.mi.dy), (-37, 5))
        self.assertEqual(event.mi.dwFlags, 0x0001)        # MOUSEEVENTF_MOVE, not absolute

    def test_w_and_tab_are_scan_code_keys_and_tracked_for_release(self):
        self.backend.key("w", True)
        self.backend.key("tab", True)
        self.assertEqual([e.ki.wScan for e in self.sent], [0x11, 0x0F])
        self.assertEqual(self.backend.held_keys, {"w", "tab"})
        self.backend.key("w", False)
        self.assertEqual(self.sent[-1].ki.dwFlags, 0x0008 | 0x0002)   # scancode | keyup
        self.assertEqual(self.backend.held_keys, {"tab"})
