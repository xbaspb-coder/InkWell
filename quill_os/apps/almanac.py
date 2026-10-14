"""Almanac — calendar."""

import datetime as _dt
import re
import tkinter as tk

from .base import AppSpec, Inst
from ..ui.widgets import Btn, Entry, ScrollArea
from ..util import DAYS, MONTHS, day_key, js_weekday, uid

COLS = ['#e8b04a', '#ff7a59', '#e0577e', '#a78bfa', '#5aa7ff', '#35c9b0', '#7ac74f']


class App(AppSpec):
    id = 'almanac'
    name = 'Almanac'
    icon = '31'
    bg = ('#ff8a7a', '#c0392b')
    w, h = 780, 540
    single = True
    kw = 'calendar events schedule date agenda planner'
    about = 'Calendar'

    def build(self, ctx):
        return Almanac(ctx).inst


class Almanac:
    def __init__(self, ctx):
        self.ctx = ctx
        os_ = self.os = ctx.os
        T = self.T = ctx.T
        now = _dt.date.today()
        self.y, self.m = now.year, now.month - 1
        self.sel = day_key(_dt.datetime.now())
        self.color = COLS[0]
        self.head = tk.Frame(ctx.body, bd=0)
        T.style(self.head, bg='bg2')
        self.head.pack(fill='x')
        line = tk.Frame(ctx.body, height=1, bd=0)
        T.style(line, bg='line')
        line.pack(fill='x')
        cal = tk.Frame(ctx.body, bd=0)
        T.style(cal, bg='bg1')
        cal.pack(fill='both', expand=True)
        self.side = ScrollArea(cal, T, bg='bg2')
        self.side.configure(width=230)
        self.side.pack(side='right', fill='y')
        self.side.canvas.configure(width=230)
        edge = tk.Frame(cal, width=1, bd=0)
        T.style(edge, bg='line')
        edge.pack(side='right', fill='y')
        self.grid = tk.Frame(cal, bd=0)
        T.style(self.grid, bg='bg1')
        self.grid.pack(side='left', fill='both', expand=True, padx=12, pady=12)
        self.draw()
        self.off = os_.bus.on('chrono', lambda _a: self.draw() if ctx.alive else None)
        self.inst = Inst(on_close=self.off, mem=lambda: 90000)

    def evs(self, k):
        return self.os.S['events'].get(k) or []

    def shift(self, d):
        self.m += d
        if self.m < 0:
            self.m, self.y = 11, self.y - 1
        elif self.m > 11:
            self.m, self.y = 0, self.y + 1
        self.draw()

    def today(self):
        d = _dt.date.today()
        self.y, self.m = d.year, d.month - 1
        self.sel = day_key(_dt.datetime.now())
        self.draw()

    def draw(self):
        T = self.T
        for c in self.head.winfo_children():
            c.destroy()
        Btn(self.head, T, '◀', lambda: self.shift(-1), kind='ibtn').pack(side='left', padx=(8, 0), pady=6)
        lbl = tk.Label(self.head, text=MONTHS[self.m] + ' %d' % self.y, width=16, font=T.font('serif', 18, 'bold', 'italic'))
        T.style(lbl, bg='bg2', fg='fg')
        lbl.pack(side='left')
        Btn(self.head, T, '▶', lambda: self.shift(1), kind='ibtn').pack(side='left')
        Btn(self.head, T, 'Today', self.today, size='sm').pack(side='left', padx=8)
        for c in self.grid.winfo_children():
            c.destroy()
        for i, d in enumerate(DAYS):
            h = tk.Label(self.grid, text=d.upper(), font=T.font('sans', 11))
            T.style(h, bg='bg1', fg='fg2')
            h.grid(row=0, column=i, sticky='ew', pady=(0, 4))
            self.grid.columnconfigure(i, weight=1, uniform='d')
        first = _dt.date(self.y, self.m + 1, 1)
        start = first - _dt.timedelta(days=js_weekday(first))
        today = day_key(_dt.datetime.now())
        for i in range(42):
            d = start + _dt.timedelta(days=i)
            k = '%d-%02d-%02d' % (d.year, d.month, d.day)
            lst = self.evs(k)
            other = d.month != self.m + 1
            on = k == self.sel
            is_today = k == today
            cell = tk.Frame(self.grid, bd=0, highlightthickness=2 if on else 1, cursor='hand2')
            bg = T['bg2']
            fg = T['fg'] if not other else T['fg2']
            cell.configure(bg=bg, highlightbackground=T['acc'] if (on or is_today) else T['line'])
            num = tk.Label(cell, text=str(d.day), font=T.font('sans', 11, 'bold'), bg=T['acc'] if is_today else bg,
                           fg=T['acc_fg'] if is_today else fg, width=2)
            num.pack(anchor='nw', padx=4, pady=3)
            for e in lst[:3]:
                bar = tk.Frame(cell, height=5, bg=e.get('color') or T['acc'])
                bar.pack(fill='x', padx=4, pady=1)
            parts = [cell, num] + list(cell.winfo_children())

            def pick(_e=None, k=k, d=d):
                self.sel = k
                if d.month != self.m + 1:
                    self.y, self.m = d.year, d.month - 1
                self.draw()
            for w in parts:
                w.bind('<Button-1>', pick)
            cell.grid(row=1 + i // 7, column=i % 7, sticky='nsew', padx=2, pady=2)
        for r in range(1, 7):
            self.grid.rowconfigure(r, weight=1, uniform='w')
        self.draw_side()
        self.ctx.set_title('Almanac — ' + MONTHS[self.m] + ' %d' % self.y)

    def draw_side(self):
        T = self.T
        os_ = self.os
        S = os_.S
        side = self.side.inner
        for c in side.winfo_children():
            c.destroy()
        box = tk.Frame(side, bd=0)
        T.style(box, bg='bg2')
        box.pack(fill='both', expand=True, padx=12, pady=12)
        y, mo, da = map(int, self.sel.split('-'))
        d = _dt.date(y, mo, da)
        t = tk.Label(box, text='%s, %d %s' % (DAYS[js_weekday(d)], d.day, MONTHS[d.month - 1]), anchor='w',
                     font=T.font('serif', 17, slant='italic'))
        T.style(t, bg='bg2', fg='fg')
        t.pack(fill='x', pady=(0, 10))
        lst = sorted(self.evs(self.sel), key=lambda e: e.get('time') or '99')
        if not lst:
            e = tk.Label(box, text='Nothing planned.', anchor='w', font=T.font('sans', 12))
            T.style(e, bg='bg2', fg='fg2')
            e.pack(fill='x', pady=(0, 12))
        for ev in lst:
            r = tk.Frame(box, bd=0, highlightthickness=1)
            T.on(r, lambda r=r: r.configure(bg=T['bg1'], highlightbackground=T['line']))
            bar = tk.Frame(r, width=4, bg=ev.get('color') or T['acc'])
            bar.pack(side='left', fill='y', padx=(6, 8), pady=6)
            col = tk.Frame(r, bd=0)
            T.style(col, bg='bg1')
            col.pack(side='left', fill='x', expand=True, pady=6)
            a = tk.Label(col, text=ev.get('title', ''), anchor='w', justify='left', wraplength=130, font=T.font('sans', 13))
            T.style(a, bg='bg1', fg='fg')
            a.pack(fill='x')
            if ev.get('time'):
                b = tk.Label(col, text=ev['time'], anchor='w', font=T.font('sans', 11))
                T.style(b, bg='bg1', fg='fg2')
                b.pack(fill='x')

            def delete(ev=ev):
                S['events'][self.sel] = [x for x in self.evs(self.sel) if x is not ev]
                if not S['events'][self.sel]:
                    del S['events'][self.sel]
                os_.touch()
                self.draw()
            Btn(r, T, '✕', delete, kind='ibtn', bg='bg1', tip='Delete').pack(side='right', padx=4)
            r.pack(fill='x', pady=(0, 6))
        h = tk.Label(box, text='ADD AN EVENT', anchor='w', font=T.font('sans', 11))
        T.style(h, bg='bg2', fg='fg2')
        h.pack(fill='x', pady=(14, 8))
        ti = Entry(box, T, placeholder='New event', width=18)
        ti.pack(fill='x', ipady=4, pady=(0, 6))
        tm = Entry(box, T, placeholder='Time (HH:MM)', width=18)
        tm.pack(fill='x', ipady=4, pady=(0, 6))
        sw = tk.Frame(box, bd=0)
        T.style(sw, bg='bg2')
        sw.pack(fill='x', pady=(0, 8))
        dots = []
        for c in COLS:
            cv = tk.Canvas(sw, width=22, height=22, bd=0, highlightthickness=0, cursor='hand2')
            T.style(cv, bg='bg2')
            cv.pack(side='left', padx=(0, 4))
            dots.append((c, cv))

        def paint_dots():
            for c, cv in dots:
                cv.delete('all')
                if c == self.color:
                    cv.create_oval(1, 1, 21, 21, outline=T['fg'], width=2)
                cv.create_oval(4, 4, 18, 18, fill=c, outline=c)
        for c, cv in dots:
            cv.bind('<Button-1>', lambda e, c=c: (setattr(self, 'color', c), paint_dots()))
        paint_dots()

        def add(_e=None):
            title = ti.get().strip()[:80]
            if not title:
                ti.focus_set()
                return
            time_ = tm.get().strip()
            m = re.fullmatch(r'(\d{1,2}):(\d{2})', time_)
            if time_ and (not m or int(m.group(1)) > 23 or int(m.group(2)) > 59):
                os_.toast('Use a time like 14:30, or leave it empty', '📅')
                return
            time_ = '%02d:%s' % (int(m.group(1)), m.group(2)) if m else ''
            S['events'].setdefault(self.sel, []).append({'id': uid(), 'title': title, 'time': time_, 'color': self.color})
            os_.touch()
            self.draw()
            os_.toast('Event added', '📅')
        ti.bind('<Return>', add)
        tm.bind('<Return>', add)
        Btn(box, T, '＋ Add', add, kind='pri', bg='bg2').pack(fill='x')
        n = tk.Label(box, text='Events with a time send a notification when it arrives.', anchor='w', justify='left',
                     wraplength=190, font=T.font('sans', 12))
        T.style(n, bg='bg2', fg='fg2')
        n.pack(fill='x', pady=(8, 0))
