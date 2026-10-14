"""Lens — image viewer."""

import io
import os
import tempfile
import tkinter as tk

from .base import AppSpec, Inst
from ..core import kind_of
from ..imaging import HAVE_PIL, parse_ppm, photo_from_bytes, ppm
from ..ui.widgets import Btn
from ..util import clamp, fmt_bytes


def rotate_rgb(w, h, rgb, deg):
    """Rotate RGB pixels clockwise by 90, 180 or 270 degrees. Returns (w, h, rgb)."""
    deg %= 360
    if deg == 0:
        return w, h, rgb
    stride = w * 3
    if deg == 180:
        out = bytearray(len(rgb))
        for c in range(3):
            out[c::3] = rgb[c::3][::-1]
        return w, h, out
    out = bytearray(len(rgb))
    nw = h
    for r in range(w):           # each new row is one old column
        x = r if deg == 90 else w - 1 - r
        row = bytearray(nw * 3)
        for c in range(3):
            col = rgb[x * 3 + c::stride]
            row[c::3] = col[::-1] if deg == 90 else col
        out[r * nw * 3:(r + 1) * nw * 3] = row
    return h, w, out


class App(AppSpec):
    id = 'lens'
    name = 'Lens'
    icon = '◍'
    bg = ('#55c6ff', '#2a58d6')
    w, h = 800, 560
    kw = 'image viewer photos pictures gallery png jpg svg wallpaper'
    about = 'Image viewer'

    def build(self, ctx):
        return Lens(ctx).inst


class Lens:
    def __init__(self, ctx):
        self.ctx = ctx
        os_ = self.os = ctx.os
        T = self.T = ctx.T
        self.fs = os_.fs
        self.cur = None
        self.zoom, self.rot, self.px, self.py, self.fit = 1.0, 0, 0.0, 0.0, True
        self.src = None          # PIL image or Tk PhotoImage, already rotated
        self.src_size = (1, 1)
        self.shown = None
        self.drag = None
        body = ctx.body
        bar = tk.Frame(body, bd=0)
        T.style(bar, bg='bg2')
        bar.pack(fill='x')
        line = tk.Frame(body, height=1, bd=0)
        T.style(line, bg='line')
        line.pack(fill='x')
        ib = lambda text, fn, tip: Btn(bar, T, text, fn, kind='ibtn', tip=tip)  # noqa: E731
        ib('◀', lambda: self.go(-1), 'Previous (←)').pack(side='left', padx=(8, 0), pady=6)
        ib('▶', lambda: self.go(1), 'Next (→)').pack(side='left')
        self._sep(bar)
        ib('−', lambda: self.zoom_by(1 / 1.25), 'Zoom out (−)').pack(side='left')
        self.zl = tk.Label(bar, text='100%', width=5, font=T.font('sans', 12))
        T.style(self.zl, bg='bg2', fg='fg')
        self.zl.pack(side='left')
        ib('+', lambda: self.zoom_by(1.25), 'Zoom in (+)').pack(side='left')
        Btn(bar, T, 'Fit', self.do_fit, size='sm').pack(side='left', padx=3)
        Btn(bar, T, '1:1', self.one_to_one, size='sm').pack(side='left', padx=3)
        self._sep(bar)
        ib('↺', lambda: self.rotate(270), 'Rotate left').pack(side='left')
        ib('↻', lambda: self.rotate(90), 'Rotate right (R)').pack(side='left')
        Btn(bar, T, '🗑', self.delete, size='sm', tip='Move to Trash (Delete)').pack(side='right', padx=(3, 8))
        Btn(bar, T, '🖌 Edit', lambda: self.cur and os_.wm.open('brush', {'file': self.cur['id']}), size='sm').pack(side='right', padx=3)
        Btn(bar, T, '🖼 Wallpaper', self.wallpaper, size='sm').pack(side='right', padx=3)
        Btn(bar, T, '📂 Open', self.open_picker, size='sm').pack(side='right', padx=3)
        self.name_lbl = tk.Label(bar, text='', anchor='w', font=T.font('sans', 12))
        T.style(self.name_lbl, bg='bg2', fg='fg2')
        self.name_lbl.pack(side='left', fill='x', expand=True, padx=8)

        self.strip_wrap = tk.Frame(body, bd=0)
        T.style(self.strip_wrap, bg='bg2')
        self.strip = tk.Canvas(self.strip_wrap, height=60, bd=0, highlightthickness=0)
        T.style(self.strip, bg='bg2')
        self.strip.pack(fill='x')
        self.strip_inner = tk.Frame(self.strip, bd=0)
        T.style(self.strip_inner, bg='bg2')
        self.strip.create_window(0, 0, window=self.strip_inner, anchor='nw')
        self.strip_inner.bind('<Configure>', lambda e: self.strip.configure(scrollregion=self.strip.bbox('all')))
        self.strip._wheel = lambda u: self.strip.xview_scroll(u, 'units')
        self.strip_imgs = []
        self.stage = tk.Canvas(body, bd=0, highlightthickness=0, takefocus=1)
        self.stage.pack(fill='both', expand=True)
        T.on(self.stage, self._backdrop)
        s = self.stage
        s.bind('<Configure>', lambda e: (self._backdrop(), self._fit_empty(), self.do_fit() if self.fit else self.render()))
        s._wheel = lambda u: None
        s.bind('<MouseWheel>', self._wheel)
        s.bind('<Button-4>', self._wheel)
        s.bind('<Button-5>', self._wheel)
        s.bind('<ButtonPress-1>', self._down)
        s.bind('<B1-Motion>', self._move)
        s.bind('<ButtonRelease-1>', lambda e: (setattr(self, 'drag', None), s.configure(cursor='')))
        s.bind('<Double-Button-1>', lambda e: self.one_to_one() if (self.fit and abs(self.zoom - 1) > 1e-3) else self.do_fit())
        for key, fn in (('<Right>', lambda: self.go(1)), ('<Left>', lambda: self.go(-1)), ('<plus>', lambda: self.zoom_by(1.25)),
                        ('<equal>', lambda: self.zoom_by(1.25)), ('<minus>', lambda: self.zoom_by(1 / 1.25)),
                        ('<Key-0>', self.do_fit), ('<r>', lambda: self.rotate(90)), ('<R>', lambda: self.rotate(90)),
                        ('<Delete>', self.delete)):
            s.bind(key, lambda e, fn=fn: (fn(), 'break')[1])
        self.off = os_.bus.on('fs', self._fs_changed)
        arg = ctx.arg or {}
        files = self.files()
        first = arg.get('file') if arg.get('file') and self.fs.get(arg['file']) else (files[0]['id'] if files else None)
        if first:
            os_.root.after(10, lambda: self.show(first))
        else:
            ctx.set_title('Lens')
            self.show_empty()
        os_.root.after(30, s.focus_set)
        self.inst = Inst(on_arg=self.on_arg, on_focus=lambda: s.focus_set(), on_resize=lambda: self.do_fit() if self.fit else self.render(),
                         on_close=self.off, mem=lambda: len((self.cur or {}).get('c') or '') * 1.6 + 60000)

    def _sep(self, bar):
        s = tk.Frame(bar, width=1, height=20, bd=0)
        self.T.style(s, bg='line')
        s.pack(side='left', padx=6)

    def _backdrop(self):
        T = self.T
        c = self.stage
        c.delete('checker')
        c.configure(bg=T['bg1'])
        w, h = c.winfo_width(), c.winfo_height()
        for y in range(0, h, 24):
            for x in range(0, w, 24):
                if (x // 24 + y // 24) % 2 == 0:
                    c.create_rectangle(x, y, x + 24, y + 24, fill=T['bg0'], outline='', tags='checker')
        c.tag_lower('checker')

    # ---------------------------------------------------------- files
    def files(self):
        return sorted([n for n in self.fs.all() if n['t'] == 'f' and kind_of(n) == 'image' and n.get('c') is not None],
                      key=lambda n: n['n'].lower())

    def show(self, fid):
        n = self.fs.get(fid)
        if n is None:
            return
        self.stage.delete('empty')
        for c in self.stage.winfo_children():
            c.destroy()
        self.cur = n
        self.rot = 0
        self.load_source()
        size = len(n.get('c') or '') * (.75 if n.get('b') else 1)
        self.name_lbl.configure(text=n['n'] + ' · ' + fmt_bytes(size))
        self.ctx.set_title('Lens — ' + n['n'])
        self.draw_strip()
        self.do_fit()

    def load_source(self):
        data = self.fs.file_bytes(self.cur)
        self.src = None
        if HAVE_PIL:
            from PIL import Image
            try:
                im = Image.open(io.BytesIO(data))
                im.load()
                im = im.convert('RGBA')
                if self.rot:
                    im = im.rotate(-self.rot, expand=True)
                self.src = im
                self.src_size = im.size
                return
            except Exception:
                self.src = None
        photo = photo_from_bytes(self.os.root, data)
        if photo is None:
            self.src = None
            return
        if self.rot:
            photo = self._rotate_photo(photo, self.rot)
        self.src = photo
        self.src_size = (photo.width(), photo.height())

    def _rotate_photo(self, photo, deg):
        fd, path = tempfile.mkstemp(suffix='.ppm')
        os.close(fd)
        try:
            photo.write(path, format='ppm')
            with open(path, 'rb') as f:
                w, h, rgb = parse_ppm(f.read())
        finally:
            os.unlink(path)
        w, h, rgb = rotate_rgb(w, h, rgb, deg)
        return tk.PhotoImage(master=self.os.root, data=ppm(w, h, rgb), format='ppm')

    def render(self):
        c = self.stage
        c.delete('img')
        self.zl.configure(text='%d%%' % round(self.zoom * 100))
        if self.cur is None:
            return
        if self.src is None:
            c.delete('empty')
            self.zl.configure(text='—')
            name = (self.cur.get('n') or '').lower()
            if name.endswith('.svg'):
                msg = 'SVG drawings cannot be shown here.\nOpen the file in Glyph to see or edit its code.'
            elif HAVE_PIL:
                msg = 'This picture cannot be shown here.'
            else:
                msg = 'This picture cannot be shown here.\nInstall Pillow (pip install pillow) to open JPEG, WebP and BMP files.'
            c.create_text(c.winfo_width() / 2, c.winfo_height() / 2, fill=self.T['fg2'], font=self.T.font('sans', 14),
                          text=msg, justify='center', tags='img')
            return
        cw, ch = max(1, c.winfo_width()), max(1, c.winfo_height())
        iw, ih = self.src_size
        z = self.zoom
        left = cw / 2 + self.px - iw * z / 2
        top = ch / 2 + self.py - ih * z / 2
        sx0, sy0 = clamp(int(-left / z) - 1, 0, iw), clamp(int(-top / z) - 1, 0, ih)
        sx1, sy1 = clamp(int((cw - left) / z) + 2, 0, iw), clamp(int((ch - top) / z) + 2, 0, ih)
        if sx1 <= sx0 or sy1 <= sy0:
            return
        if HAVE_PIL:
            from PIL import Image, ImageTk
            region = self.src.crop((sx0, sy0, sx1, sy1))
            tw, th = max(1, round((sx1 - sx0) * z)), max(1, round((sy1 - sy0) * z))
            region = region.resize((tw, th), Image.NEAREST if z >= 3 else Image.BILINEAR)
            self.shown = ImageTk.PhotoImage(region, master=self.os.root)
        else:
            num, den = _ratio(z)
            if den > 1:
                sx0, sy0 = sx0 - sx0 % den, sy0 - sy0 % den
            part = tk.PhotoImage(master=self.os.root)
            part.tk.call(part, 'copy', self.src, '-from', sx0, sy0, sx1, sy1, '-zoom', num, num)
            if den > 1:
                part = part.subsample(den, den)
            self.shown = part
        c.create_image(left + sx0 * z, top + sy0 * z, image=self.shown, anchor='nw', tags='img')

    def do_fit(self):
        self.fit = True
        self.px = self.py = 0.0
        if self.src is None:
            self.zoom = 1.0
            self.render()
            return
        c = self.stage
        iw, ih = self.src_size
        z = min((c.winfo_width() - 24) / max(1, iw), (c.winfo_height() - 24) / max(1, ih), 6)
        self.zoom = z if z > 0 else 1
        self.render()

    def one_to_one(self):
        self.fit = False
        self.zoom = 1.0
        self.px = self.py = 0.0
        self.render()

    def zoom_by(self, f, cx=None, cy=None):
        z0 = self.zoom
        self.zoom = clamp(self.zoom * f, .05, 32)
        self.fit = False
        if cx is not None:
            ox = cx - self.stage.winfo_width() / 2
            oy = cy - self.stage.winfo_height() / 2
            self.px = ox - (ox - self.px) * self.zoom / z0
            self.py = oy - (oy - self.py) * self.zoom / z0
        self.render()

    def rotate(self, d):
        if self.cur is None:
            return
        self.rot = (self.rot + d) % 360
        self.load_source()
        self.do_fit()

    def go(self, d):
        lst = self.files()
        if not lst:
            return
        i = next((k for k, n in enumerate(lst) if self.cur and n['id'] == self.cur['id']), 0)
        self.show(lst[(i + d) % len(lst)]['id'])

    def draw_strip(self):
        lst = self.files()
        for c in self.strip_inner.winfo_children():
            c.destroy()
        self.strip_imgs = []
        if len(lst) < 2:
            self.strip_wrap.pack_forget()
            return
        T = self.T
        if not self.strip_wrap.winfo_ismapped():
            self.strip_wrap.pack(fill='x', side='bottom', before=self.stage)
        for n in lst:
            img = self.os.thumb(n, 48)
            on = self.cur is not None and n['id'] == self.cur['id']
            if img is not None:
                lbl = tk.Label(self.strip_inner, image=img, bd=0, highlightthickness=2, cursor='hand2')
            else:
                lbl = tk.Label(self.strip_inner, text='🖼️', width=4, height=2, bd=0, highlightthickness=2, cursor='hand2',
                               font=T.font('sans', 16))
            lbl.configure(bg=T['bg2'], fg=T['fg'], highlightbackground=T['acc'] if on else T['bg2'])
            lbl.bind('<Button-1>', lambda e, i=n['id']: self.show(i))
            lbl.pack(side='left', padx=3, pady=6)
            self.strip_imgs.append(img)

    def delete(self):
        if self.cur is None:
            return
        lst = self.files()
        i = next((k for k, n in enumerate(lst) if n['id'] == self.cur['id']), 0)
        self._deleting = True
        try:
            self.fs.trash(self.cur['id'])
        finally:
            self._deleting = False
        rest = self.files()
        if rest:
            self.show(rest[min(i, len(rest) - 1)]['id'])
        else:
            self.show_empty()

    def show_empty(self):
        self.cur = None
        self.src = None
        self.stage.delete('img')
        self.name_lbl.configure(text='')
        self.strip_wrap.pack_forget()
        self.ctx.set_title('Lens')
        for c in self.stage.winfo_children():
            c.destroy()
        holder = tk.Frame(self.stage, bd=0)
        self.T.style(holder, bg='bg1')
        self.os.empty_state(holder, '🖼️', 'No pictures yet.', buttons=[
            ('⇧ Add pictures', lambda: self.os.upload_into('d-pictures')), ('🖌 Draw one', lambda: self.os.wm.open('brush'))])
        self.stage.delete('empty')
        self.stage.create_window(0, 0, window=holder, anchor='nw', tags='empty')
        self.os.root.after(10, self._fit_empty)

    def _fit_empty(self, _e=None):
        self.stage.itemconfigure('empty', width=self.stage.winfo_width(), height=self.stage.winfo_height())

    def wallpaper(self):
        if self.cur is None:
            return
        S = self.os.S
        S['set']['wall'] = 'image'
        S['set']['wallImg'] = self.cur['id']
        self.os.touch()
        self.os.apply_look()
        self.os.toast('Wallpaper changed', '🖼')

    def open_picker(self):
        fid = self.os.dialogs.pick_file(lambda n: kind_of(n) == 'image', 'Open an image')
        if fid:
            self.show(fid)

    def on_arg(self, a):
        if isinstance(a, dict) and a.get('file') and self.fs.get(a['file']):
            self.show(a['file'])

    def _fs_changed(self, _a=None):
        if not self.ctx.alive or getattr(self, '_deleting', False):
            return
        lst = self.files()
        if self.cur is not None and (self.fs.get(self.cur['id']) is None or self.fs.get(self.cur['id']).get('x')
                                     or not self.fs.live(self.fs.get(self.cur['id']))):
            if lst:
                self.show(lst[0]['id'])
            else:
                self.show_empty()
            return
        if self.cur is None and lst:
            self.show(lst[0]['id'])
            return
        self.draw_strip()

    # ---------------------------------------------------------- mouse
    def _wheel(self, e):
        from ..ui.widgets import wheel_units
        u = wheel_units(e)
        if u:
            self.zoom_by(1.15 if u < 0 else 1 / 1.15, e.x, e.y)
        return 'break'

    def _down(self, e):
        self.stage.focus_set()
        self.drag = (e.x, e.y, self.px, self.py)
        self.stage.configure(cursor='fleur')

    def _move(self, e):
        if not self.drag:
            return
        x, y, px, py = self.drag
        self.px = px + e.x - x
        self.py = py + e.y - y
        self.fit = False
        self.render()


def _ratio(z):
    best, err = (1, 1), 1e9
    for num in range(1, 17):
        den = max(1, int(round(num / z)))
        if den > 64:
            continue
        e = abs(num / den - z)
        if e < err - 1e-9:
            best, err = (num, den), e
    return best
