"""The Quill sound engine: a small software synthesiser and mixer.

The browser version used the Web Audio API.  Python has no built-in
equivalent, so this module renders the same sounds itself (interface blips,
the alarm ring, Lyre's piano voices and drum kit, and music playback) and
sends them to the speakers through the best output it can find:

1. the `sounddevice` package, if it is installed (any system — best quality);
2. Windows: the built-in waveOut API through ctypes (no extra packages);
3. Linux: a pipe to `pw-cat`, `paplay` or `aplay`;
4. otherwise "clip mode": each sound is rendered to a short WAV file and played
   with `afplay` (macOS) or `winsound` (Windows).  Held notes then have a fixed
   length.

If no output exists at all, sounds are silently skipped.
"""

import array
import io
import math
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave

RATE = 22050
BLOCK = 512
TWO_PI = 2 * math.pi
_TABLE_N = 4096
_SINE = [math.sin(TWO_PI * i / _TABLE_N) for i in range(_TABLE_N)]


def midi_freq(m):
    return 440.0 * math.pow(2, (m - 69) / 12)


# ================================================================ automation (like AudioParam)

class Auto:
    """A value that changes over time through set / linear / exponential ramps."""

    def __init__(self, value=0.0):
        self.ev = []          # (time, kind, value) kept in time order
        self.t_prev = -1e9
        self.v_prev = value
        self.idx = 0

    def set(self, t, v):
        self._add(t, 's', v)
        return self

    def lin(self, t, v):
        self._add(t, 'l', v)
        return self

    def exp(self, t, v):
        self._add(t, 'e', max(1e-6, v))
        return self

    def _add(self, t, kind, v):
        i = len(self.ev)
        while i > self.idx and self.ev[i - 1][0] > t:
            i -= 1
        self.ev.insert(i, (t, kind, v))

    def value_at(self, t):
        ev = self.ev
        while self.idx < len(ev) and ev[self.idx][0] <= t:
            self.t_prev, _, self.v_prev = ev[self.idx]
            self.idx += 1
        if self.idx < len(ev):
            t1, kind, v1 = ev[self.idx]
            if kind == 'l':
                span = t1 - self.t_prev
                return v1 if span <= 0 else self.v_prev + (v1 - self.v_prev) * (t - self.t_prev) / span
            if kind == 'e':
                span = t1 - self.t_prev
                v0 = self.v_prev if self.v_prev > 0 else 1e-6
                return v1 if span <= 0 else v0 * math.pow(v1 / v0, (t - self.t_prev) / span)
        return self.v_prev

    def block(self, t0, n):
        dt = 1.0 / RATE
        return [self.value_at(t0 + i * dt) for i in range(n)]

    def cancel_after(self, t):
        """Like cancelScheduledValues + setValueAtTime(current) at time t."""
        v = self.value_at(t)
        self.ev = self.ev[:self.idx]
        self.set(t, v)
        return v


# ================================================================ oscillators and filters

def _wave(kind, p):
    """One sample of a waveform at phase p (0…1)."""
    if kind == 'sine':
        return _SINE[int(p * _TABLE_N) % _TABLE_N]
    if kind == 'square':
        return 1.0 if p < 0.5 else -1.0
    if kind == 'sawtooth':
        return 2.0 * p - 1.0
    # triangle
    return 4.0 * p - 1.0 if p < 0.5 else 3.0 - 4.0 * p


class Osc:
    def __init__(self, kind, freq):
        self.kind = kind
        self.freq = freq if isinstance(freq, Auto) else None
        self.f = 0.0 if isinstance(freq, Auto) else float(freq)
        self.p = 0.0

    def block(self, t0, n):
        out = [0.0] * n
        p = self.p
        kind = self.kind
        if self.freq is None:
            inc = self.f / RATE
            if kind == 'sine':
                tab, tn = _SINE, _TABLE_N
                for i in range(n):
                    out[i] = tab[int(p * tn)]
                    p += inc
                    if p >= 1.0:
                        p -= 1.0
            else:
                for i in range(n):
                    out[i] = _wave(kind, p)
                    p += inc
                    if p >= 1.0:
                        p -= 1.0
        else:
            dt = 1.0 / RATE
            for i in range(n):
                out[i] = _wave(kind, p)
                p += self.freq.value_at(t0 + i * dt) / RATE
                p -= int(p)
        self.p = p
        return out


class Biquad:
    """RBJ biquad filter (high-pass or band-pass)."""

    def __init__(self, kind, f0, q=0.7071):
        w0 = TWO_PI * f0 / RATE
        cw, sw = math.cos(w0), math.sin(w0)
        alpha = sw / (2 * q)
        if kind == 'highpass':
            b0, b1, b2 = (1 + cw) / 2, -(1 + cw), (1 + cw) / 2
        else:  # bandpass, constant 0 dB peak gain
            b0, b1, b2 = alpha, 0.0, -alpha
        a0, a1, a2 = 1 + alpha, -2 * cw, 1 - alpha
        self.c = (b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)
        self.x1 = self.x2 = self.y1 = self.y2 = 0.0

    def run(self, xs):
        b0, b1, b2, a1, a2 = self.c
        x1, x2, y1, y2 = self.x1, self.x2, self.y1, self.y2
        out = [0.0] * len(xs)
        for i, x in enumerate(xs):
            y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            x2, x1, y2, y1 = x1, x, y1, y
            out[i] = y
        self.x1, self.x2, self.y1, self.y2 = x1, x2, y1, y2
        return out


_NOISE = None


def _noise():
    global _NOISE
    if _NOISE is None:
        rnd = random.Random(7)
        _NOISE = [rnd.random() * 2 - 1 for _ in range(int(RATE * 0.6))]
    return _NOISE


# ================================================================ voices

class Voice:
    """Something that makes sound from `start` (engine seconds) until it is done."""

    start = 0.0
    stop_at = 1e18
    done = False

    def render(self, t0, n):
        raise NotImplementedError


class Tone(Voice):
    """Snd.tone(): one oscillator with a quick attack and an exponential fade."""

    def __init__(self, start, f, d, kind, vol):
        self.start = start
        self.osc = Osc(kind or 'sine', f)
        d = d or 0.15
        self.g = Auto(0.0001).set(start, 0.0001).exp(start + 0.012, max(0.0002, vol or 0.2)).exp(start + d, 0.0001)
        self.stop_at = start + d + 0.03

    def render(self, t0, n):
        s = self.osc.block(t0, n)
        g = self.g.block(t0, n)
        return [a * b for a, b in zip(s, g)]


INSTRUMENTS = {
    # name: ([(wave, frequency multiple, level)], peak, sustain, decay)
    'bell': ([('sine', 1, 1), ('sine', 2.76, .45), ('sine', 5.4, .2)], .22, .15, 1.2),
    'pluck': ([('triangle', 1, 1), ('sine', 2, .35)], .35, .05, .5),
    'organ': ([('sine', 1, 1), ('sine', 2, .5), ('sine', 3, .3), ('sine', 4, .2)], .2, .8, .05),
}


class Synth(Voice):
    """A held piano-style note (Lyre's voice()). Call release() to let it fade."""

    def __init__(self, start, midi, inst):
        self.start = start
        f = midi_freq(midi)
        if inst in INSTRUMENTS:
            parts, peak, sustain, decay = INSTRUMENTS[inst]
        else:
            parts, peak, sustain, decay = [(inst, 1, 1)], .28, .6, .25
            if inst in ('sawtooth', 'square'):
                peak = .13
        self.inst = inst
        self.oscs = [(Osc(w, f * mult), lvl) for w, mult, lvl in parts]
        self.g = Auto(0.0001).set(start, 0.0001).lin(start + .012, peak).exp(start + .012 + decay, max(.0002, peak * sustain))
        self.released = False

    def release(self, now):
        if self.released:
            return
        self.released = True
        t = max(now, self.start)
        self.g.cancel_after(t)
        self.g.exp(t + (.5 if self.inst in ('pluck', 'bell') else .22), .0001)
        self.stop_at = t + .6

    def render(self, t0, n):
        mix = [0.0] * n
        for osc, lvl in self.oscs:
            s = osc.block(t0, n)
            for i in range(n):
                mix[i] += s[i] * lvl
        g = self.g.block(t0, n)
        return [a * b for a, b in zip(mix, g)]


class Drum(Voice):
    """Lyre's four drums: 0 kick, 1 snare, 2 hat, 3 clap."""

    def __init__(self, start, kind):
        self.start = start
        self.kind = kind
        self.parts = []   # (source, filter or None, gain Auto)
        t = start
        if kind == 0:
            fq = Auto(160).set(t, 160).exp(t + .14, 42)
            self.parts.append((Osc('sine', fq), None, Auto().set(t, .95).exp(t + .38, .001)))
            self.stop_at = t + .4
        elif kind == 1:
            self.parts.append(('noise', Biquad('highpass', 1100), Auto().set(t, .45).exp(t + .2, .001)))
            fq = Auto(220).set(t, 220).exp(t + .08, 130)
            self.parts.append((Osc('triangle', fq), None, Auto().set(t, .4).exp(t + .12, .001)))
            self.stop_at = t + .22
        elif kind == 2:
            self.parts.append(('noise', Biquad('highpass', 7500), Auto().set(t, .28).exp(t + .06, .001)))
            self.stop_at = t + .08
        else:
            g = Auto(0.0001).set(t, .0001)
            for i in range(3):
                g.set(t + i * .012, .5).exp(t + i * .012 + .01, .02)
            g.set(t + .036, .5).exp(t + .22, .001)
            self.parts.append(('noise', Biquad('bandpass', 1600, .8), g))
            self.stop_at = t + .24
        self.npos = 0

    def render(self, t0, n):
        mix = [0.0] * n
        for src, flt, g in self.parts:
            if src == 'noise':
                nz = _noise()
                s = [nz[(self.npos + i) % len(nz)] for i in range(n)]
            else:
                s = src.block(t0, n)
            if flt is not None:
                s = flt.run(s)
            gv = g.block(t0, n)
            for i in range(n):
                mix[i] += s[i] * gv[i]
        self.npos += n
        return mix


class Sample(Voice):
    """Recorded sound (music playback). Samples are mono floats at RATE."""

    def __init__(self, start, samples, gain=1.0):
        self.start = start
        self.data = samples
        self.pos = 0
        self.gain = gain
        self.paused = False
        self.on_end = None

    @property
    def duration(self):
        return len(self.data) / RATE

    @property
    def position(self):
        return self.pos / RATE

    def seek(self, seconds):
        self.pos = int(max(0, min(len(self.data), seconds * RATE)))

    def render(self, t0, n):
        if self.paused:
            return None
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        if self.pos >= len(self.data):
            self.done = True
        if len(chunk) < n:
            chunk = list(chunk) + [0.0] * (n - len(chunk))
        g = self.gain
        return [x * g for x in chunk] if g != 1.0 else list(chunk)


# ================================================================ the engine

class Engine:
    def __init__(self):
        self.lock = threading.RLock()
        self.voices = []
        self.frames = 0          # frames rendered so far (the engine clock)
        self.volume = 0.7
        self.backend = None
        self.state = 'idle'      # idle | running | unavailable | clips
        self.last_block = [0.0] * BLOCK
        self._tried = False
        self._ring = None

    # ---- clock and start-up
    def now(self):
        if self.backend is not None and self.backend.clip:
            return time.monotonic()
        return self.frames / RATE

    def ensure(self):
        """Start the audio output the first time a sound is needed."""
        if self._tried:
            return self.backend is not None
        self._tried = True
        for factory in _backend_factories():
            try:
                b = factory(self)
                if b is not None:
                    self.backend = b
                    self.state = 'clips' if b.clip else 'running'
                    return True
            except Exception:
                continue
        self.state = 'unavailable'
        return False

    def add(self, v):
        if not self.ensure():
            return v
        if self.backend.clip:
            self.backend.play_voice(v)
        else:
            with self.lock:
                self.voices.append(v)
            self.backend.wake()
        return v

    def render(self, n):
        """Mix the next n frames; returns signed 16-bit mono samples."""
        with self.lock:
            t0 = self.frames / RATE
            mix = [0.0] * n
            alive = []
            for v in self.voices:
                if v.done or t0 >= v.stop_at:
                    if isinstance(v, Sample) and v.on_end and not getattr(v, '_ended', False):
                        v._ended = True
                        _call_soon(v.on_end)
                    continue
                if t0 + n / RATE <= v.start:
                    alive.append(v)
                    continue
                if v.start > t0:
                    # The voice begins inside this block: render only from its start.
                    skip = min(n - 1, int(round((v.start - t0) * RATE)))
                    s = v.render(v.start, n - skip)
                    if s is not None:
                        for i in range(n - skip):
                            mix[skip + i] += s[i]
                else:
                    s = v.render(t0, n)
                    if s is not None:
                        for i in range(n):
                            mix[i] += s[i]
                alive.append(v)
            self.voices = alive
            self.frames += n
            vol = self.volume
        self.last_block = mix
        out = array.array('h', [0]) * n
        for i, x in enumerate(mix):
            x *= vol
            if x > 1.0:
                x = 1.0
            elif x < -1.0:
                x = -1.0
            out[i] = int(x * 32767)
        return out

    def busy(self):
        with self.lock:
            return bool(self.voices)

    def close(self):
        if self.backend is not None:
            try:
                self.backend.close()
            except Exception:
                pass
        self.backend = None

    # ---- the sounds the system uses (Snd in the original)
    def tone(self, f, d=0.15, kind='sine', vol=0.2, when=0.0):
        if not self.ensure():
            return
        self.add(Tone(self.now() + (when or 0) + self._lead(), f, d, kind, vol))

    def _lead(self):
        return 0.01 if self.backend is not None and not self.backend.clip else 0.0

    def ui(self, kind):
        if kind == 'open':
            self.tone(520, .09, 'triangle', .05)
            self.tone(780, .12, 'triangle', .04, .05)
        elif kind == 'close':
            self.tone(600, .08, 'triangle', .04)
            self.tone(400, .1, 'triangle', .035, .05)
        elif kind == 'click':
            self.tone(900, .04, 'sine', .03)
        elif kind == 'error':
            self.tone(180, .2, 'square', .05)
        elif kind == 'notify':
            self.tone(880, .14, 'sine', .08)
            self.tone(1175, .22, 'sine', .07, .12)

    def beep(self):
        self.tone(988, .18, 'square', .09)
        self.tone(988, .18, 'square', .09, .24)
        self.tone(1319, .3, 'square', .09, .48)

    def drum(self, kind, at=None):
        if not self.ensure():
            return
        t = self.now() + self._lead() if at is None else at
        self.add(Drum(t, kind))

    def note(self, midi, inst):
        if not self.ensure():
            return None
        v = Synth(self.now() + self._lead(), midi, inst)
        if self.backend.clip:
            v.auto_release_at = v.start + 0.6   # clips cannot be held, so give notes a fixed length
        self.add(v)
        return v

    def release(self, v):
        if v is None or self.backend is None:
            return
        if self.backend.clip:
            return
        with self.lock:
            v.release(self.now())

    def play_samples(self, samples):
        if not self.ensure():
            return None
        if self.backend.clip:
            return None
        v = Sample(self.now() + self._lead(), samples)
        self.add(v)
        return v

    def stop_voice(self, v):
        with self.lock:
            v.done = True


_SOON = []


def _call_soon(fn):
    """Callbacks from the audio thread are collected and run by the UI timer."""
    _SOON.append(fn)


def run_pending_callbacks():
    while _SOON:
        fn = _SOON.pop(0)
        try:
            fn()
        except Exception:
            import traceback
            traceback.print_exc()


# ================================================================ outputs

class _Stream:
    clip = False

    def wake(self):
        pass

    def close(self):
        pass


class SoundDeviceOut(_Stream):
    def __init__(self, engine):
        import sounddevice as sd  # optional package
        self.engine = engine

        import numpy as np

        def cb(outdata, frames, t, status):
            outdata[:, 0] = np.frombuffer(self.engine.render(frames), dtype=np.int16)

        self.stream = sd.OutputStream(samplerate=RATE, channels=1, dtype='int16', blocksize=BLOCK, callback=cb,
                                      latency='low')
        self.stream.start()

    def close(self):
        self.stream.stop()
        self.stream.close()


class PacedThreadOut(_Stream):
    """Renders a little ahead of real time and writes to a sink in a thread."""

    lead = 0.08

    def __init__(self, engine):
        self.engine = engine
        self.alive = True
        self.idle_since = time.monotonic()
        self.cv = threading.Condition()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self.thread.start()

    def wake(self):
        with self.cv:
            self.cv.notify()

    def _loop(self):
        while self.alive:
            if not self.engine.busy() and time.monotonic() - self.idle_since > 8:
                self._sleep_sink()
                with self.cv:
                    self.cv.wait(timeout=0.5)
                continue
            if self.engine.busy():
                self.idle_since = time.monotonic()
            if not self._wake_sink():
                time.sleep(0.2)
                continue
            self._write(self.engine.render(BLOCK))

    def _sleep_sink(self):
        pass

    def _wake_sink(self):
        return True

    def close(self):
        self.alive = False
        self.wake()


class PipeOut(PacedThreadOut):
    """Linux: stream raw samples to pw-cat, paplay or aplay."""

    COMMANDS = [
        ['pw-cat', '--playback', '--format', 's16', '--rate', str(RATE), '--channels', '1', '--latency', '40ms', '-'],
        ['paplay', '--raw', '--format=s16le', '--rate=%d' % RATE, '--channels=1', '--latency-msec=40'],
        ['aplay', '-q', '-t', 'raw', '-f', 'S16_LE', '-r', str(RATE), '-c', '1', '-B', '60000'],
    ]

    def __init__(self, engine):
        super().__init__(engine)
        self.cmd = None
        for c in self.COMMANDS:
            if shutil.which(c[0]):
                self.cmd = c
                break
        if self.cmd is None:
            raise OSError('no audio command')
        self.proc = None
        self.t_start = 0.0
        self.written = 0
        self.start()

    def _wake_sink(self):
        if self.proc is None or self.proc.poll() is not None:
            try:
                self.proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL)
            except OSError:
                self.proc = None
                return False
            self.t_start = time.monotonic()
            self.written = 0
        # keep only a short lead over real time so sounds start promptly
        ahead = self.written / RATE - (time.monotonic() - self.t_start)
        if ahead > self.lead:
            time.sleep(min(0.05, ahead - self.lead))
        elif ahead < -0.25:  # fell behind (system was busy): resynchronise
            self.t_start = time.monotonic() - self.written / RATE
        return True

    def _write(self, samples):
        proc = self.proc
        if proc is None or not self.alive:
            return
        try:
            proc.stdin.write(samples.tobytes())
            proc.stdin.flush()
            self.written += len(samples)
        except (OSError, ValueError, AttributeError):
            self._sleep_sink()

    def _sleep_sink(self):
        if self.proc is not None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.terminate()
            except OSError:
                pass
            self.proc = None

    def close(self):
        super().close()
        self.thread.join(timeout=1.0)
        self._sleep_sink()


class WinWaveOut(PacedThreadOut):
    """Windows: the built-in waveOut API, double-buffered, through ctypes."""

    NBUF = 4

    def __init__(self, engine):
        import ctypes
        from ctypes import wintypes
        super().__init__(engine)
        self.ct = ctypes
        winmm = ctypes.WinDLL('winmm')

        class WAVEFORMATEX(ctypes.Structure):
            _fields_ = [('wFormatTag', wintypes.WORD), ('nChannels', wintypes.WORD),
                        ('nSamplesPerSec', wintypes.DWORD), ('nAvgBytesPerSec', wintypes.DWORD),
                        ('nBlockAlign', wintypes.WORD), ('wBitsPerSample', wintypes.WORD), ('cbSize', wintypes.WORD)]

        class WAVEHDR(ctypes.Structure):
            pass
        WAVEHDR._fields_ = [('lpData', ctypes.c_void_p), ('dwBufferLength', wintypes.DWORD),
                            ('dwBytesRecorded', wintypes.DWORD), ('dwUser', ctypes.c_size_t),
                            ('dwFlags', wintypes.DWORD), ('dwLoops', wintypes.DWORD),
                            ('lpNext', ctypes.POINTER(WAVEHDR)), ('reserved', ctypes.c_size_t)]
        self.WAVEHDR = WAVEHDR
        self.winmm = winmm
        winmm.waveOutOpen.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.UINT, ctypes.POINTER(WAVEFORMATEX),
                                      ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD]
        winmm.waveOutPrepareHeader.argtypes = [wintypes.HANDLE, ctypes.POINTER(WAVEHDR), wintypes.UINT]
        winmm.waveOutUnprepareHeader.argtypes = [wintypes.HANDLE, ctypes.POINTER(WAVEHDR), wintypes.UINT]
        winmm.waveOutWrite.argtypes = [wintypes.HANDLE, ctypes.POINTER(WAVEHDR), wintypes.UINT]
        winmm.waveOutReset.argtypes = [wintypes.HANDLE]
        winmm.waveOutClose.argtypes = [wintypes.HANDLE]
        fmt = WAVEFORMATEX(1, 1, RATE, RATE * 2, 2, 16, 0)
        self.handle = wintypes.HANDLE()
        WAVE_MAPPER = 0xFFFFFFFF
        if winmm.waveOutOpen(ctypes.byref(self.handle), WAVE_MAPPER, ctypes.byref(fmt), 0, 0, 0) != 0:
            raise OSError('waveOutOpen failed')
        self.bufs = [ctypes.create_string_buffer(BLOCK * 2) for _ in range(self.NBUF)]
        self.hdrs = []
        for b in self.bufs:
            h = WAVEHDR()
            h.lpData = ctypes.cast(b, ctypes.c_void_p)
            h.dwBufferLength = BLOCK * 2
            h.dwFlags = 0
            winmm.waveOutPrepareHeader(self.handle, ctypes.byref(h), ctypes.sizeof(WAVEHDR))
            h.dwFlags |= 0x1  # WHDR_DONE: free to fill
            self.hdrs.append(h)
        self.next = 0
        self.start()

    def _wake_sink(self):
        h = self.hdrs[self.next]
        waited = 0
        while not (h.dwFlags & 0x1) and self.alive and waited < 400:
            time.sleep(0.004)
            waited += 1
        return bool(h.dwFlags & 0x1)

    def _write(self, samples):
        h = self.hdrs[self.next]
        data = samples.tobytes()
        self.ct.memmove(self.bufs[self.next], data, len(data))
        h.dwFlags &= ~0x1
        self.winmm.waveOutWrite(self.handle, self.ct.byref(h), self.ct.sizeof(self.WAVEHDR))
        self.next = (self.next + 1) % self.NBUF

    def _sleep_sink(self):
        pass

    def close(self):
        super().close()
        self.thread.join(timeout=1.0)
        try:
            self.winmm.waveOutReset(self.handle)
            for h in self.hdrs:
                self.winmm.waveOutUnprepareHeader(self.handle, self.ct.byref(h), self.ct.sizeof(self.WAVEHDR))
            self.winmm.waveOutClose(self.handle)
        except Exception:
            pass


class ClipOut:
    """Fallback: render each sound to a WAV file and play it with the system player."""

    clip = True

    def __init__(self, engine):
        self.engine = engine
        if sys.platform == 'darwin' and shutil.which('afplay'):
            self.kind = 'afplay'
        elif sys.platform.startswith('win'):
            import winsound  # noqa: F401
            self.kind = 'winsound'
        else:
            raise OSError('no clip player')
        self.dir = tempfile.mkdtemp(prefix='quill-snd-')
        self.n = 0

    def play_voice(self, v):
        delay = max(0.0, v.start - time.monotonic())
        threading.Thread(target=self._play, args=(v, delay), daemon=True).start()

    def _play(self, v, delay):
        # Render on this thread, using a private clock that starts at v.start.
        frames = []
        t = v.start
        limit = min(v.stop_at, v.start + 4.0)
        release_at = getattr(v, 'auto_release_at', None)
        while t < limit and not v.done:
            if release_at is not None and t >= release_at and not v.released:
                v.release(t)
                limit = min(v.stop_at, limit)
            s = v.render(t, BLOCK)
            if s is None:
                break
            frames.extend(s)
            t += BLOCK / RATE
        if delay:
            time.sleep(delay)
        vol = self.engine.volume
        pcm = array.array('h', (int(max(-1.0, min(1.0, x * vol)) * 32767) for x in frames))
        self.n += 1
        path = os.path.join(self.dir, 'c%d.wav' % (self.n % 32))
        write_wav(path, pcm)
        try:
            if self.kind == 'afplay':
                subprocess.run(['afplay', path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            else:
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception:
            pass

    def wake(self):
        pass

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def _backend_factories():
    if os.environ.get('QUILL_OS_NO_SOUND'):
        return []
    out = []
    try:
        import sounddevice  # noqa: F401
        out.append(SoundDeviceOut)
    except Exception:
        pass
    if sys.platform.startswith('win'):
        out.append(WinWaveOut)
    elif sys.platform != 'darwin':
        out.append(PipeOut)
    out.append(ClipOut)
    return out


# ================================================================ files

def write_wav(path_or_file, pcm, rate=RATE):
    w = wave.open(path_or_file, 'wb')
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)
    if sys.byteorder == 'big':
        pcm = array.array('h', pcm)
        pcm.byteswap()
    w.writeframes(pcm.tobytes())
    w.close()


def decode_wav(data):
    """WAV bytes → mono float samples at RATE. Raises ValueError if unsupported."""
    try:
        w = wave.open(io.BytesIO(data), 'rb')
    except (wave.Error, EOFError) as e:
        raise ValueError(str(e))
    ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
    raw = w.readframes(n)
    w.close()
    if width == 1:
        vals = [(b - 128) / 128.0 for b in raw]
    elif width == 2:
        a = array.array('h')
        a.frombytes(raw[:len(raw) // 2 * 2])
        if sys.byteorder == 'big':
            a.byteswap()
        vals = [x / 32768.0 for x in a]
    elif width == 3:
        vals = [int.from_bytes(raw[i:i + 3], 'little', signed=True) / 8388608.0 for i in range(0, len(raw) - 2, 3)]
    elif width == 4:
        a = array.array('i')
        a.frombytes(raw[:len(raw) // 4 * 4])
        if sys.byteorder == 'big':
            a.byteswap()
        vals = [x / 2147483648.0 for x in a]
    else:
        raise ValueError('unsupported sample size')
    if ch > 1:
        vals = [sum(vals[i:i + ch]) / ch for i in range(0, len(vals) - ch + 1, ch)]
    return resample(vals, rate)


def resample(vals, rate):
    if rate == RATE or not vals:
        return vals
    ratio = rate / RATE
    n = int(len(vals) / ratio)
    out = [0.0] * n
    last = len(vals) - 1
    for i in range(n):
        x = i * ratio
        j = int(x)
        f = x - j
        a = vals[j]
        b = vals[j + 1] if j < last else a
        out[i] = a + (b - a) * f
    return out


def decode_audio(data, name):
    """Any audio file → mono floats at RATE, using WAV support, ffmpeg or afconvert.

    Returns (samples, None) or (None, message).
    """
    try:
        return decode_wav(data), None
    except ValueError:
        pass
    ext = os.path.splitext(name)[1] or '.bin'
    tmp = tempfile.mkdtemp(prefix='quill-dec-')
    src = os.path.join(tmp, 'in' + ext)
    dst = os.path.join(tmp, 'out.wav')
    try:
        with open(src, 'wb') as f:
            f.write(data)
        cmds = []
        if shutil.which('ffmpeg'):
            cmds.append(['ffmpeg', '-v', 'quiet', '-y', '-i', src, '-ac', '1', '-ar', str(RATE), '-f', 'wav', dst])
        if shutil.which('afconvert'):
            cmds.append(['afconvert', '-f', 'WAVE', '-d', 'LEI16@%d' % RATE, '-c', '1', src, dst])
        for cmd in cmds:
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=True)
                with open(dst, 'rb') as f:
                    return decode_wav(f.read()), None
            except (subprocess.SubprocessError, OSError, ValueError):
                continue
        return None, ('Quill can play WAV files directly. For %s files, install ffmpeg (ffmpeg.org) '
                      'and open the file again.' % ext.lstrip('.').upper())
    finally:
        try:
            for fn in os.listdir(tmp):
                os.unlink(os.path.join(tmp, fn))
            os.rmdir(tmp)
        except OSError:
            pass


def levels(block, bands=32):
    """Rough spectrum of the last mixed block, for the music visualiser (0…1 each)."""
    n = len(block)
    if not n:
        return [0.0] * bands
    out = []
    step = max(1, n // 128)
    xs = block[::step][:128]
    m = len(xs)
    for b in range(bands):
        k = 1 + b * (m // 2 - 1) / bands
        re_ = im = 0.0
        w = TWO_PI * k / m
        for i, x in enumerate(xs):
            re_ += x * math.cos(w * i)
            im -= x * math.sin(w * i)
        out.append(min(1.0, math.hypot(re_, im) / m * 6))
    return out


__all__ = ['Engine', 'RATE', 'decode_audio', 'decode_wav', 'write_wav', 'midi_freq', 'levels', 'run_pending_callbacks',
           'struct']
