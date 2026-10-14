"""Quill Shell — the terminal."""

import tkinter as tk

from .base import AppSpec, Inst
from .. import shell
from ..ui.widgets import bar_width


class App(AppSpec):
    id = 'term'
    name = 'Quill Shell'
    icon = '❯_'
    bg = ('#3b4252', '#12151c')
    w, h = 740, 460
    kw = 'terminal shell console command line qsh bash cli'
    about = 'Command line'

    def build(self, ctx):
        return Terminal(ctx).inst


class Terminal:
    def __init__(self, ctx):
        self.ctx = ctx
        os_ = self.os = ctx.os
        T = self.T = ctx.T
        S = os_.S
        user = (S['user']['name'] or os_.me or 'guest').replace(' ', '_').replace('\t', '_')
        self.sh = shell.Session(os_, user, printer=self.print, clearer=self.clear, closer=ctx.close)
        self.hi = -1
        self.draft = ''
        self.busy = False
        body = ctx.body
        wrap = tk.Frame(body, bd=0)
        T.on(wrap, lambda: wrap.configure(bg=T['term_bg']))
        wrap.pack(fill='both', expand=True)
        mono = T.font('mono', 13)
        self.out = tk.Text(wrap, bd=0, highlightthickness=0, padx=12, pady=10, font=mono, wrap='char', cursor='xterm',
                           width=1, height=1,
                           state='disabled', spacing1=1, spacing3=1)
        bar = tk.Scrollbar(wrap, orient='vertical', command=self.out.yview, width=bar_width(), bd=0, highlightthickness=0)
        self.out.configure(yscrollcommand=bar.set)

        def paint():
            self.out.configure(bg=T['term_bg'], fg=T['term_fg'], selectbackground=T['acc'], selectforeground=T['acc_fg'],
                               inactiveselectbackground=T['acc_soft'])
            for tag, col in (('pr', T['acc']), ('er', T['red']), ('ok', T['ok']), ('dm', T['dim']), ('bl', T['blue']),
                             ('w', T['warn'])):
                self.out.tag_configure(tag, foreground=col)
            bar.configure(bg=T['bg3'], troughcolor=T['term_bg'], activebackground=T['hover'])
        T.on(self.out, paint)
        row = tk.Frame(wrap, bd=0)
        T.on(row, lambda: row.configure(bg=T['term_bg']))
        row.pack(side='bottom', fill='x', padx=12, pady=(0, 10))
        bar.pack(side='right', fill='y')
        self.out.pack(side='left', fill='both', expand=True)
        self.prompt = tk.Text(row, height=1, bd=0, highlightthickness=0, font=mono, width=1, wrap='none', state='disabled',
                              cursor='arrow', takefocus=0)
        self.inp = tk.Entry(row, bd=0, highlightthickness=0, relief='flat', font=mono)
        T.on(self.inp, lambda: (
            self.inp.configure(bg=T['term_bg'], fg=T['term_fg'], insertbackground=T['acc'], selectbackground=T['acc'],
                               selectforeground=T['acc_fg']),
            self.prompt.configure(bg=T['term_bg'], fg=T['term_fg']),
            self.prompt.tag_configure('pr', foreground=T['acc']),
            self.prompt.tag_configure('dm', foreground=T['dim']),
            self.prompt.tag_configure('bl', foreground=T['blue'])))
        self.prompt.pack(side='left')
        self.inp.pack(side='left', fill='x', expand=True)
        self.row = row
        i = self.inp
        i.bind('<Return>', self._enter)
        i.bind('<KP_Enter>', self._enter)
        i.bind('<Tab>', self._tab)
        i.bind('<Up>', self._up)
        i.bind('<Down>', self._down)
        i.bind('<Control-l>', lambda e: (self.clear(), 'break')[1])
        i.bind('<Control-L>', lambda e: (self.clear(), 'break')[1])
        i.bind('<Control-c>', self._ctrl_c)
        i.bind('<Control-C>', self._ctrl_c)
        i.bind('<Control-d>', self._ctrl_d)
        self.out.bind('<ButtonRelease-1>', self._click_out)
        wrap.bind('<Button-1>', lambda e: self.inp.focus_set())
        self.set_prompt()
        self.print(shell.sty('pr', 'Quill shell') + ' — type ' + shell.sty('bl', 'help') + ' for commands, ' +
                   shell.sty('bl', 'neofetch') + ' for a summary.')
        ctx.set_title('Quill Shell')
        self.inst = Inst(on_arg=self.on_arg, on_focus=lambda: self.inp.focus_set(), on_close=self.on_close,
                         mem=lambda: int(self.out.index('end-1c').split('.')[0]) * 400 + 70000)
        self.sh.inst = self.inst
        arg = ctx.arg or {}
        if arg.get('cmd'):
            os_.root.after(50, lambda: self.submit(arg['cmd']))
        os_.root.after(30, self.inp.focus_set)

    # ---------------------------------------------------------- output
    def disp_path(self):
        p = self.os.fs.path(self.sh.cwd) or '/'
        return '~' if p == '/' else '~' + p

    def prompt_parts(self):
        return [(self.sh.env['USER'] + '@quill', 'pr'), (':', 'dm'), (self.disp_path(), 'bl'), ('$ ', 'dm')]

    def set_prompt(self):
        p = self.prompt
        p.configure(state='normal')
        p.delete('1.0', 'end')
        width = 0
        for text, tag in self.prompt_parts():
            p.insert('end', text, (tag,))
            width += len(text)
        p.configure(width=width, state='disabled')

    def print(self, text, cls=None):
        if not self.ctx.alive:
            return
        o = self.out
        o.configure(state='normal')
        base = ('w',) if cls == 'w' else ((cls,) if cls else ())
        for part, tag in shell.styled_parts(str(text)):
            tags = base + ((tag,) if tag and tag != 'dm0' else ())
            o.insert('end', part, tags)
        o.insert('end', '\n', base)
        lines = int(o.index('end-1c').split('.')[0])
        if lines > 800:
            o.delete('1.0', '%d.0' % (lines - 800))
        o.configure(state='disabled')
        o.see('end')

    def clear(self):
        self.out.configure(state='normal')
        self.out.delete('1.0', 'end')
        self.out.configure(state='disabled')

    # ---------------------------------------------------------- input
    def submit(self, line):
        o = self.out
        o.configure(state='normal')
        for text, tag in self.prompt_parts():
            o.insert('end', text, (tag,))
        o.insert('end', line + '\n')
        o.configure(state='disabled')
        o.see('end')
        hist = self.os.S['hist']
        if line.strip() and (not hist or hist[-1] != line):
            hist.append(line)
            if len(hist) > 200:
                hist.pop(0)
            self.os.touch()
        self.hi = -1
        self.busy = True
        self.sh.aborted = False
        self.inp.configure(state='disabled')
        try:
            if line.strip():
                shell.execute(self.sh, line)
        except Exception as e:
            self.print(str(e), 'er')
        self.busy = False
        if not self.ctx.alive:
            return
        self.inp.configure(state='normal')
        self.set_prompt()
        o.see('end')
        if self.os.wm.active is self.ctx.win:
            self.inp.focus_set()

    def _enter(self, _e):
        if self.busy:
            return 'break'
        line = self.inp.get()
        self.inp.delete(0, 'end')
        self.submit(line)
        return 'break'

    def _tab(self, _e):
        if self.busy:
            return 'break'
        nv, info = shell.complete(self.sh, self.inp.get(), self.inp.index('insert'))
        if nv is not None:
            self.inp.delete(0, 'end')
            self.inp.insert(0, nv)
            self.inp.icursor(info)
        elif info:
            self.print('  '.join(x if not x.endswith('/') else shell.sty('bl', x) for x in info))
        return 'break'

    def _up(self, _e):
        hist = self.os.S['hist']
        if not hist:
            return 'break'
        if self.hi < 0:
            self.draft = self.inp.get()
            self.hi = len(hist)
        self.hi = max(0, self.hi - 1)
        self._set_input(hist[self.hi])
        return 'break'

    def _down(self, _e):
        hist = self.os.S['hist']
        if self.hi < 0:
            return 'break'
        self.hi += 1
        if self.hi >= len(hist):
            self.hi = -1
            self._set_input(self.draft)
        else:
            self._set_input(hist[self.hi])
        return 'break'

    def _set_input(self, v):
        self.inp.delete(0, 'end')
        self.inp.insert(0, v)
        self.inp.icursor('end')

    def _ctrl_c(self, _e):
        if self.busy:
            self.sh.aborted = True
            if self.sh.cancel:
                self.sh.cancel()
            self.print('^C', 'dm')
        else:
            if self.inp.selection_present():
                return None   # copy the selected text as usual
            self.print(''.join(t for t, _ in self.prompt_parts()) + self.inp.get() + '^C', 'dm')
            self.inp.delete(0, 'end')
        return 'break'

    def _ctrl_d(self, _e):
        if not self.inp.get():
            self.ctx.close()
            return 'break'
        return None

    def _click_out(self, _e):
        try:
            self.out.get('sel.first', 'sel.last')
        except tk.TclError:
            self.inp.focus_set()

    def on_arg(self, a):
        if isinstance(a, dict) and a.get('cmd') and not self.busy:
            self.submit(a['cmd'])

    def on_close(self):
        self.sh.aborted = True
        if self.sh.cancel:
            self.sh.cancel()
