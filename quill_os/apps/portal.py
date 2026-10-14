"""Portal — the other OG sites."""

import tkinter as tk

from .base import AppSpec, Inst
from ..ui.widgets import Btn, ScrollArea

PORTAL_SITES = [
    {'name': 'Galau Mail', 'host': 'galaumail.og', 'icon': '✉️', 'sub': 'Read and send mail'},
    {'name': 'Ferret', 'host': 'ferret.og', 'icon': '💬', 'sub': 'Chat and call'},
    {'name': 'Reminders', 'host': 'reminder.og', 'icon': '⏰', 'sub': 'Alerts and notifications'},
    {'name': 'LifeCraft', 'host': 'lifecraft.og', 'icon': '⛏️', 'sub': 'Build a world'},
    {'name': 'LifeCraft roots', 'host': 'lifecraft.roots', 'icon': '🌱', 'sub': 'Every root'},
    {'name': 'LifeGames', 'host': 'lifegames.og', 'icon': '🎮', 'sub': 'Play games'},
    {'name': 'LifeGames Studio', 'host': 'lifegames.create', 'icon': '🛠️', 'sub': 'Make a game'},
    {'name': 'Galau', 'host': 'galau3.og', 'icon': '🌌', 'sub': 'Social network'},
    {'name': 'Ohmstead', 'host': 'ohmstead3d.og', 'icon': '🔌', 'sub': 'Learn circuits'},
    {'name': 'POS-ify', 'host': 'posify.og', 'icon': '🧾', 'sub': 'Point of sale'},
    {'name': 'My account', 'host': 'account.auth', 'icon': '👤', 'sub': 'Galau account'},
    {'name': 'All OG sites', 'host': None, 'icon': '🗺️', 'sub': 'The site directory'},
]


class App(AppSpec):
    id = 'portal'
    name = 'Portal'
    icon = '◎'
    bg = ('#4fd1c5', '#2b6cb0')
    w, h = 640, 520
    single = True
    kw = 'sites og browser mail ferret lifecraft lifegames galau links open tabs'
    about = 'Open other OG sites'

    def build(self, ctx):
        os_, T = ctx.os, ctx.T
        area = ScrollArea(ctx.body, T, bg='bg1')
        area.pack(fill='both', expand=True)
        root = tk.Frame(area.inner, bd=0)
        T.style(root, bg='bg1')
        root.pack(fill='both', expand=True, padx=18, pady=18)
        h = tk.Label(root, text='Portal', anchor='w', font=T.font('serif', 22, 'bold', 'italic'))
        T.style(h, bg='bg1', fg='fg')
        h.pack(fill='x')
        s = tk.Label(root, text='Open any OG site in a new browser tab. Quill stays where it is.', anchor='w',
                     font=T.font('sans', 12))
        T.style(s, bg='bg1', fg='fg2')
        s.pack(fill='x')
        card = tk.Frame(root, bd=0, highlightthickness=1)
        T.on(card, lambda: card.configure(bg=T['bg2'], highlightbackground=T['line']))
        card.pack(fill='x', pady=(12, 0))
        col = tk.Frame(card, bd=0)
        T.style(col, bg='bg2')
        col.pack(side='left', fill='x', expand=True, padx=14, pady=14)
        a = tk.Label(col, text='Signed in as ' + os_.me if os_.me else 'Not signed in', anchor='w',
                     font=T.font('sans', 13, 'bold'))
        T.style(a, bg='bg2', fg='fg')
        a.pack(fill='x')
        b = tk.Label(col, text='Your Galau services account is connected.' if os_.me else
                     'Sign in to use Galau services and cloud sync.', anchor='w', font=T.font('sans', 12))
        T.style(b, bg='bg2', fg='fg2')
        b.pack(fill='x')
        if not os_.me:
            Btn(card, T, 'Sign in', lambda: os_.toast('Not running inside OG Browser.', '⚠️'), kind='pri', size='sm',
                bg='bg2').pack(side='right', padx=14)
        grid = tk.Frame(root, bd=0)
        T.style(grid, bg='bg1')
        grid.pack(fill='x', pady=(12, 0))
        cells = []
        for site in PORTAL_SITES:
            cell = tk.Frame(grid, bd=0, highlightthickness=1, cursor='hand2')
            ic = tk.Label(cell, text=site['icon'], font=T.font('sans', 28))
            nm = tk.Label(cell, text=site['name'], font=T.font('sans', 13, 'bold'))
            sb = tk.Label(cell, text=site['sub'], font=T.font('sans', 11))
            ic.pack(pady=(14, 4))
            nm.pack()
            sb.pack(pady=(0, 14))
            hover = {'on': False}

            def paint(cell=cell, ic=ic, nm=nm, sb=sb, hover=hover):
                cell.configure(bg=T['bg2'], highlightbackground=T['acc'] if hover['on'] else T['line'])
                for w in (ic, nm):
                    w.configure(bg=T['bg2'], fg=T['fg'])
                sb.configure(bg=T['bg2'], fg=T['fg2'])
            T.on(cell, paint)

            def go(_e=None, site=site):
                if site['host']:
                    os_.open_web({'type': 'og', 'host': site['host'], 'path': '/'})
                else:
                    os_.open_web({'type': 'directory'})
                os_.toast('Opening ' + site['name'] + '…', site['icon'])
            for w in (cell, ic, nm, sb):
                w.bind('<Button-1>', go)
                w.bind('<Enter>', lambda e, p=paint, hv=hover: (hv.__setitem__('on', True), p()))
                w.bind('<Leave>', lambda e, p=paint, hv=hover: (hv.__setitem__('on', False), p()))
            cells.append(cell)

        def layout(_e=None):
            width = max(200, grid.winfo_width())
            cols = max(1, width // 162)
            for i in range(6):
                grid.columnconfigure(i, weight=1 if i < cols else 0, uniform='p' if i < cols else '')
            for i, c in enumerate(cells):
                c.grid(row=i // cols, column=i % cols, padx=6, pady=6, sticky='nsew')
        grid.bind('<Configure>', layout)
        layout()
        ctx.set_title('Portal')
        return Inst(mem=lambda: 60000)
