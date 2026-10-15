"""The on-screen keyboard: a Portuguese keyboard drawn on the screen, for typing with a finger.

It types into the text box that has the keyboard focus (or the last one that had it). Its keys
are labels, not buttons, so touching them never takes the focus away from that text box, and it
also works over a dialog (a dialog holds every click while it is open, see _grabbed_press).
"""

import tkinter as tk

# The four rows of letters, as on a Portuguese keyboard; the second string is with Shift.
LETTERS = [
    ("1234567890'«", '!"#$%&/()=?»'),
    ('qwertyuiop+', 'QWERTYUIOP*'),
    ('asdfghjklçº', 'ASDFGHJKLÇª'),
    ('<zxcvbnm,.-', '>ZXCVBNM;:_'),
]
# The symbols and accented letters ("?123"); Shift gives the capital accented letters.
SYMBOLS = [
    ('@€£§{}[]\\|~', None),
    ('áàâãéêíóôõ^', None),
    ('úüçñ`´¨¡¿°', None),
    ('<>«»;:_"\'', None),
]
# Plain ASCII characters as X names them, for windows that are not text boxes (games, the piano).
_NAMES = {' ': 'space', '!': 'exclam', '"': 'quotedbl', '#': 'numbersign', '$': 'dollar', '%': 'percent',
          '&': 'ampersand', "'": 'apostrophe', '(': 'parenleft', ')': 'parenright', '*': 'asterisk', '+': 'plus',
          ',': 'comma', '-': 'minus', '.': 'period', '/': 'slash', ':': 'colon', ';': 'semicolon', '<': 'less',
          '=': 'equal', '>': 'greater', '?': 'question', '@': 'at', '[': 'bracketleft', '\\': 'backslash',
          ']': 'bracketright', '^': 'asciicircum', '_': 'underscore', '`': 'grave', '{': 'braceleft', '|': 'bar',
          '}': 'braceright', '~': 'asciitilde'}
REPEAT_DELAY, REPEAT_EVERY = 450, 70       # holding ⌫ or an arrow repeats it


def keysym_of(ch):
    if ch.isascii() and ch.isalnum():
        return ch
    return _NAMES.get(ch)


class OSK:
    def __init__(self, os_):
        self.os = os_
        self.el = None
        self.shift = 0              # 0 off, 1 for the next letter, 2 locked (Caps)
        self.symbols = False
        self.top = False            # shown at the top of the screen instead of the bottom
        self.moved = False          # ⇅ was pressed: keep the place the user chose
        self.target = None          # the last text box that had the focus
        self._keys = {}             # label -> what it does
        self._repeat = None
        self._lift_job = None
        root = os_.root
        root.bind_all('<FocusIn>', self._focus_in, add='+')
        root.bind_all('<ButtonPress-1>', self._grabbed_press, add='+')
        root.bind_all('<ButtonRelease-1>', lambda e: self._stop_repeat(), add='+')

    # ---------------------------------------------------------- showing
    @property
    def visible(self):
        return self.el is not None

    def toggle(self):
        self.hide() if self.visible else self.show()

    def show(self):
        if self.el is None:
            self.moved = False
            self._build()
        self._auto_side()
        self._place()
        self._keep_on_top()

    def hide(self):
        self._stop_repeat()
        if self._lift_job is not None:
            try:
                self.os.root.after_cancel(self._lift_job)
            except tk.TclError:
                pass
            self._lift_job = None
        if self.el is not None:
            try:
                self.el.destroy()
            except tk.TclError:
                pass
        self.el = None
        self._keys = {}

    def owns(self, w):
        """True when the widget w is part of the keyboard."""
        el = self.el
        while el is not None and w is not None and not isinstance(w, str):
            if w is el:
                return True
            w = getattr(w, 'master', None)
        return False

    def height(self):
        h = max(240, self.os.root.winfo_height())
        return max(150, min(280, int(h * 0.42)))

    def _auto_side(self):
        """Sit at the bottom, or at the top when the text box being typed in would be under the keys."""
        if self.moved:
            return
        w = self._where()
        if w is None:
            self.top = False
            return
        try:
            root = self.os.root
            y = w.winfo_rooty() - root.winfo_rooty()
            bottom = y + w.winfo_height()
            h, full = self.height(), root.winfo_height()
        except tk.TclError:
            return
        self.top = bottom > full - h and y >= h

    def _place(self):
        if self.el is None:
            return
        h = self.height()
        if self.top:
            self.el.place(x=0, y=0, relwidth=1, height=h)
        else:
            self.el.place(x=0, rely=1.0, y=-h, relwidth=1, height=h)
        tk.Misc.lift(self.el)

    def _keep_on_top(self):
        """Windows, dialogs and the lock screen raise themselves when they open; stay above them."""
        self._lift_job = None
        if self.el is None or self.os.quitting:
            return
        try:
            tk.Misc.lift(self.el)
        except tk.TclError:
            return
        self._lift_job = self.os.root.after(300, self._keep_on_top)

    # ---------------------------------------------------------- drawing
    def _build(self):
        T = self.os.theme
        el = tk.Frame(self.os.root, bd=0, highlightthickness=1)
        T.style(el, bg='bg0', highlightbackground='line')
        self.el = el
        self._keys = {}
        rows = SYMBOLS if self.symbols else LETTERS
        caps = self.shift > 0
        for plain, shifted in rows:
            text = (shifted if shifted is not None else plain.upper()) if caps else plain
            row = tk.Frame(el, bd=0)
            T.style(row, bg='bg0')
            row.pack(fill='both', expand=True, padx=3, pady=(3, 0))
            for ch in text:
                self._key(row, ch, ('char', ch))
            if rows[0][0] == plain:
                self._key(row, '⌫', ('key', 'BackSpace'), wide=1.6, repeat=True)
        row = tk.Frame(el, bd=0)
        T.style(row, bg='bg0')
        row.pack(fill='both', expand=True, padx=3, pady=3)
        self._key(row, '⇪' if self.shift == 2 else '⇧', ('shift',), wide=1.4, on=self.shift > 0)
        self._key(row, 'ABC' if self.symbols else '?123', ('symbols',), wide=1.4)
        self._key(row, ' ', ('char', ' '), wide=5)
        for label, ks in (('←', 'Left'), ('↑', 'Up'), ('↓', 'Down'), ('→', 'Right')):
            self._key(row, label, ('key', ks), repeat=True)
        self._key(row, '↵', ('key', 'Return'), wide=1.4, kind='acc')
        self._key(row, '⇅', ('move',))
        self._key(row, '⌄', ('hide',))

    def _key(self, row, text, what, wide=1.0, repeat=False, on=False, kind=''):
        T = self.os.theme
        lbl = tk.Label(row, text=text, bd=0, font=T.font('sans', 17), cursor='hand2', takefocus=0)

        def paint():
            if kind == 'acc' or on:
                lbl.configure(bg=T['acc'], fg=T['acc_fg'])
            else:
                lbl.configure(bg=T['bg2'], fg=T['fg'])
        T.on(lbl, paint)
        # Every key gets the same width per unit, so the rows line up.
        lbl.pack(side='left', fill='both', expand=True, padx=2, ipadx=int(10 * (wide - 1)))
        self._keys[lbl] = (what, repeat)
        lbl.bind('<ButtonPress-1>', lambda e: self._press(lbl))
        return lbl

    # ---------------------------------------------------------- pressing
    def _grabbed_press(self, e):
        """While a dialog is open it holds every click (a Tk "grab"), and clicks elsewhere are
        handed to the dialog instead. When such a click is on one of our keys, press the key."""
        if self.el is None or isinstance(e.widget, str) or e.widget in self._keys:
            return None
        try:
            grab = self.os.root.grab_current()
            under = self.os.root.winfo_containing(e.x_root, e.y_root)
        except (tk.TclError, KeyError):
            return None
        if grab is not None and under in self._keys and e.widget is not under:
            self._press(under)
            return 'break'
        return None

    def _press(self, lbl):
        what, repeat = self._keys.get(lbl, (None, False))
        if what is None:
            return 'break'
        self.os.last_active = self.os.monotonic()
        kind = what[0]
        if kind == 'char':
            self.type_text(what[1])
            if self.shift == 1:
                self.shift = 0
                self._rebuild()
        elif kind == 'key':
            self.send_key(what[1])
        elif kind == 'shift':
            self.shift = {0: 1, 1: 2, 2: 0}[self.shift]
            self._rebuild()
        elif kind == 'symbols':
            self.symbols = not self.symbols
            self._rebuild()
        elif kind == 'move':
            self.top = not self.top
            self.moved = True
            self._place()
        elif kind == 'hide':
            self.os.root.after_idle(self.hide)
        if repeat:
            self._stop_repeat()
            self._repeat = self.os.root.after(REPEAT_DELAY, lambda: self._again(what))
        return 'break'

    def _again(self, what):
        if self.el is None:
            self._repeat = None
            return
        self.send_key(what[1])
        self._repeat = self.os.root.after(REPEAT_EVERY, lambda: self._again(what))

    def _stop_repeat(self):
        if self._repeat is not None:
            try:
                self.os.root.after_cancel(self._repeat)
            except tk.TclError:
                pass
            self._repeat = None

    def _rebuild(self):
        """Redraw the keys (after Shift or ?123) in the same place."""
        if self.el is None:
            return
        old = self.el
        self._build()
        self._place()
        try:
            old.destroy()
        except tk.TclError:
            pass

    # ---------------------------------------------------------- typing
    def _focus_in(self, e):
        w = e.widget
        if isinstance(w, str) or self.owns(w):
            return
        try:
            if w.winfo_toplevel() is self.os.root.winfo_toplevel():
                self.target = w
        except (tk.TclError, KeyError):
            return
        if self.el is not None and not self.moved:
            # Wait until the new text box has its place on the screen.
            self.os.root.after(30, lambda: self.el is not None and (self._auto_side(), self._place()))

    def _where(self):
        try:
            w = self.os.root.focus_get()
        except (tk.TclError, KeyError):
            w = None
        if w is None:
            w = self.target
        try:
            if w is not None and w.winfo_exists() and w.winfo_ismapped():
                return w
        except tk.TclError:
            pass
        return None

    def type_text(self, s):
        """Type the characters s into the focused text box (any character, accents included)."""
        w = self._where()
        if w is None:
            return False
        cls = w.winfo_class()
        if cls in ('Entry', 'Text'):
            if str(w.cget('state')) != 'normal':
                return False
            # The same commands Tk runs for a real key: they replace a selection and scroll to the cursor.
            w.tk.call('::tk::EntryInsert' if cls == 'Entry' else '::tk::TextInsert', w._w, s)
            # Programs listen for a key being released to notice typing (search boxes, notes …).
            try:
                w.event_generate('<KeyRelease>', keysym='Shift_L')
            except tk.TclError:
                pass
            return True
        for ch in s:                # not a text box (a game, the piano): send real key presses
            ks = keysym_of(ch)
            if ks is not None:
                self._generate(w, ks)
        return True

    def send_key(self, keysym):
        w = self._where()
        if w is not None:
            self._generate(w, keysym)

    @staticmethod
    def _generate(w, keysym):
        try:
            w.event_generate('<KeyPress>', keysym=keysym)
            w.event_generate('<KeyRelease>', keysym=keysym)
        except tk.TclError:
            pass
