"""OG Browser and web pages: shown by the web engine in their own window (see webview.py).

The Quill window that stands for them shows what is happening and has buttons to
bring the web window back or close it. Closing the web window closes this one too.
"""

import os
import tkinter as tk
import webbrowser

from .base import AppSpec, Inst
from .. import web
from ..ui.widgets import Btn

POLL_MS = 150


def web_dir(os_, name):
    return os.path.join(os.path.abspath(os_.core.store.folder), 'web', name)


class WebLauncher:
    """The Quill side of one web window."""

    def __init__(self, ctx, mode, title, icon, data_name, file=None, url=None, open_address=None):
        self.ctx = ctx
        os_ = self.os = ctx.os
        T = self.T = ctx.T
        self.title = title
        self.proc = None
        self._job = None
        box = tk.Frame(ctx.body, bd=0)
        T.style(box, bg='bg1')
        box.pack(fill='both', expand=True)
        inner = tk.Frame(box, bd=0)
        T.style(inner, bg='bg1')
        inner.place(relx=0.5, rely=0.5, anchor='center')
        big = tk.Label(inner, text=icon, font=T.font('sans', 40), bd=0)
        T.style(big, bg='bg1', fg='fg2')
        big.pack()
        self.msg = tk.Label(inner, font=T.font('sans', 15), bd=0, wraplength=460, justify='center')
        T.style(self.msg, bg='bg1', fg='fg')
        self.msg.pack(pady=(8, 2))
        self.small = tk.Label(inner, font=T.font('sans', 12), bd=0, wraplength=460, justify='center')
        T.style(self.small, bg='bg1', fg='fg2')
        self.small.pack()
        row = tk.Frame(inner, bd=0)
        T.style(row, bg='bg1')
        row.pack(pady=(14, 0))
        self.b_show = Btn(row, T, '↗ Show ' + title, self.show, kind='pri', bg='bg1')
        self.b_show.pack(side='left', padx=4)
        self.b_close = Btn(row, T, '✕ Close ' + title, self.close, bg='bg1')
        self.b_close.pack(side='left', padx=4)
        self.inst = Inst(on_close=self.on_close, on_arg=self.on_arg, mem=lambda: 120 * 1024 * 1024)

        ok, why = web.available()
        if not ok:
            self.b_show.set_disabled(True)
            self.b_close.pack_forget()
            if url:
                self.msg.configure(text='Opening the page in the computer\'s own browser.')
                self.small.configure(text=why)
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
            else:
                self.msg.configure(text=title + ' cannot start here.')
                self.small.configure(text='It needs %s. On the Raspberry Pi, run pi/install.sh again.' % why)
            return
        self.msg.configure(text='Starting %s…' % title)
        self.small.configure(text='It opens in its own window. Press “◀ Quill.OS” there to come back here.')
        self.proc = web.WebProcess(mode, web_dir(os_, data_name), file=file, url=url, open_address=open_address,
                                   title=title)
        self._job = ctx.body.after(POLL_MS, self._poll)

    def _poll(self):
        self._job = None
        if self.proc is None or not self.ctx.alive:
            return
        for ev in self.proc.poll():
            kind = ev.get('ev')
            if kind == 'shown':
                self.msg.configure(text='%s is open in its own window.' % self.title)
            elif kind == 'hidden':
                self.msg.configure(text='%s is waiting in the background.' % self.title)
                self.small.configure(text='Press “Show” to go back to it. Close it to free the memory it uses.')
            elif kind == 'title' and ev.get('title'):
                self.ctx.set_title(ev['title'])
            elif kind == 'error':
                self.msg.configure(text=self.title + ' could not start.')
                self.small.configure(text=ev.get('error') or '')
            elif kind == 'closed':
                self.proc = None
                self.ctx.close()
                return
        self._job = self.ctx.body.after(POLL_MS, self._poll)

    def show(self):
        if self.proc is not None:
            self.proc.show()

    def on_arg(self, arg):
        if self.proc is None or not isinstance(arg, dict):
            return
        if arg.get('open'):
            self.proc.open(arg['open'])
        else:
            self.proc.show()

    def close(self):
        self.ctx.close()

    def on_close(self):
        if self._job is not None:
            try:
                self.ctx.body.after_cancel(self._job)
            except (tk.TclError, ValueError):
                pass
            self._job = None
        if self.proc is not None:
            proc, self.proc = self.proc, None
            proc.quit()


class App(AppSpec):
    id = 'ogb'
    name = 'OG Browser'
    icon = '🌐'
    bg = ('#4d7cff', '#1a2f8f')
    w, h = 560, 360
    single = True
    kw = 'og browser web internet sites search tabs mail ferret lifecraft lifegames reminders galau'
    about = 'The OG Browser'

    def build(self, ctx):
        arg = ctx.arg if isinstance(ctx.arg, dict) else {}
        return WebLauncher(ctx, 'og', 'OG Browser', '🌐', 'og', file=web.OG_HTML,
                           open_address=arg.get('open')).inst


class WebPage(AppSpec):
    id = 'webpage'
    name = 'Web page'
    icon = '🔗'
    bg = ('#7a8699', '#3b4456')
    w, h = 560, 360
    hidden = True               # opened by links, not from the app list
    about = 'A web page'

    def build(self, ctx):
        url = (ctx.arg or {}).get('url') or 'about:blank'
        ctx.set_title('Web page')
        return WebLauncher(ctx, 'url', 'Web page', '🔗', 'pages', url=url).inst
