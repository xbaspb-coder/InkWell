"""Everything that floats above the desktop: menus, dialogs, toasts, the Inkwell,
Spread, the quick-settings and notification panels, and the boot, lock, setup
and power-off screens.

Dialogs and the lock screen *wait* for an answer: they keep the program
running (Tk's wait_variable) and return the result, so callers read like the
original `await Dlg.confirm(...)` code.
"""

import math
import tkinter as tk

from .widgets import Btn, Entry, ScrollArea, Slider, tile_image, wheel_units, wrap_lines, ellipsize
from .theme import THEME_NAMES, THEME_BG
from ..calc import CalcError, calc_eval, fmt_num
from ..core import icon_of
from ..state import ACCENTS
from ..util import DAYS, MONTHS, ago, check_password, clamp, fmt_time, js_weekday, mix
import datetime as _dt
import re

ROM = ['I', 'II', 'III', 'IV']


# ================================================================ context menu

class Menu:
    def __init__(self, os_):
        self.os = os_
        self.menu = None

    def hide(self):
        if self.menu is not None:
            try:
                self.menu.unpost()
                self.menu.destroy()
            except tk.TclError:
                pass
            self.menu = None

    def show(self, x, y, items):
        """items: dicts with label, icon, key, action, danger, disabled — or {'sep': True}."""
        self.hide()
        T = self.os.theme
        m = tk.Menu(self.os.root, tearoff=0, bg=T['bg2'], fg=T['fg'], activebackground=T['acc'],
                    activeforeground=T['acc_fg'], disabledforeground=T['disabled'], bd=1, relief='flat',
                    font=T.font('sans', 13), activeborderwidth=0)
        last_sep = True
        for it in items:
            if not it:
                continue
            if it.get('sep'):
                if not last_sep:
                    m.add_separator()
                last_sep = True
                continue
            last_sep = False
            label = (it.get('icon') or ' ') + '   ' + it['label']
            act = it.get('action')
            opts = dict(label=label, command=(lambda a=act: self.os.root.after(1, a)) if act else None,
                        state='disabled' if it.get('disabled') else 'normal')
            if it.get('key'):
                opts['accelerator'] = it['key']
            if it.get('danger'):
                opts['foreground'] = T['red']
                opts['activebackground'] = '#c0392b'
                opts['activeforeground'] = '#ffffff'
            try:
                m.add_command(**opts)
            except tk.TclError:
                opts.pop('foreground', None)
                opts.pop('activebackground', None)
                opts.pop('activeforeground', None)
                m.add_command(**opts)
        self.menu = m
        try:
            m.tk_popup(int(x), int(y))
        finally:
            try:
                m.grab_release()
            except tk.TclError:
                pass


# ================================================================ dialogs

class Dialogs:
    def __init__(self, os_):
        self.os = os_
        self.busy = False
        self.box = None

    @property
    def active(self):
        return self.box is not None

    def show(self, build, sticky=False, on_show=None):
        """Show a modal dialog. build(box, close) fills it and returns the widget to focus."""
        os_ = self.os
        os_.wait(lambda: not self.busy or os_.quitting)
        if os_.quitting:
            return None
        self.busy = True
        T = os_.theme
        root = os_.root
        prev = root.focus_get()
        result = {'v': None, 'done': False}
        outer = tk.Frame(root, bd=0, highlightthickness=1)
        box = tk.Frame(outer, bd=0)
        box.pack(fill='both', expand=True, padx=18, pady=16)
        T.on(outer, lambda: (outer.configure(bg=T['bg1'], highlightbackground=T['line'], highlightcolor=T['line']),
                             box.configure(bg=T['bg1'])))
        self.box = outer

        def close(v=None):
            if result['done']:
                return
            result['done'] = True
            result['v'] = v
            try:
                outer.grab_release()
            except tk.TclError:
                pass
            try:
                outer.destroy()
            except tk.TclError:
                pass
            if self.box is outer:
                self.box = None
            self.busy = False

        focus_el = build(box, close)
        width = min(420, max(260, root.winfo_width() - 32))
        outer.place(relx=0.5, rely=0.5, anchor='center', width=width)
        outer.lift()
        outer.update_idletasks()

        def on_key(e):
            if e.keysym == 'Escape' and not sticky:
                close(None)
                return 'break'
            if e.keysym in ('Return', 'KP_Enter') and not (e.state & 0x1):
                w = e.widget
                if isinstance(w, (tk.Text, Btn)):
                    return None
                p = getattr(outer, '_primary', None)
                if p is not None:
                    p.invoke()
                    return 'break'
            return None

        def bind_all_children(w):
            w.bind('<Key>', on_key, add='+')
            for c in w.winfo_children():
                bind_all_children(c)
        bind_all_children(outer)
        try:
            outer.grab_set()
        except tk.TclError:
            pass
        target = focus_el or getattr(outer, '_primary', None)
        if target is not None:
            def focus_it():
                try:
                    target.focus_set()
                    if isinstance(target, tk.Entry):
                        target.select_range(0, 'end')
                        target.icursor('end')
                except tk.TclError:
                    pass
            root.after(20, focus_it)
        if on_show:
            root.after(0, on_show)
        os_.wait(lambda: result['done'] or os_.quitting)
        if not result['done']:
            close(None)
        try:
            if prev is not None and prev.winfo_exists():
                prev.focus_set()
        except tk.TclError:
            pass
        return result['v']

    # ---- the standard dialogs
    def _title(self, box, text):
        T = self.os.theme
        lbl = tk.Label(box, text=text, anchor='w', justify='left', font=T.font('serif', 18, 'bold', 'italic'))
        T.style(lbl, bg='bg1', fg='fg')
        lbl.pack(fill='x', pady=(0, 6))

    def _text(self, box, text):
        T = self.os.theme
        lbl = tk.Label(box, text=text, anchor='w', justify='left', wraplength=370, font=T.font('sans', 13))
        T.style(lbl, bg='bg1', fg='fg2')
        lbl.pack(fill='x', pady=(0, 12))
        return lbl

    def _acts(self, box):
        T = self.os.theme
        row = tk.Frame(box, bd=0)
        T.style(row, bg='bg1')
        row.pack(fill='x')
        return row

    def prompt(self, title='Name', value='', text=None, ok='OK', validate=None, password=False, placeholder=''):
        T = self.os.theme

        def build(box, close):
            self._title(box, title)
            if text:
                self._text(box, text)
            inp = Entry(box, T, value=value if value is not None else '', placeholder=placeholder,
                        show='•' if password else None, font=T.font('sans', 14))
            inp.pack(fill='x', ipady=6, pady=(0, 10))
            msg = tk.Label(box, text='', anchor='w', font=T.font('sans', 12))
            T.style(msg, bg='bg1', fg='red')
            msg.pack(fill='x')

            def go():
                v = inp.get()
                bad = validate(v) if validate else None
                if bad:
                    msg.configure(text=bad)
                    self.os.ui_sound('error')
                    return
                close(v)
            row = self._acts(box)
            okb = Btn(row, T, ok, go, kind='pri', bg='bg1')
            okb.pack(side='right')
            Btn(row, T, 'Cancel', lambda: close(None), bg='bg1').pack(side='right', padx=(0, 8))
            box.master._primary = okb
            return inp

        return self.show(build)

    def confirm(self, title='Are you sure?', text='', ok='OK', danger=False, cancel='Cancel'):
        T = self.os.theme

        def build(box, close):
            self._title(box, title)
            self._text(box, text)
            row = self._acts(box)
            okb = Btn(row, T, ok, lambda: close(True), kind='dng' if danger else 'pri', bg='bg1')
            okb.pack(side='right')
            Btn(row, T, cancel, lambda: close(False), bg='bg1').pack(side='right', padx=(0, 8))
            box.master._primary = okb
            return okb

        return bool(self.show(build))

    def alert(self, title='Notice', text=''):
        T = self.os.theme

        def build(box, close):
            self._title(box, title)
            self._text(box, text)
            row = self._acts(box)
            okb = Btn(row, T, 'OK', lambda: close(True), kind='pri', bg='bg1')
            okb.pack(side='right')
            box.master._primary = okb
            return okb

        return self.show(build)

    def choose(self, title='', text='', buttons=(), sticky=False, on_show=None):
        """buttons: list of (label, value, kind). The first one is the default."""
        T = self.os.theme

        def build(box, close):
            self._title(box, title)
            self._text(box, text)
            row = self._acts(box)
            made = []
            for label, value, kind in buttons:
                made.append(Btn(row, T, label, lambda v=value: close(v), kind=kind or 'btn', bg='bg1'))
            for b in reversed(made):
                b.pack(side='right', padx=(8, 0))
            box.master._primary = made[0] if made else None
            return made[0] if made else None

        return self.show(build, sticky=sticky, on_show=on_show)

    def pick_file(self, filt=None, title='Choose a file'):
        os_ = self.os
        files = [n for n in os_.fs.all() if n['t'] == 'f' and (filt is None or filt(n))]
        if not files:
            os_.toast('There are no matching files yet', '📂')
            return None
        T = os_.theme

        def build(box, close):
            self._title(box, title)
            q = Entry(box, T, placeholder='Search files…')
            q.pack(fill='x', ipady=5, pady=(0, 8))
            area = ScrollArea(box, T, bg='bg1')
            area.pack(fill='both', expand=True, pady=(0, 12))
            area.configure(height=300)
            area.canvas.configure(height=300)

            def draw(*_):
                for c in area.inner.winfo_children():
                    c.destroy()
                f = q.get().lower()
                hits = sorted([n for n in files if not f or f in n['n'].lower()], key=lambda n: -n['m'])
                if not hits:
                    lbl = tk.Label(area.inner, text='No files match.', anchor='w', font=T.font('sans', 13))
                    T.style(lbl, bg='bg1', fg='fg2')
                    lbl.pack(fill='x', padx=10, pady=10)
                for n in hits[:80]:
                    row = Btn(area.inner, T, iconize(n) + '   ' + n['n'] + '      ' + os_.fs.path(n['p']),
                              lambda i=n['id']: close(i), kind='flat', bg='bg1', anchor='w', font=T.font('sans', 13))
                    row.pack(fill='x')
                area.to_top()
            q.bind('<KeyRelease>', draw)
            draw()
            row = self._acts(box)
            Btn(row, T, 'Cancel', lambda: close(None), bg='bg1').pack(side='right')
            return q

        return self.show(build)


def iconize(n):
    return icon_of(n)


# ================================================================ toasts

class Toasts:
    """Pop-up notices stacked under the ribbon on the right (newest at the bottom, at most four)."""

    def __init__(self, os_):
        self.os = os_
        self.items = []

    def show(self, title, body='', icon='🔔', ms=5000):
        T = self.os.theme
        t = tk.Frame(self.os.root, bd=0, highlightthickness=1, cursor='hand2')
        accent = tk.Frame(t, width=3, bd=0)
        accent.pack(side='left', fill='y')
        ic = tk.Label(t, text=icon, font=T.font('sans', 19), bd=0)
        ic.pack(side='left', anchor='n', padx=(9, 8), pady=8)
        col = tk.Frame(t, bd=0)
        col.pack(side='left', fill='both', expand=True, pady=8, padx=(0, 10))
        tl = tk.Label(col, text=title, anchor='w', justify='left', wraplength=260, font=T.font('sans', 13, 'bold'))
        tl.pack(fill='x')
        bl = None
        if body:
            bl = tk.Label(col, text=body, anchor='w', justify='left', wraplength=260, font=T.font('sans', 12))
            bl.pack(fill='x')

        def paint():
            t.configure(bg=T['glass'], highlightbackground=T['line'])
            accent.configure(bg=T['acc'])
            col.configure(bg=T['glass'])
            ic.configure(bg=T['glass'], fg=T['fg'])
            tl.configure(bg=T['glass'], fg=T['fg'])
            if bl is not None:
                bl.configure(bg=T['glass'], fg=T['fg2'])
        T.on(t, paint)
        self.items.append(t)
        while len(self.items) > 4:
            self._kill(self.items[0])

        def kill(_e=None):
            self._kill(t)
        for w in (t, ic, col, tl) + ((bl,) if bl else ()):
            w.bind('<Button-1>', kill)
        self.os.root.after(ms, kill)
        self._place()

    def _kill(self, t):
        if t in self.items:
            self.items.remove(t)
            try:
                t.destroy()
            except tk.TclError:
                pass
            self._place()

    def _place(self):
        root = self.os.root
        width = min(340, root.winfo_width() - 24)
        y = self.os.RIBBON + 10
        for t in self.items:
            t.place(relx=1.0, x=-12, y=y, anchor='ne', width=width)
            t.lift()
            t.update_idletasks()
            y += t.winfo_reqheight() + 8


# ================================================================ Inkwell (launcher)

class Inkwell:
    def __init__(self, os_):
        self.os = os_
        self.el = None
        self.items = []
        self.sel = 0

    def toggle(self, q=''):
        if self.el is not None:
            self.close()
        else:
            self.open(q)

    def close(self):
        if self.el is not None:
            try:
                self.el.destroy()
            except tk.TclError:
                pass
            self.el = None

    @staticmethod
    def score(text, q):
        text = text.lower()
        if not q:
            return 1
        if text.startswith(q):
            return 100
        i = text.find(q)
        if i >= 0:
            return 70 - min(i, 40)
        j = 0
        for c in text:
            if j < len(q) and c == q[j]:
                j += 1
            if j == len(q):
                return 15
        return 0

    def actions(self):
        os_ = self.os
        S = os_.S
        A = [
            ('Lock screen', '🔒', 'lock sleep', lambda: os_.lock.show()),
            ('Restart Quill', '🔄', 'restart reboot', os_.restart),
            ('Shut down', '⏻', 'shutdown power off', os_.power_off),
            ('New margin note', '🗒', 'note sticky margin',
             lambda: os_.notes.add(os_.wm.area()[0] - 240, 20)),
            ('Empty Trash', '🗑', 'trash empty delete', os_.empty_trash_confirm),
            (('Turn off' if S['set']['dnd'] else 'Turn on') + ' Do Not Disturb', '🔕', 'dnd quiet silence notifications',
             os_.toggle_dnd),
            ('Show Spread', '▦', 'overview windows spread', os_.spread.open),
            ('Close all windows', '✕', 'close everything windows', lambda: [os_.wm.close(w) for w in list(os_.wm.list)]),
        ]
        for t, name in THEME_NAMES.items():
            A.append(('Theme: ' + name, '🎨', 'theme appearance dark light ' + t,
                      lambda t=t, name=name: (os_.set_theme(t), os_.toast(name + ' theme', '🎨'))))
        from ..apps.portal import PORTAL_SITES
        for p in PORTAL_SITES:
            A.append(('Open ' + p['name'], p['icon'], 'site og browser ' + (p['host'] or ''),
                      lambda p=p: os_.open_web({'type': 'og', 'host': p['host'], 'path': '/'})))
        return A

    def build(self, raw):
        os_ = self.os
        q = raw.strip().lower()
        out = []

        def add(sec, **o):
            o['sec'] = sec
            out.append(o)

        if raw.startswith('>'):
            cmd = raw[1:].strip()
            add('Terminal', icon='❯', label='Run “' + cmd + '” in the terminal', sub='Enter',
                run=lambda: os_.wm.open('term', {'cmd': cmd}))
            return out
        math_raw = None
        if raw.startswith('='):
            math_raw = raw[1:]
        elif re.match(r'^calc\s+', raw, re.I):
            math_raw = re.sub(r'^calc\s+', '', raw, flags=re.I)
        elif (re.search(r'[0-9]', raw) and re.search(r'[-+*/^%!()]|sqrt|sin|cos|tan|log|ln|pi', raw, re.I)
              and re.match(r'^[0-9a-z\s.+\-*/^%!(),×÷π√]+$', raw, re.I)):
            math_raw = raw
        if math_raw is not None and math_raw.strip():
            try:
                t = fmt_num(calc_eval(math_raw))

                def copy(t=t):
                    os_.toast(('Copied ' + t) if os_.copy_text(t) else ('Result: ' + t), '🧮')
                add('Calculator', icon='🧮', label='= ' + t, sub='Enter copies', run=copy)
            except CalcError as e:
                if raw.startswith('='):
                    add('Calculator', icon='🧮', label=str(e), sub='', run=lambda: None)
        apps = []
        for id_, a in os_.apps.items():
            if a.hidden:
                continue
            s = max(self.score(a.name, q), self.score(a.kw or '', q) * 0.6, self.score(id_, q) * 0.8)
            if s > 0:
                apps.append((s, id_))
        apps.sort(key=lambda x: -x[0])
        for _, id_ in apps:
            a = os_.apps[id_]
            add('Apps', icon=a.icon, bg=a.bg, label=a.name, sub=a.about or '', run=lambda i=id_: os_.wm.open(i))
        if q:
            files = [(self.score(n['n'], q), n) for n in os_.fs.all()]
            files = sorted([x for x in files if x[0] > 0], key=lambda x: -x[0])[:8]
            for _, n in files:
                add('Files', icon=icon_of(n), label=n['n'], sub=os_.fs.path(n['p']) or '/', run=lambda n=n: os_.open_file(n))
        else:
            for id_ in os_.S.get('recent') or []:
                n = os_.fs.get(id_)
                if n is not None and os_.fs.live(n):
                    add('Recent', icon=icon_of(n), label=n['n'], sub=os_.fs.path(n['p']) or '/',
                        run=lambda n=n: os_.open_file(n))
        acts = [(max(self.score(lbl, q), self.score(kw, q) * 0.6), lbl, ic, run) for lbl, ic, kw, run in self.actions()]
        acts = sorted([a for a in acts if a[0] > 0], key=lambda a: -a[0])
        for _, lbl, ic, run in (acts if q else acts[:6]):
            add('Actions', icon=ic, label=lbl, sub='', run=run)
        if q and not raw.startswith('='):
            t = raw.strip()
            add('Elsewhere', icon='🔎', label='Search OG for “' + t + '”', sub='Opens in a browser tab',
                run=lambda: os_.open_web({'type': 'search', 'q': t}))
            add('Elsewhere', icon='❯', label='Run “' + t + '” in the terminal', sub='',
                run=lambda: os_.wm.open('term', {'cmd': t}))
        return out

    def open(self, prefill=''):
        if self.el is not None:
            return
        os_ = self.os
        os_.menu.hide()
        os_.panels.hide()
        T = os_.theme
        root = os_.root
        width = min(640, root.winfo_width() - 20)
        box = tk.Frame(root, bd=0, highlightthickness=1)
        self.el = box
        T.on(box, lambda: box.configure(bg=T['glass'], highlightbackground=T['line']))
        inp = tk.Entry(box, bd=0, relief='flat', highlightthickness=0, font=T.font('serif', 20, slant='italic'))
        T.on(inp, lambda: inp.configure(bg=T['glass'], fg=T['fg'], insertbackground=T['fg'],
                                        selectbackground=T['acc'], selectforeground=T['acc_fg']))
        inp.insert(0, prefill or '')
        inp.pack(fill='x', ipady=14, padx=20)
        hint = tk.Label(box, text='', anchor='w', font=T.font('serif', 20, slant='italic'))
        sep = tk.Frame(box, height=1, bd=0)
        T.on(sep, lambda: sep.configure(bg=T['line']))
        sep.pack(fill='x')
        area = ScrollArea(box, T, bg='glass', bar=True)
        area.pack(fill='both', expand=True, padx=8, pady=8)
        sep2 = tk.Frame(box, height=1, bd=0)
        T.on(sep2, lambda: sep2.configure(bg=T['line']))
        sep2.pack(fill='x')
        foot = tk.Frame(box, bd=0)
        T.on(foot, lambda: foot.configure(bg=T['glass']))
        foot.pack(fill='x', padx=14, pady=6)
        for t in ('↑↓ choose', '↵ open', 'esc close', '= maths', '> terminal'):
            lbl = tk.Label(foot, text=t, font=T.font('sans', 11))
            T.style(lbl, bg='glass', fg='fg2')
            lbl.pack(side='left', padx=(0, 14))
        placeholder = 'Open an app, find a file, or type 2+2…'
        rows = []

        def go(i):
            if not (0 <= i < len(self.items)):
                return
            it = self.items[i]
            self.close()
            root.after(10, lambda: os_.safe(it['run']))

        def render(*_):
            v = inp.get()
            self.items = self.build(v)
            self.sel = clamp(self.sel, 0, max(0, len(self.items) - 1))
            for c in area.inner.winfo_children():
                c.destroy()
            rows.clear()
            last = None
            for i, it in enumerate(self.items):
                if it['sec'] != last:
                    sl = tk.Label(area.inner, text=it['sec'].upper(), anchor='w', font=T.font('sans', 11))
                    T.style(sl, bg='glass', fg='fg2')
                    sl.pack(fill='x', padx=10, pady=(8, 4))
                    last = it['sec']
                row = tk.Frame(area.inner, bd=0, cursor='hand2')
                if it.get('bg'):
                    c1, c2 = it['bg']
                    ic = tk.Label(row, text=it['icon'], compound='center', fg='#ffffff', bd=0, font=T.font('sans', 13),
                                  image=tile_image(root, c1, c2, 26, 8, T['glass']))
                else:
                    ic = tk.Label(row, text=it['icon'], width=2, font=T.font('sans', 18), bd=0)
                ic.pack(side='left', padx=(10, 12), pady=6)
                lt = tk.Label(row, text=ellipsize(T.font('sans', 14), it['label'], width - 260), anchor='w',
                              font=T.font('sans', 14), bd=0)
                lt.pack(side='left', fill='x', expand=True)
                ls = None
                if it.get('sub'):
                    ls = tk.Label(row, text=ellipsize(T.font('sans', 12), it['sub'], 220), anchor='e',
                                  font=T.font('sans', 12), bd=0)
                    ls.pack(side='right', padx=(8, 10))
                row.pack(fill='x')
                rows.append((row, ic, lt, ls, bool(it.get('bg'))))
                for w in (row, ic, lt) + ((ls,) if ls else ()):
                    w.bind('<Button-1>', lambda e, i=i: go(i))
                    w.bind('<Motion>', lambda e, i=i: hover(i))
            if not self.items:
                e = tk.Label(area.inner, text='Nothing found.', font=T.font('sans', 13))
                T.style(e, bg='glass', fg='fg2')
                e.pack(pady=20)
            paint_sel()
            area.to_top()
            hint_update()

        def paint_sel():
            for i, (row, ic, lt, ls, tile) in enumerate(rows):
                on = i == self.sel
                bg = T['acc'] if on else T['glass']
                fg = T['acc_fg'] if on else T['fg']
                row.configure(bg=bg)
                ic.configure(bg=bg) if tile else ic.configure(bg=bg, fg=fg)
                lt.configure(bg=bg, fg=fg)
                if ls is not None:
                    ls.configure(bg=bg, fg=fg if on else T['fg2'])
            if 0 <= self.sel < len(rows):
                area.see(rows[self.sel][0])

        def hover(i):
            if self.sel != i:
                self.sel = i
                paint_sel()

        def hint_update():
            if inp.get():
                hint.place_forget()
            else:
                hint.configure(text=placeholder, bg=T['glass'], fg=T['fg2'])
                hint.place(x=20, y=0, height=inp.winfo_height() or 56)
                hint.bind('<Button-1>', lambda e: inp.focus_set())

        def on_key(e):
            k = e.keysym
            if k == 'Escape':
                self.close()
                return 'break'
            if k == 'Down':
                self.sel = min(len(self.items) - 1, self.sel + 1)
                paint_sel()
                return 'break'
            if k == 'Up':
                self.sel = max(0, self.sel - 1)
                paint_sel()
                return 'break'
            if k in ('Return', 'KP_Enter'):
                go(self.sel)
                return 'break'
            if k == 'Tab':
                return 'break'
            return None

        def on_change(*_):
            self.sel = 0
            render()

        inp.bind('<KeyPress>', on_key)
        var_watch = {'v': inp.get()}

        def poll_change(_e=None):
            if self.el is None:
                return
            if inp.get() != var_watch['v']:
                var_watch['v'] = inp.get()
                on_change()
        inp.bind('<KeyRelease>', poll_change)
        inp.bind('<<Paste>>', lambda e: root.after(1, poll_change))
        box.place(relx=0.5, y=int(root.winfo_height() * 0.12), anchor='n', width=width,
                  height=int(min(root.winfo_height() * 0.72, 560)))
        box.lift()
        self.sel = 0
        render()
        inp.focus_set()
        inp.icursor('end')
        os_.outside_click(box, self.close, lambda: self.el is box)


# ================================================================ Spread

class Spread:
    def __init__(self, os_):
        self.os = os_
        self.el = None

    def close(self):
        if self.el is not None:
            try:
                self.el.destroy()
            except tk.TclError:
                pass
            self.el = None

    def open(self):
        if self.el is not None:
            self.close()
            return
        os_ = self.os
        os_.menu.hide()
        os_.panels.hide()
        T = os_.theme
        root = os_.root
        ov = tk.Frame(root, bd=0)
        self.el = ov
        T.on(ov, lambda: ov.configure(bg=mix(T['bg0'], '#000000', .45)))
        area = ScrollArea(ov, T, bg='bg0', bar=True)
        T.on(area, lambda: [w.configure(bg=mix(T['bg0'], '#000000', .45)) for w in (area, area.canvas, area.inner)])
        area.pack(fill='both', expand=True, padx=(os_.SPINE + 30, 30), pady=(os_.RIBBON + 30, 30))

        def draw():
            for c in area.inner.winfo_children():
                c.destroy()
            bg = mix(T['bg0'], '#000000', .45)
            h2 = tk.Label(area.inner, text='Every page you have open' if os_.wm.list else 'No windows are open',
                          font=T.font('serif', 22, 'bold', 'italic'), bg=bg, fg='#ffffff')
            h2.pack(pady=(0, 18))
            grid = tk.Frame(area.inner, bg=bg)
            grid.pack(fill='x')
            avail = max(260, root.winfo_width() - os_.SPINE - 60)
            cols = max(1, avail // 248)
            for c in range(cols):
                grid.columnconfigure(c, weight=1, uniform='spread')
            wins = sorted(os_.wm.list, key=lambda w: (0 if w.ch == os_.wm.ch else 1, w.id))
            for i, w in enumerate(wins):
                card = tk.Frame(grid, bd=0, highlightthickness=1, cursor='hand2', bg=T['bg1'],
                                highlightbackground=T['line'])
                st = tk.Frame(card, bg=T['bg2'])
                st.pack(fill='x')
                c1, c2 = w.spec.bg
                ic = tk.Label(st, image=tile_image(root, c1, c2, 22, 7, T['bg2']), text=w.spec.icon, compound='center',
                              fg='#ffffff', bg=T['bg2'], font=T.font('sans', 11))
                ic.pack(side='left', padx=(12, 8), pady=9)
                tl = tk.Label(st, text=ellipsize(T.font('serif', 13, slant='italic'), w.title, 140), anchor='w',
                              bg=T['bg2'], fg=T['fg'], font=T.font('serif', 13, slant='italic'))
                tl.pack(side='left', fill='x', expand=True)
                tk.Label(st, text=ROM[w.ch], bg=T['bg2'], fg=T['fg2'], font=T.font('sans', 12)).pack(side='left', padx=4)
                x = Btn(st, T, '✕', lambda w=w: (os_.wm.close(w), root.after(60, draw)), kind='ibtn', bg='bg2')
                x.pack(side='right', padx=6)
                sb = tk.Label(card, text=w.spec.icon, bg=T['bg1'], fg=T['fg'], font=T.font('sans', 42), height=2)
                sb.pack(fill='both', expand=True, pady=12)

                def go(_e=None, w=w):
                    self.close()
                    os_.wm.focus(w)
                for el in (card, st, ic, tl, sb):
                    el.bind('<Button-1>', go)
                card.bind('<Enter>', lambda e, c=card: c.configure(highlightbackground=T['acc']))
                card.bind('<Leave>', lambda e, c=card: c.configure(highlightbackground=T['line']))
                card.grid(row=i // cols, column=i % cols, padx=9, pady=9, sticky='nsew')
        draw()
        for w in (ov, area.canvas, area.inner):
            w.bind('<Button-1>', lambda e: self.close() if e.widget in (ov, area.canvas, area.inner) else None)
        ov.place(x=0, y=0, relwidth=1, relheight=1)
        ov.lift()
        ov.bind('<Escape>', lambda e: self.close())
        ov.focus_set()


# ================================================================ panels

class Panels:
    def __init__(self, os_):
        self.os = os_
        self.el = None
        self.kind = None

    def hide(self):
        if self.el is not None:
            try:
                self.el.destroy()
            except tk.TclError:
                pass
            self.el = None
            self.kind = None
            self.os.tray_paint()

    def toggle(self, kind):
        if self.kind == kind:
            self.hide()
            return
        self.hide()
        self.os.menu.hide()
        self.kind = kind
        self.el = self.quick() if kind == 'quick' else self.notifs()
        self.os.tray_paint()

    def _panel(self, width):
        T = self.os.theme
        p = tk.Frame(self.os.root, bd=0, highlightthickness=1)
        T.on(p, lambda: p.configure(bg=T['glass'], highlightbackground=T['line']))
        p.place(relx=1.0, x=-8, y=self.os.RIBBON + 6, anchor='ne', width=width)
        p.lift()
        self.os.outside_click(p, self.hide, lambda: self.el is p, ignore=self.os.tray_buttons)
        return p

    def _label(self, parent, text, font, fg='fg', **kw):
        T = self.os.theme
        lbl = tk.Label(parent, text=text, font=font, **kw)
        T.style(lbl, bg='glass', fg=fg)
        return lbl

    def quick(self):
        os_ = self.os
        T = os_.theme
        S = os_.S
        p = self._panel(320)
        inner = tk.Frame(p, bd=0)
        T.style(inner, bg='glass')
        inner.pack(fill='both', expand=True, padx=14, pady=14)
        self._label(inner, 'Quick settings', T.font('serif', 15, 'bold', 'italic'), anchor='w').pack(fill='x', pady=(0, 10))

        def slider(ico, lo, hi, val, on):
            row = tk.Frame(inner, bd=0)
            T.style(row, bg='glass')
            self._label(row, ico, T.font('sans', 16), width=2).pack(side='left')
            s = Slider(row, T, lo, hi, val, on, length=240, bg='glass')
            s.pack(side='left', fill='x', expand=True, padx=(8, 0))
            row.pack(fill='x', pady=6)

        def set_bright(v):
            S['set']['bright'] = v
            os_.apply_look()
            os_.touch()

        def set_vol(v):
            S['set']['volume'] = v
            os_.apply_look()
            os_.touch()
        slider('☀', 20, 100, S['set']['bright'], set_bright)
        slider('🔊', 0, 100, S['set']['volume'], set_vol)
        grid = tk.Frame(inner, bd=0)
        T.style(grid, bg='glass')
        grid.pack(fill='x', pady=12)

        def refresh():
            self.hide()
            self.toggle('quick')

        def tile(i, ico, label, on, fn):
            b = tk.Frame(grid, bd=0, highlightthickness=1, cursor='hand2', height=54)
            b.pack_propagate(False)
            top = tk.Label(b, text=ico, font=T.font('sans', 17))
            bot = tk.Label(b, text=label, font=T.font('sans', 11))
            top.pack(pady=(6, 0))
            bot.pack()
            bg = T['acc'] if on else T['bg2']
            fg = T['acc_fg'] if on else T['fg']
            b.configure(bg=bg, highlightbackground=T['acc'] if on else T['line'])
            top.configure(bg=bg, fg=fg)
            bot.configure(bg=bg, fg=fg)
            for w in (b, top, bot):
                w.bind('<Button-1>', lambda e: (fn(), os_.root.after(1, refresh)))
            b.grid(row=0, column=i, sticky='ew', padx=4)
            grid.columnconfigure(i, weight=1, uniform='q')

        def cycle_theme():
            ks = list(THEME_NAMES)
            os_.set_theme(ks[(ks.index(S['set']['theme']) + 1) % len(ks)])

        def flip(key, after=None):
            def fn():
                S['set'][key] = not S['set'][key]
                os_.touch()
                if after:
                    after()
            return fn
        tile(0, '🎨', THEME_NAMES.get(S['set']['theme'], ''), False, cycle_theme)
        tile(1, '🔕', 'Quiet', S['set']['dnd'], flip('dnd'))
        tile(2, '🔔', 'Sounds', S['set']['uisnd'], flip('uisnd'))
        tile(3, '✨', 'Motion', S['set']['anim'], flip('anim', os_.apply_look))
        who = ('Signed in as ' + os_.me + ' · cloud sync ' + ('on' if S['set']['autosync'] else 'off')) if os_.me \
            else 'Guest · files stay on this device'
        self._label(inner, who, T.font('sans', 12), fg='fg2', anchor='w').pack(fill='x', pady=(2, 10))
        row = tk.Frame(inner, bd=0)
        T.style(row, bg='glass')
        row.pack(fill='x', pady=(6, 0))
        for i, (t, fn) in enumerate((('🔒 Lock', lambda: (self.hide(), os_.lock.show())),
                                     ('🔄 Restart', lambda: (self.hide(), os_.restart())),
                                     ('⏻ Off', lambda: (self.hide(), os_.power_off())))):
            Btn(row, T, t, fn, bg='glass').grid(row=0, column=i, sticky='ew', padx=(0 if i == 0 else 8, 0))
            row.columnconfigure(i, weight=1, uniform='b')
        row2 = tk.Frame(inner, bd=0)
        T.style(row2, bg='glass')
        row2.pack(fill='x', pady=(8, 0))
        Btn(row2, T, '⚙️ All settings', lambda: (self.hide(), os_.wm.open('loom')), bg='glass').pack(fill='x')
        return p

    def notifs(self):
        os_ = self.os
        T = os_.theme
        S = os_.S
        S['meta']['seen'] = os_.now_ms()
        os_.bell_update()
        p = self._panel(340)
        head = tk.Frame(p, bd=0)
        T.style(head, bg='glass')
        head.pack(fill='x', padx=14, pady=(12, 8))
        self._label(head, 'Notifications', T.font('serif', 15, 'bold', 'italic')).pack(side='left')
        lst = ScrollArea(p, T, bg='glass')
        lst.pack(fill='both', expand=True)
        h = int(os_.root.winfo_height() * 0.7)

        def quiet():
            S['set']['dnd'] = not S['set']['dnd']
            os_.touch()
            qb.set_text('🔕 Quiet on' if S['set']['dnd'] else '🔕 Quiet')

        def clear():
            S['notifs'] = []
            os_.touch()
            draw()
            os_.bell_update()
        Btn(head, T, 'Clear all', clear, kind='ghost', size='sm', bg='glass').pack(side='right')
        qb = Btn(head, T, '🔕 Quiet on' if S['set']['dnd'] else '🔕 Quiet', quiet, kind='ghost', size='sm', bg='glass')
        qb.pack(side='right', padx=6)

        def draw():
            for c in lst.inner.winfo_children():
                c.destroy()
            if not S['notifs']:
                e = tk.Frame(lst.inner, bd=0)
                T.style(e, bg='glass')
                self._label(e, '🕊️', T.font('sans', 38)).pack(pady=(18, 4))
                self._label(e, 'All quiet. Nothing new.', T.font('sans', 13), fg='fg2').pack(pady=(0, 18))
                e.pack(fill='x')
            for n in S['notifs']:
                row = tk.Frame(lst.inner, bd=0)
                T.style(row, bg='glass')
                self._label(row, n.get('icon', '🔔'), T.font('sans', 20)).pack(side='left', anchor='n', padx=(12, 10), pady=10)
                col = tk.Frame(row, bd=0)
                T.style(col, bg='glass')
                col.pack(side='left', fill='x', expand=True, pady=10)
                self._label(col, n.get('title', ''), T.font('sans', 13, 'bold'), anchor='w', justify='left',
                            wraplength=230).pack(fill='x')
                if n.get('body'):
                    self._label(col, n['body'], T.font('sans', 12), fg='fg2', anchor='w', justify='left',
                                wraplength=230).pack(fill='x')
                self._label(col, ago(n.get('t', 0)), T.font('sans', 11), fg='fg2', anchor='w').pack(fill='x')

                def dismiss(n=n):
                    S['notifs'] = [x for x in S['notifs'] if x is not n]
                    os_.touch()
                    draw()
                Btn(row, T, '✕', dismiss, kind='ibtn', bg='glass').pack(side='right', anchor='n', padx=8, pady=8)
                row.pack(fill='x')
                sep = tk.Frame(lst.inner, height=1, bd=0)
                T.style(sep, bg='line')
                sep.pack(fill='x')
            lst.update_idletasks()
            need = lst.inner.winfo_reqheight()
            lst.canvas.configure(height=min(h - 60, max(60, need)))
        draw()
        return p


# ================================================================ full-screen layers

def full_layer(os_, z_name):
    """A canvas covering the whole window with the soft radial background."""
    T = os_.theme
    c = tk.Canvas(os_.root, bd=0, highlightthickness=0)
    c._qname = z_name

    def paint(_e=None):
        c.delete('bgfill')
        w, h = max(1, c.winfo_width()), max(1, c.winfo_height())
        c.configure(bg=T['bg0'])
        steps = 36
        for i in range(steps, 0, -1):
            t = i / steps
            rx, ry = 1.2 * w * t, 1.0 * h * t
            col = mix(T['bg2'], T['bg0'], t)
            c.create_oval(w / 2 - rx, -ry, w / 2 + rx, ry, fill=col, outline=col, tags='bgfill')
        c.tag_lower('bgfill')
    c.bind('<Configure>', paint)
    T.on(c, paint)
    c.place(x=0, y=0, relwidth=1, relheight=1)
    tk.Misc.lift(c)   # Canvas.lift() raises drawn items, not the widget
    return c


QUILL_PATH = [('M', 27, 3), ('C', 14.5, 3.4, 7.4, 10.4, 6.4, 21.3), ('L', 4, 29), ('L', 11.6, 26.7),
              ('C', 22.5, 25.8, 28.4, 17.6, 27, 3)]


def quill_points(scale, ox, oy):
    pts = []
    cur = (0, 0)
    for seg in QUILL_PATH:
        if seg[0] in ('M', 'L'):
            cur = (seg[1], seg[2])
            pts.append(cur)
        else:
            x1, y1, x2, y2, x3, y3 = seg[1:]
            x0, y0 = cur
            for k in range(1, 21):
                t = k / 20
                a = (1 - t) ** 3
                b = 3 * (1 - t) ** 2 * t
                cc = 3 * (1 - t) * t * t
                d = t ** 3
                pts.append((a * x0 + b * x1 + cc * x2 + d * x3, a * y0 + b * y1 + cc * y2 + d * y3))
            cur = (x3, y3)
    return [(ox + x * scale, oy + y * scale) for x, y in pts]


class Boot:
    def __init__(self, os_):
        self.os = os_
        self.el = None

    def show(self, msg=None):
        if self.el is not None:
            self.el.destroy()
        os_ = self.os
        T = os_.theme
        c = full_layer(os_, 'boot')
        self.el = c
        state = {'t': 0.0}

        def layout(_e=None):
            c.delete('fg')
            w, h = c.winfo_width(), c.winfo_height()
            cx, cy = w / 2, h / 2 - 40
            pts = quill_points(3.0, cx - 48, cy - 48)
            n = max(2, int(len(pts) * min(1.0, state['t'] / 1.2)))
            flat = [v for p in pts[:n] for v in p]
            c.create_line(*flat, fill=T['acc'], width=2.2, capstyle='round', joinstyle='round', tags='fg')
            if state['t'] >= 1.2:
                a, b = (cx - 48 + 5.5 * 3, cy - 48 + 28.5 * 3), (cx - 48 + 19 * 3, cy - 48 + 12.5 * 3)
                c.create_line(*a, *b, fill=T['acc'], width=2.2, capstyle='round', tags='fg')
            c.create_text(cx, cy + 82, text='Quill.OS', fill=T['fg'], font=T.font('serif', 34, slant='italic'), tags='fg')
            c.create_text(cx, cy + 116, text=msg or 'Opening the inkwell…', fill=T['fg2'], font=T.font('sans', 13),
                          tags='fg')
            bw = 200
            c.create_rectangle(cx - bw / 2, cy + 140, cx + bw / 2, cy + 143, fill=T['bg3'], outline='', tags='fg')
            frac = 1 - (1 - min(1.0, state['t'] / 1.4)) ** 2
            if frac > 0:
                c.create_rectangle(cx - bw / 2, cy + 140, cx - bw / 2 + bw * frac, cy + 143, fill=T['acc'], outline='',
                                   tags='fg')

        def tick():
            if self.el is not c:
                return
            state['t'] += 0.04
            layout()
            if state['t'] < 1.5:
                c.after(40, tick)
        c.bind('<Configure>', lambda e: layout(), add='+')
        c.after(10, tick)
        return c

    def hide(self):
        c = self.el
        if c is None:
            return
        self.el = None
        self.os.sleep(150)
        try:
            c.destroy()
        except tk.TclError:
            pass

    def wait(self, ms):
        """Wait up to ms, or until a key is pressed or the screen is clicked."""
        os_ = self.os
        state = {'done': False}

        def fin(_e=None):
            state['done'] = True
        os_.root.after(ms, fin)

        def arm():
            if self.el is not None:
                self.el.bind('<Button-1>', fin, add='+')
            os_.root.bind('<Key>', fin, add='+')
        os_.root.after(250, arm)
        os_.wait(lambda: state['done'] or os_.quitting)
        try:
            os_.root.unbind('<Key>')
        except tk.TclError:
            pass


class Lock:
    def __init__(self, os_):
        self.os = os_
        self.el = None
        self.active = False

    def show(self):
        if self.active:
            return
        os_ = self.os
        self.active = True
        os_.menu.hide()
        os_.panels.hide()
        os_.ink.close()
        os_.spread.close()
        T = os_.theme
        S = os_.S
        c = full_layer(os_, 'lock')
        self.el = c
        name = S['user']['name'] or os_.me or 'Guest'
        # Text and the avatar are drawn straight onto the background so nothing hides the gradient;
        # only the password box and the button are real widgets.
        row = tk.Frame(c, bd=0)
        state = {'done': False, 'msg': ''}
        inp = None
        if S['user']['pin']:
            inp = Entry(row, T, placeholder='Password', show='•', width=14, font=T.font('sans', 18), justify='center')
            inp.pack(side='left', ipady=6, padx=(0, 8))

        def unlock():
            state['done'] = True

        def try_pin(_e=None):
            if inp is None:
                unlock()
                return
            if check_password(inp.get(), S['user']['pin']):
                unlock()
            else:
                state['msg'] = 'That is not the right password.'
                layout()
                inp.set('')
                os_.ui_sound('error')
                shake(inp)
                inp.focus_set()
        go = Btn(row, T, 'Unlock' if S['user']['pin'] else 'Click to unlock', try_pin, kind='pri', bg='bg0')
        go.pack(side='left')
        if inp is not None:
            inp.bind('<Return>', try_pin)
            inp.bind('<KP_Enter>', try_pin)

        def bg_at(x, y):
            w, h = max(1, c.winfo_width()), max(1, c.winfo_height())
            t = math.sqrt(((x - w / 2) / (1.2 * w)) ** 2 + (y / h) ** 2)
            t = min(1.0, math.ceil(t * 36) / 36)
            return mix(T['bg2'], T['bg0'], t)

        def layout(_e=None):
            c.delete('content')
            w, h = c.winfo_width(), c.winfo_height()
            cx, cy = w / 2, h / 2
            d = _dt.datetime.now()
            c.create_text(cx, cy - 150, text=fmt_time(d, clock24=S['set'].get('clock24', True)), fill=T['fg'],
                          font=T.font('serif', 76), tags=('content', 'clock'))
            c.create_text(cx, cy - 92, text='%s, %d %s' % (DAYS[js_weekday(d)], d.day, MONTHS[d.month - 1]),
                          fill=T['fg2'], font=T.font('serif', 17, slant='italic'), tags=('content', 'date'))
            r = 42
            for i in range(18):
                col = mix(T['acc'], T['acc_dark'], i / 18)
                inset = i * 0.5
                c.create_oval(cx - r + inset, cy - 30 - r + inset, cx + r - inset, cy - 30 + r - inset, fill=col,
                              outline=col, tags='content')
            c.create_text(cx, cy - 30, text=(name[:1] or 'Q').upper(), fill=T['acc_fg'],
                          font=T.font('serif', 38, 'bold', 'italic'), tags='content')
            c.create_text(cx, cy + 32, text=name, fill=T['fg'], font=T.font('sans', 16, 'bold'), tags='content')
            surface = bg_at(cx, cy + 80)
            row.configure(bg=surface)
            go.surface = surface
            go.paint()
            c.create_window(cx, cy + 80, window=row, tags='content')
            if state['msg']:
                c.create_text(cx, cy + 122, text=state['msg'], fill=T['red'], font=T.font('sans', 12), tags='content')
        c.bind('<Configure>', layout, add='+')
        layout()

        def upd():
            if self.el is not c:
                return
            d = _dt.datetime.now()
            c.itemconfigure('clock', text=fmt_time(d, clock24=S['set'].get('clock24', True)))
            c.itemconfigure('date', text='%s, %d %s' % (DAYS[js_weekday(d)], d.day, MONTHS[d.month - 1]))
            c.after(1000, upd)
        upd()
        if inp is None:
            c.bind('<Return>', lambda e: unlock())
            c.bind('<space>', lambda e: unlock())
        (inp or go).focus_set()
        os_.root.after(30, lambda: (inp or go).focus_set() if self.el is c else None)
        os_.wait(lambda: state['done'] or os_.quitting)
        self.el = None
        self.active = False
        try:
            c.destroy()
        except tk.TclError:
            pass
        os_.last_active = os_.monotonic()


def shake(widget):
    try:
        info = widget.pack_info()
    except tk.TclError:
        return
    base = info.get('padx', 0)
    if isinstance(base, (tuple, list)):
        base = base[0]
    seq = [-8, 8, -5, 5, 0]

    def step(i=0):
        if i >= len(seq):
            try:
                widget.pack_configure(padx=info.get('padx', 0))
            except tk.TclError:
                pass
            return
        try:
            off = seq[i]
            widget.pack_configure(padx=(max(0, int(base) + off + 8), max(0, 8 - off)))
        except tk.TclError:
            return
        widget.after(60, lambda: step(i + 1))
    step()


def avatar(parent, T, letter, size, surface):
    c = tk.Canvas(parent, width=size, height=size, bd=0, highlightthickness=0)

    def paint():
        c.delete('all')
        c.configure(bg=T[surface])
        steps = 18
        for i in range(steps):
            t = i / steps
            col = mix(T['acc'], T['acc_dark'], t)
            inset = i * 0.5
            c.create_oval(inset, inset, size - inset, size - inset, fill=col, outline=col)
        c.create_oval(1, 1, size - 1, size - 1, outline='')
        c.create_text(size / 2, size / 2, text=letter, fill=T['acc_fg'],
                      font=T.font('serif', int(size * 0.45), 'bold', 'italic'))
    T.on(c, paint)
    return c


def setup_wizard(os_):
    """The welcome wizard: Galau account, display name, Quill's password, look, tips.

    The Galau step has no way to skip it; it is left out when an account is already signed in.
    Waits until the wizard is finished."""
    from .account import galau_form
    from ..util import hash_password
    T = os_.theme
    S = os_.S
    c = full_layer(os_, 'setup')
    steps = ([] if os_.galau.signed_in else ['galau']) + ['name', 'password', 'look', 'done']
    state = {'i': 0, 'done': False, 'name': S['user']['name'] or os_.me or '', 'pw': None}
    holder = {'card': None}
    pad = 16 if os_.compact else 26
    os_.setup_state = state            # for tests

    def go(step):
        state['i'] = steps.index(step)
        render()

    def galau_name():
        return (os_.galau.address or '').split('@')[0]

    def render():
        if holder['card'] is not None:
            holder['card'].destroy()
        step = steps[state['i']]
        state['step'] = step
        card = tk.Frame(c, bd=0, highlightthickness=1)
        T.on(card, lambda: card.configure(bg=T['bg1'], highlightbackground=T['line']))
        holder['card'] = card
        inner = tk.Frame(card, bd=0)
        T.style(inner, bg='bg1')
        inner.pack(fill='both', expand=True, padx=pad, pady=pad)

        def h2(text):
            lbl = tk.Label(inner, text=text, anchor='w', font=T.font('serif', 22 if os_.compact else 26, 'bold', 'italic'))
            T.style(lbl, bg='bg1', fg='fg')
            lbl.pack(fill='x', pady=(0, 6))

        def p(text, after=16):
            lbl = tk.Label(inner, text=text, anchor='w', justify='left', wraplength=400, font=T.font('sans', 13))
            T.style(lbl, bg='bg1', fg='fg2')
            lbl.pack(fill='x', pady=(0, after))
            return lbl

        def footer():
            f = tk.Frame(inner, bd=0)
            T.style(f, bg='bg1')
            return f

        foot = None
        if step == 'galau':
            h2('Welcome to Quill.OS')
            p('First, sign in or sign up to Galau services. It is the same account as OG Browser and Galau Mail.', 10)

            def signed(_address):
                if not state['name']:
                    state['name'] = galau_name()
                go('name')
            form = galau_form(inner, os_, signed)
            form.pack(fill='x')
            os_.account_form = form
        elif step == 'name':
            if not os_.compact:
                av = avatar(inner, T, ((state['name'] or 'Q')[:1] or 'Q').upper(), 84, 'bg1')
                av.pack(anchor='w', pady=(0, 14))
            h2('Your display name')
            p('What should Quill call you? It is shown on the lock screen and in the terminal.')
            inp = Entry(inner, T, value=state['name'] or galau_name(), placeholder='Your name', font=T.font('sans', 15))
            inp.pack(fill='x', ipady=8, pady=(0, 6))
            msg = p('', 8)

            def nxt(_e=None):
                v = inp.get().strip()[:30]
                if not v:
                    msg.configure(text='Please type a name.')
                    return
                state['name'] = v
                go('password')
            inp.bind('<Return>', nxt)
            foot = footer()
            Btn(foot, T, 'Next →', nxt, kind='pri', bg='bg1').pack(side='right')
            c.after(30, inp.focus_set)
        elif step == 'password':
            h2('A password for Quill')
            p('You type it when Quill starts and to unlock the screen. It stays on this computer and is separate '
              'from your Galau password.', 10)
            a = Entry(inner, T, placeholder='Password (at least 4 characters)', show='•', font=T.font('sans', 14))
            a.pack(fill='x', ipady=6, pady=(0, 8))
            b = Entry(inner, T, placeholder='Type it again', show='•', font=T.font('sans', 14))
            b.pack(fill='x', ipady=6, pady=(0, 6))
            msg = p('', 8)

            def nxt(_e=None):
                if len(a.get()) < 4:
                    msg.configure(text='The password needs at least 4 characters.')
                    return
                if a.get() != b.get():
                    msg.configure(text='The two passwords are different.')
                    return
                state['pw'] = a.get()
                go('look')
            a.bind('<Return>', lambda e: b.focus_set())
            b.bind('<Return>', nxt)
            foot = footer()
            Btn(foot, T, '← Back', lambda: go('name'), bg='bg1').pack(side='left')
            Btn(foot, T, 'Next →', nxt, kind='pri', bg='bg1').pack(side='right')
            c.after(30, a.focus_set)
        elif step == 'look':
            h2('Choose your look')
            p('Pick a theme and an accent colour. You can change both any time in Loom.')
            tg = tk.Frame(inner, bd=0)
            T.style(tg, bg='bg1')
            tg.pack(fill='x', pady=(0, 14))
            for i, (t, label) in enumerate(THEME_NAMES.items()):
                on = S['set']['theme'] == t
                b = tk.Label(tg, text=label, anchor='sw', height=3, padx=6, pady=4, cursor='hand2',
                             bg=THEME_BG[t], fg='#2b2418' if t == 'parchment' else '#ebe7da',
                             font=T.font('sans', 11, 'bold'), highlightthickness=2,
                             highlightbackground=T['acc'] if on else T['line'])
                b.bind('<Button-1>', lambda e, t=t: (os_.set_theme(t), render()))
                b.grid(row=0, column=i, sticky='ew', padx=4)
                tg.columnconfigure(i, weight=1, uniform='t')
            sw = swatches(inner, T, ACCENTS, S['set']['accent'],
                          lambda a: (S['set'].__setitem__('accent', a), os_.touch(), os_.apply_look(), render()), 'bg1')
            sw.pack(anchor='w', pady=(0, 14))
            foot = footer()
            Btn(foot, T, '← Back', lambda: go('password'), bg='bg1').pack(side='left')
            nb = Btn(foot, T, 'Next →', lambda: go('done'), kind='pri', bg='bg1')
            nb.pack(side='right')
            c.after(30, nb.focus_set)
        else:
            h2('You are all set')
            p('A few things to know:')
            kv = tk.Frame(inner, bd=0)
            T.style(kv, bg='bg1')
            kv.pack(fill='x', pady=(0, 16))
            rows = [('Ctrl+K', 'The Inkwell: launch apps, find files, do maths'),
                    ('Left bar', 'The Spine holds your apps; right-click to pin'),
                    ('I II III IV', 'Four chapters (desktops); Alt+1 to Alt+4'),
                    ('Loom', 'Settings, your Galau account and your password')]
            for i, (k, v) in enumerate(rows):
                a = tk.Label(kv, text=k, anchor='w', font=T.font('sans', 13, 'bold'))
                b = tk.Label(kv, text=v, anchor='w', font=T.font('sans', 13))
                T.style(a, bg='bg1', fg='fg2')
                T.style(b, bg='bg1', fg='fg')
                a.grid(row=i, column=0, sticky='w', padx=(0, 12), pady=3)
                b.grid(row=i, column=1, sticky='w', pady=3)

            def finish():
                S['user']['name'] = (state['name'] or '').strip()[:30]
                if state['pw']:
                    S['user']['pin'] = hash_password(state['pw'])
                    state['pw'] = None
                S['meta']['setup'] = True
                os_.touch()
                state['done'] = True
            foot = footer()
            Btn(foot, T, '← Back', lambda: go('look'), bg='bg1').pack(side='left')
            sb = Btn(foot, T, 'Start using Quill', finish, kind='pri', bg='bg1')
            sb.pack(side='right')
            c.after(30, sb.focus_set)
        if foot is not None:
            foot.pack(fill='x')
        c.delete('card')
        c.create_window(c.winfo_width() / 2, c.winfo_height() / 2, window=card, tags='card',
                        width=min(460, max(300, c.winfo_width() - 24)))

    def center(_e=None):
        c.coords('card', c.winfo_width() / 2, c.winfo_height() / 2)
        c.itemconfigure('card', width=min(460, max(300, c.winfo_width() - 24)))
    c.bind('<Configure>', center, add='+')
    c.update_idletasks()
    render()
    os_.wait(lambda: state['done'] or os_.quitting)
    os_.account_form = None
    try:
        c.destroy()
    except tk.TclError:
        pass


def swatches(parent, T, colors, current, on_pick, surface='bg1', size=30):
    row = tk.Frame(parent, bd=0)
    T.style(row, bg=surface)
    for col in colors:
        cv = tk.Canvas(row, width=size, height=size, bd=0, highlightthickness=0, cursor='hand2')

        def paint(cv=cv, col=col):
            cv.delete('all')
            cv.configure(bg=T[surface])
            on = col.lower() == (current or '').lower()
            if on:
                cv.create_oval(1, 1, size - 1, size - 1, outline=T['fg'], width=2)
            cv.create_oval(4, 4, size - 4, size - 4, fill=col, outline=col)
        T.on(cv, paint)
        cv.bind('<Button-1>', lambda e, col=col: on_pick(col))
        cv.pack(side='left', padx=(0, 8))
    return row


class PowerOff:
    def __init__(self, os_):
        self.os = os_

    def show(self):
        """Black screen with a Power on button. Waits until it is pressed."""
        os_ = self.os
        T = os_.theme
        f = tk.Frame(os_.root, bg='#000000')
        f.place(x=0, y=0, relwidth=1, relheight=1)
        f.lift()
        inner = tk.Frame(f, bg='#000000')
        inner.place(relx=0.5, rely=0.5, anchor='center')
        tk.Label(inner, text='Quill.OS is off.', bg='#000000', fg=T['fg2'], font=T.font('sans', 13)).pack(pady=(0, 14))
        state = {'on': False}
        b = Btn(inner, T, '⏻ Power on', lambda: state.__setitem__('on', True), kind='pri', bg='#000000')
        b.pack()
        b.focus_set()
        os_.wait(lambda: state['on'] or os_.quitting)
        try:
            f.destroy()
        except tk.TclError:
            pass


__all__ = ['Menu', 'Dialogs', 'Toasts', 'Inkwell', 'Spread', 'Panels', 'Boot', 'Lock', 'PowerOff', 'setup_wizard',
           'swatches', 'avatar', 'wheel_units', 'wrap_lines', 'math']
