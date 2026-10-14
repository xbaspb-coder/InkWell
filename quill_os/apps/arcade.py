"""Arcade — Snake, 2048 and Minesweeper."""

import random
import time
import tkinter as tk

from .base import AppSpec, Inst
from ..ui.widgets import Btn, Select


def bump_score(os_, key, v, lower_better=False):
    old = os_.S['scores'].get(key)
    if old is None or (v < old if lower_better else v > old):
        os_.S['scores'][key] = v
        os_.touch()
        return True
    return False


class App(AppSpec):
    id = 'arcade'
    name = 'Arcade'
    icon = '🕹'
    bg = ('#ff9f5a', '#d9455f')
    w, h = 560, 620
    kw = 'games snake 2048 minesweeper play fun'
    about = 'Snake, 2048 and Minesweeper'

    def build(self, ctx):
        return Arcade(ctx).inst


class Arcade:
    def __init__(self, ctx):
        self.ctx = ctx
        self.os = ctx.os
        self.T = ctx.T
        self.root = tk.Frame(ctx.body, bd=0)
        self.T.style(self.root, bg='bg1')
        self.root.pack(fill='both', expand=True)
        self.stop = None
        self.box = None
        self.menu()
        self.inst = Inst(on_close=lambda: self.stop and self.stop(), on_focus=self._focus, mem=lambda: 120000)

    def _focus(self):
        if self.box is not None:
            try:
                self.box.focus_set()
            except tk.TclError:
                pass

    def clear(self):
        if self.stop:
            self.stop()
            self.stop = None
        for c in self.root.winfo_children():
            c.destroy()
        self.box = None

    def menu(self):
        T, S = self.T, self.os.S
        self.clear()
        self.ctx.set_title('Arcade')
        h = tk.Label(self.root, text='Pick a game', font=T.font('serif', 22, 'bold', 'italic'))
        T.style(h, bg='bg1', fg='fg')
        h.pack(pady=(18, 8))
        grid = tk.Frame(self.root, bd=0)
        T.style(grid, bg='bg1')
        grid.pack(fill='x', padx=14)

        def mines_sub():
            b = S['scores'].get('mines_' + (S['scores'].get('minesCfg') or 'easy'))
            return 'Best %d s' % b if b else 'No time yet'
        games = [('snake', '🐍', 'Snake', lambda: 'Best %d' % (S['scores'].get('snake') or 0)),
                 ('g2048', '🔢', '2048', lambda: 'Best %d' % (S['scores'].get('g2048') or 0)),
                 ('mines', '💣', 'Minesweeper', mines_sub)]
        for i, (gid, ico, name, sub) in enumerate(games):
            card = tk.Frame(grid, bd=0, highlightthickness=1, cursor='hand2')
            a = tk.Label(card, text=ico, font=T.font('sans', 38))
            b = tk.Label(card, text=name, font=T.font('sans', 14, 'bold'))
            c = tk.Label(card, text=sub(), font=T.font('sans', 12))
            a.pack(pady=(18, 6))
            b.pack()
            c.pack(pady=(2, 18))
            hover = {'on': False}

            def paint(card=card, a=a, b=b, c=c, hover=hover):
                card.configure(bg=T['bg2'], highlightbackground=T['acc'] if hover['on'] else T['line'])
                a.configure(bg=T['bg2'], fg=T['fg'])
                b.configure(bg=T['bg2'], fg=T['fg'])
                c.configure(bg=T['bg2'], fg=T['fg2'])
            T.on(card, paint)
            for w in (card, a, b, c):
                w.bind('<Button-1>', lambda e, gid=gid, name=name: self.play(gid, name))
                w.bind('<Enter>', lambda e, p=paint, hv=hover: (hv.__setitem__('on', True), p()))
                w.bind('<Leave>', lambda e, p=paint, hv=hover: (hv.__setitem__('on', False), p()))
            card.grid(row=0, column=i, sticky='nsew', padx=6, pady=6)
            grid.columnconfigure(i, weight=1, uniform='g')

    def play(self, gid, name):
        T = self.T
        self.clear()
        self.ctx.set_title('Arcade — ' + name)
        top = tk.Frame(self.root, bd=0)
        T.style(top, bg='bg1')
        top.pack(fill='x', padx=12, pady=(12, 0))
        Btn(top, T, '← Games', self.menu, size='sm', bg='bg1').pack(side='left')
        box = tk.Frame(self.root, bd=0, takefocus=1, highlightthickness=0)
        T.style(box, bg='bg1')
        box.pack(fill='both', expand=True, padx=12, pady=10)
        self.box = box
        self.stop = getattr(self, 'game_' + gid)(box)
        box.focus_set()

    def _info(self, box):
        info = tk.Frame(box, bd=0)
        self.T.style(info, bg='bg1')
        info.pack(pady=(0, 8))
        return info

    def _set_info(self, info, parts):
        T = self.T
        for c in info.winfo_children():
            c.destroy()
        for text, fg, bold in parts:
            if not text:
                continue
            lbl = tk.Label(info, text=text, font=T.font('sans', 14, 'bold' if bold else 'normal'))
            T.style(lbl, bg='bg1', fg=fg)
            lbl.pack(side='left', padx=7)

    def _hint(self, box, text):
        lbl = tk.Label(box, text=text, font=self.T.font('sans', 12))
        self.T.style(lbl, bg='bg1', fg='fg2')
        lbl.pack(pady=(8, 0))

    # ---------------------------------------------------------- Snake
    def game_snake(self, box):
        T, os_ = self.T, self.os
        N, C = 20, 18
        info = self._info(box)
        cv = tk.Canvas(box, width=N * C, height=N * C, bd=0, highlightthickness=1)
        T.on(cv, lambda: cv.configure(bg=T['bg0'], highlightbackground=T['line']))
        cv.pack()
        st = {}
        job = {'id': None}

        def reset():
            st.update(sn=[(10, 10), (9, 10), (8, 10)], dir=(1, 0), nd=(1, 0), score=0, alive=True, paused=False,
                      started=False)
            place_food()
            draw()
            status()
            if job['id']:
                os_.root.after_cancel(job['id'])
            job['id'] = os_.root.after(150, tick)

        def place_food():
            while True:
                f = (random.randrange(N), random.randrange(N))
                if f not in st['sn']:
                    st['food'] = f
                    return

        def status():
            self._set_info(info, [('Score %d' % st['score'], 'fg', True), ('Best %d' % (os_.S['scores'].get('snake') or 0), 'fg2', True),
                                  ('Game over — press Space' if not st['alive'] else 'Press an arrow key to start'
                                   if not st['started'] else 'Paused' if st['paused'] else '', 'fg2', True)])

        def tick():
            job['id'] = None
            if not st['alive'] or not self.ctx.alive:
                return
            if st['paused'] or not st['started']:
                job['id'] = os_.root.after(80, tick)
                return
            st['dir'] = st['nd']
            hx, hy = st['sn'][0][0] + st['dir'][0], st['sn'][0][1] + st['dir'][1]
            if hx < 0 or hy < 0 or hx >= N or hy >= N or (hx, hy) in st['sn']:
                st['alive'] = False
                if bump_score(os_, 'snake', st['score']):
                    os_.toast('New best: %d' % st['score'], '🐍')
                os_.ui_sound('error')
                draw()
                status()
                return
            st['sn'].insert(0, (hx, hy))
            if (hx, hy) == st['food']:
                st['score'] += 1
                place_food()
                os_.sound.tone(660 + st['score'] * 12, .08, 'square', .04)
            else:
                st['sn'].pop()
            draw()
            status()
            job['id'] = os_.root.after(max(55, 150 - st['score'] * 4), tick)

        def draw():
            from ..util import mix
            cv.delete('all')
            shade = mix(T['bg0'], '#808080', .07)
            for x in range(N):
                for y in range(N):
                    if (x + y) % 2:
                        cv.create_rectangle(x * C, y * C, x * C + C, y * C + C, fill=shade, outline='')
            fx, fy = st['food']
            cv.create_oval(fx * C + 2, fy * C + 2, fx * C + C - 2, fy * C + C - 2, fill='#e0577e', outline='')
            n = len(st['sn'])
            for i, (x, y) in enumerate(st['sn']):
                k = max(.35, 1 - i / (n + 6))
                col = mix(T['bg0'], T['acc'], k)
                cv.create_rectangle(x * C + 1, y * C + 1, x * C + C - 1, y * C + C - 1, fill=col, outline='')

        def turn(dx, dy):
            if not st['alive']:
                return
            if (dx, dy) == (-st['dir'][0], -st['dir'][1]):
                return
            st['nd'] = (dx, dy)
            st['started'] = True

        def key(e):
            m = {'Up': (0, -1), 'w': (0, -1), 'Down': (0, 1), 's': (0, 1), 'Left': (-1, 0), 'a': (-1, 0),
                 'Right': (1, 0), 'd': (1, 0)}.get(e.keysym)
            if m:
                turn(*m)
                return 'break'
            if e.keysym == 'space':
                if not st['alive']:
                    reset()
                else:
                    st['paused'] = not st['paused']
                    status()
                return 'break'
            return None
        box.bind('<KeyPress>', key)
        swipe = {}
        cv.bind('<ButtonPress-1>', lambda e: (swipe.update(x=e.x, y=e.y), box.focus_set(), reset() if not st['alive'] else None))

        def release(e):
            dx, dy = e.x - swipe.get('x', e.x), e.y - swipe.get('y', e.y)
            if (dx * dx + dy * dy) ** 0.5 < 20:
                return
            if abs(dx) > abs(dy):
                turn(1 if dx > 0 else -1, 0)
            else:
                turn(0, 1 if dy > 0 else -1)
        cv.bind('<ButtonRelease-1>', release)
        pad = tk.Frame(box, bd=0)
        T.style(pad, bg='bg1')
        pad.pack(pady=(8, 0))
        for label, dx, dy in (('◀', -1, 0), ('▲', 0, -1), ('▼', 0, 1), ('▶', 1, 0)):
            Btn(pad, T, label, lambda dx=dx, dy=dy: (turn(dx, dy), box.focus_set()), size='sm', bg='bg1').pack(side='left', padx=3)
        self._hint(box, 'Arrow keys or WASD · drag to steer · Space pauses')
        reset()

        def stop():
            st['alive'] = False
            if job['id']:
                os_.root.after_cancel(job['id'])
        return stop

    # ---------------------------------------------------------- 2048
    def game_g2048(self, box):
        T, os_ = self.T, self.os
        COL = {0: '#cdc1b4', 2: '#eee4da', 4: '#ede0c8', 8: '#f2b179', 16: '#f59563', 32: '#f67c5f', 64: '#f65e3b',
               128: '#edcf72', 256: '#edcc61', 512: '#edc850', 1024: '#edc53f', 2048: '#edc22e'}
        info = self._info(box)
        board = tk.Frame(box, bd=0, padx=8, pady=8)
        T.style(board, bg='bg3')
        board.pack()
        tiles = []
        for i in range(16):
            lbl = tk.Label(board, width=4, height=2, font=T.font('sans', 26, 'bold'), bd=0)
            lbl.grid(row=i // 4, column=i % 4, padx=4, pady=4)
            tiles.append(lbl)
        st = {}

        def add():
            empty = [i for i, v in enumerate(st['g']) if not v]
            if empty:
                st['g'][random.choice(empty)] = 2 if random.random() < .9 else 4

        def reset():
            st.update(g=[0] * 16, score=0, over=False, won=False)
            add()
            add()
            draw()

        def draw():
            for i, v in enumerate(st['g']):
                tiles[i].configure(text=str(v) if v else '', bg=COL.get(v, '#3c3a32'),
                                   fg='#ffffff' if v > 4 else '#776e65',
                                   font=T.font('sans', 18 if v >= 1024 else 26, 'bold'))
            parts = [('Score %d' % st['score'], 'fg', True), ('Best %d' % (os_.S['scores'].get('g2048') or 0), 'fg2', True)]
            if st['over']:
                parts.append(('No moves left — press N for a new game', 'red', True))
            elif st['won']:
                parts.append(('You made 2048!', 'acc', True))
            self._set_info(info, parts)

        def line(arr):
            a = [x for x in arr if x]
            i = 0
            while i < len(a) - 1:
                if a[i] == a[i + 1]:
                    a[i] *= 2
                    st['score'] += a[i]
                    if a[i] == 2048:
                        st['won'] = True
                    a.pop(i + 1)
                i += 1
            return a + [0] * (4 - len(a))

        def move(d):
            if st['over']:
                return
            before = list(st['g'])
            ng = list(st['g'])
            for i in range(4):
                idx = [i * 4 + j if d == 'l' else i * 4 + 3 - j if d == 'r' else j * 4 + i if d == 'u' else (3 - j) * 4 + i
                       for j in range(4)]
                res = line([st['g'][k] for k in idx])
                for j, k in enumerate(idx):
                    ng[k] = res[j]
            st['g'] = ng
            if st['g'] == before:
                draw()
                return
            add()
            os_.sound.tone(300 + min(st['score'], 800) / 4, .05, 'sine', .03)
            g = st['g']
            if not any(not g[i] or (i % 4 < 3 and g[i] == g[i + 1]) or (i < 12 and g[i] == g[i + 4]) for i in range(16)):
                st['over'] = True
            bump_score(os_, 'g2048', st['score'])
            draw()

        def key(e):
            m = {'Left': 'l', 'a': 'l', 'Right': 'r', 'd': 'r', 'Up': 'u', 'w': 'u', 'Down': 'd', 's': 'd'}.get(e.keysym)
            if m:
                move(m)
                return 'break'
            if e.keysym.lower() == 'n':
                reset()
                return 'break'
            return None
        box.bind('<KeyPress>', key)
        swipe = {}

        def press(e):
            swipe.update(x=e.x_root, y=e.y_root)
            box.focus_set()

        def release(e):
            dx, dy = e.x_root - swipe.get('x', e.x_root), e.y_root - swipe.get('y', e.y_root)
            if (dx * dx + dy * dy) ** 0.5 < 24:
                return
            move(('r' if dx > 0 else 'l') if abs(dx) > abs(dy) else ('d' if dy > 0 else 'u'))
        for w in [board] + tiles:
            w.bind('<ButtonPress-1>', press)
            w.bind('<ButtonRelease-1>', release)
        row = tk.Frame(box, bd=0)
        T.style(row, bg='bg1')
        row.pack(pady=(10, 0))
        Btn(row, T, 'New game', lambda: (reset(), box.focus_set()), size='sm', bg='bg1').pack()
        self._hint(box, 'Arrow keys or WASD · drag to slide')
        reset()
        return lambda: None

    # ---------------------------------------------------------- Minesweeper
    def game_mines(self, box):
        T, os_ = self.T, self.os
        S = os_.S
        CFG = {'easy': (9, 9, 10), 'medium': (12, 12, 24), 'hard': (16, 16, 40)}
        COLORS = ['', '#5aa7ff', '#7ac74f', '#ff7a6b', '#a78bfa', '#c9772a', '#35c9b0', '#888888', '#bbbbbb']
        st = {'cfg': S['scores'].get('minesCfg') or 'easy', 'flag_mode': False, 'timer': None}
        if st['cfg'] not in CFG:
            st['cfg'] = 'easy'
        info = tk.Frame(box, bd=0)
        T.style(info, bg='bg1')
        info.pack(pady=(0, 8))

        def set_cfg(v):
            st['cfg'] = v
            S['scores']['minesCfg'] = v
            os_.touch()
            reset()
        Select(info, T, [(k, k.capitalize()) for k in CFG], st['cfg'], set_cfg, bg='bg1', size='sm').pack(side='left', padx=4)
        mines_lbl = tk.Label(info, font=T.font('sans', 14, 'bold'))
        time_lbl = tk.Label(info, font=T.font('sans', 14, 'bold'))
        result = tk.Label(info, font=T.font('sans', 14, 'bold'))
        for w in (mines_lbl, time_lbl, result):
            T.style(w, bg='bg1', fg='fg')
            w.pack(side='left', padx=6)

        def toggle_flag():
            st['flag_mode'] = not st['flag_mode']
            fb.set_text('🚩 Flag mode: ' + ('on' if st['flag_mode'] else 'off'))
            fb.set_kind('pri' if st['flag_mode'] else 'btn')
        fb = Btn(info, T, '🚩 Flag mode: off', toggle_flag, size='sm', bg='bg1')
        fb.pack(side='left', padx=4)
        Btn(info, T, 'New', lambda: reset(), size='sm', bg='bg1').pack(side='left', padx=4)
        grid = tk.Frame(box, bd=0, padx=4, pady=4)
        T.style(grid, bg='bg3')
        grid.pack()
        self._hint(box, 'Click to reveal · right-click to flag · click a number to clear around it')

        def nb(i):
            R, Cn = st['R'], st['C']
            r, c = divmod(i, Cn)
            out = []
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr or dc:
                        rr, cc = r + dr, c + dc
                        if 0 <= rr < R and 0 <= cc < Cn:
                            out.append(rr * Cn + cc)
            return out

        def reset():
            R, Cn, M = CFG[st['cfg']]
            st.update(R=R, C=Cn, M=M, cells=[{'m': 0, 'o': 0, 'f': 0, 'n': 0, 'x': 0} for _ in range(R * Cn)], state='ready',
                      flags=0, revealed=0, t0=0, end_sec=0)
            if st['timer']:
                os_.root.after_cancel(st['timer'])
                st['timer'] = None
            for c in grid.winfo_children():
                c.destroy()
            st['btns'] = []
            for i in range(R * Cn):
                b = tk.Label(grid, width=2, height=1, bd=0, font=T.font('sans', 13, 'bold'), cursor='hand2')
                b.grid(row=i // Cn, column=i % Cn, padx=1, pady=1, ipadx=1, ipady=2)
                b.bind('<Button-1>', lambda e, i=i: click(i, False))
                b.bind('<Button-3>', lambda e, i=i: click(i, True))
                if os_.root.tk.call('tk', 'windowingsystem') == 'aqua':
                    b.bind('<Button-2>', lambda e, i=i: click(i, True))
                st['btns'].append(b)
            draw()

        def plant(safe):
            bad = set([safe] + nb(safe))
            n = 0
            total = st['R'] * st['C']
            while n < st['M']:
                i = random.randrange(total)
                if not st['cells'][i]['m'] and i not in bad:
                    st['cells'][i]['m'] = 1
                    n += 1
            for i, cl in enumerate(st['cells']):
                cl['n'] = sum(1 for j in nb(i) if st['cells'][j]['m'])

        def open_(i):
            stack = [i]
            cells = st['cells']
            while stack:
                k = stack.pop()
                cl = cells[k]
                if cl['o'] or cl['f']:
                    continue
                cl['o'] = 1
                st['revealed'] += 1
                if not cl['n'] and not cl['m']:
                    stack.extend(j for j in nb(k) if not cells[j]['o'])

        def lose(i):
            st['state'] = 'lost'
            st['end_sec'] = int(time.time() - st['t0'])
            stop_timer()
            for c in st['cells']:
                if c['m']:
                    c['o'] = 1
            st['cells'][i]['x'] = 1
            os_.ui_sound('error')
            draw()

        def check():
            if st['revealed'] == st['R'] * st['C'] - st['M']:
                st['state'] = 'won'
                stop_timer()
                sec = st['end_sec'] = int(time.time() - st['t0'])
                best = bump_score(os_, 'mines_' + st['cfg'], sec, True)
                for c in st['cells']:
                    if c['m']:
                        c['f'] = 1
                os_.toast('Cleared in %d s' % sec + (' — a new best!' if best else ''), '💣')

        def stop_timer():
            if st['timer']:
                os_.root.after_cancel(st['timer'])
                st['timer'] = None

        def tick():
            st['timer'] = None
            if st['state'] == 'play' and self.ctx.alive:
                draw_info()
                st['timer'] = os_.root.after(500, tick)

        def click(i, flag):
            if st['state'] in ('won', 'lost'):
                return
            cl = st['cells'][i]
            if flag or st['flag_mode']:
                if cl['o']:
                    return
                cl['f'] = 0 if cl['f'] else 1
                st['flags'] += 1 if cl['f'] else -1
                draw()
                return
            if cl['f']:
                return
            if cl['o']:
                ns = nb(i)
                if sum(1 for j in ns if st['cells'][j]['f']) == cl['n']:
                    for j in ns:
                        c2 = st['cells'][j]
                        if not c2['f'] and not c2['o']:
                            if c2['m']:
                                lose(j)
                                return
                            open_(j)
                    check()
                    draw()
                return
            if st['state'] == 'ready':
                plant(i)
                st['state'] = 'play'
                st['t0'] = time.time()
                st['timer'] = os_.root.after(500, tick)
            if cl['m']:
                lose(i)
                return
            open_(i)
            check()
            draw()

        def draw_info():
            sec = int(time.time() - st['t0']) if st['state'] == 'play' else 0 if st['state'] == 'ready' else st['end_sec']
            mines_lbl.configure(text='💣 %d' % (st['M'] - st['flags']))
            time_lbl.configure(text='⏱ %d s' % sec)
            if st['state'] == 'won':
                result.configure(text='You won!', fg=T['ok'])
            elif st['state'] == 'lost':
                result.configure(text='Boom.', fg=T['red'])
            else:
                result.configure(text='')

        def draw():
            draw_info()
            for i, cl in enumerate(st['cells']):
                b = st['btns'][i]
                if cl['o']:
                    bg = '#a93226' if cl['x'] else T['bg0']
                    text = '💣' if cl['m'] else (str(cl['n']) if cl['n'] else '')
                    fg = COLORS[cl['n']] if cl['n'] and not cl['m'] else T['fg']
                else:
                    bg = T['bg2']
                    text = '🚩' if cl['f'] else ''
                    fg = T['fg']
                b.configure(text=text, bg=bg, fg=fg or T['fg'])
        reset()
        return stop_timer
