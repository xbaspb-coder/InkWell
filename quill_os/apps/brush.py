"""Brush — paint and draw."""

import random
import re
import tkinter as tk
from tkinter import colorchooser

from .base import AppSpec, Inst
from .scribe import bind_mod
from ..core import kind_of
from ..imaging import ImageError, Raster, decode_any, png_encode, ppm, scale_rgb
from ..state import FIXED
from ..ui.widgets import Btn, Check, Slider
from ..util import bytes_to_data_url, hex_to_rgb

TOOLS = [('pen', '✏️', 'Pencil'), ('brush', '🖌', 'Soft brush'), ('spray', '💨', 'Spray'), ('eraser', '🧽', 'Eraser'),
         ('line', '╱', 'Line'), ('rect', '▭', 'Rectangle'), ('ellipse', '◯', 'Ellipse'), ('fill', '🪣', 'Fill'),
         ('pick', '💧', 'Colour picker')]
PAL = ['#000000', '#444444', '#888888', '#ffffff', '#e0577e', '#ff7a59', '#e8b04a', '#f4e04d', '#7ac74f', '#35c9b0',
       '#5aa7ff', '#3b4fd8', '#a78bfa', '#c9772a', '#7a4a2a', '#f7c6a8']
PAD = 14


class App(AppSpec):
    id = 'brush'
    name = 'Brush'
    icon = '🖌'
    bg = ('#ff6fa8', '#8a3fd1')
    w, h = 860, 580
    kw = 'paint draw drawing art sketch image canvas pencil'
    about = 'Paint and draw'

    def build(self, ctx):
        return Brush(ctx).inst


class Brush:
    def __init__(self, ctx):
        self.ctx = ctx
        os_ = self.os = ctx.os
        T = self.T = ctx.T
        self.fs = os_.fs
        self.tool = 'pen'
        self.color = '#e8b04a'
        self.size = 6
        self.filled = False
        self.down = False
        self.sx = self.sy = self.lx = self.ly = 0
        self.file_id = None
        self.dirty = False
        self.undo, self.redo = [], []
        self.raster = Raster(800, 500)
        self._flush_job = None
        self.rnd = random.Random()
        body = ctx.body

        bar = tk.Frame(body, bd=0)
        T.style(bar, bg='bg2')
        bar.pack(fill='x')
        Btn(bar, T, '＋ New', self.new_canvas, size='sm').pack(side='left', padx=(8, 3), pady=6)
        Btn(bar, T, '📂 Open', self.open_img, size='sm').pack(side='left', padx=3)
        Btn(bar, T, '💾 Save', self.save_img, kind='pri', size='sm').pack(side='left', padx=3)
        self._sep(bar)
        self.b_undo = Btn(bar, T, '↶ Undo', self.do_undo, size='sm', tip='Undo (Ctrl+Z)')
        self.b_redo = Btn(bar, T, '↷ Redo', self.do_redo, size='sm', tip='Redo (Ctrl+Y)')
        self.b_undo.pack(side='left', padx=3)
        self.b_redo.pack(side='left', padx=3)
        Btn(bar, T, 'Clear', self.clear, size='sm').pack(side='left', padx=3)
        self._sep(bar)
        self.swatch = tk.Label(bar, width=3, bd=0, highlightthickness=1, cursor='hand2')
        T.on(self.swatch, lambda: self.swatch.configure(highlightbackground=T['line']))
        self.swatch.pack(side='left', padx=3, ipady=4)
        self.swatch.bind('<Button-1>', lambda e: self.choose_color())
        self.slider = Slider(bar, T, 1, 60, self.size, self.set_size, length=90, bg='bg2')
        self.slider.pack(side='left', padx=4)
        self.size_lbl = tk.Label(bar, text='6px', font=T.font('sans', 12), width=4)
        T.style(self.size_lbl, bg='bg2', fg='fg')
        self.size_lbl.pack(side='left')
        self.fill_chk = Check(bar, T, 'Filled', False, lambda v: setattr(self, 'filled', v), bg='bg2')
        self.fill_chk.pack(side='left', padx=4)
        line = tk.Frame(body, height=1, bd=0)
        T.style(line, bg='line')
        line.pack(fill='x')

        pal_bar = tk.Frame(body, bd=0)
        T.style(pal_bar, bg='bg2')
        pal_bar.pack(fill='x', side='bottom')
        pline = tk.Frame(body, height=1, bd=0)
        T.style(pline, bg='line')
        pline.pack(fill='x', side='bottom')
        self.pal_cells = []
        for col in PAL:
            c = tk.Frame(pal_bar, width=18, height=18, bg=col, highlightthickness=1, cursor='hand2')
            c.pack(side='left', padx=(8 if not self.pal_cells else 2, 0), pady=6)
            c.bind('<Button-1>', lambda e, col=col: self.set_color(col))
            self.pal_cells.append((col, c))
        self.pos_lbl = tk.Label(pal_bar, text='800 × 500', font=T.font('sans', 12))
        T.style(self.pos_lbl, bg='bg2', fg='fg2')
        self.pos_lbl.pack(side='right', padx=10)

        main = tk.Frame(body, bd=0)
        T.style(main, bg='bg1')
        main.pack(fill='both', expand=True)
        tools = tk.Frame(main, bd=0, width=56)
        T.style(tools, bg='bg2')
        tools.pack(side='left', fill='y')
        tedge = tk.Frame(main, width=1, bd=0)
        T.style(tedge, bg='line')
        tedge.pack(side='left', fill='y')
        self.tool_btns = {}
        for tid, ico, name in TOOLS:
            b = Btn(tools, T, ico, lambda t=tid: self.set_tool(t), kind='ibtn', tip=name, font=T.font('sans', 17))
            b.pack(padx=8, pady=2)
            self.tool_btns[tid] = b
        stage = tk.Frame(main, bd=0)
        T.style(stage, bg='bg1')
        stage.pack(side='left', fill='both', expand=True)
        self.cv = tk.Canvas(stage, bd=0, highlightthickness=0, cursor='crosshair', takefocus=1)
        vb = tk.Scrollbar(stage, orient='vertical', command=self.cv.yview, width=10, bd=0, highlightthickness=0)
        hb = tk.Scrollbar(stage, orient='horizontal', command=self.cv.xview, width=10, bd=0, highlightthickness=0)
        for sb in (vb, hb):
            T.on(sb, lambda sb=sb: sb.configure(bg=T['bg3'], troughcolor=T['bg1'], activebackground=T['hover']))
        self.cv.configure(yscrollcommand=vb.set, xscrollcommand=hb.set)
        vb.pack(side='right', fill='y')
        hb.pack(side='bottom', fill='x')
        self.cv.pack(side='left', fill='both', expand=True)
        self.cv._wheel = lambda u: self.cv.yview_scroll(u, 'units')
        T.on(self.cv, self._draw_backdrop)
        self.photo = None
        self.rebuild_photo()
        c = self.cv
        c.bind('<ButtonPress-1>', self.on_down)
        c.bind('<B1-Motion>', self.on_move)
        c.bind('<Motion>', self.on_hover)
        c.bind('<ButtonRelease-1>', self.on_up)
        for w in (body, c):
            bind_mod(w, 'z', lambda e: self.do_redo() if e.state & 0x1 else self.do_undo())
            bind_mod(w, 'y', lambda e: self.do_redo())
            bind_mod(w, 's', lambda e: self.save_img())
        self.set_tool('pen')
        self.set_color(self.color)
        self.sync_btns()
        ctx.set_title('Brush')
        arg = ctx.arg or {}
        if arg.get('file') and self.fs.get(arg['file']):
            os_.root.after(20, lambda: self.load_file(arg['file']))
        self.inst = Inst(on_arg=lambda a: self.load_file(a['file']) if isinstance(a, dict) and a.get('file') and self.fs.get(a['file']) else None,
                         before_close=self.before_close, on_focus=lambda: self.cv.focus_set(),
                         mem=lambda: self.raster.w * self.raster.h * 3 * (1 + len(self.undo) + len(self.redo)))

    def _sep(self, bar):
        s = tk.Frame(bar, width=1, height=20, bd=0)
        self.T.style(s, bg='line')
        s.pack(side='left', padx=6)

    # ---------------------------------------------------------- display
    def _draw_backdrop(self):
        T = self.T
        c = self.cv
        c.delete('checker')
        w, h = self.raster.w + PAD * 2, self.raster.h + PAD * 2
        c.configure(bg=T['bg1'], scrollregion=(0, 0, w, h))
        a = T['bg2']
        for y in range(0, h, 20):          # two darker squares per 20 px cell make the checker pattern
            for x in range(0, w, 20):
                c.create_rectangle(x, y, x + 10, y + 10, fill=a, outline='', tags='checker')
                c.create_rectangle(x + 10, y + 10, x + 20, y + 20, fill=a, outline='', tags='checker')
        c.tag_lower('checker')

    def rebuild_photo(self):
        r = self.raster
        self.photo = tk.PhotoImage(master=self.os.root, data=ppm(r.w, r.h, r.buf), format='ppm')
        self.cv.delete('img')
        self.cv.create_image(PAD, PAD, image=self.photo, anchor='nw', tags='img')
        self._draw_backdrop()
        r.take_dirty()

    def flush(self):
        self._flush_job = None
        box = self.raster.take_dirty()
        if box is None:
            return
        part = tk.PhotoImage(master=self.os.root, data=self.raster.region_ppm(box), format='ppm')
        self.photo.tk.call(self.photo, 'copy', part, '-to', box[0], box[1])

    def flush_soon(self):
        if self._flush_job is None:
            self._flush_job = self.os.root.after(16, self.flush)

    # ---------------------------------------------------------- tools and colours
    def set_tool(self, t):
        self.tool = t
        for k, b in self.tool_btns.items():
            b.set_on(k == t)
        self.cv.configure(cursor='tcross' if t == 'pick' else 'crosshair')

    def set_color(self, col):
        self.color = col.lower()
        self.swatch.configure(bg=self.color)
        for c, cell in self.pal_cells:
            cell.configure(highlightbackground=self.T['acc'] if c == self.color else self.T['line'],
                           highlightthickness=2 if c == self.color else 1)

    def choose_color(self):
        r = colorchooser.askcolor(color=self.color, parent=self.os.root, title='Colour')
        if r and r[1]:
            self.set_color(r[1])

    def set_size(self, v):
        self.size = int(v)
        self.size_lbl.configure(text='%dpx' % self.size)

    # ---------------------------------------------------------- undo
    def push_undo(self):
        r = self.raster
        self.undo.append((r.w, r.h, r.copy_buf()))
        del self.undo[:-20]
        self.redo.clear()
        self.sync_btns()

    def sync_btns(self):
        self.b_undo.set_disabled(not self.undo)
        self.b_redo.set_disabled(not self.redo)

    def _swap(self, src, dst):
        if not src:
            return
        r = self.raster
        dst.append((r.w, r.h, r.copy_buf()))
        w, h, buf = src.pop()
        resized = (w, h) != (r.w, r.h)
        r.load(w, h, buf)
        if resized:
            self.rebuild_photo()
        else:
            self.flush()
        self.sync_btns()

    def do_undo(self):
        self._swap(self.undo, self.redo)

    def do_redo(self):
        self._swap(self.redo, self.undo)

    def clear(self):
        self.push_undo()
        self.raster.fill_all((255, 255, 255))
        self.flush()
        self.dirty = True

    # ---------------------------------------------------------- pointer
    def pt(self, e):
        return self.cv.canvasx(e.x) - PAD, self.cv.canvasy(e.y) - PAD

    def on_hover(self, e):
        x, y = self.pt(e)
        self.pos_lbl.configure(text='%d × %d  ·  %d, %d' % (self.raster.w, self.raster.h, int(x), int(y)))

    def on_down(self, e):
        self.cv.focus_set()
        x, y = self.pt(e)
        self.sx = self.lx = x
        self.sy = self.ly = y
        r = self.raster
        if self.tool == 'pick':
            if 0 <= x < r.w and 0 <= y < r.h:
                self.set_color('#%02x%02x%02x' % r.get(int(x), int(y)))
            return
        self.push_undo()
        self.dirty = True
        rgb = hex_to_rgb(self.color)
        if self.tool == 'fill':
            r.flood_fill(x, y, rgb)
            self.flush()
            return
        self.down = True
        if self.tool in ('line', 'rect', 'ellipse'):
            r.begin()
        elif self.tool == 'spray':
            r.spray(x, y, self.size, rgb, self.rnd)
        else:
            r.begin()
            self.stroke(x, y, x, y)
        self.flush_soon()

    def stroke(self, x0, y0, x1, y1):
        r = self.raster
        if self.tool == 'eraser':
            r.capsule(x0, y0, x1, y1, self.size, (255, 255, 255))
        elif self.tool == 'brush':
            r.capsule(x0, y0, x1, y1, self.size, hex_to_rgb(self.color), alpha=0.35, soft=self.size * 0.3)
        else:
            r.capsule(x0, y0, x1, y1, self.size, hex_to_rgb(self.color))

    def shape(self, x0, y0, x1, y1):
        r = self.raster
        rgb = hex_to_rgb(self.color)
        if self.tool == 'line':
            r.capsule(x0, y0, x1, y1, self.size, rgb)
        elif self.tool == 'rect':
            r.rect(x0, y0, x1, y1, self.size, rgb, self.filled)
        else:
            r.ellipse(x0, y0, x1, y1, self.size, rgb, self.filled)

    def on_move(self, e):
        self.on_hover(e)
        if not self.down:
            return
        x, y = self.pt(e)
        if self.tool in ('line', 'rect', 'ellipse'):
            self.raster.reset_stroke()
            self.shape(self.sx, self.sy, x, y)
        elif self.tool == 'spray':
            self.raster.spray(x, y, self.size, hex_to_rgb(self.color), self.rnd)
        else:
            self.stroke(self.lx, self.ly, x, y)
            self.lx, self.ly = x, y
        self.flush_soon()

    def on_up(self, _e):
        if self.down:
            self.down = False
            self.raster.end()
            self.flush()

    # ---------------------------------------------------------- files
    def new_canvas(self):
        def valid(s):
            m = re.match(r'^(\d+)\s*[x×,]\s*(\d+)$', s.strip(), re.I)
            ok = m and 50 <= int(m.group(1)) <= 1600 and 50 <= int(m.group(2)) <= 1200
            return None if ok else 'Use a size like 800x500.'
        v = self.os.dialogs.prompt('New canvas', '800x500', text='Width × height in pixels (up to 1600 × 1200).',
                                   validate=valid)
        if v is None:
            return
        m = re.match(r'^(\d+)\s*[x×,]\s*(\d+)$', v.strip(), re.I)
        self.raster = Raster(int(m.group(1)), int(m.group(2)))
        self.undo.clear()
        self.redo.clear()
        self.sync_btns()
        self.file_id = None
        self.dirty = False
        self.rebuild_photo()
        self.ctx.set_title('Brush')

    def load_file(self, fid):
        n = self.fs.get(fid)
        if n is None:
            return False
        try:
            w, h, rgb = decode_any(self.fs.file_bytes(n), self.os.root)
        except (ImageError, ValueError) as e:
            self.os.toast('That image could not be opened: %s' % e, '⚠️')
            return False
        sc = min(1.0, 1600 / w, 1200 / h)
        nw, nh = max(1, round(w * sc)), max(1, round(h * sc))
        if (nw, nh) != (w, h):
            rgb = scale_rgb(w, h, rgb, nw, nh)
        self.push_undo()
        self.raster.load(nw, nh, rgb)
        self.rebuild_photo()
        self.file_id = fid
        self.dirty = False
        self.ctx.set_title('Brush — ' + n['n'])
        return True

    def open_img(self):
        fid = self.os.dialogs.pick_file(lambda n: kind_of(n) == 'image', 'Open an image')
        if fid:
            self.load_file(fid)

    def save_img(self):
        r = self.raster
        data = bytes_to_data_url(png_encode(r.w, r.h, r.buf), 'image/png')
        if len(data) > 1500000:
            self.os.toast('This picture is too large to store (try a smaller canvas).', '⚠️')
            return
        n = self.fs.get(self.file_id) if self.file_id else None
        if n is not None and not n.get('x') and n.get('b'):
            self.fs.write(self.file_id, data)
            self.dirty = False
            self.os.toast('Saved', '💾')
            return
        v = self.os.dialogs.prompt('Save picture', 'Drawing.png', text='It will be saved in Pictures.', ok='Save',
                                   validate=self.os.valid_name)
        if v is None:
            return
        name = v.strip()
        if not name.lower().endswith('.png'):
            name += '.png'
        n = self.fs.mk(FIXED['pictures'], name, 'f', data, {'b': 1})
        self.file_id = n['id']
        self.dirty = False
        self.ctx.set_title('Brush — ' + n['n'])
        self.os.toast('Saved to Pictures', '💾')

    def before_close(self):
        if not self.dirty:
            return True
        v = self.os.dialogs.choose('Save your drawing?', 'You have changes that are not saved.',
                                   [('Save', 's', 'pri'), ('Discard', 'd', 'dng'), ('Cancel', 'c', 'btn')])
        if v == 's':
            self.save_img()
            return not self.dirty
        return v == 'd'
