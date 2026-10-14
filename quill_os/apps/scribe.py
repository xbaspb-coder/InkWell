"""Scribe — notes and Markdown."""

import re
import tkinter as tk

from .base import AppSpec, Inst
from ..core import kind_of
from ..state import FIXED
from ..ui.mdview import make_view, render
from ..ui.widgets import Btn


def mod_keys(widget):
    aqua = widget.tk.call('tk', 'windowingsystem') == 'aqua'
    return ['Control'] + (['Command'] if aqua else [])


def bind_mod(widget, key, fn):
    """Bind Ctrl+key (and Cmd+key on macOS), both letter cases; fn's result decides 'break'."""
    for m in mod_keys(widget):
        for k in {key.lower(), key.upper()} if len(key) == 1 else {key}:
            widget.bind('<%s-%s>' % (m, k), lambda e: (fn(e), 'break')[1])


class App(AppSpec):
    id = 'scribe'
    name = 'Scribe'
    icon = '✒'
    bg = ('#c58cff', '#6d3fb5')
    w, h = 780, 540
    kw = 'notes text editor markdown write document word'
    about = 'Notes and Markdown'

    def build(self, ctx):
        return Scribe(ctx).inst


class Scribe:
    def __init__(self, ctx):
        self.ctx = ctx
        os_ = self.os = ctx.os
        T = self.T = ctx.T
        self.fs = os_.fs
        self.file_id = None
        self.dirty = False
        self.preview = False
        self.saved_text = ''
        body = ctx.body
        bar = tk.Frame(body, bd=0)
        T.style(bar, bg='bg2')
        bar.pack(fill='x')
        sep = tk.Frame(body, height=1, bd=0)
        T.style(sep, bg='line')
        sep.pack(fill='x')
        Btn(bar, T, '＋ New', self.new, size='sm').pack(side='left', padx=(8, 3), pady=6)
        Btn(bar, T, '📂 Open', self.open_picker, size='sm').pack(side='left', padx=3)
        Btn(bar, T, '💾 Save', self.save, kind='pri', size='sm', tip='Save (Ctrl+S)').pack(side='left', padx=3)
        s2 = tk.Frame(bar, width=1, height=20, bd=0)
        T.style(s2, bg='line')
        s2.pack(side='left', padx=6)
        for label, tip, fn, font in (('B', 'Bold', lambda: self.wrap('**', '**'), T.font('sans', 14, 'bold')),
                                     ('I', 'Italic', lambda: self.wrap('*', '*'), T.font('serif', 15, slant='italic')),
                                     ('</>', 'Code', lambda: self.wrap('`', '`'), T.font('mono', 11)),
                                     ('H', 'Heading', lambda: self.line_start('## '), None),
                                     ('•', 'List', lambda: self.line_start('- '), None),
                                     ('❝', 'Quote', lambda: self.line_start('> '), None)):
            Btn(bar, T, label, fn, kind='ibtn', tip=tip, font=font).pack(side='left')
        self.b_prev = Btn(bar, T, '👁 Preview', lambda: self.set_preview(not self.preview), size='sm',
                          tip='Toggle preview (Ctrl+P)')
        self.b_prev.pack(side='right', padx=8)
        self.ed = tk.Frame(body, bd=0)
        T.style(self.ed, bg='bg1')
        self.ed.pack(fill='both', expand=True)
        self.status = tk.Frame(body, bd=0)
        T.style(self.status, bg='bg2')
        self.status.pack(fill='x', side='bottom')
        self.st_l = tk.Label(self.status, anchor='w', font=T.font('sans', 12))
        self.st_r = tk.Label(self.status, anchor='e', font=T.font('sans', 12))
        for w in (self.st_l, self.st_r):
            T.style(w, bg='bg2', fg='fg2')
        self.st_l.pack(side='left', padx=12, pady=4)
        self.st_r.pack(side='right', padx=12, pady=4)
        self.text = tk.Text(self.ed, wrap='word', undo=True, autoseparators=True, maxundo=-1, bd=0, width=1, height=1,
                            highlightthickness=0, padx=22, pady=18, font=T.font('serif', 16), spacing2=4,
                            tabs=(T.font('serif', 16).measure('    '),))
        T.on(self.text, lambda: self.text.configure(
            bg=T['paper'], fg=T['paper_fg'], insertbackground=T['paper_fg'], selectbackground=T['acc'],
            selectforeground=T['acc_fg'], inactiveselectbackground=T['acc_soft']))
        self.prev_frame, self.prev = make_view(os_, self.ed, bg='bg1')
        self.text.pack(side='left', fill='both', expand=True)
        self.text.bind('<<Modified>>', self._modified)
        bind_mod(self.text, 's', lambda e: self.save())
        bind_mod(self.text, 'p', lambda e: self.set_preview(not self.preview))
        bind_mod(self.text, 'b', lambda e: self.wrap('**', '**'))
        bind_mod(self.text, 'i', lambda e: self.wrap('*', '*'))
        self.text.bind('<Tab>', self._tab)
        self._placeholder()
        self.auto = None
        self._schedule_autosave()
        self.off = os_.bus.on('fs', self._fs_changed)
        arg = ctx.arg or {}
        if arg.get('file'):
            self.load(arg['file'])
        else:
            self.title()
            self.stats()
        os_.root.after(30, self.text.focus_set)
        self.inst = Inst(on_arg=self.on_arg, before_close=self.confirm_discard, on_close=self.on_close,
                         on_focus=lambda: self.text.focus_set(), mem=lambda: len(self.value()) * 2 + 60000)

    # ---------------------------------------------------------- helpers
    def value(self):
        return self.text.get('1.0', 'end-1c')

    def set_value(self, v):
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', v)
        self.text.edit_reset()
        self.text.edit_modified(False)
        self.text.mark_set('insert', '1.0')

    def _placeholder(self):
        # A soft "Start writing…" hint while the page is empty.
        T = self.T
        self.ph = tk.Label(self.text, text='Start writing…', font=T.font('serif', 16), bd=0)
        T.on(self.ph, lambda: self.ph.configure(bg=T['paper'], fg=T['fg2'] if not T.dark else '#8a8270'))
        self.ph.bind('<Button-1>', lambda e: self.text.focus_set())

    def _update_placeholder(self):
        if self.value():
            self.ph.place_forget()
        else:
            self.ph.place(x=24, y=18)

    def name_of(self):
        n = self.fs.get(self.file_id) if self.file_id else None
        return n['n'] if n else 'Untitled'

    def title(self):
        self.ctx.set_title('Scribe — ' + self.name_of() + (' •' if self.dirty else ''))

    def stats(self):
        t = self.value()
        words = len(re.findall(r'\S+', t.strip()))
        self.st_l.configure(text='%d %s · %d characters' % (words, 'word' if words == 1 else 'words', len(t)))
        n = self.fs.get(self.file_id) if self.file_id else None
        self.st_r.configure(text=(self.fs.path(self.file_id) if n else 'Not saved yet') + (' — unsaved' if self.dirty else ''))
        self._update_placeholder()

    def _modified(self, _e=None):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self.on_input()

    def on_input(self):
        self.dirty = self.value() != self.saved_text
        if self.preview:
            self._render_preview()
        self.title()
        self.stats()

    def _render_preview(self):
        y = self.prev.yview()[0]
        render(self.os, self.prev, self.value())
        self.prev.yview_moveto(y)

    def wrap(self, a, b):
        t = self.text
        try:
            s, e = t.index('sel.first'), t.index('sel.last')
        except tk.TclError:
            s = e = t.index('insert')
        t.mark_set('q_end', e)
        t.mark_gravity('q_end', 'left')
        t.edit_separator()
        t.insert('q_end', b)
        t.insert(s, a)
        start = t.index('%s+%dc' % (s, len(a)))
        t.tag_remove('sel', '1.0', 'end')
        t.tag_add('sel', start, 'q_end')
        t.mark_set('insert', 'q_end')
        t.focus_set()

    def line_start(self, pre):
        t = self.text
        t.insert('insert linestart', pre)
        t.focus_set()

    def _tab(self, _e):
        t = self.text
        try:
            t.delete('sel.first', 'sel.last')
        except tk.TclError:
            pass
        t.insert('insert', '    ')
        return 'break'

    # ---------------------------------------------------------- files
    def load(self, fid):
        n = self.fs.get(fid)
        if n is None or n['t'] != 'f':
            return
        self.file_id = fid
        self.set_value('' if n.get('b') else (n.get('c') or ''))
        self.saved_text = self.value()
        self.dirty = False
        self.title()
        self.stats()
        self.set_preview(n['n'].lower().endswith('.md'))

    def set_preview(self, on):
        self.preview = bool(on)
        self.b_prev.set_kind('pri' if self.preview else 'btn')
        if self.preview:
            self.prev_frame.pack(side='left', fill='both', expand=True)
            self._render_preview()
        else:
            self.prev_frame.pack_forget()

    def save_as(self):
        nm = self.name_of()
        v = self.os.dialogs.prompt('Save as', 'Untitled.md' if nm == 'Untitled' else nm, text='It will be saved in Documents.',
                                   ok='Save', validate=self.os.valid_name)
        if v is None:
            return False
        n = self.fs.mk(FIXED['documents'], v.strip(), 'f', self.value())
        self.file_id = n['id']
        self.saved_text = self.value()
        self.dirty = False
        self.title()
        self.stats()
        self.os.toast('Saved ' + n['n'], '💾')
        return True

    def save(self):
        n = self.fs.get(self.file_id) if self.file_id else None
        if n is None or n.get('x'):
            return self.save_as()
        self.fs.write(self.file_id, self.value())
        self.saved_text = self.value()
        self.dirty = False
        self.title()
        self.stats()
        self.os.toast('Saved', '💾')
        return True

    def confirm_discard(self):
        if not self.dirty:
            return True
        v = self.os.dialogs.choose('Save changes?', '“' + self.name_of() + '” has changes that are not saved.',
                                   [('Save', 'save', 'pri'), ('Discard', 'drop', 'dng'), ('Cancel', 'cancel', 'btn')])
        if v == 'save':
            return self.save()
        return v == 'drop'

    def open_picker(self):
        pick = self.os.dialogs.pick_file(lambda n: kind_of(n) == 'text', 'Open a file')
        if pick and self.confirm_discard():
            self.load(pick)

    def new(self):
        if self.confirm_discard():
            self.file_id = None
            self.set_value('')
            self.saved_text = ''
            self.dirty = False
            self.title()
            self.stats()
            self.text.focus_set()

    def _schedule_autosave(self):
        def tick():
            if not self.ctx.alive:
                return
            n = self.fs.get(self.file_id) if self.file_id else None
            if (self.dirty and n is not None and not n.get('x') and self.os.S['set'].get('autosave') is not False
                    and len(self.value()) < 400000):
                self.fs.write(self.file_id, self.value())
                self.saved_text = self.value()
                self.dirty = False
                self.title()
                self.stats()
            self.auto = self.os.root.after(8000, tick)
        self.auto = self.os.root.after(8000, tick)

    def _fs_changed(self, _a=None):
        if self.file_id and not self.fs.get(self.file_id):
            self.file_id = None
            self.dirty = True
            self.title()
            self.stats()

    def on_arg(self, a):
        if not isinstance(a, dict):
            return
        if a.get('file'):
            if self.confirm_discard():
                self.load(a['file'])
        elif a.get('fresh'):
            self.new()

    def on_close(self):
        if self.auto:
            try:
                self.os.root.after_cancel(self.auto)
            except tk.TclError:
                pass
        self.off()
