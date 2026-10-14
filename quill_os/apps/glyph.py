"""Glyph — a code editor with Run."""

import json
import os
import pathlib
import re
import tempfile
import time
import tkinter as tk
import webbrowser

from .base import AppSpec, Inst
from .scribe import bind_mod
from ..core import kind_of
from ..highlight import LANG_NAMES, lang_of, spans
from ..state import FIXED
from ..ui.widgets import Btn, Check, Entry, bar_width
from ..util import ext_of

TAB = '  '
PAIRS = {'(': ')', '[': ']', '{': '}', '"': '"', "'": "'", '`': '`'}
_WIDE = tk.TkVersion < 9.0   # Tk 8.6 counts characters beyond U+FFFF as two


def tk_len(s):
    if _WIDE:
        return len(s.encode('utf-16-le')) // 2
    return len(s)


def off_to_index(v, off):
    off = max(0, min(len(v), off))
    line = v.count('\n', 0, off) + 1
    ls = v.rfind('\n', 0, off) + 1
    return '%d.%d' % (line, tk_len(v[ls:off]))


def index_to_off(text, v, idx):
    line, col = map(int, text.index(idx).split('.'))
    pos = 0
    for _ in range(line - 1):
        nl = v.find('\n', pos)
        if nl < 0:
            return len(v)
        pos = nl + 1
    end = v.find('\n', pos)
    end = len(v) if end < 0 else end
    if not _WIDE:
        return min(pos + col, end)
    units = 0
    i = pos
    while i < end and units < col:
        units += 2 if ord(v[i]) > 0xFFFF else 1
        i += 1
    return i


class App(AppSpec):
    id = 'glyph'
    name = 'Glyph'
    icon = '{ }'
    bg = ('#4fb7c4', '#2a6a9c')
    w, h = 900, 600
    kw = 'code editor programming javascript python html css json run script ide'
    about = 'Code editor with Run'

    def build(self, ctx):
        return Glyph(ctx).inst


class Glyph:
    def __init__(self, ctx):
        self.ctx = ctx
        os_ = self.os = ctx.os
        T = self.T = ctx.T
        self.fs = os_.fs
        self.docs = []
        self.cur = -1
        self.runner = None
        self.find_open = False
        self._hl_job = None
        self._loading = False
        body = ctx.body

        bar = tk.Frame(body, bd=0)
        T.style(bar, bg='bg2')
        bar.pack(fill='x')
        Btn(bar, T, '＋ New', lambda: self.add_doc({'name': 'untitled.js'}), size='sm').pack(side='left', padx=(8, 3), pady=6)
        Btn(bar, T, '📂 Open', self.open_picker, size='sm').pack(side='left', padx=3)
        Btn(bar, T, '💾 Save', lambda: self.save_doc() and os_.toast('Saved', '💾'), size='sm',
            tip='Save (Ctrl+S)').pack(side='left', padx=3)
        self._sep(bar)
        self.b_run = Btn(bar, T, '▶ Run', self.run, kind='pri', size='sm', tip='Run (Ctrl+Enter)')
        self.b_run.pack(side='left', padx=3)
        self.b_stop = Btn(bar, T, '■ Stop', self.stop, size='sm')
        self.b_stop.pack(side='left', padx=3)
        self.b_stop.set_disabled(True)
        self._sep(bar)
        Btn(bar, T, '🔍 Find', lambda: self.toggle_find(True), size='sm', tip='Find (Ctrl+F)').pack(side='left', padx=3)
        Btn(bar, T, '✨ Format', self.format_json, size='sm', tip='Format JSON').pack(side='left', padx=3)
        line = tk.Frame(body, height=1, bd=0)
        T.style(line, bg='line')
        line.pack(fill='x')

        self.tabs = tk.Frame(body, bd=0)
        T.style(self.tabs, bg='bg2')
        self.tabs.pack(fill='x')
        self.tabs_line = tk.Frame(body, height=1, bd=0)
        T.style(self.tabs_line, bg='line')
        self.tabs_line.pack(fill='x')

        self.findbar = tk.Frame(body, bd=0)
        T.style(self.findbar, bg='bg2')
        self.f_in = Entry(self.findbar, T, placeholder='Find', width=16)
        self.r_in = Entry(self.findbar, T, placeholder='Replace', width=16)
        self.f_in.pack(side='left', padx=(8, 4), pady=6, ipady=2)
        self.r_in.pack(side='left', padx=4, ipady=2)
        self.cs = Check(self.findbar, T, 'Aa', False, lambda v: self.count_matches(), bg='bg2')
        self.cs.pack(side='left', padx=4)
        Btn(self.findbar, T, '↑', lambda: self.find(-1), size='sm').pack(side='left', padx=2)
        Btn(self.findbar, T, '↓', lambda: self.find(1), size='sm').pack(side='left', padx=2)
        Btn(self.findbar, T, 'Replace', self.replace_one, size='sm').pack(side='left', padx=2)
        Btn(self.findbar, T, 'All', self.replace_all, size='sm').pack(side='left', padx=2)
        self.f_count = tk.Label(self.findbar, font=T.font('sans', 12))
        T.style(self.f_count, bg='bg2', fg='fg2')
        self.f_count.pack(side='left', padx=6)
        Btn(self.findbar, T, '✕', lambda: self.toggle_find(False), kind='ghost', size='sm').pack(side='right', padx=8)
        self.f_in.bind('<KeyRelease>', lambda e: self.count_matches() if e.keysym not in ('Return', 'KP_Enter', 'Escape') else None)
        self.f_in.bind('<Return>', lambda e: (self.find(-1 if e.state & 0x1 else 1), 'break')[1])
        self.f_in.bind('<Escape>', lambda e: (self.toggle_find(False), 'break')[1])
        self.r_in.bind('<Return>', lambda e: (self.replace_one(), 'break')[1])
        self.r_in.bind('<Escape>', lambda e: (self.toggle_find(False), 'break')[1])

        self.status = tk.Frame(body, bd=0)
        T.style(self.status, bg='bg2')
        self.status.pack(fill='x', side='bottom')
        self.st_l = tk.Label(self.status, anchor='w', font=T.font('sans', 12))
        self.st_r = tk.Label(self.status, anchor='e', font=T.font('sans', 12))
        for w in (self.st_l, self.st_r):
            T.style(w, bg='bg2', fg='fg2')
        self.st_l.pack(side='left', padx=12, pady=4)
        self.st_r.pack(side='right', padx=12, pady=4)

        self.cons = tk.Text(body, height=7, bd=0, highlightthickness=0, padx=10, pady=6, font=T.font('mono', 12),
                            wrap='char', state='disabled')
        T.on(self.cons, lambda: (self.cons.configure(bg=T['bg0'], fg=T['fg'], selectbackground=T['acc'],
                                                    selectforeground=T['acc_fg']),
                                 self.cons.tag_configure('e', foreground=T['red']),
                                 self.cons.tag_configure('w', foreground=T['warn']),
                                 self.cons.tag_configure('dm', foreground=T['dim'])))
        self.cons_bar = tk.Frame(body, bd=0)
        T.style(self.cons_bar, bg='bg2')
        cl = tk.Label(self.cons_bar, text='Console', font=T.font('sans', 12, 'bold'))
        T.style(cl, bg='bg2', fg='fg')
        cl.pack(side='left', padx=10, pady=3)
        Btn(self.cons_bar, T, '✕', lambda: self.show_cons(False), kind='ghost', size='sm').pack(side='right', padx=(2, 8))
        Btn(self.cons_bar, T, 'Clear', self.clear_cons, kind='ghost', size='sm').pack(side='right', padx=2)

        self.ed = tk.Frame(body, bd=0)
        T.style(self.ed, bg='bg0')
        self.ed.pack(fill='both', expand=True)
        self.gut = tk.Canvas(self.ed, width=46, bd=0, highlightthickness=0)
        T.style(self.gut, bg='bg1')
        self.gut.pack(side='left', fill='y')
        gedge = tk.Frame(self.ed, width=1, bd=0)
        T.style(gedge, bg='line')
        gedge.pack(side='left', fill='y')
        self.vbar = tk.Scrollbar(self.ed, orient='vertical', width=bar_width(), bd=0, highlightthickness=0)
        self.hbar = tk.Scrollbar(self.ed, orient='horizontal', width=bar_width(), bd=0, highlightthickness=0)
        for sb in (self.vbar, self.hbar):
            T.on(sb, lambda sb=sb: sb.configure(bg=T['bg3'], troughcolor=T['bg0'], activebackground=T['hover']))
        mono = T.font('mono', 13)
        self.text = tk.Text(self.ed, wrap='none', undo=True, maxundo=-1, bd=0, highlightthickness=0, padx=12, pady=10,
                            width=1, height=1,
                            font=mono, tabs=(mono.measure(TAB),), spacing1=2, spacing3=2)

        def paint_text():
            t = self.text
            t.configure(bg=T['bg0'], fg=T['fg'], insertbackground=T['acc'], selectbackground=T['acc_soft'],
                        selectforeground=T['fg'], inactiveselectbackground=T['acc_soft'])
            for c in 'ksncfta':
                t.tag_configure('tk_' + c, foreground=T['tk_' + c])
            t.tag_configure('tk_c', font=T.font('mono', 13, slant='italic'))
            t.tag_configure('found', background=T['acc_soft2'])
            self.redraw_gutter()
        T.on(self.text, paint_text)
        self.vbar.configure(command=self._yview)
        self.hbar.configure(command=self.text.xview)
        self.text.configure(yscrollcommand=self._yscroll, xscrollcommand=self.hbar.set)
        self.vbar.pack(side='right', fill='y')
        self.hbar.pack(side='bottom', fill='x')
        self.text.pack(side='left', fill='both', expand=True)
        self.pv = None

        t = self.text
        t.bind('<<Modified>>', self._modified)
        t.bind('<KeyPress>', self._key)
        for seq in ('<KeyRelease>', '<ButtonRelease-1>', '<<Selection>>'):
            t.bind(seq, lambda e: self.pos(), add='+')
        t.bind('<Configure>', lambda e: self.redraw_gutter(), add='+')
        bind_mod(t, 's', lambda e: self.save_doc() and os_.toast('Saved', '💾'))
        bind_mod(t, 'Return', lambda e: self.run())
        bind_mod(t, 'f', lambda e: self.toggle_find(True))
        bind_mod(t, 'slash', lambda e: self.toggle_comment())
        bind_mod(t, 'd', lambda e: self.dup_line())
        t.bind('<Tab>', lambda e: (self.indent(False), 'break')[1])
        t.bind('<Shift-Tab>', lambda e: (self.indent(True), 'break')[1])
        t.bind('<ISO_Left_Tab>', lambda e: (self.indent(True), 'break')[1])

        self.off = os_.bus.on('fs', self._fs_changed)
        arg = ctx.arg or {}
        if arg.get('file'):
            self.open_file(arg['file'])
        if not self.docs:
            self.add_doc({'name': 'untitled.js', 'text': '// Write JavaScript here and press ▶ Run\nconsole.log("Hello, Quill!");\n',
                          'saved': ''})
        os_.root.after(30, self.text.focus_set)
        self.inst = Inst(on_arg=self.on_arg, before_close=self.before_close, on_close=self.on_close,
                         on_focus=lambda: self.text.focus_set(), on_resize=self.redraw_gutter,
                         mem=lambda: sum(len(d['text']) * 3 for d in self.docs) + 80000)

    def _sep(self, bar):
        s = tk.Frame(bar, width=1, height=20, bd=0)
        self.T.style(s, bg='line')
        s.pack(side='left', padx=6)

    # ---------------------------------------------------------- documents
    def D(self):
        return self.docs[self.cur] if 0 <= self.cur < len(self.docs) else None

    @staticmethod
    def is_dirty(d):
        return d['text'] != d['saved']

    def value(self):
        return self.text.get('1.0', 'end-1c')

    def stash(self):
        d = self.D()
        if d is not None:
            d['text'] = self.value()
            d['ins'] = self.text.index('insert')
            d['scr'] = (self.text.yview()[0], self.text.xview()[0])

    def switch_to(self, i):
        self.stash()
        self.cur = i
        d = self.D()
        self._loading = True
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', d['text'])
        self.text.edit_reset()
        self.text.edit_modified(False)
        self._loading = False
        self.text.mark_set('insert', d.get('ins', '1.0'))
        y, x = d.get('scr', (0, 0))
        self.text.yview_moveto(y)
        self.text.xview_moveto(x)
        self.highlight_now()
        self.pos()
        self.render_tabs()
        self.text.focus_set()

    def add_doc(self, o):
        if o.get('fid'):
            for i, d in enumerate(self.docs):
                if d['fid'] == o['fid']:
                    self.switch_to(i)
                    return
        d = {'fid': None, 'name': 'untitled.js', 'text': '', 'saved': ''}
        d.update(o)
        d['lang'] = lang_of(d['name'])
        self.docs.append(d)
        self.switch_to(len(self.docs) - 1)

    def open_file(self, fid):
        n = self.fs.get(fid)
        if n is None or n['t'] != 'f':
            return
        if n.get('b'):
            self.os.toast('That is a binary file', '⚠️')
            return
        self.add_doc({'fid': fid, 'name': n['n'], 'text': n.get('c') or '', 'saved': n.get('c') or ''})

    def open_picker(self):
        fid = self.os.dialogs.pick_file(lambda n: kind_of(n) == 'text', 'Open a file')
        if fid:
            self.open_file(fid)

    def save_doc(self, d=None):
        if d is None:
            self.stash()
            d = self.D()
        if d is None:
            return False
        n = self.fs.get(d['fid']) if d['fid'] else None
        if n is not None and not n.get('x'):
            self.fs.write(d['fid'], d['text'])
            d['saved'] = d['text']
            d['name'] = n['n']
            d['lang'] = lang_of(d['name'])
            self.render_tabs()
            self.highlight_now()
            self.pos()
            return True
        v = self.os.dialogs.prompt('Save as', d['name'], text='It will be saved in Projects.', ok='Save',
                                   validate=self.os.valid_name)
        if v is None:
            return False
        n = self.fs.mk(FIXED['projects'], v.strip(), 'f', d['text'])
        d['fid'] = n['id']
        d['saved'] = d['text']
        d['name'] = n['n']
        d['lang'] = lang_of(n['n'])
        self.render_tabs()
        self.highlight_now()
        self.pos()
        self.os.toast('Saved ' + n['n'], '💾')
        return True

    def close_doc(self, i):
        self.stash()
        d = self.docs[i]
        if self.is_dirty(d) and not (d['fid'] is None and not d['text'].strip()):
            v = self.os.dialogs.choose('Save changes?', '“' + d['name'] + '” has unsaved changes.',
                                       [('Save', 's', 'pri'), ('Discard', 'd', 'dng'), ('Cancel', 'c', 'btn')])
            if v == 's':
                if not self.save_doc(d):
                    return
            elif v != 'd':
                return
        if d not in self.docs:
            return
        idx = self.docs.index(d)
        was = self.cur
        self.docs.pop(idx)
        if not self.docs:
            self.cur = -1
            self.add_doc({'name': 'untitled.js'})
            return
        nc = was - 1 if was > idx else was
        nc = min(nc, len(self.docs) - 1)
        self.cur = -1
        self.switch_to(nc)

    def render_tabs(self):
        T = self.T
        for c in self.tabs.winfo_children():
            c.destroy()
        row = tk.Frame(self.tabs, bd=0)
        T.style(row, bg='bg2')
        row.pack(side='left', padx=6, pady=(4, 0))
        for i, d in enumerate(self.docs):
            on = i == self.cur
            bg = T['bg1'] if on else T['bg2']
            cell = tk.Frame(row, bd=0, bg=bg)
            topline = tk.Frame(cell, height=2, bd=0, bg=T['acc'] if on else bg)
            topline.pack(fill='x')
            inner = tk.Frame(cell, bd=0, bg=bg)
            inner.pack()
            lbl = tk.Label(inner, text=d['name'] + (' •' if self.is_dirty(d) else ''), bg=bg, fg=T['fg'] if on else T['fg2'],
                           font=T.font('sans', 13), padx=10, pady=5, cursor='hand2')
            lbl.pack(side='left')
            x = tk.Label(inner, text='✕', bg=bg, fg=T['fg2'], font=T.font('sans', 10), cursor='hand2', padx=4)
            x.pack(side='left', padx=(0, 6))
            for w in (cell, inner, lbl):
                w.bind('<Button-1>', lambda e, i=i: self.switch_to(i))
                w.bind('<Button-2>', lambda e, i=i: self.close_doc(i))
            x.bind('<Button-1>', lambda e, i=i: self.close_doc(i))
            cell.pack(side='left', padx=(0, 2))
        d = self.D()
        self.ctx.set_title('Glyph' + (' — ' + d['name'] + (' •' if self.is_dirty(d) else '') if d else ''))

    # ---------------------------------------------------------- display
    def _yscroll(self, a, b):
        self.vbar.set(a, b)
        self.redraw_gutter()

    def _yview(self, *args):
        self.text.yview(*args)
        self.redraw_gutter()

    def redraw_gutter(self):
        T = self.T
        g = self.gut
        g.delete('all')
        t = self.text
        try:
            idx = t.index('@0,0')
        except tk.TclError:
            return
        font = T.font('mono', 13)
        last = int(t.index('end-1c').split('.')[0])
        width = max(46, font.measure(str(last)) + 20)
        if int(g.cget('width')) != width:
            g.configure(width=width)
        while True:
            info = t.dlineinfo(idx)
            if info is None:
                break
            y = info[1]
            ln = idx.split('.')[0]
            g.create_text(width - 8, y + info[3] / 2 + 1, text=ln, anchor='e', fill=T['fg2'], font=font)
            nxt = t.index('%s+1line' % idx)
            if nxt == idx:
                break
            idx = nxt

    def highlight_now(self):
        self._hl_job = None
        d = self.D()
        t = self.text
        v = self.value()
        for c in 'ksncfta':
            t.tag_remove('tk_' + c, '1.0', 'end')
        if d is None:
            return
        line_starts = [0]
        for m in re.finditer('\n', v):
            line_starts.append(m.end())
        import bisect

        def ix(off):
            ln = bisect.bisect_right(line_starts, off) - 1
            return '%d.%d' % (ln + 1, tk_len(v[line_starts[ln]:off]))
        for a, b, cls in spans(v, d['lang']):
            t.tag_add('tk_' + cls, ix(a), ix(b))
        self.redraw_gutter()

    def highlight_soon(self):
        if self._hl_job:
            self.os.root.after_cancel(self._hl_job)
        self._hl_job = self.os.root.after(120, self.highlight_now)

    def pos(self):
        d = self.D()
        if d is None:
            return
        t = self.text
        ln, col = t.index('insert').split('.')
        txt = 'Ln %s, Col %d' % (ln, int(col) + 1)
        try:
            n = len(t.get('sel.first', 'sel.last'))
            if n:
                txt += ' (%d selected)' % n
        except tk.TclError:
            pass
        self.st_l.configure(text=txt)
        self.st_r.configure(text=LANG_NAMES.get(d['lang'], 'Plain text') + ' · %d chars' % len(d['text']) +
                            ('' if d['fid'] else ' · unsaved file'))

    def _modified(self, _e=None):
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        if self._loading:
            return
        d = self.D()
        if d is None:
            return
        was = self.is_dirty(d)
        d['text'] = self.value()
        self.highlight_soon()
        self.pos()
        if was != self.is_dirty(d):
            self.render_tabs()
        if self.find_open:
            self.count_matches()

    # ---------------------------------------------------------- editing helpers
    def _sel(self):
        v = self.value()
        t = self.text
        try:
            s = index_to_off(t, v, 'sel.first')
            e = index_to_off(t, v, 'sel.last')
        except tk.TclError:
            s = e = index_to_off(t, v, 'insert')
        return v, s, e

    def replace(self, v, a, b, new, sel_a, sel_b=None):
        """Replace v[a:b] with new (one undo step) and select sel_a…sel_b (offsets in the new text)."""
        t = self.text
        t.edit_separator()
        ia, ib = off_to_index(v, a), off_to_index(v, b)
        if b > a:
            t.delete(ia, ib)
        if new:
            t.insert(ia, new)
        t.edit_separator()
        nv = v[:a] + new + v[b:]
        t.tag_remove('sel', '1.0', 'end')
        if sel_b is not None and sel_b != sel_a:
            t.tag_add('sel', off_to_index(nv, sel_a), off_to_index(nv, sel_b))
        t.mark_set('insert', off_to_index(nv, sel_b if sel_b is not None else sel_a))
        t.see('insert')
        self.pos()

    def _key(self, e):
        ws = self.text.tk.call('tk', 'windowingsystem')
        if e.state & 0x4 or (e.state & 0x8 and ws == 'aqua'):      # Ctrl, or Command on macOS
            return None
        k = e.char
        ks = e.keysym
        if ks in ('Return', 'KP_Enter') and not (e.state & 0x1):
            v, s, en = self._sel()
            a = v.rfind('\n', 0, s) + 1
            indent = re.match(r'[ \t]*', v[a:s]).group(0)
            prev = v[s - 1] if s > 0 else ''
            nxt = v[en] if en < len(v) else ''
            if prev in '{[(' and prev and PAIRS.get(prev) == nxt:
                ins = '\n' + indent + TAB + '\n' + indent
                self.replace(v, s, en, ins, s + 1 + len(indent) + len(TAB))
            else:
                extra = TAB if re.search(r'[{\[(:]\s*$', v[a:s]) else ''
                ins = '\n' + indent + extra
                self.replace(v, s, en, ins, s + len(ins))
            return 'break'
        if ks == 'BackSpace':
            v, s, en = self._sel()
            if s == en and s > 0 and en < len(v) and PAIRS.get(v[s - 1]) == v[s]:
                self.replace(v, s - 1, s + 1, '', s - 1)
                return 'break'
            return None
        if e.state & 0x20000 or (e.state & 0x8 and ws == 'x11'):    # Alt (on Windows 0x8 is Num Lock)
            return None
        if len(k) != 1 or ord(k) < 32:
            return None
        v, s, en = self._sel()
        if k in PAIRS and s != en:
            sel = v[s:en]
            self.replace(v, s, en, k + sel + PAIRS[k], s + 1, en + 1)
            return 'break'
        if k in PAIRS and s == en and not re.match(r'\w', v[s] if s < len(v) else ''):
            if k in ('"', "'", '`') and ((s < len(v) and v[s] == k) or re.match(r'\w', v[s - 1] if s > 0 else '')):
                if s < len(v) and v[s] == k:
                    self.text.mark_set('insert', off_to_index(v, s + 1))
                    self.pos()
                    return 'break'
                return None
            self.replace(v, s, en, k + PAIRS[k], s + 1)
            return 'break'
        if k in ')]}' and s == en and s < len(v) and v[s] == k:
            self.text.mark_set('insert', off_to_index(v, s + 1))
            self.pos()
            return 'break'
        return None

    def indent(self, outdent):
        v, s, en = self._sel()
        if (s != en and '\n' in v[s:en]) or outdent:
            a = v.rfind('\n', 0, s) + 1
            seg = v[a:en]
            lines = seg.split('\n')
            if outdent:
                out = [re.sub(r'^( {1,%d}|\t)' % len(TAB), '', l) for l in lines]
            else:
                out = [TAB + l for l in lines]
            r = '\n'.join(out)
            self.replace(v, a, en, r, a, a + len(r))
        else:
            self.replace(v, s, en, TAB, s + len(TAB))

    def toggle_comment(self):
        d = self.D()
        v, s, en = self._sel()
        a = v.rfind('\n', 0, s) + 1
        b = v.find('\n', max(s, en - (1 if en > s and v[en - 1] == '\n' else 0)))
        b = len(v) if b < 0 else b
        mark = {'css': ('/* ', ' */'), 'html': ('<!-- ', ' -->'), 'qsh': ('# ', ''), 'py': ('# ', '')}.get(d['lang'], ('// ', ''))
        lines = v[a:b].split('\n')
        allc = all(not l.strip() or l.strip().startswith(mark[0].strip()) for l in lines)
        out = []
        for l in lines:
            if not l.strip():
                out.append(l)
            elif allc:
                l2 = l.replace(mark[0], '', 1) if mark[0] in l else l.replace(mark[0].strip(), '', 1)
                if mark[1] and l2.endswith(mark[1]):
                    l2 = l2[:-len(mark[1])]
                out.append(l2)
            else:
                ind = re.match(r'\s*', l).group(0)
                out.append(ind + mark[0] + l[len(ind):] + mark[1])
        r = '\n'.join(out)
        self.replace(v, a, b, r, a, a + len(r))

    def dup_line(self):
        v, s, en = self._sel()
        a = v.rfind('\n', 0, s) + 1
        b = v.find('\n', en)
        b = len(v) if b < 0 else b
        line = v[a:b]
        self.replace(v, b, b, '\n' + line, en + len(line) + 1)

    # ---------------------------------------------------------- find and replace
    def matches(self):
        q = self.f_in.get()
        if not q:
            return []
        v = self.value()
        hay, nd = (v, q) if self.cs.get() else (v.lower(), q.lower())
        out, i = [], 0
        while len(out) < 5000:
            i = hay.find(nd, i)
            if i < 0:
                break
            out.append(i)
            i += max(1, len(nd))
        return out

    def count_matches(self):
        m = self.matches()
        self.f_count.configure(text=('%d %s' % (len(m), 'match' if len(m) == 1 else 'matches')) if self.f_in.get() else '')
        t = self.text
        t.tag_remove('found', '1.0', 'end')
        v = self.value()
        q = len(self.f_in.get())
        for i in m[:2000]:
            t.tag_add('found', off_to_index(v, i), off_to_index(v, i + q))
        return m

    def reveal(self, i, n):
        v = self.value()
        t = self.text
        t.tag_remove('sel', '1.0', 'end')
        t.tag_add('sel', off_to_index(v, i), off_to_index(v, i + n))
        t.mark_set('insert', off_to_index(v, i + n))
        t.see(off_to_index(v, i))
        t.focus_set()
        self.pos()

    def find(self, direction):
        m = self.count_matches()
        if not m:
            return
        v, s, en = self._sel()
        if direction > 0:
            idx = next((x for x in m if x >= en), m[0])
        else:
            idx = next((x for x in reversed(m) if x < s), m[-1])
        self.reveal(idx, len(self.f_in.get()))

    def replace_one(self):
        q = self.f_in.get()
        if not q:
            return
        v, s, en = self._sel()
        sel = v[s:en]
        if (sel if self.cs.get() else sel.lower()) == (q if self.cs.get() else q.lower()) and en > s:
            rep = self.r_in.get()
            self.replace(v, s, en, rep, s + len(rep))
        self.find(1)

    def replace_all(self):
        q = self.f_in.get()
        if not q:
            return
        m = self.matches()
        if not m:
            return
        v = self.value()
        rep = self.r_in.get()
        out, last = [], 0
        for i in m:
            out.append(v[last:i] + rep)
            last = i + len(q)
        out.append(v[last:])
        self.replace(v, 0, len(v), ''.join(out), 0)
        self.os.toast('Replaced %d' % len(m), '🔍')

    def toggle_find(self, on=None):
        self.find_open = (not self.find_open) if on is None else bool(on)
        if self.find_open:
            self.findbar.pack(fill='x', after=self.tabs_line)
            try:
                sel = self.text.get('sel.first', 'sel.last')
                if sel and '\n' not in sel:
                    self.f_in.set(sel)
            except tk.TclError:
                pass
            self.count_matches()
            self.f_in.focus_set()
            self.f_in.select_range(0, 'end')
        else:
            self.findbar.pack_forget()
            self.text.tag_remove('found', '1.0', 'end')
            self.text.focus_set()

    # ---------------------------------------------------------- console and running
    def show_cons(self, on):
        if on:
            if not self.cons.winfo_ismapped():
                # bottom-packed widgets stack upwards: status, then console, then its bar
                self.cons.pack(fill='x', side='bottom', after=self.status)
                self.cons_bar.pack(fill='x', side='bottom', after=self.cons)
        else:
            self.cons.pack_forget()
            self.cons_bar.pack_forget()

    def clear_cons(self):
        self.cons.configure(state='normal')
        self.cons.delete('1.0', 'end')
        self.cons.configure(state='disabled')

    def line(self, cls, text):
        c = self.cons
        c.configure(state='normal')
        c.insert('end', text + '\n', (cls,) if cls else ())
        lines = int(c.index('end-1c').split('.')[0])
        if lines > 500:
            c.delete('1.0', '%d.0' % (lines - 500))
        c.configure(state='disabled')
        c.see('end')

    def set_running(self, on):
        self.b_stop.set_disabled(not on)
        self.b_run.set_disabled(on)

    def stop(self):
        if self.runner is not None:
            self.runner.stop()

    def run(self):
        self.stash()
        d = self.D()
        if d is None:
            return
        if self.runner is not None:
            self.runner.stop()
            self.runner = None
        if d['lang'] == 'html':
            fd, path = tempfile.mkstemp(prefix='quill-preview-', suffix='.html')
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(d['text'])
            webbrowser.open(pathlib.Path(path).as_uri())
            self.os.toast('Preview opened in your browser', '🌐')
            return
        if d['name'].lower().endswith('.json'):
            self.show_cons(True)
            try:
                json.loads(d['text'])
                self.line('', '✔ Valid JSON.')
            except ValueError as err:
                self.line('e', '✖ ' + str(err))
            return
        if d['lang'] == 'qsh':
            if not self.save_doc(d):
                return
            self.os.wm.open('term', {'cmd': 'sh ' + self.fs.path(d['fid'])})
            return
        if d['lang'] not in ('js', 'py'):
            self.os.toast('Nothing to run for “' + (ext_of(d['name']) or 'this') +
                          '” files — try .js, .py, .html, .json or .qsh', 'ℹ️')
            return
        self.show_cons(True)
        self.clear_cons()
        self.line('dm', '▶ Running ' + d['name'] + '…')
        self.set_running(True)
        t0 = time.perf_counter()

        def cb(kind, text=''):
            if not self.ctx.alive:
                return
            if kind in ('log', 'info'):
                self.line('', text)
            elif kind == 'warn':
                self.line('w', text)
            elif kind == 'error':
                self.line('e', text)
            elif kind == 'done':
                self.line('dm', '✔ Finished in %d ms' % round((time.perf_counter() - t0) * 1000))
            elif kind == 'end':
                self.set_running(False)
                self.runner = None
                if text == 'stopped' or text.startswith('time'):
                    self.line('w', '■ Stopped (' + text + ')')
        self.runner = self.os.run_code(d['text'], d['lang'], cb)

    def format_json(self):
        self.stash()
        d = self.D()
        if d is None:
            return
        if not d['name'].lower().endswith('.json'):
            self.os.toast('Format works on .json files', 'ℹ️')
            return
        try:
            t = json.dumps(json.loads(d['text']), indent=2, ensure_ascii=False) + '\n'
            v = self.value()
            self.replace(v, 0, len(v), t, 0)
            self.os.toast('Formatted', '✨')
        except ValueError as err:
            self.show_cons(True)
            self.line('e', '✖ ' + str(err))

    # ---------------------------------------------------------- window life
    def _fs_changed(self, _a=None):
        if not self.ctx.alive:
            return
        for d in self.docs:
            n = self.fs.get(d['fid']) if d['fid'] else None
            if n is not None and n['n'] != d['name']:
                d['name'] = n['n']
                d['lang'] = lang_of(d['name'])
        self.render_tabs()

    def on_arg(self, a):
        if not isinstance(a, dict):
            return
        if a.get('file'):
            self.open_file(a['file'])
        elif a.get('fresh'):
            self.add_doc({'name': 'untitled.js'})

    def before_close(self):
        self.stash()
        dirty = [d for d in self.docs if self.is_dirty(d) and not (d['fid'] is None and not d['text'].strip())]
        if not dirty:
            return True
        v = self.os.dialogs.choose('Save changes?', ('“' + dirty[0]['name'] + '” has unsaved changes.') if len(dirty) == 1
                                   else '%d files have unsaved changes.' % len(dirty),
                                   [('Save all', 's', 'pri'), ('Discard', 'd', 'dng'), ('Cancel', 'c', 'btn')])
        if v == 's':
            for d in dirty:
                if not self.save_doc(d):
                    return False
            return True
        return v == 'd'

    def on_close(self):
        if self.runner is not None:
            self.runner.stop()
        self.off()
