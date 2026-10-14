"""Starting and steering web windows (webview.py) from Quill.OS.

Each WebProcess is one window program. Messages from it are read on a
background thread and handed to the Tk side by poll(), which Quill calls often.
"""

import json
import os
import queue
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
OG_HTML = os.path.join(HERE, 'web', 'og_browser.html')

_available = None


def available():
    """(True, '') when WebKitGTK can be used, else (False, the reason)."""
    global _available
    if _available is None:
        try:
            import gi
            gi.require_version('Gtk', '3.0')
            try:
                gi.require_version('WebKit2', '4.1')
            except ValueError:
                gi.require_version('WebKit2', '4.0')
            _available = (True, '')
        except (ImportError, ValueError) as e:
            _available = (False, 'the web engine (WebKitGTK) is not installed: %s' % e)
    return _available


def og_address(target):
    """The OG Browser address for an open_web() target, or None for a plain web page."""
    kind = target.get('type')
    if kind == 'og':
        path = target.get('path') or '/'
        return target['host'] + ('' if path == '/' else path)
    if kind == 'search':
        from urllib.parse import quote
        return 'browser://search?q=' + quote(target.get('q') or '')
    if kind == 'directory':
        return 'browser://sites'
    if kind == 'home':
        return 'browser://home'
    return None


class WebProcess:
    def __init__(self, mode, data_dir, file=None, url=None, open_address=None, title=''):
        cmd = [sys.executable, '-m', 'quill_os.webview', '--mode', mode, '--data', os.path.abspath(data_dir)]
        if file:
            cmd += ['--file', os.path.abspath(file)]
        if url:
            cmd += ['--url', url]
        if open_address:
            cmd += ['--open', open_address]
        if title:
            cmd += ['--title', title]
        env = dict(os.environ)
        env['PYTHONPATH'] = os.path.dirname(HERE) + os.pathsep + env.get('PYTHONPATH', '')
        env.setdefault('PYTHONWARNINGS', 'ignore')
        self.events = queue.Queue()
        self.alive = True
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     env=env, cwd=os.path.dirname(HERE))
        threading.Thread(target=self._read, name='quill-web', daemon=True).start()

    def _read(self):
        try:
            for raw in self.proc.stdout:
                try:
                    self.events.put(json.loads(raw.decode('utf-8')))
                except ValueError:
                    continue
        except (OSError, ValueError):
            pass
        self.proc.wait()
        self.alive = False
        self.events.put({'ev': 'closed'})

    def send(self, **msg):
        if not self.alive:
            return False
        try:
            self.proc.stdin.write((json.dumps(msg) + '\n').encode('utf-8'))
            self.proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def poll(self):
        """Every message received since the last call."""
        out = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out

    def show(self):
        return self.send(cmd='show')

    def hide(self):
        return self.send(cmd='hide')

    def open(self, address):
        return self.send(cmd='open', address=address)

    def quit(self):
        if self.send(cmd='quit'):
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        elif self.proc.poll() is None:
            self.proc.kill()
        self.alive = False
