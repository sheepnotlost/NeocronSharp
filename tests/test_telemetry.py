"""The NeocronSharp telemetry feed client, with a fake process instead of the game."""
import io
import time
import unittest

import telemetry

GOOD = ('{"t":1793247595255,"sector":1,"rotation":270,"x":-1631.0957,"y":-255.9,"z":828.47003,'
        '"fx":0.10506358,"fz":0.99446553,"heading":173.96918,"ok":true}')


class FakeProcess:
    def __init__(self, lines):
        self.stdout = io.StringIO("".join(line + "\n" for line in lines))
        self.stdin = io.StringIO()
        self.waited = False

    def wait(self, timeout=None):
        self.waited = True

    def kill(self):
        pass


class TelemetryTests(unittest.TestCase):
    def test_a_good_line_is_a_sample_and_an_error_line_is_not(self):
        sample = telemetry.parse(GOOD, now=5.0)
        self.assertEqual((sample.sector, sample.rotation, sample.x, sample.z), (1, 270.0, -1631.0957, 828.47003))
        self.assertAlmostEqual(sample.heading, 173.96918)
        self.assertIsNone(telemetry.parse('{"t":1,"ok":false,"error":"zoning"}'))
        self.assertIsNone(telemetry.parse("not json"))
        self.assertIsNone(telemetry.parse(GOOD.replace('"rotation":270', '"rotation":null')).rotation)

    def test_the_feed_keeps_the_newest_good_sample_and_forgets_stale_ones(self):
        process = FakeProcess([GOOD, '{"t":2,"ok":false,"error":"The game closed."}'])
        feed = telemetry.Feed(popen=lambda *a, **k: process, executable=__file__)
        deadline = time.monotonic() + 2
        while feed.latest() is None and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(feed.latest().sector, 1)
        time.sleep(.05)
        self.assertEqual(feed.error, "The game closed.")
        self.assertIsNone(feed.latest(now=time.monotonic() + telemetry.FRESH + 1))       # too old to steer by
        feed.close()
        self.assertTrue(process.waited)

    def test_without_neocronsharp_the_feed_is_simply_empty(self):
        feed = telemetry.Feed(executable="C:/nowhere/NeocronSharp.exe")
        self.assertIsNone(feed.latest())
        self.assertIn("not built", feed.error)
        feed.close()
