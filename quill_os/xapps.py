"""XApps — the app store for Quill.OS: everything except the window.

An XApp is one HTML file that people publish to Galau's database (table public.xapps).
Installing one keeps a copy of the file in Quill's data folder, so it also works offline;
it runs in its own web window with no access to the laptop's files (see webview.py).

The list of installed apps lives in Quill's saved state (S['xapps']); the HTML files
themselves do not, because they would fill the 4 MB of space that state has.
"""

import os
import re
import time

from .apps.base import AppSpec

COLS = 'id,name,description,icon,color,owner_id,owner_name,version,installs,published,updated_at'
MAX_HTML = 1000000
MAX_NAME = 40
MAX_DESC = 600
COLORS = ['#4d7cff', '#2fb67c', '#e8b04a', '#e5534b', '#a970ff', '#ff7ac6', '#36c5d6', '#7a8699']
_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')
_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


class XAppsError(Exception):
    pass


def check_app(name, description, icon, color, html):
    """Clean and check what someone wants to publish; returns the row to send."""
    name = (name or '').strip()
    if not name:
        raise XAppsError('Give the app a name.')
    if len(name) > MAX_NAME:
        raise XAppsError('The name can be at most %d characters.' % MAX_NAME)
    description = (description or '').strip()
    if len(description) > MAX_DESC:
        raise XAppsError('The description can be at most %d characters.' % MAX_DESC)
    icon = (icon or '').strip() or '✨'
    if len(icon) > 8:
        raise XAppsError('The icon can be at most 8 characters (one emoji is best).')
    color = color if color and _HEX.match(color) else COLORS[0]
    row = {'name': name, 'description': description, 'icon': icon, 'color': color}
    if html is not None:
        size = len(html.encode('utf-8'))
        if size == 0:
            raise XAppsError('The HTML file is empty.')
        if size > MAX_HTML:
            raise XAppsError('The HTML file is too large (at most 1 MB).')
        row['html'] = html
    return row


def search(rows, q):
    """The rows matching every word of q, in name, description or author."""
    words = [w for w in (q or '').lower().split() if w]
    if not words:
        return list(rows)
    out = []
    for r in rows:
        text = ' '.join(str(r.get(k) or '') for k in ('name', 'description', 'owner_name')).lower()
        if all(w in text for w in words):
            out.append(r)
    return out


class Store:
    """Talks to the online store and keeps the installed apps."""

    def __init__(self, galau, folder, state):
        self.g = galau
        self.folder = os.path.join(os.path.abspath(folder), 'xapps')
        self.state = state          # the dict S['xapps']: id -> what is installed

    # ---------------------------------------------------------- online (call these on a background thread)
    def browse(self):
        return self.g.select('xapps', {'select': COLS, 'published': 'eq.true', 'order': 'installs.desc,updated_at.desc',
                                       'limit': '200'}, auth=self.g.signed_in)

    def mine(self):
        if not self.g.signed_in:
            return []
        return self.g.select('xapps', {'select': COLS, 'owner_id': 'eq.' + self.g.user_id, 'order': 'updated_at.desc'})

    def latest(self, ids):
        """id -> version for the given apps that are still published."""
        ids = [i for i in ids if _UUID.match(i)]
        if not ids:
            return {}
        rows = self.g.select('xapps', {'select': 'id,version', 'id': 'in.(%s)' % ','.join(ids)}, auth=self.g.signed_in)
        return {r['id']: r['version'] for r in rows}

    def download(self, app_id):
        if not _UUID.match(app_id or ''):
            raise XAppsError('That is not an XApps app.')
        rows = self.g.select('xapps', {'select': COLS + ',html', 'id': 'eq.' + app_id}, auth=self.g.signed_in)
        if not rows:
            raise XAppsError('This app is no longer in XApps.')
        return rows[0]

    def count_install(self, app_id):
        if self.g.signed_in:
            try:
                self.g.rpc('xapps_install', {'app': app_id})
            except Exception:
                pass             # the count is a nicety; installing still worked

    def publish(self, name, description, icon, color, html):
        if not self.g.signed_in:
            raise XAppsError('Sign in with your Galau account to publish.')
        if self.g.rpc('is_verified') is not True:
            raise XAppsError('Your Galau account is not verified yet. Open Galau Mail in OG Browser to verify it, '
                             'then publish again.')
        return self.g.insert('xapps', check_app(name, description, icon, color, html))

    def change(self, app_id, **fields):
        allowed = {k: v for k, v in fields.items() if k in ('name', 'description', 'icon', 'color', 'html', 'published')}
        if any(k in allowed for k in ('name', 'description', 'icon', 'color', 'html')):
            cur = dict(fields)
            row = check_app(cur.get('name'), cur.get('description'), cur.get('icon'), cur.get('color'), cur.get('html'))
            allowed.update({k: row[k] for k in row if k in allowed})
        rows = self.g.update('xapps', {'id': 'eq.' + app_id}, allowed)
        if not rows:
            raise XAppsError('Only the person who published an app can change it.')
        return rows[0]

    def remove(self, app_id):
        rows = self.g.delete('xapps', {'id': 'eq.' + app_id})
        if not rows:
            raise XAppsError('Only the person who published an app can delete it.')

    # ---------------------------------------------------------- installed apps (local)
    def path(self, app_id):
        return os.path.join(self.folder, app_id + '.html')

    def installed(self, app_id):
        return app_id in self.state and os.path.exists(self.path(app_id))

    def install(self, row):
        """Keep a downloaded app (a row that includes its html)."""
        if not _UUID.match(row.get('id') or ''):
            raise XAppsError('That is not an XApps app.')
        html = row.get('html') or ''
        os.makedirs(self.folder, exist_ok=True)
        tmp = self.path(row['id']) + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(html)
        os.replace(tmp, self.path(row['id']))
        meta = {k: row.get(k) for k in ('name', 'description', 'icon', 'color', 'owner_name', 'version')}
        meta['installed'] = int(time.time() * 1000)
        self.state[row['id']] = meta
        return meta

    def uninstall(self, app_id):
        self.state.pop(app_id, None)
        try:
            os.remove(self.path(app_id))
        except OSError:
            pass


class XAppSpec(AppSpec):
    """An installed XApp, as Quill's window manager sees it."""

    single = True
    w, h = 560, 360

    def __init__(self, app_id, meta, store):
        self.app_id = app_id
        self.id = 'xapp:' + app_id
        self.name = meta.get('name') or 'XApp'
        self.icon = meta.get('icon') or '✨'
        color = meta.get('color') if _HEX.match(meta.get('color') or '') else COLORS[0]
        self.bg = (color, color)
        self.kw = 'xapps app ' + (meta.get('description') or '')
        self.about = 'From XApps' + (', by ' + meta['owner_name'] if meta.get('owner_name') else '')
        self.store = store

    def build(self, ctx):
        from .apps.ogb import WebLauncher
        return WebLauncher(ctx, 'xapp', self.name, self.icon, 'xapp-' + self.app_id,
                           file=self.store.path(self.app_id)).inst


def register(os_, store):
    """Make Quill's app list match what is installed (call after installing or removing)."""
    for app_id in [i for i in os_.apps if i.startswith('xapp:')]:
        if app_id[5:] not in store.state:
            for w in [w for w in os_.wm.list if w.app == app_id]:
                os_.wm.close(w)
            del os_.apps[app_id]
    for app_id, meta in store.state.items():
        if os.path.exists(store.path(app_id)):
            os_.apps['xapp:' + app_id] = XAppSpec(app_id, meta, store)
    dock = os_.S['set'].get('dock') or []
    os_.S['set']['dock'] = [i for i in dock if not i.startswith('xapp:') or i in os_.apps]
