"""Atlas — files and folders."""

import tkinter as tk

from .base import AppSpec, Inst
from ..core import icon_of, kind_of
from ..state import FIXED, STORE_LIMIT
from ..ui.widgets import Btn, Entry, ScrollArea, bind_tree, ellipsize, wrap_lines
from ..ui.wm import bind_context
from ..util import ext_of, fmt_bytes, fmt_date

CLIP = {'ids': [], 'cut': False}
PLACES = [('desktop', 'Desktop', '🖥️'), ('documents', 'Documents', '📄'), ('pictures', 'Pictures', '🖼️'),
          ('music', 'Music', '🎵'), ('downloads', 'Downloads', '📥'), ('projects', 'Projects', '🧩')]


def _multi(e, aqua):
    return bool(e.state & 0x4) or (aqua and bool(e.state & 0x8))


class App(AppSpec):
    id = 'files'
    name = 'Atlas'
    icon = '🗂'
    bg = ('#f0b84f', '#b9792a')
    w, h = 840, 540
    kw = 'files folders explorer finder documents trash'
    about = 'Files and folders'

    def build(self, ctx):
        return Atlas(ctx).inst


class Atlas:
    def __init__(self, ctx):
        self.ctx = ctx
        self.os = os_ = ctx.os
        self.T = T = ctx.T
        self.fs = os_.fs
        self.aqua = os_.root.tk.call('tk', 'windowingsystem') == 'aqua'
        arg = ctx.arg or {}
        self.cwd = FIXED['documents']
        if arg.get('dir') == 'trash':
            self.cwd = 'trash'
        elif arg.get('dir') and self.fs.get(arg['dir']) and self.fs.get(arg['dir'])['t'] == 'd':
            self.cwd = arg['dir']
        self.hist, self.fwd = [], []
        self.sel = set()
        self.anchor = None
        self.view = os_.S['set'].get('fview') or 'grid'
        self.filter = ''
        self.cells = {}
        self.press = None

        body = ctx.body
        fx = tk.Frame(body, bd=0)
        T.style(fx, bg='bg1')
        fx.pack(fill='both', expand=True)
        self.side = tk.Frame(fx, bd=0, width=170)
        self.side.pack_propagate(False)
        T.style(self.side, bg='bg2')
        self.side.pack(side='left', fill='y')
        edge = tk.Frame(fx, width=1, bd=0)
        T.style(edge, bg='line')
        edge.pack(side='left', fill='y')
        main = tk.Frame(fx, bd=0)
        T.style(main, bg='bg1')
        main.pack(side='left', fill='both', expand=True)

        bar = tk.Frame(main, bd=0)
        T.style(bar, bg='bg2')
        bar.pack(fill='x')
        sep = tk.Frame(main, height=1, bd=0)
        T.style(sep, bg='line')
        sep.pack(fill='x')
        self.b_back = Btn(bar, T, '←', self.back, kind='ibtn', tip='Back (Alt+←)')
        self.b_fwd = Btn(bar, T, '→', self.forward, kind='ibtn', tip='Forward (Alt+→)')
        self.b_up = Btn(bar, T, '↑', self.up, kind='ibtn', tip='Up one level')
        for b in (self.b_back, self.b_fwd, self.b_up):
            b.pack(side='left', padx=(6 if b is self.b_back else 0, 0), pady=6)
        self.b_up2 = Btn(bar, T, '⇧ Upload', lambda: os_.upload_into(self.cwd), size='sm')
        self.b_up2.pack(side='right', padx=(4, 8))
        self.b_new = Btn(bar, T, '＋ New', self.new_menu, size='sm')
        self.b_new.pack(side='right', padx=4)
        self.b_view = Btn(bar, T, '☰', self.toggle_view, kind='ibtn', tip='Grid or list')
        self.b_view.pack(side='right')
        self.search = Entry(bar, T, placeholder='Filter…', width=12)
        self.search.pack(side='right', padx=4, ipady=3)
        self.search.bind('<KeyRelease>', self._on_filter)
        self.crumbs = tk.Frame(bar, bd=0, highlightthickness=1)
        T.on(self.crumbs, lambda: self.crumbs.configure(bg=T['bg0'], highlightbackground=T['line']))
        self.crumbs.pack(side='left', fill='x', expand=True, padx=6, ipady=1)

        self.area = ScrollArea(main, T, bg='bg1')
        self.area.pack(fill='both', expand=True)
        self.area.canvas.configure(takefocus=1)
        self.grid = self.area.inner
        self.status = tk.Frame(main, bd=0)
        T.style(self.status, bg='bg2')
        self.status.pack(fill='x', side='bottom')
        self.st_l = tk.Label(self.status, anchor='w', font=T.font('sans', 12))
        self.st_r = tk.Label(self.status, anchor='e', font=T.font('sans', 12))
        for w in (self.st_l, self.st_r):
            T.style(w, bg='bg2', fg='fg2')
        self.st_l.pack(side='left', padx=12, pady=4)
        self.st_r.pack(side='right', padx=12, pady=4)

        for w in (self.area.canvas, self.grid):
            w.bind('<Button-1>', self._blank_click)
            bind_context(w, self._blank_menu)
            w._drop = self._drop_here
        self._bind_keys(self.area.canvas)
        self.area.canvas.bind('<Configure>', lambda e: self._relayout(), add='+')
        self._cols = 0
        self.off = os_.bus.on('fs', lambda _a: self._fs_changed())
        self.go(self.cwd, push=False)
        if arg.get('select') and self.fs.get(arg['select']):
            self.sel = {arg['select']}
            self.paint_sel()
        os_.root.after(30, self._focus)
        self.inst = Inst(on_close=self.off, on_arg=self.on_arg, on_focus=self._focus,
                         mem=lambda: len(self.cells) * 1200 + 40000)

    # ---------------------------------------------------------- data
    def in_trash(self):
        return self.cwd == 'trash'

    def items(self):
        if self.in_trash():
            a = sorted(self.fs.trashed(), key=lambda n: -(n.get('xd') or 0))
        else:
            a = self.fs.kids(self.cwd)
        if self.filter:
            f = self.filter.lower()
            a = [n for n in a if f in n['n'].lower()]
        return a

    def valid(self):
        if self.in_trash():
            return True
        n = self.fs.get(self.cwd)
        return n is not None and n['t'] == 'd' and self.fs.live(n)

    def chosen(self):
        return [n for n in self.items() if n['id'] in self.sel]

    # ---------------------------------------------------------- navigation
    def go(self, d, push=True):
        if push and d != self.cwd:
            self.hist.append(self.cwd)
            self.fwd = []
        self.cwd = d
        self.sel = set()
        self.anchor = None
        self.filter = ''
        self.search.set('')
        self.render()
        self.area.to_top()
        self.ctx.set_title('Atlas — Trash' if self.in_trash() else 'Atlas — ' + (self.fs.get(self.cwd)['n'] or '/'))

    def back(self):
        if self.hist:
            self.fwd.append(self.cwd)
            self.go(self.hist.pop(), False)

    def forward(self):
        if self.fwd:
            self.hist.append(self.cwd)
            self.go(self.fwd.pop(), False)

    def up(self):
        n = self.fs.get(self.cwd)
        if n is not None and n.get('p'):
            self.go(n['p'])

    def on_arg(self, a):
        if isinstance(a, dict) and a.get('dir'):
            if a['dir'] == 'trash':
                self.go('trash')
            elif self.fs.get(a['dir']):
                self.go(a['dir'])

    def _focus(self):
        try:
            self.area.canvas.focus_set()
        except tk.TclError:
            pass

    def _on_filter(self, _e=None):
        v = self.search.get()
        if v != self.filter:
            self.filter = v
            self.sel = set()
            self.render()

    def _fs_changed(self):
        if self.ctx.alive:
            self.render()

    # ---------------------------------------------------------- drag and drop
    def _drop_into(self, target):
        def fn(ids):
            n = sum(1 for i in ids if self.fs.move(i, target))
            if n:
                self.os.toast('Moved %d %s' % (n, 'item' if n == 1 else 'items'), '📁')
            return n > 0
        return fn

    def _drop_here(self, ids):
        if self.in_trash():
            n = sum(1 for i in ids if self.fs.trash(i))
            return n > 0
        return self._drop_into(self.cwd)(ids)

    # ---------------------------------------------------------- drawing
    def render(self):
        T = self.T
        if not self.valid():
            self.cwd = FIXED['documents']
        self.render_side()
        self.render_crumbs()
        self.b_view.set_text('▦' if self.view == 'list' else '☰')
        self.b_back.set_disabled(not self.hist)
        self.b_fwd.set_disabled(not self.fwd)
        n = self.fs.get(self.cwd)
        self.b_up.set_disabled(self.in_trash() or n is None or not n.get('p'))
        self.b_new.set_disabled(self.in_trash())
        self.b_up2.set_disabled(self.in_trash())
        lst = self.items()
        ids = {x['id'] for x in lst}
        self.sel &= ids
        for c in self.grid.winfo_children():
            c.destroy()
        self.cells = {}
        self._cols = 0
        if not lst:
            box = tk.Frame(self.grid, bd=0)
            T.style(box, bg='bg1')
            big = '🗑' if self.in_trash() else '🔍' if self.filter else '📂'
            msg = ('The Trash is empty.' if self.in_trash() else 'Nothing matches “' + self.filter + '”.' if self.filter
                   else 'This folder is empty.')
            a = tk.Label(box, text=big, font=T.font('sans', 42))
            b = tk.Label(box, text=msg, font=T.font('sans', 14))
            for w in (a, b):
                T.style(w, bg='bg1', fg='fg2')
            a.pack(pady=(50, 6))
            b.pack()
            if not self.in_trash():
                c = tk.Label(box, text='Drop files here, or use ＋ New / ⇧ Upload.', font=T.font('sans', 12))
                T.style(c, bg='bg1', fg='fg2')
                c.pack(pady=(4, 0))
            box.pack(fill='x')
            for w in (box,) + tuple(box.winfo_children()):
                w.bind('<Button-1>', self._blank_click)
                bind_context(w, self._blank_menu)
                w._drop = self._drop_here
        for n in lst:
            self.cells[n['id']] = self._cell(n)
        self._relayout(force=True)
        self.paint_sel()

    def _cell(self, n):
        T = self.T
        list_view = self.view == 'list'
        cell = tk.Frame(self.grid, bd=0, highlightthickness=1, cursor='hand2')
        if not list_view:
            cell.configure(width=96, height=104)
            cell.pack_propagate(False)
        img = self.os.thumb(n, 26 if list_view else 46) if kind_of(n) == 'image' and n.get('c') else None
        if img is not None:
            ic = tk.Label(cell, image=img, bd=0)
        else:
            ic = tk.Label(cell, text=icon_of(n), bd=0, font=T.font('sans', 18 if list_view else 34))
        meta = ('from ' + (self.fs.path(n.get('xp')) or '/')) if self.in_trash() else self._meta(n)
        if list_view:
            ic.pack(side='left', padx=(10, 10), pady=4)
            name = tk.Label(cell, text=n['n'], anchor='w', bd=0, font=T.font('sans', 13))
            name.pack(side='left', fill='x', expand=True)
            mt = tk.Label(cell, text=meta, anchor='e', bd=0, font=T.font('sans', 11))
            mt.pack(side='right', padx=10)
            parts = (cell, ic, name, mt)
        else:
            ic.pack(pady=(8, 4))
            lines = wrap_lines(T.font('sans', 12), n['n'], 86, 2)
            name = tk.Label(cell, text='\n'.join(lines), bd=0, font=T.font('sans', 12), justify='center')
            name.pack()
            mt = None
            parts = (cell, ic, name)
        cut = CLIP['cut'] and n['id'] in CLIP['ids']
        cell._parts = parts
        cell._mt = mt
        cell._cut = cut
        nid = n['id']
        for w in parts:
            w.bind('<ButtonPress-1>', lambda e, i=nid: self._item_press(e, i))
            w.bind('<B1-Motion>', lambda e, i=nid: self._item_drag(e, i))
            w.bind('<ButtonRelease-1>', lambda e, i=nid: self._item_release(e, i))
            w.bind('<Double-Button-1>', lambda e, i=nid: self._item_open(i))
            bind_context(w, lambda e, i=nid: self._item_menu(e, i))
            if n['t'] == 'd' and not self.in_trash():
                w._drop = self._drop_into(nid)
            else:
                w._drop = self._drop_here
        tip = n['n'] + '\n' + self._meta(n)
        from ..ui.widgets import tooltip
        tooltip(name, tip, 'below')
        return cell

    def _meta(self, n):
        return (fmt_bytes(self.fs.size(n)) + ' · ' if n['t'] == 'f' else '') + fmt_date(n['m'])

    def _relayout(self, force=False):
        if not self.cells:
            return
        if self.view == 'list':
            if force:
                for c in self.cells.values():
                    c.pack(fill='x', padx=6, pady=1)
            return
        width = max(110, self.area.canvas.winfo_width() - 20)
        cols = max(1, width // 102)
        if cols == self._cols and not force:
            return
        self._cols = cols
        for i, c in enumerate(self.cells.values()):
            c.grid(row=i // cols, column=i % cols, padx=3, pady=3, sticky='nw')
        if force:
            self.grid.grid_columnconfigure(0, pad=4)

    def paint_sel(self):
        T = self.T
        for nid, cell in self.cells.items():
            on = nid in self.sel
            bg = T['acc_soft'] if on else T['bg1']
            fg = T['fg']
            if cell._cut:
                fg = T['fg2']
            try:
                cell.configure(bg=bg, highlightbackground=T['acc'] if on else T['bg1'], highlightcolor=T['acc'])
                for w in cell._parts[1:]:
                    w.configure(bg=bg, fg=fg)
                if cell._mt is not None:
                    cell._mt.configure(fg=T['fg2'])
            except tk.TclError:
                pass
        self.paint_status()

    def paint_status(self):
        lst = self.items()
        ch = [n for n in lst if n['id'] in self.sel]
        txt = '%d %s' % (len(lst), 'item' if len(lst) == 1 else 'items')
        if ch:
            txt += ' · %d selected (%s)' % (len(ch), fmt_bytes(sum(self.fs.size(n) for n in ch)))
        self.st_l.configure(text=txt)
        self.st_r.configure(text='Storage ' + fmt_bytes(self.fs.usage()) + ' of ' + fmt_bytes(STORE_LIMIT))

    def render_side(self):
        T = self.T
        for c in self.side.winfo_children():
            c.destroy()

        def head(text):
            lbl = tk.Label(self.side, text=text.upper(), anchor='w', font=T.font('sans', 10))
            T.style(lbl, bg='bg2', fg='fg2')
            lbl.pack(fill='x', padx=17, pady=(10, 3))

        def item(d, label, ico):
            on = self.cwd == d
            b = Btn(self.side, T, ico + '  ' + label, lambda: self.go(d), kind='flat', bg='bg2', anchor='w',
                    font=T.font('sans', 13, 'bold' if on else 'normal'))
            b.set_on(on)
            b.pack(fill='x', padx=8, pady=1)
            b._drop = self._drop_into(d) if d != 'trash' else self._trash_drop
        head('Places')
        item('root', 'Quill', '💠')
        for k, label, ico in PLACES:
            item(FIXED[k], label, ico)
        head('System')
        t = len(self.fs.trashed())
        item('trash', 'Trash' + (' (%d)' % t if t else ''), '🗑')

    def _trash_drop(self, ids):
        n = sum(1 for i in ids if self.fs.trash(i))
        if n:
            self.os.toast('Moved to Trash', '🗑')
        return n > 0

    def render_crumbs(self):
        T = self.T
        for c in self.crumbs.winfo_children():
            c.destroy()
        if self.in_trash():
            b = Btn(self.crumbs, T, '🗑 Trash', None, kind='flat', bg='bg0', size='sm')
            b.pack(side='left')
            return
        chain = []
        n = self.fs.get(self.cwd)
        g = 0
        while n is not None and g < 60:
            g += 1
            chain.insert(0, n)
            n = self.fs.get(n['p']) if n.get('p') else None
        for i, c in enumerate(chain):
            if i:
                sep = tk.Label(self.crumbs, text='›', bd=0, font=T.font('sans', 13))
                T.style(sep, bg='bg0', fg='fg2')
                sep.pack(side='left')
            b = Btn(self.crumbs, T, '💠 Quill' if c['id'] == 'root' else ellipsize(T.font('sans', 12), c['n'], 140),
                    lambda d=c['id']: self.go(d), kind='flat', bg='bg0', size='sm', pady=1)
            b.pack(side='left')
            b._drop = self._drop_into(c['id'])

    # ---------------------------------------------------------- mouse
    def _item_press(self, e, nid):
        self._focus()
        lst = self.items()
        ids = [n['id'] for n in lst]
        if (e.state & 0x1) and self.anchor in ids and nid in ids:
            a, b = ids.index(self.anchor), ids.index(nid)
            self.sel = set(ids[min(a, b):max(a, b) + 1])
        elif _multi(e, self.aqua):
            if nid in self.sel:
                self.sel.discard(nid)
            else:
                self.sel.add(nid)
            self.anchor = nid
        elif nid not in self.sel or len(self.sel) == 1:
            self.sel = {nid}
            self.anchor = nid
        self.press = (e.x_root, e.y_root, nid)
        self.paint_sel()

    def _item_drag(self, e, nid):
        if not self.press or self.in_trash():
            return
        x, y, _ = self.press
        if (e.x_root - x) ** 2 + (e.y_root - y) ** 2 > 36:
            self.press = None
            if nid not in self.sel:
                self.sel = {nid}
                self.paint_sel()
            ids = [n['id'] for n in self.items() if n['id'] in self.sel]
            first = self.fs.get(ids[0]) if ids else None
            label = (icon_of(first) + ' ' + first['n']) if len(ids) == 1 and first else '📦 %d items' % len(ids)
            self.os.dnd.start(ids, label, e)

    def _item_release(self, e, nid):
        # A plain click inside a multiple selection (without dragging) selects just that item.
        if self.press and not (e.state & 0x1) and not _multi(e, self.aqua) and len(self.sel) > 1:
            self.sel = {nid}
            self.anchor = nid
            self.paint_sel()
        self.press = None

    def _item_open(self, nid):
        n = self.fs.get(nid)
        if n is None:
            return
        if self.in_trash():
            self.restore([n])
            return
        if n['t'] == 'd':
            self.go(nid)
        else:
            self.os.open_file(n)

    def _blank_click(self, e):
        self._focus()
        if self.sel:
            self.sel = set()
            self.paint_sel()

    # ---------------------------------------------------------- actions
    def restore(self, ns):
        for n in ns:
            self.fs.restore(n['id'])
        self.os.toast('Restored ' + ns[0]['n'] if len(ns) == 1 else 'Restored %d items' % len(ns), '↩')

    def purge(self, ns):
        if not ns:
            return
        text = ('“' + ns[0]['n'] + '” will be deleted for good.') if len(ns) == 1 else \
            '%d items will be deleted for good.' % len(ns)
        if not self.os.dialogs.confirm('Delete forever?', text, ok='Delete', danger=True):
            return
        for n in ns:
            self.fs.purge(n['id'])

    def trash_sel(self):
        ns = self.chosen()
        if not ns:
            return
        if self.in_trash():
            self.purge(ns)
            return
        for n in ns:
            self.fs.trash(n['id'])
        self.os.toast('Moved to Trash' if len(ns) == 1 else '%d items moved to Trash' % len(ns), '🗑')

    def copy_sel(self, cut):
        ns = self.chosen()
        if not ns:
            return
        CLIP['ids'] = [n['id'] for n in ns]
        CLIP['cut'] = bool(cut)
        self.render()
        self.os.toast(('Cut ' if cut else 'Copied ') + '%d %s' % (len(ns), 'item' if len(ns) == 1 else 'items'),
                      '✂' if cut else '⧉')

    def paste(self):
        if self.in_trash() or not CLIP['ids']:
            return
        n = 0
        for i in CLIP['ids']:
            node = self.fs.get(i)
            if node is None or node.get('x'):
                continue
            if CLIP['cut']:
                if self.fs.move(i, self.cwd):
                    n += 1
            elif self.fs.copy(i, self.cwd):
                n += 1
        if CLIP['cut']:
            CLIP['ids'] = []
            CLIP['cut'] = False
        if n:
            self.os.toast('Pasted %d %s' % (n, 'item' if n == 1 else 'items'), '📋')

    def select_all(self):
        self.sel = {n['id'] for n in self.items()}
        self.paint_sel()

    def toggle_view(self):
        self.view = 'list' if self.view == 'grid' else 'grid'
        self.os.S['set']['fview'] = self.view
        self.os.touch()
        self.render()

    def properties(self, n):
        self.os.dialogs.alert(n['n'], 'Type: ' + ('Folder' if n['t'] == 'd' else (ext_of(n['n']) or 'file') + ' file') +
                              '\nLocation: ' + (self.fs.path(n['p']) or '/') + '\nSize: ' + fmt_bytes(self.fs.size(n)) +
                              '\nCreated: ' + fmt_date(n['r']) + '\nModified: ' + fmt_date(n['m']))

    def _item_menu(self, e, nid):
        if nid not in self.sel:
            self.sel = {nid}
            self.anchor = nid
            self.paint_sel()
        ns = self.chosen()
        if not ns:
            return
        menu = self.os.menu
        if self.in_trash():
            menu.show(e.x_root, e.y_root, [{'label': 'Restore', 'icon': '↩', 'action': lambda: self.restore(ns)},
                                           {'label': 'Delete forever', 'icon': '✕', 'danger': True,
                                            'action': lambda: self.purge(ns)}])
            return
        if len(ns) > 1:
            menu.show(e.x_root, e.y_root, [
                {'label': 'Cut', 'icon': '✂', 'key': 'Ctrl+X', 'action': lambda: self.copy_sel(True)},
                {'label': 'Copy', 'icon': '⧉', 'key': 'Ctrl+C', 'action': lambda: self.copy_sel(False)}, {'sep': True},
                {'label': 'Move %d items to Trash' % len(ns), 'icon': '🗑', 'danger': True, 'action': self.trash_sel}])
            return
        n = ns[0]
        items = [it for it in self.os.file_menu(n, [{'sep': True},
                                                    {'label': 'Cut', 'icon': '✂', 'key': 'Ctrl+X', 'action': lambda: self.copy_sel(True)},
                                                    {'label': 'Copy', 'icon': '⧉', 'key': 'Ctrl+C', 'action': lambda: self.copy_sel(False)}])
                 if it.get('label') != 'Move to Trash']
        items += [{'label': 'Move to Trash', 'icon': '🗑', 'danger': True, 'key': 'Del', 'action': self.trash_sel},
                  {'label': 'Properties', 'icon': 'ℹ', 'action': lambda: self.properties(n)}]
        menu.show(e.x_root, e.y_root, items)

    def _blank_menu(self, e):
        self.sel = set()
        self.paint_sel()
        menu = self.os.menu
        if self.in_trash():
            tr = self.fs.trashed()
            menu.show(e.x_root, e.y_root, [
                {'label': 'Restore all', 'icon': '↩', 'disabled': not tr, 'action': lambda: self.restore(self.fs.trashed())},
                {'label': 'Empty Trash', 'icon': '🗑', 'danger': True, 'disabled': not tr,
                 'action': lambda: self.purge(self.fs.trashed())}])
            return
        menu.show(e.x_root, e.y_root, self.new_items() + [
            {'sep': True}, {'label': 'Paste', 'icon': '📋', 'key': 'Ctrl+V', 'disabled': not CLIP['ids'], 'action': self.paste},
            {'label': 'Upload files…', 'icon': '⇧', 'action': lambda: self.os.upload_into(self.cwd)},
            {'label': 'Select all', 'icon': '☑', 'key': 'Ctrl+A', 'action': self.select_all},
            {'label': 'Show as grid' if self.view == 'list' else 'Show as list', 'icon': '▦', 'action': self.toggle_view}])

    def new_items(self):
        os_ = self.os

        def mkf(title, name, content=''):
            v = os_.dialogs.prompt(title, name, ok='Create', validate=os_.valid_name)
            if v is not None:
                n = self.fs.mk(self.cwd, v.strip(), 'f', content)
                self.sel = {n['id']}
                self.render()

        def folder():
            n = os_.new_item(self.cwd, 'd')
            if n:
                self.sel = {n['id']}
                self.render()
        return [{'label': 'New folder', 'icon': '📁', 'action': folder},
                {'label': 'Text file', 'icon': '📃', 'action': lambda: mkf('New text file', 'Untitled.txt')},
                {'label': 'Markdown note', 'icon': '📝', 'action': lambda: mkf('New note', 'Note.md', '# New note\n\n')},
                {'label': 'HTML page', 'icon': '🌐', 'action': lambda: mkf(
                    'New HTML page', 'page.html',
                    '<!doctype html>\n<html>\n<head><meta charset="utf-8"><title>Page</title></head>\n<body>\n  <h1>Hello</h1>\n</body>\n</html>\n')},
                {'label': 'JavaScript file', 'icon': '🧩', 'action': lambda: mkf('New script', 'script.js',
                                                                                'console.log("Hello from Quill");\n')},
                {'label': 'Python file', 'icon': '🐍', 'action': lambda: mkf('New Python file', 'script.py',
                                                                            'print("Hello from Quill")\n')}]

    def new_menu(self):
        b = self.b_new
        self.os.menu.show(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height() + 4, self.new_items())

    # ---------------------------------------------------------- keyboard
    def _bind_keys(self, w):
        mods = ['Control'] + (['Command'] if self.aqua else [])

        def k(seq, fn):
            w.bind(seq, lambda e: (fn(), 'break')[1])
        k('<Return>', self._open_sel)
        k('<KP_Enter>', self._open_sel)
        k('<Delete>', self.trash_sel)
        k('<BackSpace>', self.up)
        k('<F2>', self._rename_sel)
        k('<Escape>', lambda: (self.sel.clear(), self.paint_sel()))
        for m in mods:
            k('<%s-BackSpace>' % m, self.trash_sel)
            for key, fn in (('a', self.select_all), ('c', lambda: self.copy_sel(False)), ('x', lambda: self.copy_sel(True)),
                            ('v', self.paste)):
                k('<%s-%s>' % (m, key), fn)
                k('<%s-%s>' % (m, key.upper()), fn)
        k('<Alt-Left>', self.back)
        k('<Alt-Right>', self.forward)
        for key in ('Left', 'Right', 'Up', 'Down'):
            w.bind('<%s>' % key, lambda e, key=key: (self._arrow(key), 'break')[1])

    def _open_sel(self):
        ns = self.chosen()
        if len(ns) == 1:
            n = ns[0]
            if n['t'] == 'd':
                self.go(n['id'])
            else:
                self.os.open_file(n)

    def _rename_sel(self):
        ns = self.chosen()
        if len(ns) == 1 and not self.in_trash():
            self.os.rename_dialog(ns[0])

    def _arrow(self, key):
        lst = self.items()
        if not lst:
            return
        cur = next((i for i, n in enumerate(lst) if n['id'] in self.sel), -1)
        i = 0 if cur < 0 else cur
        cols = 1 if self.view == 'list' else max(1, self._cols)
        if cur >= 0:
            i += {'Right': 1, 'Left': -1, 'Down': cols, 'Up': -cols}[key]
        i = max(0, min(len(lst) - 1, i))
        self.sel = {lst[i]['id']}
        self.anchor = lst[i]['id']
        self.paint_sel()
        cell = self.cells.get(lst[i]['id'])
        if cell is not None:
            self.area.see(cell)


__all__ = ['App', 'CLIP', 'bind_tree']
