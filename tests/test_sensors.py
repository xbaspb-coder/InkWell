"""Tests for the distance sensor logic and the camera connection (no hardware needed)."""

import http.server
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from quill_os.sensors import (CameraError, CameraFeed, DistanceReader, TooClose, camera_base,  # noqa: E402
                              fetch_frame)

JPEG = b'\xff\xd8\xff\xe0' + b'fake picture' + b'\xff\xd9'


class FakeSensor:
    def __init__(self, values):
        self.values = list(values)
        self.closed = False

    def read_cm(self):
        if len(self.values) > 1:
            return self.values.pop(0)
        return self.values[0]

    def close(self):
        self.closed = True


def wait_for(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


class TooCloseTest(unittest.TestCase):
    def test_needs_to_stay_close_before_warning(self):
        g = TooClose(limit=30, hold=1.5, release=1.0, margin=5)
        self.assertFalse(g.update(20, 0.0))
        self.assertFalse(g.update(20, 1.0))
        self.assertTrue(g.update(20, 1.5))

    def test_a_short_dip_does_not_warn(self):
        g = TooClose(limit=30, hold=1.5)
        g.update(20, 0.0)
        g.update(50, 1.0)            # moved back before the hold time
        self.assertFalse(g.update(20, 2.0))
        self.assertFalse(g.update(20, 3.4))
        self.assertTrue(g.update(20, 3.5))

    def test_release_needs_margin_and_time(self):
        g = TooClose(limit=30, hold=0, release=1.0, margin=5)
        self.assertTrue(g.update(20, 0.0))
        self.assertTrue(g.update(32, 1.0))   # past the limit but inside the margin: still warning
        self.assertTrue(g.update(32, 5.0))
        self.assertTrue(g.update(40, 6.0))   # far enough, but not for long enough yet
        self.assertTrue(g.update(40, 6.9))
        self.assertFalse(g.update(40, 7.0))

    def test_no_reading_clears_the_warning(self):
        g = TooClose(limit=30, hold=0)
        self.assertTrue(g.update(10, 0.0))
        self.assertFalse(g.update(None, 0.1))

    def test_exactly_at_the_limit_is_not_too_close(self):
        g = TooClose(limit=30, hold=0)
        self.assertFalse(g.update(30, 0.0))
        self.assertTrue(g.update(29.9, 0.1))


class DistanceReaderTest(unittest.TestCase):
    def test_median_smooths_a_stray_reading(self):
        sensor = FakeSensor([50, 50, 3, 50, 50])
        r = DistanceReader(make=lambda: sensor)
        r.INTERVAL = 0.01
        r.start()
        try:
            self.assertTrue(wait_for(lambda: sensor.values == [50]))
            time.sleep(0.05)
            self.assertEqual(r.latest(), 50)
        finally:
            r.stop()
        self.assertTrue(sensor.closed)
        self.assertIsNone(r.latest())

    def test_missing_sensor_reports_error_and_no_distance(self):
        def make():
            raise RuntimeError('no pins here')
        r = DistanceReader(make=make)
        r.start()
        try:
            self.assertTrue(wait_for(lambda: r.error is not None))
            self.assertIn('no pins here', r.error)
            self.assertIsNone(r.latest())
        finally:
            r.stop()

    def test_stale_reading_is_ignored(self):
        r = DistanceReader(make=lambda: FakeSensor([40]))
        r._cm, r._at = 40.0, time.monotonic() - 10
        self.assertIsNone(r.latest(max_age=2.0))


class Handler(http.server.BaseHTTPRequestHandler):
    mode = 'ok'

    def do_GET(self):
        if not self.path.startswith('/capture'):
            self.send_error(404)
            return
        if Handler.mode == 'error':
            self.send_error(500)
            return
        body = JPEG if Handler.mode == 'ok' else b'<html>not a picture</html>'
        self.send_response(200)
        self.send_header('Content-Type', 'image/jpeg')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class CameraTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.base = 'http://127.0.0.1:%d' % cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Handler.mode = 'ok'

    def test_camera_base(self):
        self.assertEqual(camera_base(''), 'http://192.168.4.1')
        self.assertEqual(camera_base('192.168.4.1/'), 'http://192.168.4.1')
        self.assertEqual(camera_base(' http://cam.local:8080/ '), 'http://cam.local:8080')

    def test_fetch_frame(self):
        self.assertEqual(fetch_frame(self.base + '/'), JPEG)

    def test_fetch_frame_errors(self):
        Handler.mode = 'error'
        with self.assertRaises(CameraError):
            fetch_frame(self.base)
        Handler.mode = 'html'
        with self.assertRaisesRegex(CameraError, 'JPEG'):
            fetch_frame(self.base)
        with self.assertRaisesRegex(CameraError, 'could not be reached'):
            fetch_frame('http://127.0.0.1:9', timeout=1)

    def test_feed_delivers_frames(self):
        feed = CameraFeed(self.base, fps=20)
        feed.start()
        try:
            self.assertTrue(wait_for(lambda: feed.latest()[0] >= 2))
            self.assertEqual(feed.latest()[1], JPEG)
            self.assertIsNone(feed.error)
        finally:
            feed.stop()

    def test_feed_reports_unreachable_camera(self):
        feed = CameraFeed('http://127.0.0.1:9')
        feed.start()
        try:
            self.assertTrue(wait_for(lambda: feed.error is not None, 6))
            self.assertEqual(feed.latest(), (0, None))
        finally:
            feed.stop()


if __name__ == '__main__':
    unittest.main()
