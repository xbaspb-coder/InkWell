"""Loom — settings."""

import json
import os
import re
import tkinter as tk
from tkinter import colorchooser, filedialog

from .base import AppSpec, Inst
from ..core import icon_of, kind_of, to_json
from ..state import ACCENTS, STORE_LIMIT, normalize_state
from ..ui.desk import WALLS
from ..ui.overlays import avatar, setup_wizard, swatches
from ..ui.theme import THEME_BG, THEME_NAMES
from ..ui.widgets import Btn, Entry, ScrollArea, Select, Slider, Switch, tile_image
from ..util import ago, day_key, fmt_bytes, fmt_date, hash_pin

SHORTCUTS = [('Ctrl+K  or  Alt+Space', 'Open the Inkwell'), ('Alt+1 … Alt+4', 'Switch chapter'), ('Alt+S', 'Spread (all windows)'),
             ('Alt+J', 'Next window'), ('Alt+W', 'Close window'), ('Alt+M', 'Minimise window'),
             ('Alt+Enter', 'Maximise or restore'), ('Alt+T', 'New terminal'), ('Alt+E', 'Open Atlas (files)'),
             ('Alt+N', 'New note in Scribe'), ('Alt+L', 'Lock the screen'), ('Alt+Q', 'Quick settings'),
             ('Ctrl+S', 'Save (editors)'), ('Ctrl+Z / Ctrl+Y', 'Undo / redo (Brush)'), ('Ctrl+Enter', 'Run code (Glyph)'),
             ('Ctrl+F', 'Find (Glyph)'), ('Ctrl+/', 'Comment lines (Glyph)'), ('F2', 'Rename (Atlas)'),
             ('Drag to a screen edge', 'Snap a window')]
PAGES = [('look', '🎨', 'Appearance'), ('display', '🔊', 'Display & sound'), ('account', '☁', 'Account & sync'),
         ('security', '🔐', 'Security'), ('storage', '💾', 'Storage'), ('system', '⚙', 'System'), ('keys', '⌨', 'Shortcuts'),
         ('about', 'ℹ', 'About')]


class App(AppSpec):
    id = 'loom'
    name = 'Loom'
    icon = '⚙'
    bg = ('#9aa4b8', '#4a5468')
    w, h = 800, 560
    single = True
    kw = 'settings preferences theme wallpaper appearance pin security storage account sync sound display'
    about = 'Settings'

    def build(self, ctx):
        return Loom(ctx).inst


class Loom:
    def __init__(self, ctx):
        self.ctx = ctx
        self.os = ctx.os
        T = self.T = ctx.T
        self.page = (ctx.arg or {}).get('page') or 'look'
        lm = tk.Frame(ctx.body, bd=0)
        T.style(lm, bg='bg1')
        lm.pack(fill='both', expand=True)
        self.nav = tk.Frame(lm, bd=0, width=168)
        self.nav.pack_propagate(False)
        T.style(self.nav, bg='bg2')
        self.nav.pack(side='left', fill='y')
        edge = tk.Frame(lm, width=1, bd=0)
        T.style(edge, bg='line')
        edge.pack(side='left', fill='y')
        self.area = ScrollArea(lm, T, bg='bg1')
        self.area.pack(side='left', fill='both', expand=True)
        self.draw()
        self.inst = Inst(on_arg=self.on_arg, mem=lambda: 100000)

    def on_arg(self, a):
        if isinstance(a, dict) and a.get('page') and hasattr(self, 'page_' + a['page']):
            self.page = a['page']
            self.draw()

    # ---------------------------------------------------------- building blocks
    def draw(self):
        T = self.T
        for c in self.nav.winfo_children():
            c.destroy()
        for pid, ico, label in PAGES:
            b = Btn(self.nav, T, ico + '  ' + label, lambda p=pid: self.go(p), kind='flat', bg='bg2', anchor='w',
                    font=T.font('sans', 13, 'bold' if pid == self.page else 'normal'))
            b.set_on(pid == self.page)
            b.pack(fill='x', padx=8, pady=(8 if pid == 'look' else 1, 1))
        for c in self.area.inner.winfo_children():
            c.destroy()
        self.body = tk.Frame(self.area.inner, bd=0)
        T.style(self.body, bg='bg1')
        self.body.pack(fill='both', expand=True, padx=22, pady=18)
        getattr(self, 'page_' + self.page)()
        self.area.to_top()
        self.ctx.set_title('Loom — ' + next(l for p, i, l in PAGES if p == self.page))

    def go(self, p):
        self.page = p
        self.draw()

    def h2(self, text):
        lbl = tk.Label(self.body, text=text, anchor='w', font=self.T.font('serif', 22, 'bold', 'italic'))
        self.T.style(lbl, bg='bg1', fg='fg')
        lbl.pack(fill='x', pady=(0, 14))

    def h4(self, text):
        lbl = tk.Label(self.body, text=text.upper(), anchor='w', font=self.T.font('sans', 12))
        self.T.style(lbl, bg='bg1', fg='fg2')
        lbl.pack(fill='x', pady=(18, 8))

    def row(self, title, sub=None, make=None):
        T = self.T
        r = tk.Frame(self.body, bd=0)
        T.style(r, bg='bg1')
        r.pack(fill='x')
        line = tk.Frame(self.body, height=1, bd=0)
        T.style(line, bg='line')
        line.pack(fill='x')
        col = tk.Frame(r, bd=0)
        T.style(col, bg='bg1')
        col.pack(side='left', fill='x', expand=True, pady=10)
        a = tk.Label(col, text=title, anchor='w', font=T.font('sans', 14))
        T.style(a, bg='bg1', fg='fg')
        a.pack(fill='x')
        if sub:
            b = tk.Label(col, text=sub, anchor='w', justify='left', wraplength=380, font=T.font('sans', 12))
            T.style(b, bg='bg1', fg='fg2')
            b.pack(fill='x')
        if make:
            w = make(r)
            w.pack(side='right', padx=(12, 0))
        return r

    def switch(self, key, after=None):
        S = self.os.S

        def make(parent):
            def set_(v):
                S['set'][key] = v
                self.os.touch()
                if after:
                    after(v)
            return Switch(parent, self.T, S['set'].get(key), set_, bg='bg1')
        return make

    def p(self, text, small=True):
        lbl = tk.Label(self.body, text=text, anchor='w', justify='left', wraplength=520,
                       font=self.T.font('sans', 12 if small else 13))
        self.T.style(lbl, bg='bg1', fg='fg2')
        lbl.pack(fill='x', pady=(16, 0))

    def frame(self, parent=None):
        f = tk.Frame(parent or self.body, bd=0)
        self.T.style(f, bg='bg1')
        return f

    # ---------------------------------------------------------- pages
    def page_look(self):
        T, os_ = self.T, self.os
        S = os_.S
        self.h2('Appearance')
        self.h4('Theme')
        tg = self.frame()
        tg.pack(fill='x')
        for i, (t, label) in enumerate(THEME_NAMES.items()):
            on = S['set']['theme'] == t
            b = tk.Label(tg, text=label, anchor='sw', height=3, padx=6, pady=4, cursor='hand2', bg=THEME_BG[t],
                         fg='#2b2418' if t == 'parchment' else '#ebe7da', font=T.font('sans', 11, 'bold'),
                         highlightthickness=2, highlightbackground=T['acc'] if on else T['line'])
            b.bind('<Button-1>', lambda e, t=t: (os_.set_theme(t), self.draw()))
            b.grid(row=0, column=i, sticky='ew', padx=4)
            tg.columnconfigure(i, weight=1, uniform='t')
        self.h4('Accent colour')
        row = self.frame()
        row.pack(fill='x')

        def accent(a):
            S['set']['accent'] = a
            os_.touch()
            os_.apply_look()
            self.draw()
        swatches(row, T, ACCENTS, S['set']['accent'], accent, 'bg1').pack(side='left')

        def custom():
            r = colorchooser.askcolor(color=S['set']['accent'], parent=os_.root, title='Accent colour')
            if r and r[1]:
                accent(r[1])
        Btn(row, T, '🎨 Custom…', custom, size='sm', bg='bg1').pack(side='left', padx=6)
        self.h4('Wallpaper')
        wp = self.frame()
        wp.pack(fill='x')
        tiles = []

        def set_wall(w):
            S['set']['wall'] = w
            os_.touch()
            os_.apply_look()
            self.draw()
        for wid, name, cols in WALLS:
            if wid == 'color':
                continue
            tiles.append((name, cols, S['set']['wall'] == wid, lambda w=wid: set_wall(w)))
        tiles.append(('Plain colour', (S['set']['wallColor'], S['set']['wallColor']), S['set']['wall'] == 'color',
                      lambda: set_wall('color')))

        def pick_picture():
            fid = os_.dialogs.pick_file(lambda n: kind_of(n) == 'image', 'Choose a picture')
            if fid:
                S['set']['wall'] = 'image'
                S['set']['wallImg'] = fid
                os_.touch()
                os_.apply_look()
                self.draw()
        tiles.append(('🖼 Your picture…', (T['bg3'], T['bg3']), S['set']['wall'] == 'image', pick_picture))
        for i, (name, cols, on, fn) in enumerate(tiles):
            cv = tk.Canvas(wp, height=68, bd=0, highlightthickness=2, cursor='hand2',
                           highlightbackground=T['acc'] if on else T['line'])

            def paint(_e=None, cv=cv, cols=cols, name=name):
                cv.delete('all')
                w, h = cv.winfo_width(), cv.winfo_height()
                for y in range(0, h, 2):
                    from ..util import mix
                    col = mix(cols[0], cols[1], y / max(1, h))
                    cv.create_rectangle(0, y, w, y + 2, fill=col, outline=col)
                cv.create_text(9, h - 9, text=name, anchor='sw', fill='#000000', font=T.font('sans', 11, 'bold'))
                cv.create_text(8, h - 10, text=name, anchor='sw', fill='#ffffff', font=T.font('sans', 11, 'bold'))
            cv.bind('<Configure>', paint)
            cv.bind('<Button-1>', lambda e, fn=fn: fn())
            cv.grid(row=i // 4, column=i % 4, sticky='ew', padx=4, pady=4)
        for c in range(4):
            wp.columnconfigure(c, weight=1, uniform='w')

        def wall_color(parent):
            def pick():
                r = colorchooser.askcolor(color=S['set']['wallColor'], parent=os_.root, title='Wallpaper colour')
                if r and r[1]:
                    S['set']['wallColor'] = r[1]
                    S['set']['wall'] = 'color'
                    os_.touch()
                    os_.apply_look()
                    self.draw()
            b = tk.Label(parent, width=4, bg=S['set']['wallColor'], highlightthickness=1, cursor='hand2',
                         highlightbackground=T['line'])
            b.bind('<Button-1>', lambda e: pick())
            return b
        self.row('Plain colour', 'Used by the “Plain colour” wallpaper', wall_color)
        self.h4('Text')

        def size_sel(parent):
            def set_(v):
                S['set']['fs'] = v
                os_.touch()
                os_.apply_look()
            return Select(parent, T, [(12, 'Small'), (14, 'Medium'), (16, 'Large'), (18, 'Extra large')], S['set']['fs'],
                          set_, bg='bg1', size='sm')
        self.row('Text size', None, size_sel)
        self.row('Smooth motion', 'Animations and transitions', self.switch('anim', lambda v: os_.apply_look()))

    def page_display(self):
        T, os_ = self.T, self.os
        S = os_.S
        self.h2('Display & sound')

        def slider(key, lo, hi, after):
            def make(parent):
                def set_(v):
                    S['set'][key] = v
                    os_.touch()
                    after()
                return Slider(parent, T, lo, hi, S['set'][key], set_, length=170, bg='bg1')
            return make
        self.row('Brightness', 'Dim the whole desktop', slider('bright', 20, 100, os_.apply_look))
        self.row('Volume', 'For alarms, music and sounds', slider('volume', 0, 100, os_.apply_look))
        self.row('Interface sounds', 'Soft clicks when windows open and close',
                 self.switch('uisnd', lambda v: os_.sound.ui('open') if v else None))
        self.row('24-hour clock', None, self.switch('clock24', lambda v: os_.ribbon.clock_text()))
        self.row('Do Not Disturb', 'Hide notification pop-ups and keep them quiet', self.switch('dnd'))

        def test(parent):
            def go():
                os_.ring(True)
                os_.root.after(2200, lambda: os_.ring(False))
            return Btn(parent, T, '🔔 Test', go, bg='bg1')
        self.row('Test the alarm sound', 'Plays for two seconds', test)
        self.p('Sound output: ' + {'running': 'streaming to your speakers.', 'clips': 'playing short clips through the '
                                   'system player (install the sounddevice package for live sound).',
                                   'unavailable': 'no sound output was found on this computer.',
                                   'idle': 'starts with the first sound.'}.get(os_.sound.state, os_.sound.state))

    def page_account(self):
        T, os_ = self.T, self.os
        S = os_.S
        self.h2('Account & sync')

        def name_entry(parent):
            e = Entry(parent, T, S['user']['name'], placeholder='Your name', width=22)

            def save(_e=None):
                v = e.get().strip()[:30]
                if v != S['user']['name']:
                    S['user']['name'] = v
                    os_.touch()
                    os_.toast('Name saved', '✒️')
            e.bind('<Return>', save)
            e.bind('<FocusOut>', save, add='+')
            return e
        self.row('Display name', 'Shown on the lock screen and in the terminal', name_entry)
        card = tk.Frame(self.body, bd=0, highlightthickness=1)
        T.on(card, lambda: card.configure(bg=T['bg2'], highlightbackground=T['line']))
        card.pack(fill='x', pady=(14, 0))
        a = tk.Label(card, text='You are using Quill as a guest.', anchor='w', font=T.font('sans', 13, 'bold'))
        b = tk.Label(card, text='Everything is saved on this computer. Sign in with Galau services to keep your files in '
                                'your account and open them anywhere.', anchor='w', justify='left', wraplength=480,
                     font=T.font('sans', 13))
        T.style(a, bg='bg2', fg='fg')
        T.style(b, bg='bg2', fg='fg2')
        a.pack(fill='x', padx=14, pady=(14, 4))
        b.pack(fill='x', padx=14)
        Btn(card, T, 'Sign in with Galau services', lambda: os_.toast('Not running inside OG Browser.', '⚠️'), kind='pri',
            bg='bg2').pack(anchor='w', padx=14, pady=14)
        self.p('Your save file: ' + os_.core.store.path)

    def page_security(self):
        T, os_ = self.T, self.os
        S = os_.S
        dl = os_.dialogs
        self.h2('Security')
        has = bool(S['user']['pin'])

        def ask(title, text):
            return dl.prompt(title, '', text=text, ok='OK', password=True,
                             validate=lambda v: None if re.fullmatch(r'\d{4,12}', v) else 'Use 4 to 12 digits.')

        def check():
            if not S['user']['pin']:
                return True
            v = dl.prompt('Enter your current PIN', '', ok='Continue', password=True)
            if v is None:
                return False
            if hash_pin(v) == S['user']['pin']:
                return True
            os_.toast('That PIN is not right', '🔐')
            return False

        def set_pin():
            if not check():
                return
            a = ask('New PIN' if has else 'Choose a PIN', '4 to 12 digits.')
            if a is None:
                return
            b = ask('Confirm the PIN', 'Type it again.')
            if b is None:
                return
            if a != b:
                os_.toast('The two PINs did not match', '🔐')
                return
            S['user']['pin'] = hash_pin(a)
            os_.touch()
            os_.toast('PIN saved', '🔐')
            self.draw()

        def remove():
            if not check():
                return
            S['user']['pin'] = ''
            os_.touch()
            os_.toast('PIN removed', '🔐')
            self.draw()

        def pin_btns(parent):
            f = self.frame(parent)
            Btn(f, T, 'Change PIN' if has else 'Set a PIN', set_pin, bg='bg1').pack(side='left')
            if has:
                Btn(f, T, 'Remove', remove, kind='dng', bg='bg1').pack(side='left', padx=(6, 0))
            return f
        self.row('PIN lock', 'A PIN is needed to unlock the screen.' if has else 'Add a PIN to the lock screen.', pin_btns)

        def autolock(parent):
            def set_(v):
                S['set']['autolock'] = v
                os_.touch()
            return Select(parent, T, [(0, 'Never'), (1, 'After 1 minute'), (5, 'After 5 minutes'), (15, 'After 15 minutes'),
                                      (30, 'After 30 minutes')], S['set'].get('autolock', 0), set_, bg='bg1', size='sm')
        self.row('Auto-lock', 'Lock the screen when you are away', autolock)
        self.row('Lock now', None, lambda parent: Btn(parent, T, '🔒 Lock', lambda: os_.lock.show(), bg='bg1'))
        self.p('The PIN keeps people from using Quill on this computer. It is stored only as a hash, and it is not a '
               'substitute for locking your computer.')

    def page_storage(self):
        T, os_ = self.T, self.os
        S = os_.S
        fs = os_.fs
        self.h2('Storage')
        u = fs.usage()
        pct = min(100, round(u / STORE_LIMIT * 100))
        top = self.frame()
        top.pack(fill='x')
        a = tk.Label(top, text=fmt_bytes(u) + ' used', font=T.font('sans', 14, 'bold'))
        b = tk.Label(top, text='of ' + fmt_bytes(STORE_LIMIT), font=T.font('sans', 13))
        T.style(a, bg='bg1', fg='fg')
        T.style(b, bg='bg1', fg='fg2')
        a.pack(side='left')
        b.pack(side='right')
        meter = tk.Canvas(self.body, height=10, bd=0, highlightthickness=0)
        T.style(meter, bg='bg1')
        meter.pack(fill='x', pady=6)

        def paint_meter(_e=None):
            meter.delete('all')
            w = meter.winfo_width()
            meter.create_rectangle(0, 0, w, 10, fill=T['bg3'], outline='')
            meter.create_rectangle(0, 0, w * pct / 100, 10, fill=T['red'] if pct > 85 else T['acc'], outline='')
        meter.bind('<Configure>', paint_meter)
        self.h4('By folder')
        for k in fs.kids('root'):
            self.row(icon_of(k) + ' ' + k['n'], None, lambda parent, k=k: self._muted(parent, fmt_bytes(fs.size(k))))
        tr = fs.trashed()

        def trash_ctl(parent):
            f = self.frame(parent)
            self._muted(f, fmt_bytes(sum(fs.size(n) for n in tr))).pack(side='left', padx=8)
            b = Btn(f, T, 'Empty', empty, size='sm', bg='bg1')
            b.set_disabled(not tr)
            b.pack(side='left')
            return f

        def empty():
            if dl_confirm():
                fs.empty_trash()
                self.draw()

        def dl_confirm():
            return os_.dialogs.confirm('Empty Trash?', 'Everything in the Trash is deleted for good.', ok='Empty', danger=True)
        self.row('🗑 Trash', '%d items' % len(tr), trash_ctl)
        big = sorted([n for n in fs.all() if n['t'] == 'f'], key=lambda n: -len(n.get('c') or ''))[:6]
        if big:
            self.h4('Largest files')
            for n in big:
                def ctl(parent, n=n):
                    f = self.frame(parent)
                    self._muted(f, fmt_bytes(len(n.get('c') or ''))).pack(side='left', padx=8)
                    Btn(f, T, 'Trash', lambda: (fs.trash(n['id']), self.draw()), size='sm', bg='bg1').pack(side='left')
                    return f
                self.row(icon_of(n) + ' ' + n['n'], fs.path(n['p']), ctl)
        self.h4('Back up')

        def export():
            path = filedialog.asksaveasfilename(parent=os_.root, title='Export everything',
                                                initialfile='quill-backup-' + day_key() + '.json',
                                                defaultextension='.json', filetypes=[('Quill backup', '*.json')])
            if not path:
                return
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(to_json(S))
                os_.toast('Backup saved', '📥')
            except OSError as e:
                os_.toast('Could not save the backup: %s' % e, '⚠️')

        def import_():
            path = filedialog.askopenfilename(parent=os_.root, title='Import a backup',
                                              filetypes=[('Quill backup', '*.json'), ('All files', '*')])
            if not path:
                return
            try:
                if os.path.getsize(path) > STORE_LIMIT:
                    raise ValueError('That file is too big.')
                with open(path, 'r', encoding='utf-8') as f:
                    obj = json.load(f)
                if not isinstance(obj, dict) or not isinstance(obj.get('fs'), dict) or not obj['fs'].get('root'):
                    raise ValueError('This is not a Quill backup.')
                if not os_.dialogs.confirm('Replace everything with this backup?',
                                           'Your current files and settings on this computer will be replaced.',
                                           ok='Import', danger=True):
                    return
                ns = normalize_state(obj)
                ns['set']['autosync'] = False
                os_.core.S = ns
                os_.touch()
                os_.save(True)
                os_.reload_ui()
                os_.toast('Backup imported', '📤')
            except (OSError, ValueError) as e:
                os_.toast(str(e) or 'Could not import', '⚠️')
        self.row('Export everything', 'Save all your files and settings as one JSON file',
                 lambda parent: Btn(parent, T, '📥 Export', export, bg='bg1'))
        self.row('Import a backup', 'Replaces everything on this computer (backups from the browser version work too)',
                 lambda parent: Btn(parent, T, '📤 Import', import_, bg='bg1'))

    def _muted(self, parent, text):
        lbl = tk.Label(parent, text=text, font=self.T.font('sans', 13))
        self.T.style(lbl, bg='bg1', fg='fg2')
        return lbl

    def page_system(self):
        T, os_ = self.T, self.os
        self.h2('System')
        self.row('Restart Quill', 'Closes every window', lambda p: Btn(p, T, '🔄 Restart', os_.restart, bg='bg1'))
        self.row('Shut down', None, lambda p: Btn(p, T, '⏻ Shut down', os_.power_off, bg='bg1'))

        def rerun():
            os_.wm.close_all()
            setup_wizard(os_)
            os_.reload_ui()
        self.row('Show the welcome setup again', 'Name, theme and accent colour', lambda p: Btn(p, T, 'Run setup', rerun, bg='bg1'))

        def reset():
            v = os_.dialogs.prompt('Reset Quill?', '', text='This deletes everything in Quill on this computer. '
                                   'Type RESET to confirm.', ok='Reset',
                                   validate=lambda s: None if s == 'RESET' else 'Type RESET in capital letters.')
            if v != 'RESET':
                return
            os_.core.S = normalize_state(None)
            os_.S['set']['autosync'] = False
            os_.save(True)
            os_.reload_ui()
            setup_wizard(os_)
            os_.reload_ui()
        self.row('Reset Quill', 'Deletes all files, notes and settings on this computer',
                 lambda p: Btn(p, T, 'Reset…', reset, kind='dng', bg='bg1'))

    def page_keys(self):
        T = self.T
        self.h2('Shortcuts')
        tbl = self.frame()
        tbl.pack(fill='x')
        for i, (k, d) in enumerate([('KEYS', 'DOES')] + SHORTCUTS):
            head = i == 0
            a = tk.Label(tbl, text=k, anchor='w', font=T.font('sans', 11) if head else T.font('mono', 12))
            b = tk.Label(tbl, text=d, anchor='w', font=T.font('sans', 11 if head else 13))
            T.style(a, bg='bg1', fg='fg2' if head else 'fg')
            T.style(b, bg='bg1', fg='fg2' if head else 'fg')
            a.grid(row=i * 2, column=0, sticky='w', padx=(0, 18), pady=5)
            b.grid(row=i * 2, column=1, sticky='w', pady=5)
            line = tk.Frame(tbl, height=1, bd=0)
            T.style(line, bg='line')
            line.grid(row=i * 2 + 1, column=0, columnspan=2, sticky='ew')
        tbl.columnconfigure(1, weight=1)

    def page_about(self):
        T, os_ = self.T, self.os
        S = os_.S
        top = self.frame()
        top.pack(fill='x', pady=(0, 14))
        av = tk.Label(top, text='✒', compound='center', fg=T['acc_fg'], font=T.font('sans', 30),
                      image=tile_image(os_.root, T['acc'], T['acc_dark'], 84, 20, T['bg1']))
        T.style(av, bg='bg1')
        av.pack(side='left')
        col = self.frame(top)
        col.pack(side='left', padx=14)
        a = tk.Label(col, text='Quill.OS 1.0', anchor='w', font=T.font('serif', 22, 'bold', 'italic'))
        b = tk.Label(col, text='An operating system made of ink and glass.', anchor='w', font=T.font('sans', 13))
        T.style(a, bg='bg1', fg='fg')
        T.style(b, bg='bg1', fg='fg2')
        a.pack(fill='x')
        b.pack(fill='x')
        nf = sum(1 for n in os_.fs.all() if n['t'] == 'f')
        kv = self.frame()
        kv.pack(fill='x')
        import platform
        import sys
        rows = [('Runs on', 'Python %s · %s' % (platform.python_version(), platform.system() or sys.platform)),
                ('Apps', '%d built in' % len(os_.apps)), ('Files', '%d files, %s used' % (nf, fmt_bytes(os_.fs.usage()))),
                ('Account', 'Guest'), ('Saving', 'On this computer'),
                ('Opened', '%d %s' % (S['meta']['boots'], 'time' if S['meta']['boots'] == 1 else 'times')),
                ('Since', fmt_date(S['meta']['created']))]
        for i, (k, v) in enumerate(rows):
            x = tk.Label(kv, text=k, anchor='w', font=T.font('sans', 13, 'bold'))
            y = tk.Label(kv, text=v, anchor='w', font=T.font('sans', 13))
            T.style(x, bg='bg1', fg='fg2')
            T.style(y, bg='bg1', fg='fg')
            x.grid(row=i, column=0, sticky='w', padx=(0, 14), pady=3)
            y.grid(row=i, column=1, sticky='w', pady=3)
        self.p('Every window, app and file system in Quill is written from scratch. Nothing is loaded from the internet.')


__all__ = ['App', 'avatar', 'ago', 'Entry']
