"""Inkwell's hardware: the HC-SR04 distance sensor ("the eyes") and the ESP32 camera.

Both are read away from the Tk thread, so a slow sensor or a camera that does not
answer never freezes the desktop. The UI asks for the latest values when it needs them.

The distance sensor is wired straight to the Raspberry Pi's GPIO pins:

    HC-SR04 VCC  -> Pi 5 V    (physical pin 2)
    HC-SR04 GND  -> Pi GND    (physical pin 6)
    HC-SR04 TRIG -> GPIO 23   (physical pin 16)
    HC-SR04 ECHO -> 1 kΩ -> GPIO 24 (physical pin 18), and GPIO 24 -> 2 kΩ -> GND

The two resistors turn the sensor's 5 V echo into about 3.3 V, which the Pi can take.
"""

import statistics
import threading
import time
import urllib.error
import urllib.request

DEFAULT_TRIG = 23
DEFAULT_ECHO = 24
DEFAULT_CAMERA = 'http://192.168.4.1'   # the ELEGOO camera's own Wi-Fi network


# ================================================================ distance

class GpioDistance:
    """Reads an HC-SR04 through gpiozero's pins (gpiozero comes with Raspberry Pi OS).

    gpiozero's own DistanceSensor is not used: when the echo never arrives (a loose wire)
    it either waits for ever or reports 0 cm, and 0 cm would set off the warning. Here a
    missing echo simply gives no reading.
    """

    SPEED_OF_SOUND = 343.26     # metres per second, as gpiozero uses

    def __init__(self, trig, echo):
        try:
            from gpiozero import DigitalInputDevice, DigitalOutputDevice
        except ImportError:
            raise SensorError('gpiozero is not installed (sudo apt install python3-gpiozero)')
        self.trig_dev = self.echo_dev = None
        try:
            self.trig_dev = DigitalOutputDevice(trig)
            self.echo_dev = DigitalInputDevice(echo)
        except Exception as e:   # no GPIO on this computer, pins busy, permissions …
            self.close()
            raise SensorError('the GPIO pins could not be opened: %s' % e)
        self.trig_pin = self.trig_dev.pin
        self.echo_pin = self.echo_dev.pin
        self.factory = self.echo_dev.pin_factory
        self._edge_evt = threading.Event()
        self._rise = self._fall = None
        self.echo_pin.edges = 'both'
        self.echo_pin.when_changed = self._edge

    def _edge(self, ticks, state):
        if state:
            self._rise = ticks
        elif self._rise is not None:
            self._fall = ticks
            self._edge_evt.set()

    def read_cm(self):
        """One measurement in cm, or None when no echo came back in time."""
        if self.echo_pin.state:                 # still high from an earlier pulse
            return None
        self._edge_evt.clear()
        self._rise = self._fall = None
        self.trig_pin.state = True              # a 10 µs pulse starts a measurement
        time.sleep(0.00001)
        self.trig_pin.state = False
        if not self._edge_evt.wait(0.1):        # the longest echo is about 38 ms
            return None
        if self._rise is None or self._fall is None:
            return None
        seconds = self.factory.ticks_diff(self._fall, self._rise)
        if seconds <= 0 or seconds > 0.04:
            return None
        return seconds * self.SPEED_OF_SOUND / 2 * 100

    def close(self):
        for dev in (self.trig_dev, self.echo_dev):
            if dev is not None:
                try:
                    dev.close()
                except Exception:
                    pass


class SensorError(Exception):
    pass


class DistanceReader:
    """Keeps the latest distance in centimetres, read on a background thread.

    make() returns an object with read_cm() and close(); by default it opens the
    HC-SR04 on the given pins. Readings are smoothed with the median of the last
    five, so one stray echo does not set off the warning.
    """

    INTERVAL = 0.2
    RETRY = 5.0

    def __init__(self, trig=DEFAULT_TRIG, echo=DEFAULT_ECHO, make=None):
        self.trig, self.echo = trig, echo
        self._make = make or (lambda: GpioDistance(self.trig, self.echo))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._cm = None
        self._at = 0.0
        self.error = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name='quill-distance', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=2)
        self._thread = None
        with self._lock:
            self._cm = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def latest(self, max_age=2.0):
        """The smoothed distance in cm, or None when there is no recent reading."""
        with self._lock:
            if self._cm is None or time.monotonic() - self._at > max_age:
                return None
            return self._cm

    def _run(self):
        recent = []
        while not self._stop.is_set():
            try:
                dev = self._make()
            except Exception as e:
                self.error = str(e)
                self._stop.wait(self.RETRY)
                continue
            self.error = None
            try:
                while not self._stop.is_set():
                    cm = dev.read_cm()
                    if cm is not None and cm >= 0:
                        recent.append(float(cm))
                        del recent[:-5]
                        with self._lock:
                            self._cm = statistics.median(recent)
                            self._at = time.monotonic()
                    self._stop.wait(self.INTERVAL)
            except Exception as e:
                self.error = 'the sensor stopped answering: %s' % e
                recent.clear()
                self._stop.wait(self.RETRY)
            finally:
                try:
                    dev.close()
                except Exception:
                    pass


class TooClose:
    """Decides when to warn, from a stream of distances. Pure logic, so it is easy to test.

    The warning starts once the reading has stayed under `limit` for `hold` seconds,
    and ends once it has stayed `margin` cm beyond the limit for `release` seconds
    (or when the sensor stops giving readings). The gap stops it flickering at the edge.
    """

    def __init__(self, limit=30, hold=1.5, release=1.0, margin=5):
        self.limit, self.hold, self.release, self.margin = limit, hold, release, margin
        self.warning = False
        self._since = None

    def update(self, cm, now):
        """Feed one reading (None = no reading); returns whether to show the warning."""
        if cm is None:
            self.warning = False
            self._since = None
            return False
        if not self.warning:
            if cm < self.limit:
                if self._since is None:
                    self._since = now
                if now - self._since >= self.hold:
                    self.warning = True
                    self._since = None
            else:
                self._since = None
        else:
            if cm >= self.limit + self.margin:
                if self._since is None:
                    self._since = now
                if now - self._since >= self.release:
                    self.warning = False
                    self._since = None
            else:
                self._since = None
        return self.warning


# ================================================================ camera

class CameraError(Exception):
    pass


def camera_base(url):
    """Normalise what the person typed: 'http://' added, no trailing slash."""
    url = (url or '').strip() or DEFAULT_CAMERA
    if '://' not in url:
        url = 'http://' + url
    return url.rstrip('/')


# The camera is always on the local network, so never send its requests through a web proxy.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch_frame(base, timeout=4.0):
    """One JPEG picture from the camera's /capture page (ESP32 CameraWebServer)."""
    url = camera_base(base) + '/capture?_=%d' % int(time.time() * 1000)
    try:
        with _OPENER.open(url, timeout=timeout) as r:
            data = r.read(4 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as e:
        raise CameraError('the camera answered with error %d' % e.code)
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, 'reason', e)
        raise CameraError('the camera could not be reached (%s)' % reason)
    if len(data) > 4 * 1024 * 1024:
        raise CameraError('the camera sent a picture that is too large')
    if not data.startswith(b'\xff\xd8'):
        raise CameraError('the camera did not send a JPEG picture')
    return data


class CameraFeed:
    """Fetches pictures one after another on a background thread; latest() gives the newest."""

    def __init__(self, base, fps=6, fetch=None):
        self.base = base
        self.gap = 1.0 / max(1, fps)
        self._fetch = fetch or fetch_frame
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._frame = None
        self._seq = 0
        self.error = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name='quill-camera', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread = None

    def latest(self):
        """(sequence number, JPEG bytes) of the newest picture, or (0, None)."""
        with self._lock:
            return self._seq, self._frame

    def _run(self):
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                data = self._fetch(self.base)
            except Exception as e:
                self.error = str(e)
                self._stop.wait(2.0)
                continue
            self.error = None
            with self._lock:
                self._frame = data
                self._seq += 1
            self._stop.wait(max(0.0, self.gap - (time.monotonic() - t0)))
