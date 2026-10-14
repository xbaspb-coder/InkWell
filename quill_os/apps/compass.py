"""Compass — open web pages.

The browser version showed pages in an inline frame. Tk cannot draw web pages,
so Compass keeps the same address bar and history and opens each page in the
computer's own web browser.
"""

import re
import tkinter as tk

from .base import AppSpec, Inst
from ..ui.widgets import Btn, Entry, ScrollArea

OG_HOST = re.compile(r'^[a-z0-9-]+(\.[a-z0-9-]+)*\.(og|gov|auth|roots|create|os)(/\S*)?$', re.I)
WEB = re.compile(r'^[^\s/]+\.[a-z]{2,}(:\d+)?(/\S*)?$', re.I)


class App(AppSpec):
    id = 'compass'
    name = 'Compass'
    icon = '🧭'
    bg = ('#6c8cff', '#2c3fa8')
    w, h = 820, 560
    kw = 'web browser internet page website url view'
    about = 'Open web pages'

    def build(self, ctx):
        os_, T = ctx.os, ctx.T
        hist, pos = [], [-1]
        bar = tk.Frame(ctx.body, bd=0)
        T.style(bar, bg='bg2')
        bar.pack(fill='x')
        sep = tk.Frame(ctx.body, height=1, bd=0)
        T.style(sep, bg='line')
        sep.pack(fill='x')
        inp = Entry(bar, T, placeholder='Type a web address or a search')
        body = tk.Frame(ctx.body, bd=0)
        T.style(body, bg='bg1')
        body.pack(fill='both', expand=True)

        def draw():
            for c in body.winfo_children():
                c.destroy()
            if not hist:
                os_.empty_state(body, '🧭', 'Type an address above.',
                                'Pages open in your web browser. Names ending in .og are OG sites, which open inside '
                                'OG Browser.')
                return
            area = ScrollArea(body, T, bg='bg1')
            area.pack(fill='both', expand=True, padx=12, pady=12)
            t = tk.Label(area.inner, text='Pages you opened', anchor='w', font=T.font('sans', 11))
            T.style(t, bg='bg1', fg='fg2')
            t.pack(fill='x', pady=(0, 6))
            for i, url in reversed(list(enumerate(hist))):
                row = Btn(area.inner, T, ('➜  ' if i == pos[0] else '     ') + url, lambda u=url: nav(u, True),
                          kind='flat', bg='bg1', anchor='w')
                row.pack(fill='x')

        def nav(url, from_hist=False):
            inp.set(url)
            if not from_hist:
                del hist[pos[0] + 1:]
                hist.append(url)
                pos[0] = len(hist) - 1
            else:
                pos[0] = hist.index(url) if url in hist else pos[0]
            os_.open_web({'type': 'url', 'url': url})
            ctx.set_title('Compass — ' + re.sub(r'^https?://', '', url)[:40])
            draw()

        def go(t=None, new_tab=False):
            t = (t if t is not None else inp.get()).strip()
            if not t:
                return
            if OG_HOST.match(t):
                m = re.match(r'^([^/]+)(/.*)?$', t)
                os_.open_web({'type': 'og', 'host': m.group(1).lower(), 'path': m.group(2) or '/'})
                os_.toast('Opening ' + m.group(1) + ' in the browser…', '🧭')
                return
            if re.match(r'^https?://', t, re.I) or WEB.match(t):
                nav(t if re.match(r'^https?://', t, re.I) else 'https://' + t)
                return
            os_.open_web({'type': 'search', 'q': t})
            os_.toast('Searching OG in the browser…', '🔎')

        def back():
            if pos[0] > 0:
                pos[0] -= 1
                nav(hist[pos[0]], True)

        def fwd():
            if pos[0] < len(hist) - 1:
                pos[0] += 1
                nav(hist[pos[0]], True)

        def reload():
            if 0 <= pos[0] < len(hist):
                nav(hist[pos[0]], True)
        Btn(bar, T, '←', back, kind='ibtn', bg='bg2').pack(side='left', padx=(8, 0), pady=6)
        Btn(bar, T, '→', fwd, kind='ibtn', bg='bg2').pack(side='left')
        Btn(bar, T, '⟳', reload, kind='ibtn', bg='bg2').pack(side='left', padx=(0, 6))
        Btn(bar, T, '↗ Open in a browser tab', lambda: go(new_tab=True), size='sm', bg='bg2').pack(side='right', padx=8)
        Btn(bar, T, 'Go', lambda: go(), size='sm', bg='bg2').pack(side='right')
        inp.pack(side='left', fill='x', expand=True, ipady=4, padx=(0, 6))
        inp.bind('<Return>', lambda e: go())
        draw()
        ctx.set_title('Compass')
        ctx.os.root.after(30, inp.focus_set)
        return Inst(on_arg=lambda a: go(a.get('url')) if isinstance(a, dict) and a.get('url') else None,
                    mem=lambda: 300000)
