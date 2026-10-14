"""The eye guard: covers the screen while someone sits too close to it.

The HC-SR04 distance sensor (see sensors.py) is read in the background; four
times a second the guard asks for the latest distance and shows or hides the
warning. The settings live in Loom → Eyes & camera.
"""

import glob
import time
import tkinter as tk

from ..sensors import DEFAULT_ECHO, DEFAULT_TRIG, DistanceReader, SensorError, TooClose
from .overlays import full_layer
from .widgets import Btn

TICK_MS = 250
SNOOZE_S = 5 * 60


def gpio_present():
    """Whether this computer has GPIO pins at all (a Raspberry Pi does; an ordinary PC does not)."""
    return bool(glob.glob('/dev/gpiochip*'))


class Eyes:
    def __init__(self, os_, make=None):
        self.os = os_
        self._make = make           # tests pass a fake sensor here
        self.reader = None
        self.logic = TooClose()
        self.layer = None
        self.snooze_until = 0.0
        self._pins = None
        self._job = None

    # ---------------------------------------------------------- settings
    def settings(self):
        s = self.os.S['set']
        return (bool(s.get('eyes', True)), int(s.get('eyesCm', 30)),
                int(s.get('eyesTrig', DEFAULT_TRIG)), int(s.get('eyesEcho', DEFAULT_ECHO)))

    def apply(self):
        """Start, stop or reconfigure after the settings change."""
        on, limit, trig, echo = self.settings()
        self.logic.limit = limit
        if not on:
            self._stop_reader()
            self.hide()
            return
        if self.reader is None or self._pins != (trig, echo):
            self._stop_reader()
            self._pins = (trig, echo)
            make = self._make
            if make is None:
                if gpio_present():
                    make = None          # DistanceReader opens the real sensor
                else:
                    def make():
                        raise SensorError('this computer has no GPIO pins, so the distance sensor cannot be read here')
            self.reader = DistanceReader(trig, echo, make)
            self.reader.start()
        if self._job is None:
            self._job = self.os.root.after(TICK_MS, self._tick)

    def _stop_reader(self):
        if self.reader is not None:
            self.reader.stop()
            self.reader = None

    def close(self):
        if self._job is not None:
            try:
                self.os.root.after_cancel(self._job)
            except (tk.TclError, ValueError):
                pass
            self._job = None
        self._stop_reader()

    # ---------------------------------------------------------- state for Loom and the shell
    def distance(self):
        return self.reader.latest() if self.reader is not None else None

    def status(self):
        """One line describing what the sensor is doing."""
        on = self.settings()[0]
        if not on:
            return 'The eye guard is off.'
        if self.reader is None:
            return 'Starting…'
        cm = self.reader.latest()
        if cm is not None:
            return '%.0f cm from the screen.' % cm
        if self.reader.error:
            return 'Sensor not found: %s.' % self.reader.error
        return 'Waiting for the sensor…'

    def snooze(self):
        self.snooze_until = time.monotonic() + SNOOZE_S
        self.hide()
        self.os.toast('Distance warning hidden for 5 minutes', '👀')

    # ---------------------------------------------------------- the loop
    def _blocked(self):
        """Times when the warning should not cover the screen."""
        os_ = self.os
        return (os_.quitting or os_.boot.el is not None or os_.lock.active or getattr(os_, 'powered_off', False)
                or time.monotonic() < self.snooze_until)

    def _tick(self):
        self._job = None
        if self.os.quitting:
            return
        try:
            on = self.settings()[0]
            if on and self.reader is not None:
                cm = self.reader.latest()
                warn = self.logic.update(cm, time.monotonic())
                if warn and not self._blocked():
                    self.show(cm)
                else:
                    self.hide()
        finally:
            if self.settings()[0] and not self.os.quitting:
                self._job = self.os.root.after(TICK_MS, self._tick)

    # ---------------------------------------------------------- the warning
    def show(self, cm):
        """Cover the screen. Everything is drawn on the background canvas (like the lock
        screen), so no box hides the soft gradient; only the button is a widget (it is filled,
        so it needs no matching background)."""
        os_ = self.os
        T = os_.theme
        self.text = ('Move back to at least %d cm to keep your eyes healthy.' % self.logic.limit,
                     '%.0f cm' % cm if cm is not None else '')
        if self.layer is None:
            c = self.layer = full_layer(os_, 'eyes')
            self.btn = Btn(c, T, 'Hide for 5 minutes', self.snooze)

            def layout(_e=None):
                c.delete('content')
                w, h = c.winfo_width(), c.winfo_height()
                cx, cy = w / 2, h / 2
                wrap = max(200, min(560, w - 40))
                c.create_text(cx, cy - 120, text='👀', fill=T['fg'], font=T.font('sans', 52), tags='content')
                c.create_text(cx, cy - 52, text='Too close to the screen', fill=T['fg'], width=wrap, justify='center',
                              font=T.font('serif', 26, 'bold', 'italic'), tags='content')
                c.create_text(cx, cy - 6, text=self.text[0], fill=T['fg2'], width=wrap, justify='center',
                              font=T.font('sans', 15), tags=('content', 'msg'))
                c.create_text(cx, cy + 48, text=self.text[1], fill=T['acc'], font=T.font('sans', 34, 'bold'),
                              tags=('content', 'now'))
                c.create_window(cx, cy + 108, window=self.btn, tags='content')
            self._layout = layout
            c.bind('<Configure>', layout, add='+')
            T.on(c, layout)
            layout()
            os_.ui_sound('notify')
        else:
            self.layer.itemconfigure('msg', text=self.text[0])
            self.layer.itemconfigure('now', text=self.text[1])
        tk.Misc.lift(self.layer)

    @property
    def now_text(self):
        return self.text[1] if self.layer is not None else ''

    def hide(self):
        if self.layer is not None:
            try:
                self.layer.destroy()
            except tk.TclError:
                pass
            self.layer = None

    @property
    def showing(self):
        return self.layer is not None
