"""Iris — the camera: shows the ESP32 camera's picture live and takes photos into Pictures."""

import datetime as _dt
import io
import tkinter as tk

from .base import AppSpec, Inst
from ..imaging import HAVE_PIL
from ..sensors import CameraFeed, camera_base
from ..state import FILE_LIMIT, FIXED, STORE_LIMIT
from ..ui.widgets import Btn
from ..util import bytes_to_data_url

POLL_MS = 60


class App(AppSpec):
    id = 'iris'
    name = 'Iris'
    icon = '◉'
    bg = ('#5ad1c8', '#1f6f8b')
    w, h = 720, 520
    single = True               # the camera serves one picture at a time
    kw = 'camera photo picture webcam esp32 elegoo snapshot'
    about = 'Camera'

    def build(self, ctx):
        return Iris(ctx).inst


class Iris:
    def __init__(self, ctx, feed_factory=None):
        self.ctx = ctx
        os_ = self.os = ctx.os
        T = self.T = ctx.T
        self._factory = feed_factory or (lambda url: CameraFeed(url))
        self.feed = None
        self.paused = False
        self.seq = 0
        self.frame = None          # JPEG bytes of the picture on screen
        self.size = None           # its width and height
        self.photo = None
        self.shown_error = None
        self._job = None

        bar = tk.Frame(ctx.body, bd=0)
        T.style(bar, bg='bg2')
        bar.pack(fill='x')
        self.b_pause = Btn(bar, T, '⏸ Pause', self.toggle_pause, size='sm', bg='bg2')
        self.b_pause.pack(side='left', padx=(8, 2), pady=6)
        self.b_shot = Btn(bar, T, '📸 Take photo', self.take_photo, kind='pri', size='sm', bg='bg2')
        self.b_shot.pack(side='left', padx=2, pady=6)
        Btn(bar, T, '⟳ Reconnect', self.connect, size='sm', bg='bg2').pack(side='left', padx=2, pady=6)
        Btn(bar, T, '⚙', lambda: os_.wm.open('loom', {'page': 'sensors'}), kind='ibtn', size='sm', bg='bg2',
            tip='Camera settings').pack(side='right', padx=8, pady=6)
        line = tk.Frame(ctx.body, height=1, bd=0)
        T.style(line, bg='line')
        line.pack(fill='x')
        self.status = tk.Label(ctx.body, anchor='w', padx=12, pady=4, font=T.font('sans', 12), bd=0)
        T.style(self.status, bg='bg2', fg='fg2')
        self.status.pack(side='bottom', fill='x')
        self.stage = tk.Canvas(ctx.body, bd=0, highlightthickness=0)
        T.on(self.stage, lambda: self.stage.configure(bg=T['bg0']))
        self.stage.pack(fill='both', expand=True)
        self.stage.bind('<Configure>', lambda e: self.draw())
        self.inst = Inst(on_close=self.on_close, on_resize=self.draw, mem=lambda: 2 * 1024 * 1024)
        self.connect()

    # ---------------------------------------------------------- the feed
    def url(self):
        return camera_base(self.os.S['set'].get('camUrl'))

    def connect(self):
        if self.feed is not None:
            self.feed.stop()
        self.feed = self._factory(self.url())
        self.feed.start()
        self.seq = 0
        self.shown_error = None
        self.paused = False
        self.b_pause.set_text('⏸ Pause')
        self.set_status('Connecting to the camera at %s …' % self.url())
        if self.frame is None:
            self.draw()
        if self._job is None:
            self._job = self.ctx.body.after(POLL_MS, self._poll)

    def on_close(self):
        if self._job is not None:
            try:
                self.ctx.body.after_cancel(self._job)
            except (tk.TclError, ValueError):
                pass
            self._job = None
        if self.feed is not None:
            self.feed.stop()
            self.feed = None

    def _poll(self):
        self._job = None
        if not self.ctx.alive or self.feed is None:
            return
        try:
            seq, data = self.feed.latest()
            if seq != self.seq and data is not None and not self.paused:
                self.seq = seq
                self.frame = data
                self.shown_error = None
                self.draw()
            elif self.feed.error and self.feed.error != self.shown_error:
                self.shown_error = self.feed.error
                if self.frame is None:
                    self.draw()
                self.set_status('Camera not found: %s.' % self.feed.error)
        finally:
            if self.ctx.alive:
                self._job = self.ctx.body.after(POLL_MS, self._poll)

    def toggle_pause(self):
        self.paused = not self.paused
        self.b_pause.set_text('▶ Live' if self.paused else '⏸ Pause')
        self.set_status('Paused — press Live to continue.' if self.paused else 'Live')

    def set_status(self, text):
        try:
            self.status.configure(text=text)
        except tk.TclError:
            pass

    # ---------------------------------------------------------- drawing
    def draw(self):
        c = self.stage
        try:
            w, h = max(1, c.winfo_width()), max(1, c.winfo_height())
        except tk.TclError:
            return
        c.delete('all')
        T = self.T
        if self.frame is None:
            err = self.feed.error if self.feed is not None else None
            lines = ['◉', 'Looking for the camera…' if not err else 'The camera is not answering.']
            small = ('Check that the camera has power and that the Raspberry Pi is connected to the camera\'s Wi-Fi '
                     'network (ELEGOO-…). The address is set in Loom → Eyes & camera.') if err else self.url()
            c.create_text(w / 2, h / 2 - 40, text=lines[0], fill=T['fg2'], font=T.font('sans', 40))
            c.create_text(w / 2, h / 2 + 10, text=lines[1], fill=T['fg2'], font=T.font('sans', 15))
            c.create_text(w / 2, h / 2 + 46, text=small, fill=T['fg2'], font=T.font('sans', 12), width=min(460, w - 40),
                          justify='center')
            return
        if not HAVE_PIL:
            c.create_text(w / 2, h / 2, text='The camera is working, but showing its pictures needs Pillow.\n'
                                             'Install it with:  sudo apt install python3-pil python3-pil.imagetk\n'
                                             'Take photo still saves pictures to Pictures.',
                          fill=T['fg2'], font=T.font('sans', 13), justify='center', width=min(520, w - 40))
            self.set_status('Live (pictures not shown: Pillow is missing)')
            return
        from PIL import Image, ImageTk
        try:
            im = Image.open(io.BytesIO(self.frame))
            im.load()
        except Exception:
            self.set_status('The camera sent a picture that could not be read.')
            return
        self.size = im.size
        k = min(w / im.width, h / im.height)
        nw, nh = max(1, int(im.width * k)), max(1, int(im.height * k))
        im = im.resize((nw, nh), Image.BILINEAR)
        self.photo = ImageTk.PhotoImage(im, master=c)
        c.create_image(w // 2, h // 2, image=self.photo, anchor='center')
        if not self.paused:
            self.set_status('Live · %d × %d · %s' % (self.size[0], self.size[1], self.url()))

    # ---------------------------------------------------------- photos
    def take_photo(self):
        os_ = self.os
        data = self.frame
        if data is None:
            os_.toast('No picture from the camera yet.', '⚠️')
            return None
        if len(data) > FILE_LIMIT or os_.fs.usage() + len(data) * 1.4 > STORE_LIMIT - 200000:
            os_.toast('Not enough storage left for the photo. Delete or export some files in Atlas.', '⚠️')
            return None
        name = 'Photo %s.jpg' % _dt.datetime.now().strftime('%Y-%m-%d %H-%M-%S')
        n = os_.fs.mk(FIXED['pictures'], name, 'f', bytes_to_data_url(data, 'image/jpeg'), {'b': 1})
        os_.ui_sound('click')
        self.flash()
        os_.toast('Saved to Pictures as ' + n['n'], '📸')
        return n

    def flash(self):
        c = self.stage
        try:
            r = c.create_rectangle(0, 0, c.winfo_width(), c.winfo_height(), fill='#ffffff', outline='')
            c.after(90, lambda: c.delete(r))
        except tk.TclError:
            pass
