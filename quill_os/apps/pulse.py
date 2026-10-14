"""Pulse — task manager, performance and services."""

import os
import sys
import time
import tkinter as tk

from .base import AppSpec, Inst
from ..state import STORE_LIMIT
from ..ui.widgets import Btn, ScrollArea, Tabs
from ..ui.wm import ROM
from ..util import clamp, fmt_bytes, fmt_dur, now_ms


def process_memory():
    """The memory this program uses, in bytes, or None if the system will not say."""
    try:
        if sys.platform.startswith('linux'):
            with open('/proc/self/statm') as f:
                return int(f.read().split()[1]) * os.sysconf('SC_PAGE_SIZE')
        if sys.platform.startswith('win'):
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD), ('PeakWorkingSetSize', ctypes.c_size_t),
                            ('WorkingSetSize', ctypes.c_size_t), ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                            ('QuotaPagedPoolUsage', ctypes.c_size_t), ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                            ('QuotaNonPagedPoolUsage', ctypes.c_size_t), ('PagefileUsage', ctypes.c_size_t),
                            ('PeakPagefileUsage', ctypes.c_size_t)]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            k32 = ctypes.WinDLL('kernel32')
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL('psapi')
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
                return pmc.WorkingSetSize
            return None
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return r if sys.platform == 'darwin' else r * 1024
    except Exception:
        return None


class App(AppSpec):
    id = 'pulse'
    name = 'Pulse'
    icon = '♥'
    bg = ('#ff6b81', '#b3243c')
    w, h = 720, 520
    single = True
    kw = 'task manager processes performance memory cpu fps monitor activity kill'
    about = 'Task manager'

    def build(self, ctx):
        return Pulse(ctx).inst


class Pulse:
    TABS = [('proc', 'Processes'), ('perf', 'Performance'), ('svc', 'Services')]

    def __init__(self, ctx):
        self.ctx = ctx
        os_ = self.os = ctx.os
        T = self.T = ctx.T
        self.tab = 'proc'
        self.sel_id = None
        self.fps_h, self.mem_h, self.sto_h = [], [], []
        self.frames = 0
        self.last_t = time.perf_counter()
        self.fps = 0
        self.tick = None
        self.tabs = Tabs(ctx.body, T, self.TABS, self.tab, self.set_tab)
        self.tabs.pack(fill='x')
        self.area = ScrollArea(ctx.body, T, bg='bg1')
        self.area.pack(fill='both', expand=True)
        self._frame_loop()
        self.sample()
        self.draw()
        self._second()
        self.off = os_.bus.on('wm', lambda _a: self.tick() if self.tab == 'proc' and self.tick and ctx.alive else None)
        self.inst = Inst(on_close=self.on_close, mem=lambda: 80000)

    def _frame_loop(self):
        if not self.ctx.alive:
            return
        self.frames += 1
        self._fl = self.os.root.after(16, self._frame_loop)

    def _second(self):
        if not self.ctx.alive:
            return
        self.sample()
        if self.tick:
            self.os.safe(self.tick)
        self._sj = self.os.root.after(1000, self._second)

    def on_close(self):
        for j in ('_fl', '_sj'):
            try:
                self.os.root.after_cancel(getattr(self, j))
            except (AttributeError, tk.TclError, ValueError):
                pass
        self.off()

    def mem_now(self):
        m = process_memory()
        if m is not None:
            return m
        return sum((w.inst.mem() if hasattr(w.inst, 'mem') else 120000) for w in self.os.wm.list) + 4e6 + self.os.fs.usage() * 2

    def sample(self):
        n = time.perf_counter()
        self.fps = round(self.frames / max(1e-3, n - self.last_t))
        self.frames = 0
        self.last_t = n
        self.fps_h.append(self.fps)
        self.mem_h.append(self.mem_now() / 1048576)
        self.sto_h.append(self.os.fs.usage() / STORE_LIMIT * 100)
        for a in (self.fps_h, self.mem_h, self.sto_h):
            del a[:-60]

    def set_tab(self, t):
        self.tab = t
        self.draw()

    def draw(self):
        T = self.T
        self.tabs.select(self.tab)
        for c in self.area.inner.winfo_children():
            c.destroy()
        self.tick = None
        self.ctx.set_title('Pulse — ' + dict(self.TABS)[self.tab])
        body = tk.Frame(self.area.inner, bd=0)
        T.style(body, bg='bg1')
        body.pack(fill='both', expand=True, padx=14, pady=10)
        getattr(self, 'draw_' + self.tab)(body)
        if self.tick:
            self.tick()

    def _table(self, parent, heads, widths):
        T = self.T
        t = tk.Frame(parent, bd=0)
        T.style(t, bg='bg1')
        t.pack(fill='x')
        for i, (h, w) in enumerate(zip(heads, widths)):
            lbl = tk.Label(t, text=h.upper(), anchor='w', font=T.font('sans', 11))
            T.style(lbl, bg='bg1', fg='fg2')
            lbl.grid(row=0, column=i, sticky='ew', padx=10, pady=6)
            t.columnconfigure(i, weight=w)
        line = tk.Frame(t, height=1, bd=0)
        T.style(line, bg='line')
        line.grid(row=1, column=0, columnspan=len(heads), sticky='ew')
        return t

    def draw_proc(self, body):
        T, os_ = self.T, self.os
        top = tk.Frame(body, bd=0)
        T.style(top, bg='bg1')
        top.pack(fill='x', pady=(0, 8))
        tot = tk.Label(top, anchor='w', font=T.font('sans', 12))
        T.style(tot, bg='bg1', fg='fg2')
        tot.pack(side='left')
        end = Btn(top, T, 'End task', lambda: self._end(), kind='dng', size='sm', bg='bg1')
        end.pack(side='right')
        end.set_disabled(True)
        holder = tk.Frame(body, bd=0)
        T.style(holder, bg='bg1')
        holder.pack(fill='x')
        state = {'sig': None}

        def tick():
            wins = sorted(os_.wm.list, key=lambda w: w.id)
            rows = []
            total = 0
            for w in wins:
                m = w.inst.mem() if hasattr(w.inst, 'mem') else 120000
                total += m
                rows.append((w.id, w.spec.icon + '  ' + w.spec.name, w.title, ROM[w.ch], fmt_bytes(m), fmt_dur(now_ms() - w.born)))
            if not any(w.id == self.sel_id for w in wins):
                self.sel_id = None
            end.set_disabled(self.sel_id is None)
            tot.configure(text='%d windows · about %s used by apps' % (len(wins), fmt_bytes(total)))
            sig = tuple(r[:4] for r in rows) + (self.sel_id,)
            if sig == state['sig'] and holder.winfo_children():
                # only the changing columns need updating
                for r, cells in zip(rows, holder._rows):
                    cells[4].configure(text=r[4])
                    cells[5].configure(text=r[5])
                return
            state['sig'] = sig
            for c in holder.winfo_children():
                c.destroy()
            t = self._table(holder, ['App', 'Window', 'Ch.', 'Memory', 'Open for'], [2, 3, 1, 1, 1])
            holder._rows = []
            if not rows:
                lbl = tk.Label(t, text='No apps are running.', anchor='w', font=T.font('sans', 13))
                T.style(lbl, bg='bg1', fg='fg2')
                lbl.grid(row=2, column=0, columnspan=5, sticky='w', padx=10, pady=8)
            for i, r in enumerate(rows):
                sel = r[0] == self.sel_id
                bg = 'acc_soft' if sel else 'bg1'
                cells = []
                for j, v in enumerate(r[1:]):
                    lbl = tk.Label(t, text=v, anchor='w', font=T.font('sans', 13), cursor='hand2')
                    T.style(lbl, bg=bg, fg='fg')
                    lbl.grid(row=2 + i * 2, column=j, sticky='ew', ipadx=10, ipady=5)
                    lbl.bind('<Button-1>', lambda e, wid=r[0]: self._select(wid))
                    cells.append(lbl)
                cells.insert(0, None)
                line = tk.Frame(t, height=1, bd=0)
                T.style(line, bg='line')
                line.grid(row=3 + i * 2, column=0, columnspan=5, sticky='ew')
                holder._rows.append(cells)
        holder._rows = []
        self.tick = tick

    def _select(self, wid):
        self.sel_id = wid
        if self.tick:
            self.tick()

    def _end(self):
        w = next((x for x in self.os.wm.list if x.id == self.sel_id), None)
        if w is not None:
            self.os.wm.close(w)

    def draw_perf(self, body):
        T = self.T

        def graph(label, color):
            head = tk.Frame(body, bd=0)
            T.style(head, bg='bg1')
            head.pack(fill='x', pady=(8, 4))
            a = tk.Label(head, text=label, font=T.font('sans', 13))
            b = tk.Label(head, text='–', font=T.font('sans', 13, 'bold'))
            T.style(a, bg='bg1', fg='fg2')
            T.style(b, bg='bg1', fg='fg')
            a.pack(side='left')
            b.pack(side='right')
            cv = tk.Canvas(body, height=90, bd=0, highlightthickness=1)
            T.on(cv, lambda: cv.configure(bg=T['bg0'], highlightbackground=T['line']))
            cv.pack(fill='x')
            return cv, b, color

        g1 = graph('Frames per second (how smoothly Quill is running)', '#7ac74f')
        g2 = graph('Memory (Quill process)', '#5aa7ff')
        g3 = graph('Quill storage', '#e8b04a')
        note = tk.Label(body, text='Memory comes from your operating system.' if process_memory() is not None else
                        'Your system hides real memory use, so memory is estimated from open apps and files.',
                        anchor='w', font=T.font('sans', 12))
        T.style(note, bg='bg1', fg='fg2')
        note.pack(fill='x', pady=(10, 0))

        def draw(cv, data, mx, color):
            cv.delete('all')
            W, H = max(10, cv.winfo_width()), 90
            for i in range(1, 4):
                cv.create_line(0, H * i / 4, W, H * i / 4, fill=T['line'])
            if len(data) < 2:
                return
            pts = []
            for i, v in enumerate(data):
                pts += [i / 59 * W, H - clamp(v / mx, 0, 1) * (H - 6) - 3]
            from ..util import mix
            poly = pts + [(len(data) - 1) / 59 * W, H, 0, H]
            cv.create_polygon(*poly, fill=mix(T['bg0'], color, .15), outline='')
            cv.create_line(*pts, fill=color, width=2)

        def tick():
            draw(g1[0], self.fps_h, 70, g1[2])
            g1[1].configure(text='%d fps' % self.fps)
            draw(g2[0], self.mem_h, max([100] + self.mem_h) * 1.2, g2[2])
            g2[1].configure(text='%.1f MB' % (self.mem_h[-1] if self.mem_h else 0))
            draw(g3[0], self.sto_h, 100, g3[2])
            g3[1].configure(text='%s (%.1f%%)' % (fmt_bytes(self.os.fs.usage()), self.sto_h[-1] if self.sto_h else 0))
        self.tick = tick

    def draw_svc(self, body):
        T, os_ = self.T, self.os
        S = os_.S
        holder = tk.Frame(body, bd=0)
        T.style(holder, bg='bg1')
        holder.pack(fill='x')

        def services():
            snd = os_.sound.state
            return [('Window manager', 'running', '%d windows' % len(os_.wm.list)),
                    ('Scheduler', 'running', '%d alarms · %d timers' % (sum(1 for a in S['alarms'] if a.get('on')),
                                                                      sum(1 for t in S['timers'] if t.get('state') == 'run'))),
                    ('Notifier', 'quiet' if S['set'].get('dnd') else 'running', '%d stored' % len(S['notifs'])),
                    ('Storage writer', 'running' if os_.core.save_status == 'saved' else os_.core.save_status,
                     fmt_bytes(os_.fs.usage())),
                    ('Cloud sync', 'off', 'guest'),
                    ('Audio engine', snd, '%d%% volume' % round(S['set'].get('volume', 70))),
                    ('OG Browser bridge', 'standalone', 'Python version')]

        def tick():
            for c in holder.winfo_children():
                c.destroy()
            t = self._table(holder, ['Service', 'State', 'Details'], [2, 1, 2])
            for i, (n, st, d) in enumerate(services()):
                color = T['ok'] if st in ('running', 'connected', 'idle', 'clips') else T['red'] if st in ('error', 'full', 'unavailable') else T['fg2']
                a = tk.Label(t, text=n, anchor='w', font=T.font('sans', 13))
                b = tk.Label(t, text='● ' + st, anchor='w', font=T.font('sans', 13), fg=color)
                c = tk.Label(t, text=d, anchor='w', font=T.font('sans', 13))
                T.style(a, bg='bg1', fg='fg')
                T.style(c, bg='bg1', fg='fg2')
                b.configure(bg=T['bg1'])
                for j, w in enumerate((a, b, c)):
                    w.grid(row=2 + i * 2, column=j, sticky='ew', padx=10, pady=5)
                line = tk.Frame(t, height=1, bd=0)
                T.style(line, bg='line')
                line.grid(row=3 + i * 2, column=0, columnspan=3, sticky='ew')
        self.tick = tick
