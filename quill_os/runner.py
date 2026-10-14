"""Running code from Glyph and the terminal in a separate process.

The browser version ran JavaScript in a sandboxed web worker.  Here the code
runs as a child process — JavaScript through Node.js (when it is installed)
and Python through the same Python that runs Quill — with the same rules:
output arrives line by line, Stop ends it, and it is stopped after 60 seconds.

The callback receives ('log' | 'error', text), then ('done', '') when the
program finishes and finally ('end', reason).
"""

import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time

TIME_LIMIT = 60.0

JS_PRE = '(async()=>{\n'
JS_POST = '\n})().catch(e=>{console.error(e&&e.stack?e.stack:String(e));process.exitCode=1;});\n'


def node_path():
    return shutil.which('node') or shutil.which('nodejs')


def python_path():
    exe = sys.executable
    if getattr(sys, 'frozen', False) or not exe:
        exe = shutil.which('python3') or shutil.which('python') or exe
    return exe


class Runner:
    """Runs one program. `poll()` must be called regularly (the UI uses a timer)."""

    def __init__(self, code, lang, callback):
        self.cb = callback
        self.q = queue.Queue()
        self.proc = None
        self.ended = False
        self.finished = False
        self.reason = ''
        self.t0 = time.monotonic()
        self.tmpdir = tempfile.mkdtemp(prefix='quill-run-')
        try:
            if lang == 'py':
                path = os.path.join(self.tmpdir, 'main.py')
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(code)
                args = [python_path(), '-u', path]
            else:
                node = node_path()
                if not node:
                    self._fail('Running JavaScript needs Node.js, which is not installed on this computer. '
                               'Install it from nodejs.org, or write Python (.py) instead.')
                    return
                path = os.path.join(self.tmpdir, 'main.js')
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(JS_PRE + code + JS_POST)
                args = [node, path]
            env = dict(os.environ)
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PYTHONUNBUFFERED'] = '1'
            kwargs = {}
            if sys.platform.startswith('win'):
                kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            self.proc = subprocess.Popen(args, cwd=self.tmpdir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, env=env, **kwargs)
        except OSError as e:
            self._fail('Could not start the program: %s' % e)
            return
        self._readers = [threading.Thread(target=self._pump, args=(self.proc.stdout, 'log'), daemon=True),
                         threading.Thread(target=self._pump, args=(self.proc.stderr, 'error'), daemon=True)]
        for t in self._readers:
            t.start()

    def _fail(self, message):
        self.q.put(('error', message))
        self.q.put(('done', ''))
        self.finished = True
        self.reason = 'error'

    def _pump(self, stream, kind):
        try:
            for raw in iter(stream.readline, b''):
                self.q.put((kind, raw.decode('utf-8', errors='replace').rstrip('\r\n')))
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass

    @property
    def running(self):
        return not self.ended

    def poll(self):
        """Deliver waiting output; returns False once the program has ended."""
        if self.ended:
            return False
        self._drain()
        if self.proc is not None and not self.finished:
            if self.proc.poll() is not None and all(not t.is_alive() for t in self._readers):
                self._drain()
                self.finished = True
                self.cb('done', '')
                self.reason = self.reason or 'finished'
            elif time.monotonic() - self.t0 > TIME_LIMIT:
                self.stop('time limit (60 s)')
                return False
        if self.finished:
            self._end(self.reason or 'finished')
            return False
        return True

    def _drain(self):
        while True:
            try:
                kind, text = self.q.get_nowait()
            except queue.Empty:
                return
            if kind == 'done':
                self.cb('done', '')
            else:
                self.cb(kind, text)

    def stop(self, why='stopped'):
        if self.ended:
            return
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.kill()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        self._drain()
        self._end(why)

    def _end(self, why):
        if self.ended:
            return
        self.ended = True
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        self.cb('end', why)
