"""Signing in or up to Galau services: the form used at first start, at start-up when
signed out, and in Loom. It works like OG Browser's service.auth (same accounts)."""

import tkinter as tk

from ..galau import MAIL_DOMAIN, friendly, run_async
from .widgets import Btn, Entry


def galau_form(parent, os_, on_done, bg='bg1', width=380):
    """A Sign in / Sign up form. on_done(address) runs once the account is signed in."""
    T = os_.theme
    g = os_.galau
    box = tk.Frame(parent, bd=0)
    T.style(box, bg=bg)
    switch = tk.Frame(box, bd=0)
    T.style(switch, bg=bg)
    switch.pack(anchor='w', pady=(0, 10))
    forms = {}
    tabs = {}

    def label(parent_, text, small=False):
        lbl = tk.Label(parent_, text=text, anchor='w', justify='left', wraplength=width, bd=0,
                       font=T.font('sans', 11 if small else 12))
        T.style(lbl, bg=bg, fg='fg2')
        lbl.pack(fill='x', pady=(0, 2) if not small else (2, 6))
        return lbl

    def show(which):
        for k, f in forms.items():
            if k == which:
                f.pack(fill='x')
            else:
                f.pack_forget()
        for k, b in tabs.items():
            b.set_on(k == which)
        focus = forms[which].first
        box.after(20, lambda: focus.winfo_exists() and focus.focus_set())

    for key, text in (('in', 'Sign in'), ('up', 'Sign up')):
        b = Btn(switch, T, text, lambda k=key: show(k), kind='chip', bg=bg)
        b.pack(side='left', padx=(0, 6))
        tabs[key] = b

    def busy_run(button, msg, work, waiting):
        if button.disabled:
            return
        button.set_disabled(True)
        msg.configure(text=waiting, fg=T['fg2'])

        def done(address, e):
            button.set_disabled(False)
            if e is not None:
                msg.configure(text=friendly(e), fg=T['dng'])
                return
            on_done(address)
        run_async(box, work, done)

    # ---- Sign in
    f_in = tk.Frame(box, bd=0)
    T.style(f_in, bg=bg)
    label(f_in, 'Galau Mail address or username')
    login = Entry(f_in, T, '', placeholder='name@' + MAIL_DOMAIN, width=30)
    login.pack(fill='x', ipady=4, pady=(0, 8))
    label(f_in, 'Password')
    pw = Entry(f_in, T, '', show='•', width=30)
    pw.pack(fill='x', ipady=4)
    msg_in = label(f_in, '', small=True)
    b_in = Btn(f_in, T, 'Sign in', None, kind='pri', bg=bg)
    b_in.pack(anchor='w')
    def do_in():
        u, p = login.get(), pw.get()      # read here, on the Tk thread
        busy_run(b_in, msg_in, lambda: g.sign_in(u, p), 'Signing in…')
    b_in.command = do_in
    login.bind('<Return>', lambda e: pw.focus_set())
    pw.bind('<Return>', lambda e: b_in.command())
    f_in.first = login
    forms['in'] = f_in

    # ---- Sign up
    f_up = tk.Frame(box, bd=0)
    T.style(f_up, bg=bg)
    label(f_up, 'Choose your address')
    row = tk.Frame(f_up, bd=0)
    T.style(row, bg=bg)
    row.pack(fill='x', pady=(0, 2))
    user = Entry(row, T, '', placeholder='yourname', width=20)
    user.pack(side='left', fill='x', expand=True, ipady=4)
    suffix = tk.Label(row, text='@' + MAIL_DOMAIN, bd=0, font=T.font('sans', 13), padx=6)
    T.style(suffix, bg=bg, fg='fg2')
    suffix.pack(side='left')
    label(f_up, '3 to 30 lowercase letters, numbers, dots or underscores.', small=True)
    label(f_up, 'Password (at least 6 characters)')
    pw1 = Entry(f_up, T, '', show='•', width=30)
    pw1.pack(fill='x', ipady=4, pady=(0, 6))
    label(f_up, 'Confirm password')
    pw2 = Entry(f_up, T, '', show='•', width=30)
    pw2.pack(fill='x', ipady=4)
    msg_up = label(f_up, '', small=True)
    b_up = Btn(f_up, T, 'Create account', None, kind='pri', bg=bg)
    b_up.pack(anchor='w')
    def do_up():
        u, a, b = user.get(), pw1.get(), pw2.get()
        busy_run(b_up, msg_up, lambda: g.sign_up(u, a, b), 'Creating your account…')
    b_up.command = do_up
    user.bind('<Return>', lambda e: pw1.focus_set())
    pw1.bind('<Return>', lambda e: pw2.focus_set())
    pw2.bind('<Return>', lambda e: b_up.command())
    f_up.first = user
    forms['up'] = f_up

    box.fields = {'login': login, 'password': pw, 'username': user, 'new1': pw1, 'new2': pw2,
                  'sign_in': b_in, 'sign_up': b_up, 'msg_in': msg_in, 'msg_up': msg_up}
    box.show = show
    show('in')
    return box


def require_galau(os_):
    """At start-up: when no Galau account is signed in, ask for one. There is no way to skip it."""
    if os_.galau.signed_in or os_.quitting:
        return
    from .overlays import full_layer
    T = os_.theme
    c = full_layer(os_, 'galau')
    done = {'v': False}
    card = tk.Frame(c, bd=0, highlightthickness=1)
    T.on(card, lambda: card.configure(bg=T['bg1'], highlightbackground=T['line']))
    inner = tk.Frame(card, bd=0)
    T.style(inner, bg='bg1')
    pad = 16 if os_.compact else 26
    inner.pack(fill='both', expand=True, padx=pad, pady=pad)
    h = tk.Label(inner, text='Sign in to Galau services', anchor='w', font=T.font('serif', 22, 'bold', 'italic'), bd=0)
    T.style(h, bg='bg1', fg='fg')
    h.pack(fill='x')
    p = tk.Label(inner, text='Quill.OS uses your Galau account (the same one as OG Browser and Galau Mail).',
                 anchor='w', justify='left', wraplength=380, font=T.font('sans', 12), bd=0)
    T.style(p, bg='bg1', fg='fg2')
    p.pack(fill='x', pady=(2, 10))

    def finished(address):
        os_.toast('Signed in as ' + address, '✅')
        done['v'] = True
    form = galau_form(inner, os_, finished)
    form.pack(fill='x')
    os_.account_form = form          # for tests and for focusing

    def place(_e=None):
        c.delete('card')
        c.create_window(c.winfo_width() / 2, c.winfo_height() / 2, window=card, tags='card',
                        width=min(440, max(300, c.winfo_width() - 24)))
    c.bind('<Configure>', place, add='+')
    c.update_idletasks()
    place()
    os_.wait(lambda: done['v'] or os_.quitting)
    os_.account_form = None
    try:
        c.destroy()
    except tk.TclError:
        pass
