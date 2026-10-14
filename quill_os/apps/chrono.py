"""Chrono — clock, stopwatch, timers and alarms."""

import datetime as _dt
import math
import re
import time
import tkinter as tk

from .base import AppSpec, Inst
from ..ui.widgets import Btn, Entry, ScrollArea, Switch, Tabs
from ..util import DAYS, MONTHS, fmt_dur, fmt_time, js_weekday, now_ms, uid

ZONES = [('Local', None), ('UTC', 'UTC'), ('Los Angeles', 'America/Los_Angeles'), ('New York', 'America/New_York'),
         ('São Paulo', 'America/Sao_Paulo'), ('London', 'Europe/London'), ('Paris', 'Europe/Paris'),
         ('Dubai', 'Asia/Dubai'), ('Mumbai', 'Asia/Kolkata'), ('Tokyo', 'Asia/Tokyo'), ('Sydney', 'Australia/Sydney')]


def zone_time(tz, clock24):
    try:
        if tz is None:
            d = _dt.datetime.now()
        else:
            from zoneinfo import ZoneInfo
            d = _dt.datetime.now(ZoneInfo(tz))
    except Exception:
        return '—'
    if clock24 is False:
        h = d.hour % 12 or 12
        return '%02d:%02d %s' % (h, d.minute, 'PM' if d.hour >= 12 else 'AM')
    return '%02d:%02d' % (d.hour, d.minute)


class App(AppSpec):
    id = 'chrono'
    name = 'Chrono'
    icon = '⏱'
    bg = ('#6fd0b4', '#2a7c8c')
    w, h = 600, 560
    single = True
    kw = 'clock timer stopwatch alarm time world'
    about = 'Clock, timers and alarms'

    def build(self, ctx):
        return Chrono(ctx).inst


class Chrono:
    TABS = [('clock', 'Clock'), ('stopwatch', 'Stopwatch'), ('timer', 'Timers'), ('alarm', 'Alarms')]

    def __init__(self, ctx):
        self.ctx = ctx
        os_ = self.os = ctx.os
        T = self.T = ctx.T
        self.tab = (ctx.arg or {}).get('tab') or 'clock'
        self.sw = {'run': False, 't0': 0.0, 'acc': 0.0, 'laps': []}
        self.live = None
        self.tabs = Tabs(ctx.body, T, self.TABS, self.tab, self.set_tab)
        self.tabs.pack(fill='x')
        self.area = ScrollArea(ctx.body, T, bg='bg1')
        self.area.pack(fill='both', expand=True)
        self.view = self.area.inner
        self.draw()
        self.job = None
        self._tick()
        self.off = os_.bus.on('chrono', lambda _a: self.draw() if ctx.alive and self.tab in ('timer', 'alarm') else None)
        self.inst = Inst(on_close=self.on_close, on_arg=self.on_arg, mem=lambda: 90000)

    def set_tab(self, t):
        self.tab = t
        self.draw()

    def on_arg(self, a):
        if isinstance(a, dict) and a.get('tab'):
            self.tab = a['tab']
            self.tabs.select(self.tab)
            self.draw()

    def on_close(self):
        if self.job:
            self.os.root.after_cancel(self.job)
        self.off()

    def _tick(self):
        if not self.ctx.alive:
            return
        if self.live:
            self.os.safe(self.live)
        self.job = self.os.root.after(250 if self.tab == 'clock' else 200, self._tick)

    def clock24(self):
        return self.os.S['set'].get('clock24', True)

    def _label(self, parent, text='', font=None, fg='fg', **kw):
        lbl = tk.Label(parent, text=text, font=font or self.T.font('sans', 13), **kw)
        self.T.style(lbl, bg='bg1', fg=fg)
        return lbl

    def _frame(self, parent):
        f = tk.Frame(parent, bd=0)
        self.T.style(f, bg='bg1')
        return f

    def draw(self):
        for c in self.view.winfo_children():
            c.destroy()
        self.live = None
        self.tabs.select(self.tab)
        self.ctx.set_title('Chrono — ' + dict(self.TABS)[self.tab])
        getattr(self, 'draw_' + self.tab)()
        self.area.to_top()
        if self.live:
            self.live()

    # ---------------------------------------------------------- clock
    def draw_clock(self):
        T = self.T
        wrap = self._frame(self.view)
        wrap.pack(fill='both', expand=True, padx=18, pady=18)
        cv = tk.Canvas(wrap, width=210, height=210, bd=0, highlightthickness=0)
        T.style(cv, bg='bg1')
        cv.pack()
        big = self._label(wrap, font=T.font('serif', 56))
        big.pack(pady=(8, 0))
        date = self._label(wrap, font=T.font('serif', 17, slant='italic'), fg='fg2')
        date.pack(pady=(0, 10))
        grid = self._frame(wrap)
        grid.pack(fill='x')
        vals = []
        for i, (name, tz) in enumerate(ZONES):
            cell = tk.Frame(grid, bd=0, highlightthickness=1)
            T.on(cell, lambda c=cell: c.configure(bg=T['bg2'], highlightbackground=T['line']))
            a = tk.Label(cell, text=name, anchor='w', font=T.font('sans', 12, 'bold'))
            b = tk.Label(cell, text='', anchor='w', font=T.font('serif', 22))
            T.style(a, bg='bg2', fg='fg2')
            T.style(b, bg='bg2', fg='fg')
            a.pack(fill='x', padx=10, pady=(8, 0))
            b.pack(fill='x', padx=10, pady=(0, 8))
            vals.append((tz, b))
            cell._i = i
        cells = list(grid.winfo_children())

        def layout(_e=None):
            cols = max(1, grid.winfo_width() // 150)
            for c in range(6):
                grid.columnconfigure(c, weight=1 if c < cols else 0, uniform='z' if c < cols else '')
            for i, c in enumerate(cells):
                c.grid(row=i // cols, column=i % cols, padx=4, pady=4, sticky='ew')
        grid.bind('<Configure>', layout)
        layout()

        def face():
            cv.delete('face')
            cx = cy = 105
            cv.create_oval(cx - 96, cy - 96, cx + 96, cy + 96, fill=T['bg2'], outline=T['line'], width=2, tags='face')
            for i in range(60):
                a = i * 6 * math.pi / 180
                r1 = 84 if i % 5 == 0 else 90
                cv.create_line(cx + math.sin(a) * r1, cy - math.cos(a) * r1, cx + math.sin(a) * 94, cy - math.cos(a) * 94,
                               fill=T['fg'] if i % 5 == 0 else T['fg2'], width=2.5 if i % 5 == 0 else 1, tags='face')
        T.on(cv, face)

        def update():
            d = _dt.datetime.now()
            s = d.second + d.microsecond / 1e6
            m = d.minute + s / 60
            hr = d.hour % 12 + m / 60
            cv.delete('hand')
            cx = cy = 105

            def hand(angle_deg, length, back, width, color):
                a = math.radians(angle_deg)
                cv.create_line(cx - math.sin(a) * back, cy + math.cos(a) * back, cx + math.sin(a) * length,
                               cy - math.cos(a) * length, fill=color, width=width, capstyle='round', tags='hand')
            hand(hr * 30, 48, 0, 5, T['fg'])
            hand(m * 6, 72, 0, 3.5, T['fg'])
            hand(s * 6, 80, 14, 1.8, T['acc'])
            cv.create_oval(cx - 4.5, cy - 4.5, cx + 4.5, cy + 4.5, fill=T['acc'], outline=T['acc'], tags='hand')
            big.configure(text=fmt_time(d, True, self.clock24()))
            date.configure(text='%s, %d %s %d' % (DAYS[js_weekday(d)], d.day, MONTHS[d.month - 1], d.year))
            for tz, lbl in vals:
                lbl.configure(text=zone_time(tz, self.clock24()))
        self.live = update

    # ---------------------------------------------------------- stopwatch
    def draw_stopwatch(self):
        T = self.T
        sw = self.sw
        wrap = self._frame(self.view)
        wrap.pack(fill='both', expand=True, padx=18, pady=18)
        big = self._label(wrap, '00:00.00', T.font('serif', 56))
        big.pack(pady=(10, 14))
        row = self._frame(wrap)
        row.pack()
        b_go = Btn(row, T, '▶ Start', None, kind='pri', bg='bg1', width=10)
        b_lap = Btn(row, T, 'Lap', None, bg='bg1')
        b_reset = Btn(row, T, 'Reset', None, bg='bg1')
        for b in (b_go, b_lap, b_reset):
            b.pack(side='left', padx=4)
        laps = self._frame(wrap)
        laps.pack(fill='x', pady=(14, 0))

        def elapsed():
            return sw['acc'] + ((time.perf_counter() - sw['t0']) * 1000 if sw['run'] else 0)

        def upd():
            t = elapsed()
            big.configure(text=fmt_dur(t, True))
            b_go.set_text('⏸ Pause' if sw['run'] else '▶ Resume' if sw['acc'] else '▶ Start')
            b_lap.set_disabled(not sw['run'])
            b_reset.set_disabled(sw['run'] or not sw['acc'])

        def draw_laps():
            for c in laps.winfo_children():
                c.destroy()
            n = len(sw['laps'])
            for i, l in enumerate(reversed(sw['laps'])):
                r = tk.Frame(laps, bd=0, highlightthickness=1)
                T.on(r, lambda r=r: r.configure(bg=T['bg2'], highlightbackground=T['line']))
                a = tk.Label(r, text='Lap %d' % (n - i), font=T.font('sans', 13))
                b = tk.Label(r, text=fmt_dur(l['split'], True), font=T.font('sans', 13))
                c = tk.Label(r, text=fmt_dur(l['total'], True), font=T.font('sans', 12))
                T.style(a, bg='bg2', fg='fg2')
                T.style(b, bg='bg2', fg='fg')
                T.style(c, bg='bg2', fg='fg2')
                a.pack(side='left', padx=12, pady=6)
                c.pack(side='right', padx=12)
                b.pack(side='right')
                r.pack(fill='x', pady=2, padx=60)

        def go():
            if sw['run']:
                sw['acc'] += (time.perf_counter() - sw['t0']) * 1000
                sw['run'] = False
            else:
                sw['t0'] = time.perf_counter()
                sw['run'] = True
            upd()

        def lap():
            t = elapsed()
            prev = sw['laps'][-1]['total'] if sw['laps'] else 0
            sw['laps'].append({'total': t, 'split': t - prev})
            draw_laps()

        def reset():
            sw.update(run=False, t0=0.0, acc=0.0, laps=[])
            draw_laps()
            upd()
        b_go.command, b_lap.command, b_reset.command = go, lap, reset
        draw_laps()
        self.live = upd

    # ---------------------------------------------------------- timers
    def draw_timer(self):
        T = self.T
        os_ = self.os
        S = os_.S
        wrap = self._frame(self.view)
        wrap.pack(fill='both', expand=True, padx=18, pady=18)
        row = self._frame(wrap)
        row.pack()
        hh = Entry(row, T, '0', width=4, justify='center')
        mm = Entry(row, T, '5', width=4, justify='center')
        ss = Entry(row, T, '0', width=4, justify='center')
        for i, e in enumerate((hh, mm, ss)):
            if i:
                self._label(row, ':').pack(side='left', padx=4)
            e.pack(side='left', ipady=5)
        quick = self._frame(wrap)
        quick.pack(pady=10)

        def preset(m):
            hh.set(str(m // 60))
            mm.set(str(m % 60))
            ss.set('0')
        for label, m in (('1 min', 1), ('5 min', 5), ('10 min', 10), ('25 min', 25), ('1 hour', 60)):
            Btn(quick, T, label, lambda m=m: preset(m), size='sm', bg='bg1').pack(side='left', padx=3)
        row2 = self._frame(wrap)
        row2.pack()
        lb = Entry(row2, T, placeholder='Label (optional)', width=18)
        lb.pack(side='left', ipady=5, padx=(0, 8))

        def num(e):
            try:
                return max(0, float(e.get() or 0))
            except ValueError:
                return 0

        def add():
            ms = (num(hh) * 3600 + num(mm) * 60 + num(ss)) * 1000
            if ms <= 0:
                os_.toast('Set a time first', '⏱')
                return
            S['timers'].append({'id': uid(), 'label': lb.get().strip()[:40], 'dur': ms, 'end': now_ms() + ms, 'state': 'run'})
            os_.touch()
            self.draw()
        Btn(row2, T, '＋ Start timer', add, kind='pri', bg='bg1').pack(side='left')
        lst = self._frame(wrap)
        lst.pack(fill='x', pady=(16, 0))
        rows = []
        if not S['timers']:
            self._label(lst, 'No timers running.', fg='fg2').pack(pady=14)
        for t in S['timers']:
            r = tk.Frame(lst, bd=0, highlightthickness=1)
            T.on(r, lambda r=r: r.configure(bg=T['bg2'], highlightbackground=T['line']))
            col = tk.Frame(r, bd=0)
            T.style(col, bg='bg2')
            col.pack(side='left', fill='x', expand=True, padx=14, pady=8)
            a = tk.Label(col, text=t.get('label') or 'Timer', anchor='w', font=T.font('sans', 12))
            tm = tk.Label(col, text='', anchor='w', font=T.font('serif', 26))
            T.style(a, bg='bg2', fg='fg2')
            T.style(tm, bg='bg2', fg='fg')
            a.pack(fill='x')
            tm.pack(fill='x')

            def toggle(t=t):
                if t['state'] == 'run':
                    t['left'] = max(0, t['end'] - now_ms())
                    t['state'] = 'paused'
                elif t['state'] == 'paused':
                    t['end'] = now_ms() + t.get('left', 0)
                    t['state'] = 'run'
                else:
                    t['end'] = now_ms() + t['dur']
                    t['state'] = 'run'
                os_.touch()
                self.draw()

            def delete(t=t):
                S['timers'] = [x for x in S['timers'] if x is not t]
                os_.touch()
                self.draw()
            Btn(r, T, '✕', delete, kind='ibtn', bg='bg2', tip='Delete').pack(side='right', padx=(0, 8))
            pb = Btn(r, T, '⏸', toggle, size='sm', bg='bg2')
            pb.pack(side='right', padx=6)
            r.pack(fill='x', pady=4)
            rows.append((t, tm, pb))

        def upd():
            for t, tm, pb in rows:
                st = t.get('state')
                left = t['end'] - now_ms() if st == 'run' else t.get('left', 0) if st == 'paused' else 0
                tm.configure(text='Done' if st == 'done' else fmt_dur(math.ceil(left / 1000) * 1000))
                pb.set_text('⏸' if st == 'run' else '▶' if st == 'paused' else '↻')
        self.live = upd

    # ---------------------------------------------------------- alarms
    def draw_alarm(self):
        T = self.T
        os_ = self.os
        S = os_.S
        wrap = self._frame(self.view)
        wrap.pack(fill='both', expand=True, padx=18, pady=18)
        row = self._frame(wrap)
        row.pack()
        tm = Entry(row, T, '07:00', width=6, justify='center', font=T.font('sans', 18))
        tm.pack(side='left', ipady=4, padx=(0, 8))
        lb = Entry(row, T, placeholder='Label', width=16)
        lb.pack(side='left', ipady=5, padx=(0, 8))
        days = set()
        day_row = self._frame(wrap)
        day_row.pack(pady=10)
        btns = []
        for i, d in enumerate(DAYS):
            def flip(i=i):
                if i in days:
                    days.discard(i)
                else:
                    days.add(i)
                btns[i].set_kind('pri' if i in days else 'btn')
            b = Btn(day_row, T, d[:2], flip, size='sm', bg='bg1', tip=d)
            b.pack(side='left', padx=2)
            btns.append(b)

        def add():
            v = tm.get().strip()
            m = re.fullmatch(r'(\d{1,2}):(\d{2})', v)
            if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
                os_.toast('Pick a time', '⏰')
                return
            t = '%02d:%s' % (int(m.group(1)), m.group(2))
            S['alarms'].append({'id': uid(), 'time': t, 'label': lb.get().strip()[:40], 'on': True, 'days': sorted(days)})
            os_.touch()
            self.draw()
            os_.toast('Alarm set for ' + t, '⏰')
        Btn(row, T, '＋ Add alarm', add, kind='pri', bg='bg1').pack(side='left')
        self._label(wrap, 'Leave the days empty for a one-time alarm. Alarms ring while Quill is open, even if this window '
                          'is closed.', T.font('sans', 12), fg='fg2', wraplength=440, justify='center').pack(pady=(0, 10))
        lst = self._frame(wrap)
        lst.pack(fill='x')
        alarms = sorted(S['alarms'], key=lambda a: a.get('time', ''))
        if not alarms:
            self._label(lst, 'No alarms yet.', fg='fg2').pack(pady=14)
        for a in alarms:
            r = tk.Frame(lst, bd=0, highlightthickness=1)
            on = bool(a.get('on'))
            T.on(r, lambda r=r: r.configure(bg=T['bg2'], highlightbackground=T['line']))
            fg = 'fg' if on else 'fg2'
            hh, mm_ = int(a['time'][:2]), int(a['time'][3:5])
            t1 = tk.Label(r, text=fmt_time(_dt.datetime(2000, 1, 1, hh, mm_), clock24=self.clock24()),
                          font=T.font('serif', 26))
            T.style(t1, bg='bg2', fg=fg)
            t1.pack(side='left', padx=14, pady=6)
            ds = a.get('days') or []
            sub = (a.get('label') or 'Alarm') + ' · ' + (('Every day' if len(ds) == 7 else ' '.join(DAYS[d] for d in ds))
                                                       if ds else 'Once')
            t2 = tk.Label(r, text=sub, anchor='w', font=T.font('sans', 12))
            T.style(t2, bg='bg2', fg='fg2')
            t2.pack(side='left', fill='x', expand=True)

            def delete(a=a):
                S['alarms'] = [x for x in S['alarms'] if x is not a]
                os_.touch()
                self.draw()

            def switch(v, a=a):
                a['on'] = v
                if v:
                    a['last'] = None
                os_.touch()
                self.draw()
            Btn(r, T, '✕', delete, kind='ibtn', bg='bg2', tip='Delete').pack(side='right', padx=(0, 8))
            Switch(r, T, on, switch, bg='bg2').pack(side='right', padx=8)
            r.pack(fill='x', pady=4)
