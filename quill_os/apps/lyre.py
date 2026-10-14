"""Lyre — piano, beat maker and music player."""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk

from .base import AppSpec, Inst
from .. import audio
from ..core import kind_of
from ..state import FIXED
from ..ui.widgets import Btn, Check, ScrollArea, Select, Slider, Tabs
from ..util import fmt_bytes, fmt_dur

KEYMAP = {'a': 0, 'w': 1, 's': 2, 'e': 3, 'd': 4, 'f': 5, 't': 6, 'g': 7, 'y': 8, 'h': 9, 'u': 10, 'j': 11, 'k': 12,
          'o': 13, 'l': 14, 'p': 15, 'semicolon': 16}
KEY_LABEL = {v: ('; ' if k == 'semicolon' else k).strip().upper() for k, v in KEYMAP.items()}
NOTE_NAMES = ['C', 'C♯', 'D', 'D♯', 'E', 'F', 'F♯', 'G', 'G♯', 'A', 'A♯', 'B']
DRUMS = ['Kick', 'Snare', 'Hat', 'Clap']
INSTS = [('triangle', 'Warm'), ('sine', 'Soft'), ('square', 'Chip'), ('sawtooth', 'Bright'), ('pluck', 'Pluck'),
         ('bell', 'Bell'), ('organ', 'Organ')]
PRESET = [[1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0], [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1],
          [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 1], [0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0]]


class App(AppSpec):
    id = 'lyre'
    name = 'Lyre'
    icon = '♪'
    bg = ('#8f7bff', '#3b2d9c')
    w, h = 760, 520
    single = True
    kw = 'music piano keyboard synth beats drum machine audio player mp3 sound'
    about = 'Piano, beat maker and player'

    def build(self, ctx):
        return Lyre(ctx).inst


class ExternalPlayer:
    """Plays a file with the computer's own player when Quill cannot stream audio itself."""

    def __init__(self, data, name):
        self.proc = None
        self.dir = tempfile.mkdtemp(prefix='quill-play-')
        self.path = os.path.join(self.dir, 'track' + (os.path.splitext(name)[1] or '.wav'))
        with open(self.path, 'wb') as f:
            f.write(data)
        self.t0 = time.monotonic()
        self.ended = False
        if sys.platform == 'darwin' and shutil.which('afplay'):
            self.proc = subprocess.Popen(['afplay', self.path])
        elif sys.platform.startswith('win') and self.path.lower().endswith('.wav'):
            import winsound
            winsound.PlaySound(self.path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        elif sys.platform.startswith('win'):
            os.startfile(self.path)  # opens the system's music player
            self.ended = True
        else:
            for cmd in (['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet'], ['paplay'], ['aplay', '-q']):
                if shutil.which(cmd[0]):
                    self.proc = subprocess.Popen(cmd + [self.path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    break
            else:
                raise OSError('no audio player found')

    def finished(self):
        if self.ended:
            return True
        return self.proc is not None and self.proc.poll() is not None

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass
        if sys.platform.startswith('win'):
            try:
                import winsound
                winsound.PlaySound(None, 0)
            except Exception:
                pass
        shutil.rmtree(self.dir, ignore_errors=True)


class Lyre:
    TABS = [('piano', '🎹 Piano'), ('beats', '🥁 Beats'), ('player', '🎧 Player')]

    def __init__(self, ctx):
        self.ctx = ctx
        os_ = self.os = ctx.os
        T = self.T = ctx.T
        self.L = os_.S['lyre']
        self.snd = os_.sound
        arg = ctx.arg or {}
        self.tab = arg.get('tab') or 'piano'
        self.pending_file = arg.get('file')
        self.held = {}
        self.rec = False
        self.rec_start = 0.0
        self.rec_events = []
        self.play_jobs = []
        self.playing = False
        self.seq_on = False
        self.seq_job = None
        self.seq_next = 0.0
        self.seq_step = 0
        self.cells = []
        self.cur_track = None
        self.voice = None          # Sample voice for music playback
        self.ext = None            # ExternalPlayer when streaming is not possible
        self.decoded = {}
        self.key_off_jobs = {}
        self.piano = None
        self.vis = None
        self.vis_job = None
        self.tabs = Tabs(ctx.body, T, self.TABS, self.tab, self.set_tab)
        self.tabs.pack(fill='x')
        self.view = tk.Frame(ctx.body, bd=0, takefocus=1)
        T.style(self.view, bg='bg1')
        self.view.pack(fill='both', expand=True)
        self.view.bind('<KeyPress>', self._keydown)
        self.view.bind('<KeyRelease>', self._keyup)
        self.view.bind('<FocusOut>', lambda e: self.all_off())
        self.off = os_.bus.on('fs', lambda _a: self.draw() if ctx.alive and self.tab == 'player' and not self._music_playing()
                              else None)
        self.draw()
        self.inst = Inst(on_arg=self.on_arg, on_focus=lambda: self.view.focus_set(), on_close=self.on_close,
                         mem=lambda: 150000 + (600000 if self.cur_track else 0))
        os_.root.after(30, self.view.focus_set)

    # ---------------------------------------------------------- tabs
    def set_tab(self, t):
        self.tab = t
        self.draw()

    def on_arg(self, a):
        if not isinstance(a, dict):
            return
        if a.get('tab'):
            self.tab = a['tab']
        if a.get('file'):
            self.pending_file = a['file']
        self.draw()

    def draw(self):
        self.all_off()
        self.tabs.select(self.tab)
        for c in self.view.winfo_children():
            c.destroy()
        if self.vis_job:
            self.os.root.after_cancel(self.vis_job)
            self.vis_job = None
        self.piano = None
        if self.tab != 'beats':
            self.stop_seq()
        getattr(self, 'draw_' + self.tab)()
        self.ctx.set_title('Lyre — ' + dict(self.TABS)[self.tab].split(' ', 1)[1])

    def _frame(self, parent, **pack):
        f = tk.Frame(parent, bd=0)
        self.T.style(f, bg='bg1')
        if pack:
            f.pack(**pack)
        return f

    def _label(self, parent, text, size=12, fg='fg2', **kw):
        lbl = tk.Label(parent, text=text, font=self.T.font('sans', size), **kw)
        self.T.style(lbl, bg='bg1', fg=fg)
        return lbl

    # ---------------------------------------------------------- piano
    def note_on(self, m):
        if m in self.held:
            return
        self.held[m] = self.snd.note(m, self.L.get('inst', 'triangle'))
        self.paint_key(m, True)
        if self.rec:
            self.rec_events.append((time.perf_counter() - self.rec_start, m, 1))

    def note_off(self, m):
        if m not in self.held:
            return
        v = self.held.pop(m)
        if v is not None:
            self.snd.release(v)
        self.paint_key(m, False)
        if self.rec:
            self.rec_events.append((time.perf_counter() - self.rec_start, m, 0))

    def all_off(self):
        for m in list(self.held):
            self.note_off(m)

    def paint_key(self, m, on):
        p = self.piano
        if p is None:
            return
        try:
            item = p['items'].get(m)
            if item is not None:
                cv, rect, black = p['cv'], item, m in p['blacks']
                cv.itemconfigure(rect, fill=self.T['acc'] if on else ('#111111' if black else '#f3efe0'))
        except tk.TclError:
            pass

    def draw_piano(self):
        T = self.T
        L = self.L
        wrap = self._frame(self.view, fill='both', expand=True, padx=14, pady=12)
        row = self._frame(wrap, fill='x')
        self._label(row, 'Sound').pack(side='left', padx=(0, 8))
        Select(row, T, INSTS, L.get('inst', 'triangle'), lambda v: (L.__setitem__('inst', v), self.os.touch()),
               bg='bg1', size='sm').pack(side='left')

        def octave(d):
            L['oct'] = max(1, min(7, L.get('oct', 4) + d))
            self.os.touch()
            self.draw()
        Btn(row, T, '−', lambda: octave(-1), size='sm', bg='bg1').pack(side='left', padx=(10, 4))
        self._label(row, 'Octave %d' % L.get('oct', 4)).pack(side='left')
        Btn(row, T, '+', lambda: octave(1), size='sm', bg='bg1').pack(side='left', padx=4)
        sep = tk.Frame(row, width=1, height=20, bd=0)
        T.style(sep, bg='line')
        sep.pack(side='left', padx=8)

        def record():
            if self.rec:
                self.rec = False
                n = len(self.rec_events) // 2
                self.os.toast('Recorded %d notes' % n if self.rec_events else 'Nothing recorded', '●')
            else:
                self.rec = True
                self.rec_start = time.perf_counter()
                self.rec_events = []
            self.draw()
        Btn(row, T, '■ Stop recording' if self.rec else '● Record', record, size='sm', bg='bg1').pack(side='left', padx=3)
        self.b_play = Btn(row, T, '■ Stop' if self.playing else '▶ Play recording', self.play_recording, size='sm', bg='bg1')
        self.b_play.pack(side='left', padx=3)
        self.b_play.set_disabled(not self.rec_events)
        cv = tk.Canvas(wrap, height=150, bd=0, highlightthickness=0, cursor='hand2')
        T.style(cv, bg='bg1')
        cv.pack(fill='x', pady=12)
        self._label(wrap, 'Play with the mouse, or with your keyboard: A S D F G H J K L ; for white keys and '
                          'W E T Y U O P for black keys.', wraplength=640, justify='left').pack(anchor='w')
        self.piano = {'cv': cv, 'items': {}, 'blacks': set()}
        state = {'m': None}

        def layout(_e=None):
            cv.delete('all')
            self.piano['items'] = {}
            w = max(300, cv.winfo_width())
            h = 150
            base = 12 * (L.get('oct', 4) + 1)
            ww = w / 15
            wi = 0
            blacks = []
            for i in range(25):
                m = base + i
                black = i % 12 in (1, 3, 6, 8, 10)
                if black:
                    blacks.append((i, m, wi))
                    continue
                x0 = wi * ww
                r = cv.create_rectangle(x0, 0, x0 + ww, h, fill='#f3efe0', outline='#222222', tags=('key', 'm%d' % m))
                self.piano['items'][m] = r
                lbl = KEY_LABEL.get(i, '')
                cv.create_text(x0 + ww / 2, h - 10, text=lbl, fill='#666666', font=T.font('sans', 11), tags=('m%d' % m,))
                wi += 1
            for i, m, wpos in blacks:
                x0 = wpos * ww - ww * .31
                r = cv.create_rectangle(x0, 0, x0 + ww * .62, h * .62, fill='#111111', outline='#222222',
                                        tags=('key', 'm%d' % m))
                self.piano['items'][m] = r
                self.piano['blacks'].add(m)
                cv.create_text(x0 + ww * .31, h * .62 - 9, text=KEY_LABEL.get(i, ''), fill='#aaaaaa',
                               font=T.font('sans', 9), tags=('m%d' % m,))
            for m in self.held:
                self.paint_key(m, True)

        def note_at(x, y):
            for item in reversed(cv.find_overlapping(x, y, x, y)):
                for tag in cv.gettags(item):
                    if tag.startswith('m'):
                        return int(tag[1:])
            return None

        def down(e):
            self.view.focus_set()
            m = note_at(e.x, e.y)
            if m is not None:
                state['m'] = m
                self.note_on(m)

        def drag(e):
            m = note_at(e.x, e.y)
            if m != state['m']:
                if state['m'] is not None:
                    self.note_off(state['m'])
                state['m'] = m
                if m is not None:
                    self.note_on(m)

        def up(_e):
            if state['m'] is not None:
                self.note_off(state['m'])
                state['m'] = None
        cv.bind('<Configure>', layout)
        cv.bind('<ButtonPress-1>', down)
        cv.bind('<B1-Motion>', drag)
        cv.bind('<ButtonRelease-1>', up)

    def play_recording(self):
        if self.playing:
            self.stop_playback()
            return
        if not self.rec_events:
            return
        self.playing = True
        self.b_play.set_text('■ Stop')
        root = self.os.root
        for t, m, on in self.rec_events:
            self.play_jobs.append(root.after(int(t * 1000), (lambda m=m: self.note_on(m)) if on else (lambda m=m: self.note_off(m))))
        self.play_jobs.append(root.after(int(self.rec_events[-1][0] * 1000) + 400, self.stop_playback))

    def stop_playback(self):
        for j in self.play_jobs:
            try:
                self.os.root.after_cancel(j)
            except tk.TclError:
                pass
        self.play_jobs = []
        self.playing = False
        self.all_off()
        try:
            self.b_play.set_text('▶ Play recording')
        except (tk.TclError, AttributeError):
            pass

    def _keydown(self, e):
        if self.tab != 'piano' or e.state & 0x4 or e.state & 0x20000:
            return None
        k = e.keysym.lower()
        if k in KEYMAP:
            job = self.key_off_jobs.pop(k, None)
            if job:   # auto-repeat: the key never really went up
                self.os.root.after_cancel(job)
                return 'break'
            self.note_on(12 * (self.L.get('oct', 4) + 1) + KEYMAP[k])
            return 'break'
        return None

    def _keyup(self, e):
        k = e.keysym.lower()
        if k in KEYMAP:
            m = 12 * (self.L.get('oct', 4) + 1) + KEYMAP[k]

            def off(k=k, m=m):
                self.key_off_jobs.pop(k, None)
                self.note_off(m)
            self.key_off_jobs[k] = self.os.root.after(30, off)

    # ---------------------------------------------------------- beats
    def draw_beats(self):
        T = self.T
        L = self.L
        wrap = self._frame(self.view, fill='both', expand=True, padx=14, pady=12)
        row = self._frame(wrap, fill='x')
        self.b_seq = Btn(row, T, '■ Stop' if self.seq_on else '▶ Play', lambda: self.stop_seq() if self.seq_on else self.start_seq(),
                         kind='pri', bg='bg1')
        self.b_seq.pack(side='left')
        bl = self._label(row, '%d BPM' % L['bpm'], fg='fg')

        def bpm(v):
            L['bpm'] = v
            bl.configure(text='%d BPM' % v)
            self.os.touch()
        Slider(row, T, 60, 200, L['bpm'], bpm, length=160, bg='bg1').pack(side='left', padx=10)
        bl.pack(side='left')

        def clear():
            L['pat'] = [[0] * 16 for _ in range(4)]
            self.os.touch()
            self.draw()

        def preset():
            L['pat'] = [list(r) for r in PRESET]
            self.os.touch()
            self.draw()
        Btn(row, T, 'Clear', clear, size='sm', bg='bg1').pack(side='left', padx=(12, 4))
        Btn(row, T, 'Preset', preset, size='sm', bg='bg1').pack(side='left')
        grid = self._frame(wrap, fill='x', pady=12)
        self.cells = []
        for r in range(4):
            self._label(grid, DRUMS[r], anchor='w', width=7).grid(row=r, column=0, sticky='w')
            rc = []
            for i in range(16):
                c = tk.Frame(grid, width=26, height=26, bd=0, highlightthickness=1, cursor='hand2')
                c.grid(row=r, column=i + 1, padx=(6 if i and i % 4 == 0 else 2, 0), pady=2)
                c.bind('<Button-1>', lambda e, r=r, i=i: self.toggle_cell(r, i))
                rc.append(c)
            self.cells.append(rc)
        self.paint_cells(-1)
        self._label(wrap, 'Click the squares to build a 16-step pattern. It loops until you press Stop and is saved '
                          'with your settings.', wraplength=640, justify='left').pack(anchor='w')

    def paint_cells(self, now_step):
        T = self.T
        pat = self.L['pat']
        for r, row in enumerate(self.cells):
            for i, c in enumerate(row):
                on = bool(pat[r][i])
                try:
                    c.configure(bg=T['acc'] if on else (T['bg3'] if i % 4 == 0 else T['bg2']),
                                highlightbackground=T['fg'] if i == now_step else (T['acc'] if on else T['line']),
                                highlightthickness=2 if i == now_step else 1)
                except tk.TclError:
                    return

    def toggle_cell(self, r, i):
        pat = self.L['pat']
        pat[r][i] = 0 if pat[r][i] else 1
        if pat[r][i]:
            self.snd.drum(r)
        self.paint_cells(self.seq_step - 1 if self.seq_on else -1)
        self.os.touch()

    def start_seq(self):
        if not self.snd.ensure():
            self.os.toast('Audio is not available here', '⚠️')
            return
        self.seq_on = True
        self.seq_step = 0
        self.seq_next = self.snd.now() + 0.06
        try:
            self.b_seq.set_text('■ Stop')
        except tk.TclError:
            pass
        root = self.os.root

        def tick():
            if not self.seq_on:
                return
            now = self.snd.now()
            while self.seq_next < now + 0.12:
                st, when = self.seq_step, self.seq_next
                for r in range(4):
                    if self.L['pat'][r][st]:
                        self.snd.drum(r, when)
                root.after(max(0, int((when - now) * 1000)), lambda st=st: self.paint_cells(st) if self.seq_on else None)
                self.seq_next += 60.0 / self.L['bpm'] / 4
                self.seq_step = (self.seq_step + 1) % 16
            self.seq_job = root.after(25, tick)
        tick()

    def stop_seq(self):
        self.seq_on = False
        if self.seq_job:
            try:
                self.os.root.after_cancel(self.seq_job)
            except tk.TclError:
                pass
            self.seq_job = None
        if self.cells:
            self.paint_cells(-1)
        try:
            self.b_seq.set_text('▶ Play')
        except (tk.TclError, AttributeError):
            pass

    # ---------------------------------------------------------- music player
    def tracks(self):
        fs = self.os.fs
        return sorted([n for n in fs.all() if n['t'] == 'f' and kind_of(n) == 'audio' and n.get('c')],
                      key=lambda n: n['n'].lower())

    def _music_playing(self):
        if self.voice is not None:
            return not self.voice.done and not self.voice.paused
        return self.ext is not None and not self.ext.finished()

    def draw_player(self):
        T = self.T
        L = self.L
        os_ = self.os
        wrap = self._frame(self.view, fill='both', expand=True)
        top = self._frame(wrap, fill='x', padx=14, pady=12)
        cur = os_.fs.get(self.cur_track) if self.cur_track else None
        self.title_lbl = tk.Label(top, text=cur['n'] if cur else 'Nothing playing', font=T.font('serif', 18, slant='italic'))
        T.style(self.title_lbl, bg='bg1', fg='fg')
        self.title_lbl.pack(fill='x')
        self.vis = tk.Canvas(top, height=80, bd=0, highlightthickness=1)
        T.on(self.vis, lambda: self.vis.configure(bg=T['bg0'], highlightbackground=T['line']))
        self.vis.pack(fill='x', pady=8)
        prog = self._frame(top, fill='x')
        self.pos_lbl = self._label(prog, '0:00', width=6)
        self.pos_lbl.pack(side='left')
        self.seek = Slider(prog, T, 0, 1000, 0, None, length=300, bg='bg1')
        self.seek.pack(side='left', fill='x', expand=True, padx=6)
        self.seek.bind('<ButtonRelease-1>', lambda e: self._seek())
        self.dur_lbl = self._label(prog, '0:00', width=6)
        self.dur_lbl.pack(side='left')
        row = self._frame(top, fill='x', pady=(6, 0))
        inner = self._frame(row)
        inner.pack()
        Btn(inner, T, '⏮ Previous', lambda: self.step(-1), size='sm', bg='bg1').pack(side='left', padx=3)
        self.b_pp = Btn(inner, T, '⏸ Pause' if self._music_playing() else '▶ Play', self.play_pause, kind='pri', size='sm',
                        bg='bg1')
        self.b_pp.pack(side='left', padx=3)
        Btn(inner, T, '⏭ Next', lambda: self.step(1), size='sm', bg='bg1').pack(side='left', padx=3)
        Check(inner, T, 'Loop', L.get('loop') is not False, lambda v: (L.__setitem__('loop', v), os_.touch()),
              bg='bg1').pack(side='left', padx=6)
        Check(inner, T, 'Shuffle', bool(L.get('shuffle')), lambda v: (L.__setitem__('shuffle', v), os_.touch()),
              bg='bg1').pack(side='left', padx=6)
        Btn(inner, T, '⇧ Add music', lambda: os_.upload_into(FIXED['music']), kind='pri', size='sm',
            bg='bg1').pack(side='left', padx=3)
        line = tk.Frame(wrap, height=1, bd=0)
        T.style(line, bg='line')
        line.pack(fill='x')
        lst = ScrollArea(wrap, T, bg='bg1')
        lst.pack(fill='both', expand=True)
        tracks = self.tracks()
        self.track_rows = {}
        for n in tracks:
            on = n['id'] == self.cur_track
            b = Btn(lst.inner, T, '🎵   ' + n['n'] + '      ' + fmt_bytes(len(n['c']) * .75),
                    lambda n=n: self.play(n), kind='flat', bg='bg1', anchor='w')
            b.set_on(on)
            b.pack(fill='x')
            self.track_rows[n['id']] = b
        if not tracks:
            os_.empty_state(lst.inner, '🎧', 'No music yet.', 'Add MP3, WAV or OGG files (up to 1.5 MB each) to your Music folder.')
        if self.pending_file:
            f = os_.fs.get(self.pending_file)
            self.pending_file = None
            if f is not None and f.get('c') and kind_of(f) == 'audio':
                os_.root.after(30, lambda: self.play(f))
        self._vis_loop()

    def play(self, n):
        os_ = self.os
        self.stop_music()
        self.cur_track = n['id']
        data = os_.fs.file_bytes(n)
        samples = self.decoded.get((n['id'], n['m']))
        if samples is None and self.snd.ensure() and not self.snd.backend.clip:
            self.title_lbl.configure(text='Opening ' + n['n'] + '…')
            res = {}
            th = threading.Thread(target=lambda: res.update(r=audio.decode_audio(data, n['n'])), daemon=True)
            th.start()
            os_.wait(lambda: not th.is_alive())
            if not self.ctx.alive:
                return
            samples, err = res.get('r', (None, 'Could not read the file.'))
            if samples is None:
                os_.toast(err, '🎧')
            else:
                self.decoded = {(n['id'], n['m']): samples}
        if samples is not None:
            v = self.snd.play_samples(samples)
            if v is not None:
                self.voice = v
                v.on_end = lambda: self.step(1) if self.ctx.alive and self.voice is v else None
        if self.voice is None:
            try:
                self.ext = ExternalPlayer(data, n['n'])
            except Exception as e:
                os_.toast('Could not play this file: %s' % e, '🎧')
                self.ext = None
        self._mark_track()
        self.ctx.set_title('Lyre — ' + n['n'])

    def _mark_track(self):
        try:
            cur = self.os.fs.get(self.cur_track) if self.cur_track else None
            self.title_lbl.configure(text=cur['n'] if cur else 'Nothing playing')
            for tid, b in self.track_rows.items():
                b.set_on(tid == self.cur_track)
            self.b_pp.set_text('⏸ Pause' if self._music_playing() else '▶ Play')
        except (tk.TclError, AttributeError):
            pass

    def play_pause(self):
        if self.voice is not None and not self.voice.done:
            self.voice.paused = not self.voice.paused
        elif self.ext is not None and not self.ext.finished():
            self.stop_music()
        else:
            tr = self.tracks()
            cur = next((t for t in tr if t['id'] == self.cur_track), None) or (tr[0] if tr else None)
            if cur is not None:
                self.play(cur)
                return
        self._mark_track()

    def stop_music(self):
        if self.voice is not None:
            self.snd.stop_voice(self.voice)
            self.voice = None
        if self.ext is not None:
            self.ext.stop()
            self.ext = None

    def step(self, d):
        tracks = self.tracks()
        if not tracks:
            return
        import random
        i = next((k for k, t in enumerate(tracks) if t['id'] == self.cur_track), -1)
        if self.L.get('shuffle') and d > 0:
            i = random.randrange(len(tracks))
        else:
            i += d
        if i >= len(tracks):
            if self.L.get('loop') is False:
                self.stop_music()
                self._mark_track()
                return
            i = 0
        if i < 0:
            i = len(tracks) - 1
        self.play(tracks[i])

    def _seek(self):
        if self.voice is not None:
            self.voice.seek(self.seek.get() / 1000 * self.voice.duration)

    def _vis_loop(self):
        if not self.ctx.alive or self.tab != 'player':
            return
        try:
            c = self.vis
            c.delete('bar')
            w, h = c.winfo_width(), c.winfo_height()
            v = self.voice
            if v is not None and not v.done and not v.paused:
                lv = audio.levels(self.snd.last_block, 32)
                bw = w / len(lv)
                for i, x in enumerate(lv):
                    bh = x * h
                    c.create_rectangle(i * bw + 1, h - bh, (i + 1) * bw - 1, h, fill=self.T['acc'], outline='', tags='bar')
            if v is not None:
                self.pos_lbl.configure(text=fmt_dur(v.position * 1000)[-5:] if v.position < 3600 else fmt_dur(v.position * 1000))
                self.dur_lbl.configure(text=fmt_dur(v.duration * 1000)[-5:])
                if not getattr(self.seek, '_drag', False):
                    self.seek.set(int(v.position / max(0.001, v.duration) * 1000))
            elif self.ext is not None:
                self.pos_lbl.configure(text=fmt_dur((time.monotonic() - self.ext.t0) * 1000)[-5:])
            if self.ext is not None and self.ext.finished() and self.voice is None:
                self.ext.stop()
                self.ext = None
                self.step(1)
        except tk.TclError:
            return
        self.vis_job = self.os.root.after(60, self._vis_loop)

    # ---------------------------------------------------------- closing
    def on_close(self):
        self.stop_seq()
        self.stop_playback()
        self.all_off()
        self.stop_music()
        for j in self.key_off_jobs.values():
            try:
                self.os.root.after_cancel(j)
            except tk.TclError:
                pass
        if self.vis_job:
            try:
                self.os.root.after_cancel(self.vis_job)
            except tk.TclError:
                pass
        self.off()
