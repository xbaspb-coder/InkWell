"""The non-visual heart of Quill.OS: event bus, saving, and the virtual file system.

Nothing in this module touches the screen, so it can be tested on its own.
The user interface supplies a `scheduler` (Tk's `after`) for delayed saves.
"""

import json
import os
import re
import sys
import tempfile
import threading
import unicodedata

from . import state as st
from .util import (bytes_to_data_url, data_url_to_bytes, ext_of, fmt_bytes, mime_for, now_ms, uid)

EXT = {
    'text': 'txt md log csv json js mjs html htm css qsh xml yml yaml ini tsv svg py'.split(),
    'image': 'png jpg jpeg gif webp bmp svg ico'.split(),
    'audio': 'mp3 wav ogg m4a flac aac oga opus'.split(),
}


# ================================================================ event bus

class Bus:
    def __init__(self):
        self._m = {}

    def on(self, event, fn):
        self._m.setdefault(event, []).append(fn)

        def off():
            lst = self._m.get(event)
            if lst and fn in lst:
                lst.remove(fn)
        return off

    def emit(self, event, arg=None):
        for fn in list(self._m.get(event, ())):
            try:
                fn(arg)
            except Exception:  # one broken listener must not stop the others
                import traceback
                traceback.print_exc()


# ================================================================ where things are saved

def data_dir():
    """The folder that holds Quill's save file.

    QUILL_OS_HOME overrides it; otherwise the usual per-user location for each system.
    """
    env = os.environ.get('QUILL_OS_HOME')
    if env:
        return env
    if sys.platform.startswith('win'):
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'QuillOS')
    if sys.platform == 'darwin':
        return os.path.expanduser('~/Library/Application Support/QuillOS')
    base = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
    return os.path.join(base, 'quill-os')


class Store:
    """Reads and writes the whole state as one JSON file, atomically."""

    def __init__(self, folder=None):
        self.folder = folder or data_dir()
        self.path = os.path.join(self.folder, 'state.json')
        self._lock = threading.Lock()

    def load(self):
        """Return the saved JSON text, or None when nothing has been saved yet."""
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return None

    def save(self, text):
        with self._lock:
            os.makedirs(self.folder, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix='.state-', suffix='.tmp', dir=self.folder)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(text)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise


def to_json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))


# ================================================================ helpers for names

def _sort_key(name):
    """Natural, case- and accent-insensitive order (localeCompare numeric/base)."""
    s = unicodedata.normalize('NFKD', name)
    s = ''.join(c for c in s if not unicodedata.combining(c)).casefold()
    parts = re.split(r'(\d+)', s)
    return [(0, int(p), '') if p.isdigit() else (1, 0, p) for p in parts if p != '']


def kind_of(n):
    if n.get('t') == 'd':
        return 'dir'
    e = ext_of(n.get('n'))
    if e in EXT['image']:
        return 'image'
    if e in EXT['audio']:
        return 'audio'
    if n.get('b'):
        return 'bin'
    return 'text'


def icon_of(n):
    if n.get('t') == 'd':
        return {st.FIXED['pictures']: '🖼️', st.FIXED['music']: '🎵', st.FIXED['documents']: '📄',
                st.FIXED['downloads']: '📥', st.FIXED['desktop']: '🖥️', st.FIXED['projects']: '🧩'}.get(n['id'], '📁')
    e, k = ext_of(n.get('n')), kind_of(n)
    if k == 'image':
        return '🖼️'
    if k == 'audio':
        return '🎵'
    if e == 'md':
        return '📝'
    if e in ('js', 'mjs', 'html', 'htm', 'css', 'json', 'xml', 'yml', 'yaml', 'py'):
        return '🧩'
    if e == 'qsh':
        return '📜'
    if e in ('csv', 'tsv'):
        return '📊'
    return '📦' if k == 'bin' else '📃'


class FSError(Exception):
    pass


# ================================================================ the core

class Core:
    """Holds the state (S), saves it, and provides the file system (fs)."""

    def __init__(self, store=None, scheduler=None):
        self.store = store or Store()
        self.bus = Bus()
        self.S = None
        self.nosave = False
        self.save_status = 'saved'
        self.fs = VFS(self)
        # scheduler(ms, fn) -> handle ; cancel(handle).  Without one, saves happen at once.
        self._schedule = scheduler[0] if scheduler else None
        self._cancel = scheduler[1] if scheduler else None
        self._pending = None
        self._once = set()

    # ---------------------------------------------------- load / save
    def load(self):
        """Load the saved state. Returns an error message if it could not be read."""
        raw, err = None, None
        for _ in range(2):
            try:
                text = self.store.load()
                raw = json.loads(text) if text else None
                err = None
                break
            except Exception as e:  # unreadable file: start empty and never overwrite it
                err = str(e)
        if err:
            self.nosave = True
        self.S = st.normalize_state(raw)
        return err

    def do_save(self):
        if self.S is None or self.nosave:
            return
        try:
            text = to_json(self.S)
        except (TypeError, ValueError):
            return
        if len(text) > st.STORE_LIMIT:
            self.save_status = 'full'
            self.bus.emit('storage')
            self.bus.emit('storage-full')
            return
        try:
            self.store.save(text)
            self.save_status = 'saved'
        except OSError as e:
            self.save_status = 'error'
            print('Quill.OS: save failed:', e, file=sys.stderr)
        self.bus.emit('storage')

    def save(self, now=False):
        if self._pending is not None and self._cancel:
            self._cancel(self._pending)
            self._pending = None
        if now or not self._schedule:
            self.do_save()
            return

        def run():
            self._pending = None
            self.do_save()
        self._pending = self._schedule(350, run)

    def touch(self):
        if self.S is None:
            return
        self.S['meta']['modified'] = now_ms()
        self.save()

    def usage(self):
        try:
            return len(to_json(self.S))
        except (TypeError, ValueError):
            return 0

    # ---------------------------------------------------- notifications
    def add_notification(self, title='Quill', body='', icon='🔔', no_save=False):
        n = {'id': uid(), 't': now_ms(), 'title': title or 'Quill', 'body': body or '', 'icon': icon or '🔔'}
        self.S['notifs'].insert(0, n)
        del self.S['notifs'][60:]
        if not no_save:
            self.save()
        return n

    def unread_count(self):
        seen = self.S['meta'].get('seen') or 0
        return sum(1 for n in self.S['notifs'] if (n.get('t') or 0) > seen)


# ================================================================ virtual file system

class VFS:
    def __init__(self, core):
        self.core = core

    @property
    def S(self):
        return self.core.S

    def _changed(self, arg=None):
        self.core.touch()
        self.core.bus.emit('fs', arg)

    def get(self, id_):
        return self.S['fs'].get(id_)

    def kids(self, id_, trashed=False):
        out = [n for n in self.S['fs'].values() if n.get('p') == id_ and bool(n.get('x')) == bool(trashed)]
        out.sort(key=lambda n: (0 if n['t'] == 'd' else 1, _sort_key(n['n'])))
        return out

    def live(self, n):
        g = 0
        while n is not None and g < 60:
            g += 1
            if n.get('x'):
                return False
            if not n.get('p'):
                return True
            n = self.S['fs'].get(n['p'])
        return n is not None

    def path(self, id_):
        parts = []
        n = self.S['fs'].get(id_)
        g = 0
        while n is not None and n.get('p') and g < 60:
            g += 1
            parts.insert(0, n['n'])
            n = self.S['fs'].get(n['p'])
        return '/' + '/'.join(parts)

    def is_desc(self, id_, anc):
        n = self.S['fs'].get(id_)
        g = 0
        while n is not None and g < 60:
            g += 1
            if n['id'] == anc:
                return True
            n = self.S['fs'].get(n['p']) if n.get('p') else None
        return False

    def child(self, pid, name):
        for n in self.S['fs'].values():
            if n.get('p') == pid and not n.get('x') and n.get('n') == name:
                return n
        return None

    def resolve(self, path, cwd=None):
        fs = self.S['fs']
        if path.startswith('/') or path.startswith('~'):
            cur = fs['root']
        else:
            cur = fs.get(cwd) or fs['root']
        parts = [x for x in re.sub(r'^~', '', path).split('/') if x and x != '.']
        for p in parts:
            if p == '..':
                cur = fs[cur['p']] if cur.get('p') and cur['p'] in fs else cur
                continue
            c = self.child(cur['id'], p)
            if c is None:
                return None
            cur = c
        return cur

    def unique(self, pid, name, ignore_id=None):
        name = re.sub(r'[/\\]', '-', str(name)).strip() or 'Untitled'

        def taken(x):
            c = self.child(pid, x)
            return c is not None and c['id'] != ignore_id

        if not taken(name):
            return name
        m = re.match(r'^(.*?)(\.[^.]+)?$', name, re.S)
        base, ext = m.group(1), m.group(2) or ''
        for i in range(2, 999):
            cand = '%s (%d)%s' % (base, i, ext)
            if not taken(cand):
                return cand
        return base + ' ' + uid() + ext

    def mk(self, pid, name, type_, content=None, extra=None):
        id_, now = uid(), now_ms()
        n = {'id': id_, 'n': self.unique(pid, name), 't': type_, 'p': pid, 'm': now, 'r': now}
        if type_ == 'f':
            n['c'] = '' if content is None else content
        if extra:
            n.update(extra)
        self.S['fs'][id_] = n
        self._changed()
        return n

    def write(self, id_, content, extra=None):
        n = self.S['fs'].get(id_)
        if n is None or n['t'] != 'f':
            return
        n['c'] = content
        n['m'] = now_ms()
        if extra:
            n.update(extra)
        self._changed(id_)

    def rename(self, id_, name):
        n = self.S['fs'].get(id_)
        if n is None or not n.get('p'):
            return None
        n['n'] = self.unique(n['p'], name, id_)
        n['m'] = now_ms()
        self._changed()
        return n

    def move(self, id_, pid):
        n, p = self.S['fs'].get(id_), self.S['fs'].get(pid)
        if n is None or p is None or p['t'] != 'd' or not n.get('p') or self.is_desc(pid, id_) or n['p'] == pid:
            return False
        n['p'] = pid
        n['n'] = self.unique(pid, n['n'], id_)
        n['m'] = now_ms()
        self._changed()
        return True

    def copy(self, id_, pid):
        n = self.S['fs'].get(id_)
        if n is None:
            return None
        if self.is_desc(pid, id_):
            return None

        def dup(src, parent):
            c = dict(src)
            c.update({'id': uid(), 'p': parent, 'r': now_ms(), 'm': now_ms()})
            c.pop('x', None)
            c.pop('xp', None)
            c.pop('xd', None)
            c['n'] = self.unique(parent, src['n'])
            self.S['fs'][c['id']] = c
            if src['t'] == 'd':
                for k in self.kids(src['id']):
                    dup(k, c['id'])
            return c

        r = dup(n, pid)
        self._changed()
        return r

    def trash(self, id_):
        n = self.S['fs'].get(id_)
        if n is None or not n.get('p') or id_ in st.FIXED.values():
            return False
        n['x'] = 1
        n['xp'] = n['p']
        n['xd'] = now_ms()
        self._changed()
        return True

    def restore(self, id_):
        n = self.S['fs'].get(id_)
        if n is None:
            return
        p = self.S['fs'].get(n.get('xp'))
        if p is None or not self.live(p):
            p = self.S['fs'][st.FIXED['documents']]
        n['p'] = p['id']
        for k in ('x', 'xp', 'xd'):
            n.pop(k, None)
        n['n'] = self.unique(n['p'], n['n'], id_)
        self._changed()

    def purge(self, id_):
        fs = self.S['fs']

        def delete(k):
            for c in [c for c in fs.values() if c.get('p') == k]:
                delete(c['id'])
            fs.pop(k, None)

        if id_ in fs and fs[id_].get('p'):
            delete(id_)
        self._changed()

    def trashed(self):
        return [n for n in self.S['fs'].values() if n.get('x')]

    def empty_trash(self):
        for n in list(self.S['fs'].values()):
            if n.get('x') and n['id'] in self.S['fs']:
                self.purge(n['id'])

    def size(self, n):
        if n['t'] == 'f':
            return len(n.get('c') or '')
        return sum(self.size(k) for k in self.S['fs'].values() if k.get('p') == n['id'] and not k.get('x'))

    def all(self):
        return [n for n in self.S['fs'].values() if n.get('p') and self.live(n)]

    def usage(self):
        return self.core.usage()

    # ---------------------------------------------------- the real computer's files
    def import_file(self, path, parent_id):
        """Add a file from the computer (the Python version of the browser's upload)."""
        name = os.path.basename(path)
        try:
            size = os.path.getsize(path)
        except OSError:
            raise FSError('Could not read ' + name + '.')
        e = ext_of(name)
        is_text = e in EXT['text']
        if size > st.FILE_LIMIT:
            raise FSError(name + ' is bigger than 1.5 MB.')
        if self.usage() + size * 1.4 > st.STORE_LIMIT - 200000:
            raise FSError('Not enough storage left for ' + name + '.')
        try:
            with open(path, 'rb') as f:
                data = f.read()
        except OSError:
            raise FSError('Could not read ' + name + '.')
        if not is_text and not e and _looks_like_text(data):
            is_text = True
        if is_text:
            return self.mk(parent_id, name, 'f', data.decode('utf-8', errors='replace'))
        return self.mk(parent_id, name, 'f', bytes_to_data_url(data, mime_for(name)), {'b': 1})

    def file_bytes(self, n):
        """The raw bytes of a file, whether it is text or binary."""
        if n.get('b'):
            return data_url_to_bytes(n.get('c') or '')[0]
        return (n.get('c') or '').encode('utf-8')

    def export_file(self, n, dest_path):
        with open(dest_path, 'wb') as f:
            f.write(self.file_bytes(n))


def _looks_like_text(data):
    if b'\x00' in data[:4096]:
        return False
    try:
        data[:4096].decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False


__all__ = ['Bus', 'Store', 'Core', 'VFS', 'FSError', 'EXT', 'kind_of', 'icon_of', 'data_dir', 'fmt_bytes', 'to_json']
