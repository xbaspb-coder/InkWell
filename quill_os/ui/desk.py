"""The desktop surface: wallpaper, desktop icons, margin notes, the Spine and the ribbon."""

import datetime as _dt
import math
import random
import tkinter as tk

from .widgets import tile_image, tooltip, wrap_lines, ellipsize
from .wm import bind_context, ROM
from ..core import icon_of, kind_of
from ..state import FIXED
from ..util import DAYS, MONTHS, clamp, fmt_time, hex_to_rgb, js_weekday, mix, rgb_to_hex, uid

WALLS = [
    ('drift', 'Ink drift', ('#2c3f8f', '#0a0c13')),
    ('aurora', 'Aurora', ('#050c14', '#0f3a3a')),
    ('dunes', 'Dunes', ('#f4c58a', '#2b1830')),
    ('stars', 'Constellation', ('#1c2a55', '#05070d')),
    ('parch', 'Parchment', ('#fff6dc', '#d8c79b')),
    ('ember', 'Ember', ('#c4421f', '#150a08')),
    ('color', 'Plain colour', None),
]
NOTE_COLORS = ['#f6e58d', '#ffb8a1', '#b8e994', '#a5d8ff', '#e1c4ff', '#ffd9a0']


def lerp_stops(stops, t):
    """Colour at position t (0…1) along gradient stops [(pos, colour), …]."""
    t = clamp(t, 0, 1)
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if t <= p1:
            return mix(c0, c1, 0 if p1 == p0 else (t - p0) / (p1 - p0))
    return stops[-1][1]


# ================================================================ wallpaper and desktop icons

class Desk:
    """Draws the wallpaper and the Desktop folder's icons on one canvas."""

    def __init__(self, os_, parent):
        self.os = os_
        self.T = os_.theme
        self.c = tk.Canvas(parent, bd=0, highlightthickness=0, takefocus=1)
        self.c.place(x=0, y=0, relwidth=1, relheight=1)
        self.key = None
        self.anim_job = None
        self.anim_items = []
        self.sel = None
        self.thumbs = {}
        self.photo = None
        self._imgs = []
        self._resize_job = None
        self.c.bind('<Configure>', self._on_resize)
        self.c.bind('<Button-1>', self._click)
        self.c.bind('<Double-Button-1>', self._dbl)
        self.c.bind('<B1-Motion>', self._drag)
        self.c.bind('<ButtonRelease-1>', self._release)
        bind_context(self.c, self._context)      # after the plain bindings, which would replace its own
        self.c.bind('<Delete>', lambda e: self._key_delete())
        self.c.bind('<Return>', lambda e: self._key_open())
        self.c._drop = self._drop
        self.icon_hits = []
        self._press = None

    # ---------------------------------------------------------- wallpaper
    def _on_resize(self, _e=None):
        if self._resize_job:
            self.c.after_cancel(self._resize_job)
        self._resize_job = self.c.after(120, self.redraw_all)

    def redraw_all(self):
        self._resize_job = None
        self.key = None
        self.apply()

    def apply(self):
        s = self.os.S['set']
        w, h = self.c.winfo_width(), self.c.winfo_height()
        img = self.os.fs.get(s.get('wallImg')) if s.get('wall') == 'image' else None
        key = (s.get('wall'), s.get('wallColor'), s.get('wallImg'), img['m'] if img else None, s.get('accent'),
               s.get('bright'), s.get('theme'), w, h, s.get('anim'))
        if key == self.key:
            self.icons()
            return
        self.key = key
        self._stop_anim()
        self.c.delete('wall')
        self._imgs = []
        if w < 2 or h < 2:
            return
        kind = s.get('wall')
        dim = self._dimmer()
        getattr(self, '_wall_' + kind, self._wall_color)(w, h, dim)
        self.c.tag_lower('wall')
        self.icons()
        if s.get('anim') and kind in ('drift', 'aurora', 'ember'):
            self._start_anim(kind, w, h)

    def _dimmer(self):
        b = 100 if getattr(self.os, 'backlight', None) is not None else self.os.S['set'].get('bright', 100)
        k = 0.35 + 0.65 * b / 100 if b < 100 else 1.0

        def dim(color):
            if k == 1.0:
                return color
            r, g, bb = hex_to_rgb(color)
            return rgb_to_hex((r * k, g * k, bb * k))
        return dim

    def _radial(self, w, h, cx, cy, rx, ry, stops, dim, steps=96, tag='wall'):
        """A radial gradient drawn as shrinking ellipses (outermost first)."""
        far = max(math.hypot(cx, cy), math.hypot(w - cx, cy), math.hypot(cx, h - cy), math.hypot(w - cx, h - cy))
        reach = max(1.2, far / max(1, min(rx, ry)) * 1.05)
        col = dim(lerp_stops(stops, 1.0))
        self.c.create_rectangle(0, 0, w, h, fill=col, outline=col, tags=tag)
        for i in range(steps, 0, -1):
            t = i / steps * reach
            col = dim(lerp_stops(stops, t))
            self.c.create_oval(cx - rx * t, cy - ry * t, cx + rx * t, cy + ry * t, fill=col, outline=col, tags=tag)

    def _linear(self, w, h, stops, dim, tag='wall'):
        step = 3
        for y in range(0, h, step):
            col = dim(lerp_stops(stops, y / max(1, h - 1)))
            self.c.create_rectangle(0, y, w, y + step, fill=col, outline=col, tags=tag)

    def _soft_image(self, w, h, fn, scale=5):
        """A see-through picture made by fn(fx, fy) -> (r, g, b, a) with fx, fy in 0…1.

        It is computed at 1/scale size and enlarged by Tk, which keeps the alpha
        channel, so soft shapes blend into whatever is underneath them.
        """
        import base64
        from ..imaging import png_encode_rgba
        sw, sh = max(2, int(w / scale)), max(2, int(h / scale))
        buf = bytearray(sw * sh * 4)
        i = 0
        for y in range(sh):
            fy = (y + 0.5) / sh
            for x in range(sw):
                r, g, b, a = fn((x + 0.5) / sw, fy)
                buf[i] = r
                buf[i + 1] = g
                buf[i + 2] = b
                buf[i + 3] = a
                i += 4
        img = tk.PhotoImage(master=self.c, data=base64.b64encode(png_encode_rgba(sw, sh, buf)).decode('ascii'))
        if scale > 1:
            img = img.zoom(scale, scale)
        self._imgs.append(img)
        return img

    def _blob(self, cx, cy, r, color, alpha, dim, tag, blur=60):
        """A circle of colour with a blurred edge (CSS: border-radius 50%; filter: blur(60px))."""
        rgb = hex_to_rgb(dim(color))
        R = r + blur
        size = int(2 * R)

        def fn(fx, fy):
            d = math.hypot((fx - .5) * size, (fy - .5) * size)
            e = (r + blur * .5 - d) / blur
            e = 0.0 if e <= 0 else 1.0 if e >= 1 else e * e * (3 - 2 * e)
            return rgb[0], rgb[1], rgb[2], int(255 * alpha * e)
        img = self._soft_image(size, size, fn, scale=max(3, size // 160))
        self.c.create_image(cx, cy, image=img, tags=(tag, 'wall'))

    def _wall_drift(self, w, h, dim):
        stops = [(0, '#1b2340'), (0.6, '#0a0c13'), (1, '#0a0c13')]
        self._radial(w, h, w * .2, h * .1, w * 1.2, h * .9, stops, dim)
        vmax = max(w, h) / 100
        acc = self.os.S['set'].get('accent') or '#e8b04a'
        self._blob(-8 * vmax + 23 * vmax, -10 * vmax + 23 * vmax, 23 * vmax, '#2c3f8f', .55, dim, 'blob0')
        self._blob(w + 6 * vmax - 19 * vmax, h + 12 * vmax - 19 * vmax, 19 * vmax, acc, .32, dim, 'blob1')
        self._blob(w * .38 + 15 * vmax, h * .3 + 15 * vmax, 15 * vmax, '#6a2c7d', .4, dim, 'blob2')

    def _wall_aurora(self, w, h, dim):
        self._linear(w, h, [(0, '#050c14'), (0.6, '#0b2233'), (1, '#0f3a3a')], dim)
        bands = [(.08, ['#2de2b0', '#3b8cff'], .55), (.26, ['#8a5cff', '#2de2b0'], .4), (.44, ['#2de2b0'], .25)]
        for bi, (top, colors, alpha) in enumerate(bands):
            bw, bh = int(w * 1.4), int(h * .4)
            cols = [hex_to_rgb(dim(c)) for c in colors]

            def fn(fx, fy, cols=cols, alpha=alpha):
                # transparent → colours → transparent across, soft ellipse top to bottom
                if len(cols) == 2:
                    if fx < 1 / 3:
                        rgb, k = cols[0], fx * 3
                    elif fx < 2 / 3:
                        t = (fx - 1 / 3) * 3
                        rgb, k = tuple(cols[0][i] + (cols[1][i] - cols[0][i]) * t for i in range(3)), 1.0
                    else:
                        rgb, k = cols[1], (1 - fx) * 3
                else:
                    rgb, k = cols[0], 1 - abs(fx - .5) * 2
                v = max(0.0, 1 - ((fy - .5) / .5) ** 2)
                a = alpha * k * v ** 1.6
                return int(rgb[0]), int(rgb[1]), int(rgb[2]), int(255 * max(0.0, min(1.0, a)))
            img = self._soft_image(bw, bh, fn, scale=6)
            self.c.create_image(-.2 * w, h * top, image=img, anchor='nw', tags=('wall', 'band%d' % bi))

    def _wall_dunes(self, w, h, dim):
        self._linear(w, h, [(0, '#f4c58a'), (.38, '#e9966a'), (.7, '#7b3b4a'), (1, '#2b1830')], dim)
        for left, right, bottom, height, color in ((-.1, -.1, -.18, .46, '#5b2a42'), (.2, -.1, -.24, .40, '#3c1d38'),
                                                   (-.1, .25, -.30, .36, '#24122b')):
            x0, x1 = w * left, w * (1 - right)
            y1 = h * (1 - bottom)
            hh = h * height
            y0 = y1 - hh
            c = dim(color)
            self.c.create_oval(x0, y0, x1, y0 + 2 * hh, fill=c, outline=c, tags='wall')
            self.c.create_rectangle(x0, y0 + hh, x1, y1 + hh, fill=c, outline=c, tags='wall')

    def _wall_stars(self, w, h, dim):
        stops = [(0, '#1c2a55'), (.7, '#05070d'), (1, '#05070d')]
        self._radial(w, h, w * .5, h * 1.0, w * 1.2, h * 1.0, stops, dim)
        W, H = max(300, w), max(300, h)
        seed = [1234567]

        def rnd():
            seed[0] = (seed[0] * 16807) % 2147483647
            return seed[0] / 2147483647
        pts = []
        for _ in range(220):
            x, y, r = rnd() * W, rnd() * H, rnd() * 1.4 + 0.2
            pts.append((x, y))
            a = 0.35 + rnd() * 0.65
            base = lerp_stops(stops, math.hypot((x - w * .5) / (w * 1.2), (y - h) / h))
            col = dim(mix(base, '#ffffff', a))
            self.c.create_oval(x - r, y - r, x + r, y + r, fill=col, outline=col, tags='wall')
        line = dim(mix('#0b1022', '#e8b04a', .28))
        for _ in range(6):
            a = pts[int(rnd() * len(pts))]
            path = [a]
            for _ in range(4):
                best, bd = None, 1e9
                for q in pts:
                    d = math.hypot(q[0] - a[0], q[1] - a[1])
                    if 20 < d < bd:
                        bd, best = d, q
                if best is None:
                    break
                path.append(best)
                a = (best[0] + (rnd() - .5) * 90, best[1] + (rnd() - .5) * 90)
                a = min(pts, key=lambda q: math.hypot(q[0] - a[0], q[1] - a[1]))
            if len(path) > 1:
                self.c.create_line(*[v for p in path for v in p], fill=line, width=1, tags='wall')

    def _wall_parch(self, w, h, dim):
        base = '#efe5c9'
        stops = [(0, mix(base, '#ffffff', .55)), (1, mix(base, '#966e28', .22))]
        self._radial(w, h, w * .5, h * .3, w * 1.0, h * .8, stops, dim)
        rnd = random.Random(4)
        for _ in range(int(w * h / 900)):
            x, y = rnd.random() * w, rnd.random() * h
            k = rnd.random() * .12
            col = dim(mix(lerp_stops(stops, math.hypot((x - w / 2) / w, (y - h * .3) / (h * .8))), '#735926', k))
            self.c.create_rectangle(x, y, x + 1, y + 1, fill=col, outline='', tags='wall')

    def _wall_ember(self, w, h, dim):
        stops = [(0, '#c4421f'), (.45, '#4a1810'), (1, '#150a08')]
        self._radial(w, h, w * .5, h * 1.1, w * .9, h * .7, stops, dim)

    def _wall_color(self, w, h, dim):
        col = dim(self.os.S['set'].get('wallColor') or '#1b2340')
        self.c.create_rectangle(0, 0, w, h, fill=col, outline=col, tags='wall')

    def _wall_image(self, w, h, dim):
        n = self.os.fs.get(self.os.S['set'].get('wallImg'))
        photo = None
        if n is not None and kind_of(n) == 'image':
            photo = self.os.photo_cover(n, w, h)
        if photo is None:
            self._wall_color(w, h, dim)
            return
        self.photo = photo
        col = dim('#000000')
        self.c.create_rectangle(0, 0, w, h, fill=col, outline=col, tags='wall')
        self.c.create_image(w / 2, h / 2, image=photo, tags='wall')

    # ---------------------------------------------------------- animation (Motion on)
    def _stop_anim(self):
        if self.anim_job:
            try:
                self.c.after_cancel(self.anim_job)
            except tk.TclError:
                pass
            self.anim_job = None
        self.c.delete('ember')

    def _start_anim(self, kind, w, h):
        t0 = [0.0]
        vmax = max(w, h) / 100
        if kind == 'drift':
            durs = [26, 32, 38]
            offs = [(0, 0)] * 3

            def step():
                t0[0] += 0.1
                for i, d in enumerate(durs):
                    ph = (t0[0] % (2 * d)) / d
                    k = ph if ph <= 1 else 2 - ph
                    k = 0.5 - 0.5 * math.cos(math.pi * k)
                    nx, ny = 8 * vmax * k, 6 * vmax * k
                    ox, oy = offs[i]
                    self.c.move('blob%d' % i, nx - ox, ny - oy)
                    offs[i] = (nx, ny)
                self.anim_job = self.c.after(100, step)
        elif kind == 'aurora':
            durs = [14, 19, 23]
            offs = [0.0] * 3

            def step():
                t0[0] += 0.1
                for i, d in enumerate(durs):
                    ph = (t0[0] % (2 * d)) / d
                    k = ph if ph <= 1 else 2 - ph
                    k = 0.5 - 0.5 * math.cos(math.pi * k)
                    nx = (-0.06 + 0.12 * k) * w
                    self.c.move('band%d' % i, nx - offs[i], 0)
                    offs[i] = nx
                self.anim_job = self.c.after(100, step)
        else:
            rnd = random.Random()
            parts = []
            for _ in range(16):
                parts.append({'x': rnd.random() * w, 'dur': 6 + rnd.random() * 6, 't': rnd.random() * 9, 'id': None})

            def step():
                self.c.delete('ember')
                dim = self._dimmer()
                for p in parts:
                    p['t'] += 0.05
                    f = (p['t'] % p['dur']) / p['dur']
                    op = f / .15 * .9 if f < .15 else .9 * (1 - (f - .15) / .85)
                    x = p['x'] + 30 * f
                    y = h * 1.1 - h * .9 * f - h * .1
                    base = '#3a120b'
                    col = dim(mix(base, '#ffb070', clamp(op, 0, 1)))
                    glow = dim(mix(base, '#ff8a3c', clamp(op * .35, 0, 1)))
                    self.c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=glow, outline='', tags=('wall', 'ember'))
                    self.c.create_oval(x - 1.5, y - 1.5, x + 1.5, y + 1.5, fill=col, outline='', tags=('wall', 'ember'))
                self.c.tag_raise('ember', 'wall')
                self.c.tag_raise('icon')
                self.anim_job = self.c.after(50, step)
        self.anim_job = self.c.after(100, step)

    # ---------------------------------------------------------- desktop icons
    def icons(self):
        os_ = self.os
        T = self.T
        c = self.c
        c.delete('icon')
        self.icon_hits = []
        h = c.winfo_height()
        rows = max(1, (h - 16) // 94)
        light = os_.S['set'].get('theme') == 'parchment'
        fg = '#2b2418' if light else '#ffffff'
        shadow = '#ffffff' if light else '#000000'
        name_font = T.font('sans', 12)
        for i, n in enumerate(os_.fs.kids(FIXED['desktop'])):
            col, row = divmod(i, rows)
            x0, y0 = 8 + col * 90, 8 + row * 94
            cx = x0 + 44
            if self.sel == n['id']:
                c.create_rectangle(x0, y0, x0 + 88, y0 + 92, fill=T['acc_soft'], outline=T['acc'], tags='icon')
            img = None
            if kind_of(n) == 'image' and n.get('c'):
                img = os_.thumb(n, 40)
            if img is not None:
                c.create_image(cx, y0 + 26, image=img, tags='icon')
            else:
                c.create_text(cx, y0 + 26, text=icon_of(n), font=T.font('sans', 32), fill=fg, tags='icon')
            lines = wrap_lines(name_font, n['n'], 82, 2)
            for j, line in enumerate(lines):
                y = y0 + 58 + j * 15
                c.create_text(cx + 1, y + 1, text=line, font=name_font, fill=shadow, tags='icon')
                c.create_text(cx, y, text=line, font=name_font, fill=fg, tags='icon')
            self.icon_hits.append(((x0, y0, x0 + 88, y0 + 92), n))
        c.tag_raise('icon')

    def _hit(self, x, y):
        for (x0, y0, x1, y1), n in self.icon_hits:
            if x0 <= x < x1 and y0 <= y < y1:
                return n
        return None

    def _click(self, e):
        self.c.focus_set()
        n = self._hit(e.x, e.y)
        self.sel = n['id'] if n else None
        self._press = (e.x, e.y, n) if n else None
        self.icons()

    def _dbl(self, e):
        n = self._hit(e.x, e.y)
        if n is not None:
            self._press = None
            self.os.open_file(n)

    def _drag(self, e):
        if not self._press:
            return
        x, y, n = self._press
        if math.hypot(e.x - x, e.y - y) > 6:
            self._press = None
            self.os.dnd.start([n['id']], icon_of(n) + ' ' + n['n'], e)

    def _release(self, e):
        self._press = None

    def _key_delete(self):
        if self.sel and self.os.fs.get(self.sel):
            self.os.fs.trash(self.sel)

    def _key_open(self):
        n = self.os.fs.get(self.sel) if self.sel else None
        if n is not None:
            self.os.open_file(n)

    def _drop(self, ids):
        moved = 0
        for i in ids:
            if self.os.fs.move(i, FIXED['desktop']):
                moved += 1
        return moved > 0

    def _context(self, e):
        os_ = self.os
        n = self._hit(e.x, e.y)
        if n is not None:
            self.sel = n['id']
            self.icons()
            os_.menu.show(e.x_root, e.y_root, os_.file_menu(n))
            return
        aw, ah = os_.wm.area()
        x, y = e.x, e.y
        os_.menu.show(e.x_root, e.y_root, [
            {'label': 'New file…', 'icon': '📃', 'action': lambda: os_.new_item(FIXED['desktop'], 'f')},
            {'label': 'New folder…', 'icon': '📁', 'action': lambda: os_.new_item(FIXED['desktop'], 'd')},
            {'label': 'New margin note', 'icon': '🗒', 'action': lambda: os_.notes.add(clamp(x, 0, aw - 200), clamp(y, 0, ah - 160))},
            {'label': 'Upload files…', 'icon': '📥', 'action': lambda: os_.upload_into(FIXED['desktop'])}, {'sep': True},
            {'label': 'Open Inkwell', 'icon': '✒️', 'key': 'Ctrl+K', 'action': os_.ink.open},
            {'label': 'Open terminal', 'icon': '❯', 'action': lambda: os_.wm.open('term')},
            {'label': 'Change wallpaper…', 'icon': '🖼', 'action': lambda: os_.wm.open('loom', {'page': 'look'})},
            {'label': 'Settings', 'icon': '⚙️', 'action': lambda: os_.wm.open('loom')},
        ])


# ================================================================ margin notes

class Notes:
    def __init__(self, os_, parent):
        self.os = os_
        self.parent = parent
        self.frames = []

    def add(self, x, y):
        S = self.os.S
        S['notes'].append({'id': uid(), 'x': x, 'y': y, 'text': '', 'color': NOTE_COLORS[len(S['notes']) % len(NOTE_COLORS)],
                           'rot': '%.1f' % (random.random() * 3 - 1.5)})
        self.os.touch()
        self.render()
        if self.frames:
            self.frames[-1].text.focus_set()

    def render(self):
        for f in self.frames:
            f.destroy()
        self.frames = []
        T = self.os.theme
        for n in self.os.S['notes']:
            self.frames.append(self._note(n, T))
        self.os.wm.restack()

    def _note(self, n, T):
        os_ = self.os
        el = tk.Frame(self.parent, bd=0, highlightthickness=1)
        hd = tk.Frame(el, height=22, bd=0, cursor='fleur')
        hd.pack(fill='x')
        hd.pack_propagate(False)
        lab = tk.Label(hd, text='✒ margin', font=T.font('sans', 11), bd=0)
        lab.pack(side='left', padx=(8, 0))
        bx = tk.Label(hd, text='✕', font=T.font('sans', 12), bd=0, cursor='hand2')
        bc = tk.Label(hd, text='◐', font=T.font('sans', 12), bd=0, cursor='hand2')
        bx.pack(side='right', padx=(0, 6))
        bc.pack(side='right', padx=4)
        txt = tk.Text(el, width=22, height=7, bd=0, highlightthickness=0, wrap='word', padx=8, pady=8,
                      font=T.font('hand', 15), undo=True)
        txt.insert('1.0', n.get('text', ''))
        txt.pack(fill='both', expand=True)
        el.text = txt

        def paint():
            col = n.get('color') or NOTE_COLORS[0]
            head = mix(col, '#000000', .08)
            el.configure(bg=col, highlightbackground=mix(col, '#000000', .3))
            hd.configure(bg=head)
            for w in (lab, bx, bc):
                w.configure(bg=head, fg='#2b2418')
            txt.configure(bg=col, fg='#2b2418', insertbackground='#2b2418', selectbackground=mix(col, '#000000', .25))
        T.on(el, paint)

        def changed(_e=None):
            v = txt.get('1.0', 'end-1c')[:2000]
            if v != n.get('text'):
                n['text'] = v
                os_.touch()
        txt.bind('<KeyRelease>', changed)
        txt.bind('<<Paste>>', lambda e: txt.after(1, changed))

        def recolor(_e=None):
            i = NOTE_COLORS.index(n['color']) if n.get('color') in NOTE_COLORS else -1
            n['color'] = NOTE_COLORS[(i + 1) % len(NOTE_COLORS)]
            paint()
            os_.touch()

        def delete(_e=None):
            os_.S['notes'] = [q for q in os_.S['notes'] if q is not n]
            os_.touch()
            el.destroy()
            if el in self.frames:
                self.frames.remove(el)
        bc.bind('<Button-1>', recolor)
        bx.bind('<Button-1>', delete)
        drag = {}

        def start(e):
            drag.update(sx=e.x_root, sy=e.y_root, ox=n['x'], oy=n['y'])

        def move(e):
            if not drag:
                return
            aw, ah = os_.wm.area()
            n['x'] = clamp(drag['ox'] + e.x_root - drag['sx'], 0, aw - 60)
            n['y'] = clamp(drag['oy'] + e.y_root - drag['sy'], 0, ah - 30)
            el.place(x=n['x'], y=n['y'])

        def end(_e):
            if drag:
                drag.clear()
                os_.touch()
        for w in (hd, lab):
            w.bind('<ButtonPress-1>', start)
            w.bind('<B1-Motion>', move)
            w.bind('<ButtonRelease-1>', end)
        el.place(x=n.get('x', 20), y=n.get('y', 20), width=190)
        return el


# ================================================================ the Spine (dock)

class Spine:
    def __init__(self, os_, parent):
        self.os = os_
        self.T = os_.theme
        self.f = parent
        T = self.T
        top = tk.Frame(parent, bd=0)
        T.style(top, bg='glass')
        top.pack(side='top', pady=(8, 2))
        self.ink_btn = tk.Label(top, text='✒', bd=0, cursor='hand2', compound='center', font=T.font('sans', 22, 'bold'))
        self.ink_btn.pack()
        T.on(self.ink_btn, lambda: self.ink_btn.configure(
            bg=T['glass'], fg=T['acc_fg'], image=tile_image(os_.root, T['acc'], T['acc_dark'], 46, 14, T['glass'])))
        self.ink_btn.bind('<Button-1>', lambda e: os_.ink.toggle())
        tooltip(self.ink_btn, 'Inkwell (Ctrl+K)')
        # The bottom group is packed before the dock so that it always keeps its place;
        # the dock takes what is left and scrolls with the mouse wheel when it overflows.
        bottom = tk.Frame(parent, bd=0)
        T.style(bottom, bg='glass')
        bottom.pack(side='bottom', pady=(2, 8))
        self.dock = tk.Frame(parent, bd=0)
        T.style(self.dock, bg='glass')
        self.dock.pack(side='top', fill='both', expand=True, pady=4)
        self.dock._wheel = self._wheel
        self.offset = 0
        sep = tk.Frame(bottom, height=1, width=30, bd=0)
        T.style(sep, bg='line')
        sep.pack(pady=(0, 4))
        self.spread_btn = self._item(bottom, '▦', ('#6d7bd1', '#3b4590'), 'Spread (Alt+S)', lambda: os_.spread.open())
        self.spread_btn.pack(pady=2)
        self.trash_btn = self._item(bottom, '🗑', ('#78808c', '#444b57'), 'Trash',
                                    lambda: os_.wm.open('files', {'dir': 'trash'}))
        self.trash_btn.pack(pady=2)
        self.trash_btn._drop = self._drop_trash

    def _drop_trash(self, ids):
        n = sum(1 for i in ids if self.os.fs.trash(i))
        if n:
            self.os.toast('Moved to Trash', '🗑')
        return n > 0

    def _wheel(self, units):
        self.offset = max(0, self.offset + units)
        self.render()

    def _item(self, parent, icon, colors, tip, command, running=0, active=False, count=0):
        T = self.T
        os_ = self.os
        cell = tk.Frame(parent, width=50, height=46, bd=0)
        cell.pack_propagate(False)
        T.style(cell, bg='glass')
        bar = tk.Frame(cell, width=3, bd=0)
        hgt = 22 if active else 10 if running else 0
        if hgt:
            bar.place(x=2, rely=0.5, anchor='w', height=hgt)
            T.style(bar, bg='acc')
        lbl = tk.Label(cell, text=icon, compound='center', fg='#ffffff', bd=0, cursor='hand2', font=T.font('sans', 19))
        lbl.place(relx=0.5, rely=0.5, anchor='center', x=2)
        hover = {'on': False}

        def paint():
            surf = T['bg3'] if (hover['on'] or active) else T['glass']
            lbl.configure(bg=surf, image=tile_image(os_.root, colors[0], colors[1], 38, 11, surf))
            cell.configure(bg=surf)
        T.on(lbl, paint)
        lbl.bind('<Enter>', lambda e: (hover.__setitem__('on', True), paint()), add='+')
        lbl.bind('<Leave>', lambda e: (hover.__setitem__('on', False), paint()), add='+')
        lbl.bind('<Button-1>', lambda e: command())
        if count > 1:
            badge = tk.Label(cell, text=str(count), font=T.font('sans', 9, 'bold'), bd=0, padx=3)
            T.style(badge, bg='acc', fg='acc_fg')
            badge.place(relx=1.0, rely=1.0, anchor='se', x=-2, y=-2)
        tooltip(lbl, tip)
        cell.lbl = lbl
        return cell

    def render(self):
        os_ = self.os
        for c in self.dock.winfo_children():
            c.destroy()
        pinned = [i for i in os_.S['set']['dock'] if i in os_.apps]
        running = []
        for w in os_.wm.list:
            if w.app not in pinned and w.app not in running:
                running.append(w.app)
        ids = pinned + running
        avail = max(1, (self.dock.winfo_height() or 600) // 52)
        self.offset = min(self.offset, max(0, len(ids) - avail))
        for app_id in ids[self.offset:]:
            a = os_.apps[app_id]
            ws = os_.wm.by_app(app_id)
            act = os_.wm.active is not None and os_.wm.active.app == app_id and not os_.wm.active.min
            cell = self._item(self.dock, a.icon, a.bg, a.name, lambda i=app_id: self._click(i), running=len(ws),
                              active=act, count=len(ws))
            cell.pack(pady=3)
            bind_context(cell.lbl, lambda e, i=app_id: self._menu(i, e))
            cell.lbl._wheel = self._wheel

    def _click(self, app_id):
        wm = self.os.wm
        ws = wm.by_app(app_id)
        if not ws:
            wm.open(app_id)
            return
        if len(ws) == 1:
            w = ws[0]
            if wm.active is w and not w.min and w.ch == wm.ch:
                wm.minimize(w)
            else:
                wm.focus(w)
            return
        if wm.active is not None and wm.active.app == app_id:
            s = sorted(ws, key=lambda x: x.id)
            wm.focus(s[(s.index(wm.active) + 1) % len(s)])
        else:
            wm.focus(sorted(ws, key=lambda x: -x.z)[0])

    def _menu(self, app_id, e):
        os_ = self.os
        a = os_.apps[app_id]
        ws = os_.wm.by_app(app_id)
        pinned = app_id in os_.S['set']['dock']

        def pin():
            d = os_.S['set']['dock']
            os_.S['set']['dock'] = [x for x in d if x != app_id] if pinned else d + [app_id]
            os_.touch()
            self.render()
        os_.menu.show(e.x_root, e.y_root, [
            {'label': 'Open ' + a.name, 'icon': '↗', 'action': lambda: os_.wm.open(app_id)},
            {'label': 'New window', 'icon': '＋', 'disabled': bool(a.single), 'action': lambda: os_.wm.open(app_id)},
            {'sep': True},
            {'label': 'Unpin from Spine' if pinned else 'Pin to Spine', 'icon': '📌', 'action': pin},
            {'label': 'Close all windows', 'icon': '✕', 'danger': True, 'disabled': not ws,
             'action': lambda: [os_.wm.close(w) for w in list(ws)]},
        ])


# ================================================================ the ribbon

class Ribbon:
    def __init__(self, os_, parent):
        self.os = os_
        T = self.T = os_.theme
        self.f = parent
        self.chaps = tk.Frame(parent, bd=0)
        T.style(self.chaps, bg='glass')
        self.chaps.pack(side='left', padx=(10, 10))
        self.chap_btns = []
        for i, r in enumerate(ROM):
            c = tk.Canvas(self.chaps, width=34, height=24, bd=0, highlightthickness=0, cursor='hand2')
            c.pack(side='left', padx=2)
            c.bind('<Button-1>', lambda e, i=i: os_.wm.switch_chapter(i))
            tooltip(c, 'Chapter %s (Alt+%d)' % (r, i + 1), 'below')
            self.chap_btns.append(c)
        self.tray = tk.Frame(parent, bd=0)
        T.style(self.tray, bg='glass')
        self.tray.pack(side='right', padx=(0, 10))
        self.title = tk.Label(parent, text='Quill.OS', font=T.font('serif', 15, slant='italic'), bd=0)
        T.style(self.title, bg='glass', fg='fg')
        self.title.pack(side='left', fill='x', expand=True)
        self.bell = self._tray_btn('🔔', lambda: os_.panels.toggle('notifs'))
        self.badge = tk.Label(self.bell, text='', font=T.font('sans', 9, 'bold'), bd=0, padx=3)
        T.style(self.badge, bg='acc', fg='acc_fg')
        self.quick = self._tray_btn('🔊 ☁', lambda: os_.panels.toggle('quick'))
        self.clock = self._tray_btn('--:--', lambda: os_.wm.open('almanac'))
        for b in (self.bell, self.quick, self.clock):
            b.pack(side='left', padx=1)
        self.paint_chapters()

    def _tray_btn(self, text, fn):
        T = self.T
        b = tk.Label(self.tray, text=text, bd=0, padx=8, pady=4, cursor='hand2', font=T.font('sans', 13))
        b.hover = False

        def paint():
            kind = getattr(getattr(self.os, 'panels', None), 'kind', None)
            on = b.hover or (kind == 'notifs' and b is getattr(self, 'bell', None)) or \
                (kind == 'quick' and b is getattr(self, 'quick', None))
            b.configure(bg=T['bg3'] if on else T['glass'], fg=T['fg'])
        b.paint = paint
        T.on(b, paint)
        b.bind('<Enter>', lambda e: (setattr(b, 'hover', True), paint()))
        b.bind('<Leave>', lambda e: (setattr(b, 'hover', False), paint()))
        b.bind('<Button-1>', lambda e: fn())
        return b

    def paint_tray(self):
        for b in (self.bell, self.quick, self.clock):
            b.paint()

    def paint_chapters(self):
        T = self.T
        wm = getattr(self.os, 'wm', None)
        for i, c in enumerate(self.chap_btns):
            c.delete('all')
            on = wm is not None and wm.ch == i
            has = wm is not None and any(w.ch == i for w in wm.list)
            c.configure(bg=T['glass'])
            fill = T['acc'] if on else T['glass']
            outline = T['acc'] if on else T['line']
            pts = [12, 1, 22, 1, 33, 1, 33, 12, 33, 23, 22, 23, 12, 23, 1, 23, 1, 12, 1, 1]
            c.create_polygon(pts, smooth=True, fill=fill, outline=outline)
            c.create_text(17, 12, text=ROM[i], fill=T['acc_fg'] if on else T['fg2'],
                          font=T.font('serif', 12, 'bold', 'italic'))
            if has:
                dot = T['acc_fg'] if on else T['acc']
                c.create_oval(26, 3, 31, 8, fill=dot, outline=dot)

    def set_title(self, text):
        self.title.configure(text=text)

    def clock_text(self):
        d = _dt.datetime.now()
        clk = self.os.S['set'].get('clock24', True)
        self.clock.configure(text='%s %d %s  %s' % (DAYS[js_weekday(d)], d.day, MONTHS[d.month - 1][:3],
                                                     fmt_time(d, clock24=clk)))

    def bell_update(self, n):
        if n <= 0:
            self.badge.place_forget()
        else:
            self.badge.configure(text='9+' if n > 9 else str(n))
            self.badge.place(relx=1.0, y=0, anchor='ne')

    def tray_icons(self, volume, sync_state):
        vol = '🔇' if volume == 0 else '🔈' if volume < 40 else '🔊'
        self.quick.configure(text=vol + ' ' + ('☁︎' if sync_state == 'off' else '☁'))


__all__ = ['Desk', 'Notes', 'Spine', 'Ribbon', 'WALLS', 'NOTE_COLORS', 'ellipsize']
