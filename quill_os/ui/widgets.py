"""Themed building blocks: buttons, inputs, switches, scroll areas, tabs, icon tiles.

Plain Tk widgets look different on every system (and macOS ignores button
colours), so Quill draws its own from Labels, Frames and Canvases.
"""

import math
import tkinter as tk

from ..util import hex_to_rgb, mix, rgb_to_hex

_TIP = {'win': None, 'job': None}


# ================================================================ tooltips

def tooltip(widget, text_or_fn, side='right'):
    """Show a small label next to widget after the pointer rests on it."""
    def show():
        _TIP['job'] = None
        hide()
        text = text_or_fn() if callable(text_or_fn) else text_or_fn
        if not text or not widget.winfo_exists():
            return
        os_ = getattr(widget.winfo_toplevel(), 'quill', None)
        T = os_.theme if os_ else None
        root = widget.winfo_toplevel()
        lbl = tk.Label(root, text=text, padx=10, pady=4, bd=0, highlightthickness=1,
                       bg=T['bg2'] if T else '#222', fg=T['fg'] if T else '#fff',
                       highlightbackground=T['line'] if T else '#444', font=T.font('sans', 12) if T else None)
        lbl.update_idletasks()
        x = widget.winfo_rootx() - root.winfo_rootx()
        y = widget.winfo_rooty() - root.winfo_rooty()
        if side == 'right':
            px, py = x + widget.winfo_width() + 10, y + widget.winfo_height() // 2 - lbl.winfo_reqheight() // 2
        else:
            px, py = x + widget.winfo_width() // 2 - lbl.winfo_reqwidth() // 2, y + widget.winfo_height() + 6
        px = max(4, min(px, root.winfo_width() - lbl.winfo_reqwidth() - 4))
        py = max(4, min(py, root.winfo_height() - lbl.winfo_reqheight() - 4))
        lbl.place(x=px, y=py)
        lbl.lift()
        _TIP['win'] = lbl

    def enter(_e):
        cancel()
        _TIP['job'] = widget.after(450, show)

    def cancel():
        if _TIP['job']:
            try:
                widget.after_cancel(_TIP['job'])
            except tk.TclError:
                pass
            _TIP['job'] = None

    def leave(_e):
        cancel()
        hide()

    widget.bind('<Enter>', enter, add='+')
    widget.bind('<Leave>', leave, add='+')
    widget.bind('<ButtonPress>', leave, add='+')


def hide():
    w = _TIP['win']
    _TIP['win'] = None
    if w is not None:
        try:
            w.destroy()
        except tk.TclError:
            pass


# ================================================================ buttons

class Btn(tk.Label):
    """A themed button.

    kind: 'btn' (default), 'pri' (accent), 'dng' (danger), 'ghost' (flat),
          'ibtn' (small icon button), 'chip' (rounded toggle like the chapter buttons)
    size: 'md' or 'sm'.  bg: colour name of the surface it sits on (for flat kinds).
    """

    def __init__(self, parent, T, text='', command=None, kind='btn', size='md', bg='bg2', font=None, width=None,
                 tip=None, fg=None, anchor='center', padx=None, pady=None, **kw):
        self.T = T
        self.kind = kind
        self.size = size
        self.surface = bg
        self.command = command
        self.disabled = False
        self.on_state = False
        self.hover = False
        self.pressed = False
        self.custom_fg = fg
        if font is None:
            if kind == 'ibtn':
                font = T.font('sans', 15)
            elif size == 'sm':
                font = T.font('sans', 12, 'bold' if kind == 'pri' else 'normal')
            else:
                font = T.font('sans', 13, 'bold' if kind == 'pri' else 'normal')
        if padx is None:
            padx = {'ibtn': 6, 'chip': 8}.get(kind, 10 if size == 'sm' else 14)
        if pady is None:
            pady = {'ibtn': 3, 'chip': 1}.get(kind, 3 if size == 'sm' else 6)
        super().__init__(parent, text=text, font=font, padx=padx, pady=pady, bd=0, cursor='hand2', takefocus=1,
                         anchor=anchor, highlightthickness=1, **kw)
        if width:
            self.configure(width=width)
        self.bind('<Enter>', self._enter)
        self.bind('<Leave>', self._leave)
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<ButtonRelease-1>', self._release)
        self.bind('<Return>', self._key)
        self.bind('<KP_Enter>', self._key)
        self.bind('<space>', self._key)
        self.bind('<FocusIn>', lambda e: self.paint())
        self.bind('<FocusOut>', lambda e: self.paint())
        T.on(self, self.paint)
        if tip:
            tooltip(self, tip, 'below')

    # ---- state
    def set_text(self, text):
        self.configure(text=text)

    def set_disabled(self, v=True):
        self.disabled = bool(v)
        self.configure(cursor='arrow' if self.disabled else 'hand2', takefocus=0 if self.disabled else 1)
        self.paint()

    def set_on(self, v=True):
        self.on_state = bool(v)
        self.paint()

    def set_kind(self, kind):
        self.kind = kind
        self.paint()

    def invoke(self):
        if not self.disabled and self.command:
            self.command()

    # ---- painting
    def colors(self):
        T, k = self.T, self.kind
        surf = T[self.surface]
        if k == 'pri' or (k == 'chip' and self.on_state):
            bg, fg, line = T['acc'], T['acc_fg'], T['acc']
            if self.hover and not self.disabled:
                bg = T['acc_hover']
        elif k == 'dng':
            bg, fg, line = T['dng'], '#ffffff', T['dng']
            if self.hover and not self.disabled:
                bg = mix(T['dng'], '#ffffff', .12)
        elif k in ('ibtn', 'ghost', 'chip', 'flat'):
            bg, fg = surf, T['fg']
            line = surf if k != 'chip' else T['line']
            if k == 'chip':
                fg = T['fg2']
            if self.on_state:
                bg, fg = T['acc_soft'], T['acc']
            if self.hover and not self.disabled and not self.on_state:
                bg, fg = T['bg3'], T['fg']
            if k == 'ghost':
                line = T['line']
        else:
            bg, fg, line = T['bg3'], T['fg'], T['line']
            if self.on_state:
                bg, fg, line = T['acc'], T['acc_fg'], T['acc']
            elif self.hover and not self.disabled:
                bg, line = T['hover'], mix(T['line'], T['fg'], .3)
        if self.custom_fg and not self.on_state and k not in ('pri', 'dng'):
            fg = T[self.custom_fg]
        if self.disabled:
            fg = mix(fg, bg, .55)
        return bg, fg, line

    def paint(self):
        try:
            bg, fg, line = self.colors()
            focus = self.focus_get() is self and not self.disabled
        except (tk.TclError, KeyError):
            return
        try:
            self.configure(bg=bg, fg=fg, highlightbackground=line, highlightcolor=self.T['acc'] if focus else line)
            if focus:
                self.configure(highlightbackground=self.T['acc'])
        except tk.TclError:
            pass

    # ---- events
    def _enter(self, _e):
        self.hover = True
        self.paint()

    def _leave(self, _e):
        self.hover = False
        self.pressed = False
        self.paint()

    def _press(self, _e):
        if self.disabled:
            return
        self.pressed = True

    def _release(self, e):
        if self.disabled or not self.pressed:
            return
        self.pressed = False
        try:
            inside = 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height()
        except tk.TclError:
            return
        if inside and self.command:
            self.command()

    def _key(self, _e):
        if not self.disabled and self.command:
            self.command()
        return 'break'


# ================================================================ text inputs

class Entry(tk.Entry):
    """A themed single-line input with an optional placeholder."""

    def __init__(self, parent, T, value='', placeholder='', show=None, width=None, font=None, bg='bg0', justify='left',
                 **kw):
        self.T = T
        self.placeholder = placeholder
        self._ph = False
        self._show = show or ''
        self.surface = bg
        super().__init__(parent, bd=0, relief='flat', highlightthickness=1, font=font or T.font('sans', 13),
                         width=width or 20, justify=justify, **kw)
        if value:
            self.insert(0, value)
        T.on(self, self._paint)
        self.bind('<FocusIn>', self._focus_in, add='+')
        self.bind('<FocusOut>', self._focus_out, add='+')
        self._focus_out(None)

    def _paint(self):
        T = self.T
        self.configure(bg=T[self.surface], insertbackground=T['fg'], highlightbackground=T['line'],
                       highlightcolor=T['acc'], selectbackground=T['acc'], selectforeground=T['acc_fg'],
                       disabledbackground=T[self.surface], disabledforeground=T['fg2'],
                       fg=T['fg2'] if self._ph else T['fg'])

    def _focus_in(self, _e):
        if self._ph:
            self._ph = False
            self.delete(0, 'end')
            self.configure(show=self._show, fg=self.T['fg'])

    def _focus_out(self, _e):
        if not super().get() and self.placeholder and self.focus_get() is not self:
            self._ph = True
            self.configure(show='')
            self.insert(0, self.placeholder)
            self.configure(fg=self.T['fg2'])
        elif not self._ph:
            self.configure(show=self._show)

    def get(self):
        return '' if self._ph else super().get()

    def set(self, value):
        if self._ph:
            self._ph = False
            self.configure(show=self._show, fg=self.T['fg'])
        self.delete(0, 'end')
        self.insert(0, value)
        if not value:
            self._focus_out(None)


def style_text(T, text, bg='bg1', fg='fg', font=None, insert='fg'):
    """Theme a tk.Text widget."""
    def fn():
        text.configure(bg=T[bg], fg=T[fg], insertbackground=T[insert], selectbackground=T['acc'],
                       selectforeground=T['acc_fg'], inactiveselectbackground=mix(T[bg], T['acc'], .35),
                       highlightthickness=0, bd=0, relief='flat')
    T.on(text, fn)
    if font is not None:
        text.configure(font=font)


# ================================================================ switch, slider, check, select

class Switch(tk.Canvas):
    """An on/off switch (42 × 24)."""

    def __init__(self, parent, T, value=False, command=None, bg='bg1'):
        super().__init__(parent, width=42, height=24, highlightthickness=0, bd=0, cursor='hand2', takefocus=1)
        self.T, self.value, self.command, self.surface = T, bool(value), command, bg
        self.bind('<Button-1>', lambda e: self.toggle())
        self.bind('<space>', lambda e: self.toggle())
        self.bind('<Return>', lambda e: self.toggle())
        T.on(self, self.paint)

    def toggle(self):
        self.value = not self.value
        self.paint()
        if self.command:
            self.command(self.value)

    def set(self, v):
        self.value = bool(v)
        self.paint()

    def paint(self):
        T = self.T
        self.delete('all')
        self.configure(bg=T[self.surface])
        track = T['acc'] if self.value else T['bg3']
        edge = T['acc'] if self.value else T['line']
        _round_rect(self, 1, 1, 41, 23, 11, fill=track, outline=edge)
        x = 23 if self.value else 4
        knob = T['acc_fg'] if self.value else T['fg']
        self.create_oval(x, 4, x + 16, 20, fill=knob, outline=knob)


def _round_rect(c, x0, y0, x1, y1, r, **kw):
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r,
           x0, y0 + r, x0, y0]
    return c.create_polygon(pts, smooth=True, splinesteps=12, **kw)


round_rect = _round_rect


class Slider(tk.Scale):
    def __init__(self, parent, T, frm=0, to=100, value=0, command=None, length=170, bg='bg1'):
        super().__init__(parent, from_=frm, to=to, orient='horizontal', showvalue=0, length=length, sliderlength=16,
                         width=10, bd=0, highlightthickness=0, relief='flat', sliderrelief='flat')
        self.set(value)
        self.T, self.surface = T, bg
        if command:
            self.configure(command=lambda v: command(int(float(v))))
        # On X11 the background colour is the handle's colour; elsewhere the system draws the handle.
        T.on(self, lambda: self.configure(bg=T['acc'], troughcolor=T['bg3'], activebackground=T['acc_hover'],
                                          highlightbackground=T[bg], fg=T['fg']))


class Check(tk.Checkbutton):
    def __init__(self, parent, T, text='', value=False, command=None, bg='bg2'):
        self.var = tk.BooleanVar(master=parent, value=bool(value))
        super().__init__(parent, text=text, variable=self.var, bd=0, highlightthickness=0, font=T.font('sans', 12),
                         command=(lambda: command(self.var.get())) if command else None, cursor='hand2')
        T.on(self, lambda: self.configure(bg=T[bg], fg=T['fg'], activebackground=T[bg], activeforeground=T['fg'],
                                          selectcolor=T['bg0']))

    def get(self):
        return self.var.get()

    def set(self, v):
        self.var.set(bool(v))


class Select(Btn):
    """A drop-down list: options are (value, label) pairs."""

    def __init__(self, parent, T, options, value=None, command=None, bg='bg2', size='md'):
        self.options = list(options)
        self.value = value if value is not None else (self.options[0][0] if self.options else None)
        self.on_change = command
        super().__init__(parent, T, text=self._label(), command=self._open, kind='btn', size=size, bg=bg)

    def _label(self):
        for v, l in self.options:
            if v == self.value:
                return l + '  ▾'
        return '—  ▾'

    def set(self, value):
        self.value = value
        self.set_text(self._label())

    def get(self):
        return self.value

    def _open(self):
        T = self.T
        m = tk.Menu(self, tearoff=0, bg=T['bg2'], fg=T['fg'], activebackground=T['acc'], activeforeground=T['acc_fg'],
                    bd=1, relief='flat', font=T.font('sans', 13))
        for v, l in self.options:
            m.add_command(label=('✓ ' if v == self.value else '    ') + l, command=lambda v=v: self._pick(v))
        try:
            m.tk_popup(self.winfo_rootx(), self.winfo_rooty() + self.winfo_height())
        finally:
            m.grab_release()

    def _pick(self, v):
        self.set(v)
        if self.on_change:
            self.on_change(v)


# ================================================================ scrolling

def wheel_units(e):
    """Mouse-wheel event → lines to scroll (positive = down)."""
    if getattr(e, 'num', None) == 4:
        return -1
    if getattr(e, 'num', None) == 5:
        return 1
    d = getattr(e, 'delta', 0) or 0
    if abs(d) >= 120:
        return int(-d / 120)
    return -1 if d > 0 else 1 if d < 0 else 0


class ScrollArea(tk.Frame):
    """A vertically scrolling container; put children in `.inner`."""

    def __init__(self, parent, T, bg='bg1', bar=True):
        super().__init__(parent, bd=0, highlightthickness=0)
        self.T, self.surface = T, bg
        self.canvas = tk.Canvas(self, bd=0, highlightthickness=0)
        self.inner = tk.Frame(self.canvas, bd=0)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor='nw')
        self.bar = tk.Scrollbar(self, orient='vertical', command=self.canvas.yview, width=10, bd=0,
                                highlightthickness=0, relief='flat') if bar else None
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.inner.bind('<Configure>', self._sync)
        self.canvas.bind('<Configure>', self._fit)
        self._wheel = self.scroll
        T.on(self, self._paint)

    def _paint(self):
        T = self.T
        self.configure(bg=T[self.surface])
        self.canvas.configure(bg=T[self.surface])
        self.inner.configure(bg=T[self.surface])
        if self.bar is not None:
            self.bar.configure(bg=T['bg3'], troughcolor=T[self.surface], activebackground=T['hover'])

    def _sync(self, _e=None):
        self.canvas.configure(scrollregion=(0, 0, self.inner.winfo_reqwidth(), self.inner.winfo_reqheight()))
        self._toggle_bar()

    def _fit(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)
        self._toggle_bar()

    def _toggle_bar(self):
        if self.bar is None:
            return
        need = self.inner.winfo_reqheight() > self.canvas.winfo_height() + 1
        if need and not self.bar.winfo_ismapped():
            self.bar.pack(side='right', fill='y', before=self.canvas)
        elif not need and self.bar.winfo_ismapped():
            self.bar.pack_forget()
            self.canvas.yview_moveto(0)

    def _on_scroll(self, a, b):
        if self.bar is not None:
            self.bar.set(a, b)

    def scroll(self, units):
        if self.inner.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(units, 'units')

    def to_top(self):
        self.canvas.yview_moveto(0)

    def see(self, widget):
        """Scroll so that widget (inside .inner) is visible."""
        try:
            self.update_idletasks()
            y = widget.winfo_rooty() - self.inner.winfo_rooty()
            h = widget.winfo_height()
            total = max(1, self.inner.winfo_reqheight())
            view_h = self.canvas.winfo_height()
            top = self.canvas.canvasy(0)
            if y < top:
                self.canvas.yview_moveto(y / total)
            elif y + h > top + view_h:
                self.canvas.yview_moveto((y + h - view_h) / total)
        except tk.TclError:
            pass


# ================================================================ tabs

class Tabs(tk.Frame):
    """A row of tabs: items are (id, label); command(id) when one is chosen."""

    def __init__(self, parent, T, items, current, command):
        super().__init__(parent, bd=0)
        self.T, self.items, self.current, self.command = T, list(items), current, command
        self.cells = {}
        T.on(self, lambda: self.configure(bg=T['bg2']))
        self.line = tk.Frame(self, height=1)
        T.on(self.line, lambda: self.line.configure(bg=T['line']))
        self.line.pack(side='bottom', fill='x')
        self.row = tk.Frame(self, bd=0)
        T.on(self.row, lambda: self.row.configure(bg=T['bg2']))
        self.row.pack(side='top', fill='x', padx=6, pady=(4, 0))
        self.render()

    def render(self, items=None):
        if items is not None:
            self.items = list(items)
        for w in self.row.winfo_children():
            w.destroy()
        self.cells = {}
        for ident, label in self.items:
            cell = tk.Frame(self.row, bd=0)
            bar = tk.Frame(cell, height=2)
            bar.pack(side='top', fill='x')
            lbl = tk.Label(cell, text=label, padx=12, pady=5, font=self.T.font('sans', 13), cursor='hand2')
            lbl.pack(side='top')
            cell.pack(side='left', padx=(0, 2))
            for w in (cell, lbl):
                w.bind('<Button-1>', lambda e, i=ident: self.select(i, True))
            self.cells[ident] = (cell, bar, lbl)
        self.paint()

    def paint(self):
        T = self.T
        for ident, (cell, bar, lbl) in self.cells.items():
            on = ident == self.current
            bg = T['bg1'] if on else T['bg2']
            cell.configure(bg=bg)
            bar.configure(bg=T['acc'] if on else bg)
            lbl.configure(bg=bg, fg=T['fg'] if on else T['fg2'])

    def select(self, ident, notify=False):
        self.current = ident
        self.paint()
        if notify and self.command:
            self.command(ident)


# ================================================================ icon tiles

_TILE_CACHE = {}


def tile_image(root, c1, c2, size, radius, surface):
    """A rounded square with a diagonal gradient, blended into `surface` at the corners."""
    key = (c1, c2, size, radius, surface)
    img = _TILE_CACHE.get(key)
    if img is not None:
        return img
    a, b, s = hex_to_rgb(c1), hex_to_rgb(c2), hex_to_rgb(surface)
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            # coverage of the rounded square at this pixel (soft edge of one pixel)
            cx = min(max(x + 0.5, radius), size - radius)
            cy = min(max(y + 0.5, radius), size - radius)
            d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
            cov = max(0.0, min(1.0, radius - d + 0.5))
            t = (x * 0.57 + y * 0.82) / (size * 1.39)
            col = tuple(a[i] + (b[i] - a[i]) * t for i in range(3))
            if y < 1.5 and cov > 0:
                col = tuple(c + (255 - c) * 0.18 for c in col)
            col = tuple(s[i] + (col[i] - s[i]) * cov for i in range(3))
            row.append(rgb_to_hex(col))
        rows.append('{' + ' '.join(row) + '}')
    img = tk.PhotoImage(master=root, width=size, height=size)
    img.put(' '.join(rows))
    _TILE_CACHE[key] = img
    return img


def clear_tile_cache():
    _TILE_CACHE.clear()


def bind_tree(widget, sequence, fn):
    """Bind an event on a widget and all of its children."""
    widget.bind(sequence, fn, add='+')
    for c in widget.winfo_children():
        bind_tree(c, sequence, fn)


def ellipsize(font, text, width):
    if font.measure(text) <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.measure(text[:mid] + '…') <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + '…'


def wrap_lines(font, text, width, max_lines=2):
    """Word-wrap text to at most max_lines lines, ellipsising the last one."""
    words = text.replace('\n', ' ').split(' ')
    lines, cur = [], ''
    for w in words:
        trial = (cur + ' ' + w) if cur else w
        if font.measure(trial) <= width:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        cur = w
        while font.measure(cur) > width and len(lines) < max_lines - 1:
            # break a long word
            k = len(cur)
            while k > 1 and font.measure(cur[:k]) > width:
                k -= 1
            lines.append(cur[:k])
            cur = cur[k:]
        if len(lines) >= max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    used = ' '.join(lines)
    if len(used) < len(text.replace('\n', ' ').strip()) and lines:
        lines[-1] = ellipsize(font, lines[-1] + '…', width) if not lines[-1].endswith('…') else lines[-1]
    lines = [ellipsize(font, l, width) for l in lines[:max_lines]]
    return lines
