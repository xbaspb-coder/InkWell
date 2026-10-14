"""Abacus — calculator."""

import math
import re
import tkinter as tk

from .base import AppSpec, Inst
from .scribe import bind_mod
from ..calc import CalcError, calc_eval, fmt_num
from ..ui.widgets import Btn


class App(AppSpec):
    id = 'calc'
    name = 'Abacus'
    icon = '÷'
    bg = ('#ff9a62', '#d4502c')
    w, h = 520, 520
    kw = 'calculator maths math scientific sum'
    about = 'Calculator'

    def build(self, ctx):
        return Abacus(ctx).inst


class Key(tk.Label):
    """A calculator key: kinds '', 'op', 'eq', 'fn'."""

    def __init__(self, parent, T, label, fn, kind=''):
        super().__init__(parent, text=label, bd=0, highlightthickness=1, cursor='hand2',
                         font=T.font('sans', 14 if kind == 'fn' else 17, 'bold' if kind == 'eq' else 'normal'))
        self.T, self.kind, self.fn = T, kind, fn
        self.hover = False
        T.on(self, self.paint)
        self.bind('<Enter>', lambda e: self._h(True))
        self.bind('<Leave>', lambda e: self._h(False))
        self.bind('<ButtonRelease-1>', lambda e: fn() if 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height() else None)

    def _h(self, v):
        self.hover = v
        self.paint()

    def paint(self):
        T = self.T
        if self.kind == 'eq':
            bg, fg, line = T['acc'], T['acc_fg'], T['acc']
        elif self.kind == 'op':
            bg, fg, line = T['bg3'], T['acc'], T['line']
        else:
            bg, fg, line = T['bg2'], T['fg2'] if self.kind == 'fn' else T['fg'], T['line']
        if self.hover:
            bg = T['acc_hover'] if self.kind == 'eq' else T['bg3'] if self.kind != 'op' else T['hover']
        self.configure(bg=bg, fg=fg, highlightbackground=line)


class Abacus:
    def __init__(self, ctx):
        self.ctx = ctx
        os_ = self.os = ctx.os
        T = self.T = ctx.T
        self.expr = ''
        self.ans = None
        self.deg = False
        self.sci = False
        self.just_eq = False
        self.hist = []
        root = tk.Frame(ctx.body, bd=0, takefocus=1)
        T.style(root, bg='bg1')
        root.pack(fill='both', expand=True)
        self.root = root
        self.tape = tk.Frame(root, bd=0, width=170)
        self.tape.pack_propagate(False)
        T.style(self.tape, bg='bg2')
        self.tape.pack(side='right', fill='y')
        edge = tk.Frame(root, width=1, bd=0)
        T.style(edge, bg='line')
        edge.pack(side='right', fill='y')
        main = tk.Frame(root, bd=0)
        T.style(main, bg='bg1')
        main.pack(side='left', fill='both', expand=True, padx=10, pady=10)
        modes = tk.Frame(main, bd=0)
        T.style(modes, bg='bg1')
        modes.pack(fill='x')
        self.b_sci = Btn(modes, T, 'Scientific', self.toggle_sci, size='sm', bg='bg1')
        self.b_sci.pack(side='left')
        self.b_deg = Btn(modes, T, 'Rad', self.toggle_deg, size='sm', bg='bg1', tip='Angle mode')
        self.b_deg.pack(side='left', padx=6)
        disp = tk.Frame(main, bd=0, highlightthickness=1)
        T.on(disp, lambda: disp.configure(bg=T['bg0'], highlightbackground=T['line']))
        disp.pack(fill='x', pady=8)
        self.ex = tk.Label(disp, text='', anchor='e', font=T.font('mono', 14))
        self.rs = tk.Label(disp, text='0', anchor='e', font=T.font('serif', 34))
        T.style(self.ex, bg='bg0', fg='fg2')
        T.style(self.rs, bg='bg0', fg='fg')
        self.ex.pack(fill='x', padx=14, pady=(12, 0))
        self.rs.pack(fill='x', padx=14, pady=(0, 8))
        pad = tk.Frame(main, bd=0)
        T.style(pad, bg='bg1')
        pad.pack(fill='both', expand=True)
        self.sci_keys = tk.Frame(pad, bd=0, width=210)
        T.style(self.sci_keys, bg='bg1')
        keys = tk.Frame(pad, bd=0)
        T.style(keys, bg='bg1')
        keys.pack(side='left', fill='both', expand=True)
        self.keys = keys
        rows = [('C', self.clear, 'fn'), ('⌫', self.back, 'fn'), ('%', lambda: self.insert('%'), 'fn'), ('÷', lambda: self.insert('÷'), 'op'),
                ('7', None, ''), ('8', None, ''), ('9', None, ''), ('×', lambda: self.insert('×'), 'op'),
                ('4', None, ''), ('5', None, ''), ('6', None, ''), ('−', lambda: self.insert('−'), 'op'),
                ('1', None, ''), ('2', None, ''), ('3', None, ''), ('+', lambda: self.insert('+'), 'op'),
                ('±', self.neg, 'fn'), ('0', None, ''), ('.', None, ''), ('=', self.equals, 'eq')]
        for i, (label, fn, kind) in enumerate(rows):
            fn = fn or (lambda l=label: self.insert(l))
            k = Key(keys, T, label, self._wrap(fn), kind)
            k.grid(row=i // 4, column=i % 4, sticky='nsew', padx=3, pady=3)
        for c in range(4):
            keys.columnconfigure(c, weight=1, uniform='k')
        for r in range(5):
            keys.rowconfigure(r, weight=1, uniform='r')
        sc = [('sin', 'sin('), ('cos', 'cos('), ('tan', 'tan('), ('asin', 'asin('), ('acos', 'acos('), ('atan', 'atan('),
              ('ln', 'ln('), ('log', 'log('), ('√', 'sqrt('), ('(', '('), (')', ')'), ('^', '^'), ('π', 'π'), ('e', 'e'),
              ('n!', '!'), ('x²', '^2'), ('1/x', '^(-1)'), ('Ans', None)]
        for i, (label, t) in enumerate(sc):
            fn = (lambda: self.insert(fmt_num(self.ans)) if self.ans is not None else None) if t is None else \
                (lambda t=t: self.insert(t))
            k = Key(self.sci_keys, T, label, self._wrap(fn), 'fn')
            k.grid(row=i // 3, column=i % 3, sticky='nsew', padx=3, pady=3)
        for c in range(3):
            self.sci_keys.columnconfigure(c, weight=1, uniform='s')
        for r in range(6):
            self.sci_keys.rowconfigure(r, weight=1, uniform='sr')
        self.draw_tape()
        root.bind('<Key>', self._key)
        bind_mod(root, 'v', lambda e: self._paste())
        root.bind('<Button-1>', lambda e: root.focus_set())
        os_.root.after(30, root.focus_set)
        ctx.set_title('Abacus')
        self.inst = Inst(on_focus=lambda: root.focus_set(), mem=lambda: 50000 + len(self.hist) * 200)

    def _wrap(self, fn):
        def run():
            fn()
            self.root.focus_set()
        return run

    def toggle_sci(self):
        self.sci = not self.sci
        if self.sci:
            self.sci_keys.pack(side='left', fill='y', before=self.keys, padx=(0, 6))
            self.sci_keys.pack_propagate(False)
        else:
            self.sci_keys.pack_forget()
        self.b_sci.set_kind('pri' if self.sci else 'btn')

    def toggle_deg(self):
        self.deg = not self.deg
        self.b_deg.set_text('Deg' if self.deg else 'Rad')
        self.preview()

    # ---------------------------------------------------------- logic (same as the original)
    def insert(self, t):
        if self.just_eq:
            if re.match(r'^[0-9.(a-z√π]', t, re.I):
                self.expr = ''
            elif self.ans is not None:
                self.expr = fmt_num(self.ans)
            self.just_eq = False
        self.expr += t
        self.paint()

    def paint(self):
        self.ex.configure(text=self.expr)
        self.preview()

    def preview(self):
        if not self.expr:
            self.rs.configure(text=fmt_num(self.ans) if (self.just_eq and self.ans is not None) else '0',
                              fg=self.T['fg'])
            return
        try:
            v = calc_eval(self.expr, self.deg)
            self.rs.configure(text=fmt_num(v), fg=self.T['fg'] if self.just_eq else self.T['fg2'])
        except CalcError:
            self.rs.configure(text='Error' if self.just_eq else '…', fg=self.T['fg2'])

    def equals(self):
        if not self.expr:
            return
        opens = self.expr.count('(') - self.expr.count(')')
        e = self.expr + ')' * max(0, opens)
        try:
            v = calc_eval(e, self.deg)
            if math.isinf(v) or math.isnan(v):
                raise CalcError('Cannot divide by zero')
            self.hist.insert(0, (e, v))
            del self.hist[40:]
            self.draw_tape()
            self.ans = v
            self.expr = ''
            self.just_eq = True
            self.ex.configure(text=e + ' =')
            self.rs.configure(text=fmt_num(v), fg=self.T['fg'])
        except CalcError as err:
            msg = str(err)
            self.rs.configure(text='Error' if len(msg) > 24 else msg, fg=self.T['fg'])
            self.os.ui_sound('error')

    def draw_tape(self):
        T = self.T
        for c in self.tape.winfo_children():
            c.destroy()
        if not self.hist:
            lbl = tk.Label(self.tape, text='History appears here.', font=T.font('mono', 12), anchor='w')
            T.style(lbl, bg='bg2', fg='fg2')
            lbl.pack(fill='x', padx=8, pady=8)
            return
        for e, v in self.hist:
            row = tk.Label(self.tape, text=e + ' = ' + fmt_num(v), anchor='w', justify='left', wraplength=150,
                           font=T.font('mono', 12), cursor='hand2')
            T.style(row, bg='bg2', fg='fg')
            row.bind('<Enter>', lambda ev, r=row: r.configure(fg=T['acc']))
            row.bind('<Leave>', lambda ev, r=row: r.configure(fg=T['fg']))
            row.bind('<Button-1>', lambda ev, v=v: self._reuse(v))
            row.pack(fill='x', padx=8, pady=(4, 0))
            line = tk.Frame(self.tape, height=1, bd=0)
            T.style(line, bg='line')
            line.pack(fill='x', padx=8, pady=(4, 0))

    def _reuse(self, v):
        self.expr = fmt_num(v)
        self.just_eq = False
        self.paint()

    def clear(self):
        self.expr = ''
        self.just_eq = False
        self.ex.configure(text='')
        self.rs.configure(text='0', fg=self.T['fg'])

    def back(self):
        if self.just_eq:
            self.expr = ''
            self.just_eq = False
            self.paint()
            return
        self.expr = re.sub(r'(sin|cos|tan|asin|acos|atan|sinh|cosh|tanh|sqrt|cbrt|ln|log2|log|exp|abs|fact)\($|.$', '',
                           self.expr, count=1)
        self.paint()

    def neg(self):
        if self.just_eq and self.ans is not None:
            self.expr = fmt_num(-self.ans)
            self.just_eq = False
            self.paint()
            return
        m = re.search(r'(-?[0-9.]+(?:e[+-]?\d+)?)$', self.expr)
        if m:
            num = m.group(1)
            self.expr = self.expr[:m.start()] + (num[1:] if num.startswith('-') else '-' + num)
        else:
            self.expr += '-'
        self.paint()

    def _paste(self):
        try:
            t = self.root.clipboard_get()
        except tk.TclError:
            return
        if t:
            self.expr = t.strip()
            self.just_eq = False
            self.paint()

    def _key(self, e):
        if e.state & 0x4 or e.state & 0x20000:
            return None
        k = e.char
        ks = e.keysym
        if k and re.match(r'^[0-9.]$', k):
            self.insert(k)
        elif k == '+':
            self.insert('+')
        elif k == '-':
            self.insert('−')
        elif k == '*':
            self.insert('×')
        elif k == '/':
            self.insert('÷')
        elif k in ('^', '(', ')', '%', '!'):
            self.insert(k)
        elif ks in ('Return', 'KP_Enter') or k == '=':
            self.equals()
        elif ks == 'BackSpace':
            self.back()
        elif ks == 'Escape' or k in ('c', 'C'):
            self.clear()
        elif k == 'p':
            self.insert('π')
        else:
            return None
        return 'break'
