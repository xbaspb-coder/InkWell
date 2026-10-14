"""The window manager: app windows inside the desk, with chapters (four desktops).

Windows can be dragged by their title bar, resized from their edges, snapped
to the left/right half by dragging to a screen edge, maximised by dragging to
the top, minimised to the Spine and moved between chapters.
"""

import tkinter as tk
import traceback

from .widgets import tile_image, bind_tree
from ..util import clamp, mix, now_ms

ROM = ['I', 'II', 'III', 'IV']
BORDER = 3
TITLE_H = 36


LONG_PRESS_MS = 600


class _Press:
    """What a long press hands to a context-menu function in place of a Tk event."""

    def __init__(self, widget, x, y, x_root, y_root):
        self.widget, self.x, self.y, self.x_root, self.y_root = widget, x, y, x_root, y_root
        self.state = 0
        self.num = 3


def bind_context(widget, fn):
    """Right-click (and its macOS equivalents); on a touchscreen, also press and hold."""
    widget.bind('<Button-3>', fn, add='+')
    if widget.tk.call('tk', 'windowingsystem') == 'aqua':
        widget.bind('<Button-2>', fn, add='+')
        widget.bind('<Control-Button-1>', fn, add='+')
    hold = {'job': None}

    def cancel(_e=None):
        if hold['job'] is not None:
            try:
                widget.after_cancel(hold['job'])
            except tk.TclError:
                pass
            hold['job'] = None

    def press(e):
        cancel()
        os_ = getattr(widget._root(), 'quill', None)
        if os_ is None or not getattr(os_, 'touch_mode', False):
            return
        hold['start'] = (e.x_root, e.y_root)

        def fire():
            hold['job'] = None
            try:
                if not widget.winfo_exists():
                    return
                # Where the finger is now, so the menu opens under it.
                px, py = widget.winfo_pointerxy()
            except tk.TclError:
                return
            sx, sy = hold['start']
            if abs(px - sx) > 10 or abs(py - sy) > 10:
                return
            fn(_Press(widget, sx - widget.winfo_rootx(), sy - widget.winfo_rooty(), sx, sy))
        hold['job'] = widget.after(LONG_PRESS_MS, fire)

    def move(e):
        if hold['job'] is not None:
            sx, sy = hold['start']
            if abs(e.x_root - sx) > 10 or abs(e.y_root - sy) > 10:
                cancel()

    widget.bind('<ButtonPress-1>', press, add='+')
    widget.bind('<B1-Motion>', move, add='+')
    widget.bind('<ButtonRelease-1>', cancel, add='+')


class Window:
    def __init__(self, id_, app_id, app):
        self.id = id_
        self.app = app_id
        self.spec = app
        self.title = app.name
        self.x = self.y = 0
        self.w, self.h = 720, 480
        self.max = False
        self.min = False
        self.snap = None
        self.rest = None
        self.ch = 0
        self.z = 0
        self.born = now_ms()
        self.inst = None
        self.closing = False
        self.el = self.body = self.bar = self.name_lbl = None


class Ctx:
    """What an app receives when its window opens."""

    def __init__(self, os_, win, arg, opts):
        self.os = os_
        self.T = os_.theme
        self.win = win
        self.body = win.body
        self.arg = arg
        self.app = win.spec
        self.opts = opts or {}

    def set_title(self, t):
        self.os.wm.set_title(self.win, t)

    def close(self):
        self.os.wm.close(self.win)

    def focus(self):
        self.os.wm.focus(self.win)

    def toast(self, msg, icon='✒️'):
        self.os.toast(msg, icon)

    @property
    def alive(self):
        return self.win in self.os.wm.list and not self.win.closing


class WindowManager:
    def __init__(self, os_):
        self.os = os_
        self.T = os_.theme
        self.list = []
        self.zc = 10
        self.ch = 0
        self.active = None
        self.next_id = 1
        self.desk = os_.desk
        self.snap_frames = [tk.Frame(self.desk, bd=0) for _ in range(4)]
        for f in self.snap_frames:
            self.T.on(f, lambda f=f: f.configure(bg=self.T['acc']))
        self._snap_mode = None

    # ---------------------------------------------------------- queries
    def area(self):
        self.desk.update_idletasks()
        return max(1, self.desk.winfo_width()), max(1, self.desk.winfo_height())

    def by_app(self, app_id):
        return [w for w in self.list if w.app == app_id]

    def visible(self):
        return [w for w in self.list if w.ch == self.ch and not w.min]

    def window_of(self, widget):
        """The Window that a widget belongs to, if any."""
        while widget is not None:
            win = getattr(widget, '_qwin', None)
            if win is not None:
                return win
            widget = getattr(widget, 'master', None)
        return None

    # ---------------------------------------------------------- open
    def open(self, app_id, arg=None, opts=None):
        app = self.os.apps.get(app_id)
        if app is None:
            return None
        if app.single:
            ex = next((w for w in self.list if w.app == app_id), None)
            if ex is not None:
                self.focus(ex)
                on_arg = getattr(ex.inst, 'on_arg', None)
                if on_arg and arg is not None:
                    try:
                        on_arg(arg)
                    except Exception:
                        traceback.print_exc()
                return ex
        win = Window(self.next_id, app_id, app)
        self.next_id += 1
        aw, ah = self.area()
        win.w = min(app.w, max(300, aw - 16))
        win.h = min(app.h, max(220, ah - 16))
        n = len(self.list) % 8
        win.x = clamp(36 + n * 28, 0, max(0, aw - win.w))
        win.y = clamp(24 + n * 26, 0, max(0, ah - win.h))
        win.ch = self.ch
        self._build_chrome(win)
        self.list.append(win)
        if self.os.compact:
            # On a small screen every window starts maximised; restoring gives it its usual size.
            win.rest = (win.x, win.y, win.w, win.h)
            win.max = True
        self.geom(win)
        ctx = Ctx(self.os, win, arg, opts)
        try:
            win.inst = app.build(ctx) or _Empty()
        except Exception as e:
            traceback.print_exc()
            win.inst = _Empty()
            for c in win.body.winfo_children():
                c.destroy()
            self.os.empty_state(win.body, '⚠️', app.name + ' hit a problem and could not start.', str(e))
        self.focus(win)
        self.os.ui_sound('open')
        self.os.bus.emit('wm')
        return win

    def _build_chrome(self, win):
        T = self.T
        el = tk.Frame(self.desk, bd=0, highlightthickness=0)
        el._qwin = win
        bar = tk.Frame(el, height=TITLE_H, bd=0)
        bar.pack_propagate(False)
        icon = tk.Label(bar, bd=0)
        name = tk.Label(bar, text=win.spec.name, anchor='w', font=T.font('serif', 14, slant='italic'), bd=0)
        ctl = tk.Frame(bar, bd=0)
        b_min = self._ctl_button(ctl, '–', 'Minimize', lambda: self.minimize(win))
        b_max = self._ctl_button(ctl, '▢', 'Maximize', lambda: self.toggle_max(win))
        b_x = self._ctl_button(ctl, '✕', 'Close', lambda: self.close(win), danger=True)
        for b in (b_min, b_max, b_x):
            b.pack(side='left', padx=2)
        icon.pack(side='left', padx=(10, 8))
        ctl.pack(side='right', padx=(4, 6))
        name.pack(side='left', fill='x', expand=True)
        sep = tk.Frame(el, height=1, bd=0)
        body = tk.Frame(el, bd=0)
        bar.pack(side='top', fill='x', padx=BORDER, pady=(BORDER, 0))
        sep.pack(side='top', fill='x', padx=BORDER)
        body.pack(side='top', fill='both', expand=True, padx=BORDER, pady=(0, BORDER))
        win.el, win.bar, win.body, win.name_lbl, win.btn_max, win.icon_lbl = el, bar, body, name, b_max, icon
        win.sep = sep

        def paint():
            act = self.active is win
            border = T['acc_line'] if act else T['line']
            el.configure(bg=border)
            bar.configure(bg=T['bg2'])
            ctl.configure(bg=T['bg2'])
            sep.configure(bg=T['line'])
            body.configure(bg=T['bg1'])
            name.configure(bg=T['bg2'], fg=T['fg'] if act else mix(T['fg'], T['bg2'], .3))
            c1, c2 = win.spec.bg
            icon.configure(bg=T['bg2'], image=tile_image(self.os.root, c1, c2, 22, 7, T['bg2']), text=win.spec.icon,
                           compound='center', fg='#ffffff', font=T.font('sans', 11))
        win.paint = paint
        T.on(el, paint)

        for w in (bar, name, icon):
            w.bind('<ButtonPress-1>', lambda e: self._drag_start(win, e))
            w.bind('<B1-Motion>', lambda e: self._drag_move(win, e))
            w.bind('<ButtonRelease-1>', lambda e: self._drag_end(win, e))
            w.bind('<Double-Button-1>', lambda e: self.toggle_max(win))
            bind_context(w, lambda e: self._title_menu(win, e))
        el.bind('<Motion>', lambda e: self._edge_cursor(win, e))
        el.bind('<Leave>', lambda e: el.configure(cursor=''))
        el.bind('<ButtonPress-1>', lambda e: self._resize_start(win, e))
        el.bind('<B1-Motion>', lambda e: self._resize_move(win, e))
        el.bind('<ButtonRelease-1>', lambda e: self._resize_end(win, e))

    def _ctl_button(self, parent, text, tip, fn, danger=False):
        T = self.T
        b = tk.Label(parent, text=text, width=2, bd=0, font=T.font('sans', 13), cursor='hand2')
        state = {'hover': False}

        def paint():
            if state['hover']:
                b.configure(bg='#c0392b' if danger else T['bg3'], fg='#ffffff' if danger else T['fg'])
            else:
                b.configure(bg=T['bg2'], fg=T['fg2'])
        T.on(b, paint)
        b.bind('<Enter>', lambda e: (state.__setitem__('hover', True), paint()))
        b.bind('<Leave>', lambda e: (state.__setitem__('hover', False), paint()))
        b.bind('<ButtonRelease-1>', lambda e: fn() if 0 <= e.x < b.winfo_width() and 0 <= e.y < b.winfo_height() else None)
        return b

    # ---------------------------------------------------------- geometry
    def geom(self, win):
        if win.min or win.ch != self.ch:
            win.el.place_forget()
            return
        if win.max:
            win.el.place(x=0, y=0, relwidth=1, relheight=1, width=0, height=0)
        else:
            win.el.place(x=int(round(win.x)), y=int(round(win.y)), width=int(round(win.w)), height=int(round(win.h)),
                         relwidth=0, relheight=0)
        try:
            win.btn_max.configure(text='❐' if win.max else '▢')
        except tk.TclError:
            pass

    def _resized(self, win):
        fn = getattr(win.inst, 'on_resize', None)
        if fn:
            self.os.root.after(10, lambda: self._safe(fn))

    @staticmethod
    def _safe(fn, *a):
        try:
            return fn(*a)
        except Exception:
            traceback.print_exc()

    def toggle_max(self, win, force=False):
        if win.max and not force:
            r = win.rest
            win.max = False
            if r:
                win.x, win.y, win.w, win.h = r
            win.snap = None
        else:
            if not win.max and not win.snap:
                win.rest = win.rest if (win.rest and force) else (win.x, win.y, win.w, win.h)
            win.max = True
            win.snap = None
        self.geom(win)
        self._resized(win)
        self.focus(win)

    def snap(self, win, side):
        aw, ah = self.area()
        if not win.max and not win.snap:
            win.rest = (win.x, win.y, win.w, win.h)
        win.max = False
        win.snap = side
        win.x = 0 if side == 'l' else aw / 2
        win.y = 0
        win.w = aw / 2
        win.h = ah
        self.geom(win)
        self._resized(win)
        self.focus(win)

    def fit(self):
        aw, ah = self.area()
        for w in self.list:
            if w.max:
                self._resized(w)
                continue
            if w.snap:
                w.x = 0 if w.snap == 'l' else aw / 2
                w.w = aw / 2
                w.h = ah
            else:
                w.w = min(w.w, max(300, aw))
                w.h = min(w.h, max(200, ah))
                w.x = clamp(w.x, -w.w + 110, max(0, aw - 110))
                w.y = clamp(w.y, 0, max(0, ah - 38))
            self.geom(w)
            self._resized(w)

    # ---------------------------------------------------------- dragging
    def _drag_start(self, win, e):
        self.focus(win)
        win._drag = {'sx': e.x_root, 'sy': e.y_root, 'ox': win.x, 'oy': win.y, 'moved': False}
        self._snap_mode = None

    def _drag_move(self, win, e):
        d = getattr(win, '_drag', None)
        if not d:
            return
        dx, dy = e.x_root - d['sx'], e.y_root - d['sy']
        aw, ah = self.area()
        if not d['moved']:
            if (dx * dx + dy * dy) ** 0.5 < 4:
                return
            d['moved'] = True
            if win.max or win.snap:
                r = win.rest or (0, 0, 680, 460)
                left = self.desk.winfo_rootx()
                frac = clamp((e.x_root - left) / max(1, aw if win.max else win.w), 0.1, 0.9)
                win.max = False
                win.snap = None
                win.w, win.h = r[2], r[3]
                win.x = clamp(e.x_root - left - win.w * frac, 0, max(0, aw - win.w))
                win.y = 0
                self.geom(win)
                d.update(sx=e.x_root, sy=e.y_root, ox=win.x, oy=win.y)
                return
        win.x = clamp(d['ox'] + dx, -win.w + 110, aw - 110)
        win.y = clamp(d['oy'] + dy, 0, ah - 38)
        self.geom(win)
        px = e.x_root - self.desk.winfo_rootx()
        py = e.y_root - self.desk.winfo_rooty()
        mode = 'max' if py <= 5 else 'l' if px <= 5 else 'r' if px >= aw - 5 else None
        self._show_snap(mode, aw, ah)

    def _show_snap(self, mode, aw, ah):
        self._snap_mode = mode
        if not mode:
            for f in self.snap_frames:
                f.place_forget()
            return
        x, y, w, h = {'max': (0, 0, aw, ah), 'l': (0, 0, aw // 2, ah), 'r': (aw // 2, 0, aw - aw // 2, ah)}[mode]
        t = 3
        top, bottom, left, right = self.snap_frames
        top.place(x=x, y=y, width=w, height=t)
        bottom.place(x=x, y=y + h - t, width=w, height=t)
        left.place(x=x, y=y, width=t, height=h)
        right.place(x=x + w - t, y=y, width=t, height=h)
        for f in self.snap_frames:
            f.lift()

    def _drag_end(self, win, e):
        d = getattr(win, '_drag', None)
        win._drag = None
        mode = self._snap_mode
        self._show_snap(None, 0, 0)
        if d and d['moved'] and mode:
            if mode == 'max':
                win.rest = (win.x, win.y, win.w, win.h)
                self.toggle_max(win, True)
            else:
                self.snap(win, mode)

    # ---------------------------------------------------------- resizing
    def _edge(self, win, e):
        if win.max:
            return ''
        w, h = win.el.winfo_width(), win.el.winfo_height()
        x, y = e.x, e.y
        c = 14
        d = ''
        if y < BORDER + 2 or (y < c and (x < BORDER + 2 or x > w - BORDER - 3)):
            d += 'n'
        elif y > h - BORDER - 3 or (y > h - c and (x < BORDER + 2 or x > w - BORDER - 3)):
            d += 's'
        if x < BORDER + 2 or (x < c and (y < BORDER + 2 or y > h - BORDER - 3)):
            d += 'w'
        elif x > w - BORDER - 3 or (x > w - c and (y < BORDER + 2 or y > h - BORDER - 3)):
            d += 'e'
        return d

    CURSORS = {'n': 'sb_v_double_arrow', 's': 'sb_v_double_arrow', 'e': 'sb_h_double_arrow',
               'w': 'sb_h_double_arrow', 'nw': 'top_left_corner', 'ne': 'top_right_corner',
               'sw': 'bottom_left_corner', 'se': 'bottom_right_corner', '': ''}

    def _edge_cursor(self, win, e):
        if getattr(win, '_rz', None):
            return
        try:
            win.el.configure(cursor=self.CURSORS[self._edge(win, e)])
        except tk.TclError:
            pass

    def _resize_start(self, win, e):
        self.focus(win)
        d = self._edge(win, e)
        if not d:
            return
        win.snap = None
        win._rz = {'d': d, 'sx': e.x_root, 'sy': e.y_root, 'o': (win.x, win.y, win.w, win.h)}

    def _resize_move(self, win, e):
        r = getattr(win, '_rz', None)
        if not r:
            return
        aw, ah = self.area()
        ox, oy, ow, oh = r['o']
        dx, dy = e.x_root - r['sx'], e.y_root - r['sy']
        x, y, w, h = ox, oy, ow, oh
        mw, mh = 300, 200
        if 'e' in r['d']:
            w = clamp(ow + dx, mw, aw - ox + 200)
        if 's' in r['d']:
            h = clamp(oh + dy, mh, ah - oy + 100)
        if 'w' in r['d']:
            w = clamp(ow - dx, mw, 4000)
            x = ox + (ow - w)
        if 'n' in r['d']:
            h = clamp(oh - dy, mh, 4000)
            y = oy + (oh - h)
            if y < 0:
                h += y
                y = 0
        win.x, win.y, win.w, win.h = x, y, w, h
        self.geom(win)
        fn = getattr(win.inst, 'on_resize', None)
        if fn:
            self._safe(fn)

    def _resize_end(self, win, e):
        win._rz = None

    # ---------------------------------------------------------- menus
    def _title_menu(self, win, e):
        items = [{'label': 'Minimize', 'icon': '–', 'action': lambda: self.minimize(win)},
                 {'label': 'Restore' if win.max else 'Maximize', 'icon': '▢', 'action': lambda: self.toggle_max(win)},
                 {'label': 'Snap left', 'icon': '◧', 'action': lambda: self.snap(win, 'l')},
                 {'label': 'Snap right', 'icon': '◨', 'action': lambda: self.snap(win, 'r')}, {'sep': True}]
        for i in range(4):
            if i != win.ch:
                items.append({'label': 'Move to chapter ' + ROM[i], 'icon': '➜', 'action': lambda i=i: self.move_to(win, i)})
        items += [{'sep': True}, {'label': 'Close', 'icon': '✕', 'danger': True, 'action': lambda: self.close(win)}]
        self.os.menu.show(e.x_root, e.y_root, items)

    # ---------------------------------------------------------- focus and state
    def set_title(self, win, t):
        win.title = t or win.spec.name
        try:
            win.name_lbl.configure(text=win.title)
        except tk.TclError:
            pass
        if self.active is win:
            self.ribbon()
        self.os.bus.emit('wm')

    def focus(self, win):
        if win is None or win not in self.list:
            return
        if win.ch != self.ch:
            self.switch_chapter(win.ch, True)
        if win.min:
            win.min = False
            self.geom(win)
        self.zc += 1
        win.z = self.zc
        win.el.lift()
        for f in self.snap_frames:
            f.lift()
        prev = self.active
        self.active = win
        if prev is not None and prev is not win and prev in self.list:
            prev.paint()
        win.paint()
        self.ribbon()
        self.os.bus.emit('wm')
        fn = getattr(win.inst, 'on_focus', None)
        if fn:
            self._safe(fn)

    def restack(self):
        for w in sorted(self.list, key=lambda w: w.z):
            if w.el.winfo_ismapped():
                w.el.lift()

    def _top_visible(self):
        vis = sorted(self.visible(), key=lambda w: -w.z)
        return vis[0] if vis else None

    def minimize(self, win):
        win.min = True
        self.geom(win)
        if self.active is win:
            self.active = None
            win.paint()
            nxt = self._top_visible()
            if nxt is not None:
                self.focus(nxt)
        self.ribbon()
        self.os.bus.emit('wm')

    def close(self, win):
        if win not in self.list or win.closing:
            return
        before = getattr(win.inst, 'before_close', None)
        if before:
            try:
                ok = before()
            except Exception:
                traceback.print_exc()
                ok = True
            if ok is False:
                return
        if win not in self.list or win.closing:
            return
        win.closing = True
        fn = getattr(win.inst, 'on_close', None)
        if fn:
            self._safe(fn)
        self.list.remove(win)
        try:
            win.el.destroy()
        except tk.TclError:
            pass
        if self.active is win:
            self.active = None
            nxt = self._top_visible()
            if nxt is not None:
                self.focus(nxt)
        self.os.ui_sound('close')
        self.ribbon()
        self.os.bus.emit('wm')

    def move_to(self, win, ch):
        win.ch = ch
        self.geom(win)
        if self.active is win and ch != self.ch:
            self.active = None
            nxt = self._top_visible()
            if nxt is not None:
                self.focus(nxt)
        self.ribbon()
        self.os.bus.emit('wm')
        self.os.toast('Moved to chapter ' + ROM[ch], '➜')

    def switch_chapter(self, i, keep=False):
        i = clamp(int(i), 0, 3)
        self.ch = i
        for w in self.list:
            self.geom(w)
        self.restack()
        if not keep:
            top = self._top_visible()
            if top is not None:
                self.focus(top)
            else:
                prev = self.active
                self.active = None
                if prev is not None and prev in self.list:
                    prev.paint()
        self.ribbon()
        self.os.bus.emit('wm')

    def cycle(self):
        ws = sorted([w for w in self.list if w.ch == self.ch], key=lambda w: w.id)
        if not ws:
            return
        i = ws.index(self.active) if self.active in ws else -1
        self.focus(ws[(i + 1) % len(ws)])

    def close_all(self):
        for w in list(self.list):
            fn = getattr(w.inst, 'on_close', None)
            if fn:
                self._safe(fn)
            try:
                w.el.destroy()
            except tk.TclError:
                pass
        self.list = []
        self.active = None
        self.ribbon()
        self.os.bus.emit('wm')

    def ribbon(self):
        self.os.ribbon_update()


class _Empty:
    pass


__all__ = ['WindowManager', 'Window', 'Ctx', 'ROM', 'bind_context', 'bind_tree']
