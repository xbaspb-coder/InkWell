"""XApps — the app store window: discover, install, update and publish apps."""

import tkinter as tk

from .base import AppSpec, Inst
from ..galau import friendly, run_async
from ..ui.overlays import swatches
from ..ui.widgets import Btn, Entry, ScrollArea, Tabs, style_text, tile_image
from ..xapps import COLORS, XAppsError, check_app, register, search
from ..util import fmt_bytes


class App(AppSpec):
    id = 'xapps'
    name = 'XApps'
    icon = 'X'
    bg = ('#ff6a3d', '#c2185b')
    w, h = 780, 540
    single = True
    kw = 'xapps app store apps download install publish market shop'
    about = 'The app store'

    def build(self, ctx):
        return XApps(ctx).inst


class XApps:
    def __init__(self, ctx):
        self.ctx = ctx
        os_ = self.os = ctx.os
        T = self.T = ctx.T
        self.store = os_.xstore
        self.g = os_.galau
        self.tab = 'discover'
        self.rows = None          # the store's list, once loaded
        self.mine = None
        self.error = None
        self.busy = set()         # ids being installed / changed
        self.editing = None       # the publish form: None, 'new' or an app row

        top = tk.Frame(ctx.body, bd=0)
        T.style(top, bg='bg2')
        top.pack(fill='x')
        self.tabs = Tabs(top, T, [('discover', 'Discover'), ('installed', 'Installed'), ('publish', 'Publish')],
                         self.tab, self.go)
        self.tabs.pack(side='left', fill='x', expand=True)
        self.account = tk.Label(top, font=T.font('sans', 12), bd=0, padx=10)
        T.style(self.account, bg='bg2', fg='fg2')
        self.account.pack(side='right')
        self.area = ScrollArea(ctx.body, T, bg='bg1')
        self.area.pack(fill='both', expand=True)
        self.inst = Inst(on_arg=self.on_arg, mem=lambda: 2 * 1024 * 1024)
        self.refresh()

    def on_arg(self, arg):
        if isinstance(arg, dict) and arg.get('tab') in ('discover', 'installed', 'publish'):
            self.go(arg['tab'])

    # ---------------------------------------------------------- loading
    def refresh(self):
        self.error = None
        self.draw()

        def work():
            rows = self.store.browse()
            return rows, (self.store.mine() if self.g.signed_in else [])

        def done(r, e):
            if e is not None:
                self.error = friendly(e)
                self.rows = self.rows or []
            else:
                self.rows, self.mine = r
            self.draw()
        run_async(self.ctx.body, work, done)

    def go(self, tab):
        self.tab = tab
        self.tabs.current = tab
        self.tabs.paint()
        self.editing = None
        self.draw()

    # ---------------------------------------------------------- drawing
    def clear(self):
        for c in self.area.inner.winfo_children():
            c.destroy()
        body = tk.Frame(self.area.inner, bd=0)
        self.T.style(body, bg='bg1')
        body.pack(fill='both', expand=True, padx=18, pady=14)
        return body

    def label(self, parent, text, size=13, fg='fg', bold=False, wrap=0, bg='bg1', **pack):
        lbl = tk.Label(parent, text=text, anchor='w', justify='left', font=self.T.font('sans', size, 'bold' if bold else 'normal'),
                       wraplength=wrap or 0, bd=0)
        self.T.style(lbl, bg=bg, fg=fg)
        lbl.pack(fill='x', **pack)
        return lbl

    def draw(self):
        g = self.g
        self.account.configure(text=('Signed in as ' + g.address) if g.signed_in else 'Not signed in')
        body = self.clear()
        getattr(self, 'draw_' + self.tab)(body)
        self.area.to_top()

    def card(self, parent, row, buttons):
        T = self.T
        c = tk.Frame(parent, bd=0, highlightthickness=1)
        T.on(c, lambda: c.configure(bg=T['bg2'], highlightbackground=T['line']))
        c.pack(fill='x', pady=(0, 8))
        color = row.get('color') or COLORS[0]
        tile = tk.Label(c, bd=0, text=row.get('icon') or '✨', compound='center', fg='#ffffff', font=T.font('sans', 20))
        T.on(tile, lambda: tile.configure(bg=T['bg2'], image=tile_image(self.os.root, color, color, 48, 12, T['bg2'])))
        tile.pack(side='left', padx=12, pady=10)
        right = tk.Frame(c, bd=0)
        T.style(right, bg='bg2')
        right.pack(side='right', padx=10)
        for b in buttons:
            b_ = Btn(right, T, b[0], b[1], kind=b[2] if len(b) > 2 else 'btn', size='sm', bg='bg2')
            b_.pack(side='left', padx=3)
        col = tk.Frame(c, bd=0)
        T.style(col, bg='bg2')
        col.pack(side='left', fill='x', expand=True, pady=8)
        self.label(col, row.get('name') or 'XApp', 14, bold=True, bg='bg2')
        bits = []
        if row.get('owner_name'):
            bits.append('by ' + row['owner_name'])
        if row.get('installs') is not None:
            bits.append('%d install%s' % (row['installs'], '' if row['installs'] == 1 else 's'))
        if row.get('version'):
            bits.append('version %d' % row['version'])
        if 'published' in row and not row['published']:
            bits.append('not published')
        self.label(col, ' · '.join(bits), 11, fg='fg2', bg='bg2')
        if row.get('description'):
            self.label(col, row['description'], 12, fg='fg2', wrap=380, bg='bg2', pady=(3, 0))
        return c

    def message(self, body, text, small=None):
        self.label(body, text, 14, fg='fg2', pady=(30, 4)).configure(anchor='center', justify='center')
        if small:
            self.label(body, small, 12, fg='fg2', wrap=480).configure(anchor='center', justify='center')

    # ---------------------------------------------------------- Discover
    def draw_discover(self, body):
        T = self.T
        bar = tk.Frame(body, bd=0)
        T.style(bar, bg='bg1')
        bar.pack(fill='x', pady=(0, 12))
        self.q = Entry(bar, T, getattr(self, 'qtext', ''), placeholder='Search apps…', width=28)
        self.q.pack(side='left', fill='x', expand=True, ipady=4)
        self.q.bind('<KeyRelease>', lambda e: self._search_later())
        Btn(bar, T, '⟳ Refresh', self.refresh, size='sm', bg='bg1').pack(side='left', padx=(8, 0))
        self.list_box = tk.Frame(body, bd=0)
        T.style(self.list_box, bg='bg1')
        self.list_box.pack(fill='x')
        self.fill_discover()

    def _search_later(self):
        self.qtext = self.q.get()
        job = getattr(self, '_qjob', None)
        if job:
            self.ctx.body.after_cancel(job)
        self._qjob = self.ctx.body.after(250, self.fill_discover)

    def fill_discover(self):
        self._qjob = None
        box = self.list_box
        for c in box.winfo_children():
            c.destroy()
        if self.rows is None:
            self.message(box, 'Loading XApps…')
            return
        if self.error and not self.rows:
            self.message(box, 'XApps could not load.', self.error)
            return
        rows = search(self.rows, getattr(self, 'qtext', ''))
        if not rows:
            self.message(box, 'No apps yet.' if not self.rows else 'No apps match your search.',
                         'Make one in Glyph as an HTML file and share it from the Publish tab.' if not self.rows else None)
            return
        for row in rows:
            self.card(box, row, self.buttons_for(row))

    def buttons_for(self, row):
        i = row['id']
        if i in self.busy:
            return [('Working…', lambda: None)]
        if self.store.installed(i):
            out = [('Open', lambda: self.open(i), 'pri')]
            if (row.get('version') or 0) > (self.store.state[i].get('version') or 0):
                out.insert(0, ('⬆ Update', lambda: self.install(i)))
            return out
        return [('⬇ Install', lambda: self.install(i), 'pri')]

    # ---------------------------------------------------------- install, open, remove
    def install(self, app_id):
        os_ = self.os
        if not self.store.installed(app_id):
            if not os_.dialogs.confirm('Install this app?', 'XApps are made by other people. An app runs in its own '
                                       'window and cannot see your files, but only install apps you trust.',
                                       ok='Install'):
                return
        self.busy.add(app_id)
        self.draw()

        def work():
            row = self.store.download(app_id)
            fresh = not self.store.installed(app_id)
            self.store.install(row)
            if fresh:
                self.store.count_install(app_id)
            return row

        def done(row, e):
            self.busy.discard(app_id)
            if e is not None:
                os_.toast('Could not install: ' + friendly(e), '⚠️')
            else:
                os_.touch()
                register(os_, self.store)
                os_.spine.render()
                os_.toast('%s is installed. Find it with Ctrl+K.' % row.get('name', 'The app'), '⬇')
            self.draw()
        run_async(self.ctx.body, work, done)

    def open(self, app_id):
        self.os.wm.open('xapp:' + app_id)

    def uninstall(self, app_id):
        os_ = self.os
        name = (self.store.state.get(app_id) or {}).get('name', 'this app')
        if not os_.dialogs.confirm('Uninstall %s?' % name, 'Its saved data on this computer is kept until you install '
                                   'it again or remove Quill\'s data folder.', ok='Uninstall', danger=True):
            return
        self.store.uninstall(app_id)
        os_.touch()
        register(os_, self.store)
        os_.spine.render()
        os_.toast(name + ' was uninstalled', '🗑')
        self.draw()

    # ---------------------------------------------------------- Installed
    def draw_installed(self, body):
        st = self.store.state
        if not st:
            self.message(body, 'No apps installed yet.', 'Find some in Discover.')
            return
        latest = {r['id']: r.get('version') for r in (self.rows or [])}
        for app_id, meta in sorted(st.items(), key=lambda kv: (kv[1].get('name') or '').lower()):
            row = dict(meta, id=app_id)
            row.pop('installs', None)
            buttons = [('Open', lambda i=app_id: self.open(i), 'pri'), ('Uninstall', lambda i=app_id: self.uninstall(i))]
            if (latest.get(app_id) or 0) > (meta.get('version') or 0):
                buttons.insert(0, ('⬆ Update', lambda i=app_id: self.install(i)))
            self.card(body, row, buttons)

    # ---------------------------------------------------------- Publish
    def draw_publish(self, body):
        if not self.g.signed_in:
            self.draw_sign_in(body)
            return
        if self.editing is not None:
            self.draw_form(body)
            return
        T = self.T
        row = tk.Frame(body, bd=0)
        T.style(row, bg='bg1')
        row.pack(fill='x', pady=(0, 12))
        self.label(row, 'Your apps', 16, bold=True).pack(side='left')
        Btn(row, T, 'Sign out', self.sign_out, size='sm', bg='bg1').pack(side='right')
        Btn(row, T, '+ New app', lambda: self.edit('new'), kind='pri', size='sm', bg='bg1').pack(side='right', padx=6)
        if self.mine is None:
            self.message(body, 'Loading…')
            return
        if not self.mine:
            self.message(body, 'You have not published any apps yet.',
                         'An app is a single HTML file (with its CSS and JavaScript inside). Write it in Glyph, save '
                         'it, then press “New app”.')
            return
        for r in self.mine:
            pub = r.get('published')
            self.card(body, r, [('Edit', lambda r=r: self.edit(r)),
                                ('Hide' if pub else 'Publish', lambda r=r: self.set_published(r, not r.get('published'))),
                                ('Delete', lambda r=r: self.delete(r), 'dng')])

    def draw_sign_in(self, body):
        T = self.T
        self.label(body, 'Publish your own apps', 18, bold=True, pady=(4, 4))
        self.label(body, 'Sign in with your Galau account (the same one as OG Browser and Galau Mail). Only verified '
                         'accounts can publish.', 12, fg='fg2', wrap=520, pady=(0, 14))
        form = tk.Frame(body, bd=0)
        T.style(form, bg='bg1')
        form.pack(anchor='w')
        login = Entry(form, T, '', placeholder='name@gla.ml or username', width=30)
        login.pack(anchor='w', ipady=4, pady=(0, 8))
        pw = Entry(form, T, '', placeholder='Password', show='•', width=30)
        pw.pack(anchor='w', ipady=4)
        msg = self.label(form, '', 12, fg='fg2', wrap=420, pady=(8, 8))
        b = Btn(form, T, 'Sign in', None, kind='pri', bg='bg1')
        b.pack(anchor='w')

        def go(_e=None):
            if b.disabled:
                return
            b.set_disabled(True)
            msg.configure(text='Signing in…')
            user, password = login.get(), pw.get()

            def done(_r, e):
                b.set_disabled(False)
                if e is not None:
                    msg.configure(text=friendly(e))
                    return
                self.os.toast('Signed in as ' + self.g.address, '✅')
                self.mine = None
                self.refresh()
            run_async(self.ctx.body, lambda: self.g.sign_in(user, password), done)
        b.command = go
        pw.bind('<Return>', go)
        login.bind('<Return>', lambda e: pw.focus_set())
        self.label(body, 'No account yet? Create one in OG Browser at galaumail.og.', 12, fg='fg2', pady=(16, 0))
        Btn(body, T, '🌐 Open Galau Mail', lambda: self.os.open_web({'type': 'og', 'host': 'galaumail.og', 'path': '/'}),
            size='sm', bg='bg1').pack(anchor='w', pady=(6, 0))

    def sign_out(self):
        self.g.sign_out()
        self.mine = None
        self.draw()

    def edit(self, row):
        self.editing = row
        self.form = {'html': None, 'file': None}
        if isinstance(row, dict):
            self.form.update({k: row.get(k) for k in ('name', 'description', 'icon', 'color')})
        else:
            self.form.update({'name': '', 'description': '', 'icon': '✨', 'color': COLORS[0]})
        self.draw()

    def draw_form(self, body):
        T, os_ = self.T, self.os
        f = self.form
        new = self.editing == 'new'
        self.label(body, 'New app' if new else 'Edit ' + (self.editing.get('name') or 'app'), 18, bold=True, pady=(0, 12))
        grid = tk.Frame(body, bd=0)
        T.style(grid, bg='bg1')
        grid.pack(fill='x')

        def field(r, title):
            lbl = tk.Label(grid, text=title, anchor='w', font=T.font('sans', 12), bd=0)
            T.style(lbl, bg='bg1', fg='fg2')
            lbl.grid(row=r, column=0, sticky='nw', pady=6, padx=(0, 12))
        field(0, 'Name')
        name = Entry(grid, T, f['name'], placeholder='My app', width=30)
        name.grid(row=0, column=1, sticky='w', ipady=3)
        field(1, 'Icon')
        icon = Entry(grid, T, f['icon'], placeholder='✨', width=6)
        icon.grid(row=1, column=1, sticky='w', ipady=3)
        field(2, 'Colour')

        def pick(c):
            f['color'] = c
            self.draw()
        swatches(grid, T, COLORS, f['color'], pick, 'bg1', 26).grid(row=2, column=1, sticky='w')
        field(3, 'Description')
        desc = tk.Text(grid, height=3, width=40, wrap='word', bd=0, highlightthickness=1, padx=6, pady=4,
                       font=T.font('sans', 12))
        style_text(T, desc, bg='bg0')
        desc.insert('1.0', f['description'] or '')
        desc.grid(row=3, column=1, sticky='we')
        field(4, 'HTML file')
        frow = tk.Frame(grid, bd=0)
        T.style(frow, bg='bg1')
        frow.grid(row=4, column=1, sticky='w')
        chosen = tk.Label(frow, bd=0, font=T.font('sans', 12),
                          text=(f['file'] + ' · ' + fmt_bytes(len(f['html'].encode('utf-8')))) if f['html'] else
                          ('No file chosen' if new else 'Keep the current version'))
        T.style(chosen, bg='bg1', fg='fg2')

        def keep():
            f['name'], f['icon'] = name.get(), icon.get()
            f['description'] = desc.get('1.0', 'end-1c')

        def choose():
            keep()
            fid = os_.dialogs.pick_file(lambda n: n['n'].lower().endswith(('.html', '.htm')) and not n.get('b'),
                                        'Choose the app\'s HTML file')
            if fid:
                n = os_.fs.get(fid)
                f['html'], f['file'] = n.get('c') or '', n['n']
            self.draw()
        Btn(frow, T, '📄 Choose…', choose, size='sm', bg='bg1').pack(side='left', padx=(0, 8))
        chosen.pack(side='left')
        grid.columnconfigure(1, weight=1)
        msg = self.label(body, 'Everyone can see and install published apps. The file is checked to be at most 1 MB.',
                         12, fg='fg2', wrap=520, pady=(12, 8))
        row = tk.Frame(body, bd=0)
        T.style(row, bg='bg1')
        row.pack(fill='x')
        save = Btn(row, T, 'Publish' if new else 'Save', None, kind='pri', bg='bg1')
        save.pack(side='left')
        Btn(row, T, 'Cancel', lambda: self.edit_done(), bg='bg1').pack(side='left', padx=8)

        def go():
            keep()
            try:
                check_app(f['name'], f['description'], f['icon'], f['color'], f['html'])
                if new and not f['html']:
                    raise XAppsError('Choose the app\'s HTML file.')
            except XAppsError as e:
                msg.configure(text=str(e))
                return
            save.set_disabled(True)
            msg.configure(text='Publishing…' if new else 'Saving…')

            def work():
                if new:
                    return self.store.publish(f['name'], f['description'], f['icon'], f['color'], f['html'])
                fields = {k: f[k] for k in ('name', 'description', 'icon', 'color')}
                if f['html']:
                    fields['html'] = f['html']
                return self.store.change(self.editing['id'], **fields)

            def done(_r, e):
                if e is not None:
                    save.set_disabled(False)
                    msg.configure(text=friendly(e))
                    return
                os_.toast('Published to XApps' if new else 'Saved', '✅')
                self.edit_done()
                self.refresh()
            run_async(self.ctx.body, work, done)
        save.command = go

    def edit_done(self):
        self.editing = None
        self.draw()

    def set_published(self, row, value):
        def done(_r, e):
            if e is not None:
                self.os.toast(friendly(e), '⚠️')
            self.refresh()
        run_async(self.ctx.body, lambda: self.store.change(row['id'], published=value), done)

    def delete(self, row):
        if not self.os.dialogs.confirm('Delete %s from XApps?' % row.get('name', 'this app'),
                                       'People who installed it keep their copy, but nobody can install it any more.',
                                       ok='Delete', danger=True):
            return

        def done(_r, e):
            if e is not None:
                self.os.toast(friendly(e), '⚠️')
            else:
                self.os.toast('Deleted from XApps', '🗑')
            self.refresh()
        run_async(self.ctx.body, lambda: self.store.remove(row['id']), done)
