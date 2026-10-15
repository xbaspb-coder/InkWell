"""QuillOS — the running system: it builds the screen and ties every part together."""

import datetime as _dt
import os
import platform
import sys
import time
import tkinter as tk
import traceback
import webbrowser
from tkinter import filedialog

from . import audio, web
from .apps import load_apps
from .core import Core, Store, kind_of
from .galau import Galau
from .xapps import Store as XStore, register as register_xapps
from .imaging import HAVE_PIL, photo_from_bytes
from .keys import LAYOUTS, Keyboard
from .ui.desk import Desk, Notes, Ribbon, Spine
from .ui.account import require_galau
from .ui.eyes import Eyes
from .ui.osk import OSK
from .ui.overlays import Boot, Dialogs, Inkwell, Lock, Menu, Panels, PowerOff, Spread, Toasts, setup_wizard
from .ui.theme import THEME_WALL, Theme
from .ui.widgets import hide as hide_tip, install_touch_scroll, set_touch, wheel_units
from .ui.wm import WindowManager
from .util import fmt_time, now_ms, uid


class Backlight:
    """A screen backlight in /sys/class/backlight that this user may change."""

    def __init__(self, folder):
        self.folder = folder
        with open(os.path.join(folder, 'max_brightness')) as f:
            self.max = int(f.read().strip())
        self.last = None

    def set(self, percent):
        value = max(1, round(self.max * max(5, min(100, int(percent))) / 100))
        if value == self.last:
            return True
        try:
            with open(os.path.join(self.folder, 'brightness'), 'w') as f:
                f.write(str(value))
        except OSError:
            return False
        self.last = value
        return True


def find_backlight(base='/sys/class/backlight'):
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return None
    for n in names:
        folder = os.path.join(base, n)
        if not os.access(os.path.join(folder, 'brightness'), os.W_OK):
            continue
        try:
            b = Backlight(folder)
        except (OSError, ValueError):
            continue
        if b.max > 0:
            return b
    return None


class DnD:
    """Dragging files between the desktop, Atlas windows, folders and the Trash."""

    def __init__(self, os_):
        self.os = os_
        self.ids = None
        self.label = None
        self._bound = False

    def start(self, ids, text, e):
        os_ = self.os
        T = os_.theme
        self.ids = list(ids)
        self.label = tk.Label(os_.root, text=text, bd=0, padx=10, pady=4, font=T.font('sans', 12),
                              bg=T['acc'], fg=T['acc_fg'])
        self._move(e)
        if not self._bound:
            # Added once and left in place: replacing the global bindings would remove the
            # touch-scrolling handlers that share them.
            self._bound = True
            os_.root.bind_all('<B1-Motion>', self._move, add='+')
            os_.root.bind_all('<ButtonRelease-1>', self._drop, add='+')

    def _move(self, e):
        if self.label is None:
            return
        root = self.os.root
        self.label.place(x=e.x_root - root.winfo_rootx() + 12, y=e.y_root - root.winfo_rooty() + 8)
        self.label.lift()

    def _drop(self, e):
        root = self.os.root
        if self.ids is None and self.label is None:
            return
        if self.label is not None:
            self.label.destroy()
            self.label = None
        ids, self.ids = self.ids, None
        if not ids:
            return
        try:
            target = root.winfo_containing(e.x_root, e.y_root)
        except (tk.TclError, KeyError):
            target = None
        while target is not None:
            fn = getattr(target, '_drop', None)
            if fn is not None:
                try:
                    fn(ids)
                except Exception:
                    traceback.print_exc()
                return
            target = getattr(target, 'master', None)


class QuillOS:
    SPINE = 64
    RIBBON = 38

    def __init__(self, root=None, store=None, compact=None, touch=None, fullscreen=False):
        self.root = root or tk.Tk()
        self.root.quill = self
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        # A small screen (such as a 7-inch 800 x 480 or 1024 x 600 panel) fills the whole screen
        # and opens every window maximised. Touch mode adds press-and-hold menus and finger scrolling.
        self.compact = (sw <= 1024 or sh <= 640) if compact is None else bool(compact)
        self.touch_mode = self.compact if touch is None else bool(touch)
        self.fullscreen = bool(fullscreen)
        set_touch(self.touch_mode)
        self.root.title('Quill.OS')
        self.quitting = False
        self._waits = []          # Tk variables of the waits in progress (Variables are not hashable)
        self.started = time.monotonic()
        self.last_active = time.monotonic()
        self.me = None
        self.cloud_state = 'off'
        self._once = {}
        self._thumbs = {}
        self.core = Core(store or Store(), (self._schedule, self._cancel))
        self.bus = self.core.bus
        self.fs = self.core.fs
        self.load_error = self.core.load()
        self.sound = audio.Engine()
        self.theme = Theme(self.root)
        self.backlight = find_backlight()
        self.theme.apply(self._look_settings())
        self.apps = load_apps()
        self.galau = Galau(self.core.store.folder)
        self.xstore = XStore(self.galau, self.core.store.folder, self.S['xapps'])
        self._build_screen()
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

    # ------------------------------------------------------------------ basics
    @property
    def S(self):
        return self.core.S

    def settings(self):
        return self.S['set']

    def touch(self):
        self.core.touch()

    def save(self, now=False):
        self.core.save(now)

    @staticmethod
    def now_ms():
        return now_ms()

    @staticmethod
    def monotonic():
        return time.monotonic()

    def _schedule(self, ms, fn):
        return self.root.after(ms, fn)

    def _cancel(self, h):
        try:
            self.root.after_cancel(h)
        except (tk.TclError, ValueError):
            pass

    def safe(self, fn, *a):
        try:
            return fn(*a)
        except Exception:
            traceback.print_exc()
            return None

    def later(self, ms, fn):
        self.root.after(ms, lambda: self.safe(fn))

    def wait(self, pred, poll=25):
        """Keep the program running until pred() is true (or Quill is closing)."""
        if self.quitting or pred():
            return
        var = tk.IntVar(master=self.root, value=0)
        self._waits.append(var)

        def check():
            try:
                done = self.quitting or pred()
            except Exception:
                traceback.print_exc()
                done = True
            if done:
                var.set(1)
            else:
                self.root.after(poll, check)
        self.root.after(poll, check)
        try:
            self.root.wait_variable(var)
        except tk.TclError:
            pass
        if var in self._waits:
            self._waits.remove(var)

    def sleep(self, ms):
        end = time.monotonic() + ms / 1000.0
        self.wait(lambda: time.monotonic() >= end)

    # ------------------------------------------------------------------ the screen
    def _build_screen(self):
        root = self.root
        T = self.theme
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        if self.compact or self.fullscreen:
            root.geometry('%dx%d+0+0' % (sw, sh))
            root.minsize(320, 240)
            if self.fullscreen:
                try:
                    root.attributes('-fullscreen', True)
                except tk.TclError:
                    pass
        else:
            w, h = min(1440, max(900, int(sw * 0.9))), min(900, max(600, int(sh * 0.88)))
            root.geometry('%dx%d+%d+%d' % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 3)))
            root.minsize(760, 520)
        self.desk_frame = tk.Frame(root, bd=0, highlightthickness=0)
        self.desk_frame.place(x=self.SPINE, y=self.RIBBON, relwidth=1, relheight=1, width=-self.SPINE, height=-self.RIBBON)
        T.style(self.desk_frame, bg='bg0')
        self.desk = self.desk_frame
        self.spine_frame = tk.Frame(root, bd=0, highlightthickness=0)
        self.spine_frame.place(x=0, y=0, width=self.SPINE, relheight=1)
        T.style(self.spine_frame, bg='glass')
        spine_edge = tk.Frame(root, bd=0, width=1)
        spine_edge.place(x=self.SPINE - 1, y=0, width=1, relheight=1)
        T.style(spine_edge, bg='line')
        self.ribbon_frame = tk.Frame(root, bd=0, highlightthickness=0)
        self.ribbon_frame.place(x=self.SPINE, y=0, relwidth=1, width=-self.SPINE, height=self.RIBBON - 1)
        T.style(self.ribbon_frame, bg='glass')
        ribbon_edge = tk.Frame(root, bd=0, height=1)
        ribbon_edge.place(x=self.SPINE, y=self.RIBBON - 1, relwidth=1, width=-self.SPINE, height=1)
        T.style(ribbon_edge, bg='line')
        self.menu = Menu(self)
        self.dialogs = Dialogs(self)
        self.desktop = Desk(self, self.desk_frame)
        self.wm = WindowManager(self)
        self.notes = Notes(self, self.desk_frame)
        self.spine = Spine(self, self.spine_frame)
        self.ribbon = Ribbon(self, self.ribbon_frame)
        self.toasts = Toasts(self)
        self.ink = Inkwell(self)
        self.spread = Spread(self)
        self.panels = Panels(self)
        self.boot = Boot(self)
        self.lock = Lock(self)
        self.dnd = DnD(self)
        self.eyes = Eyes(self)
        self.osk = OSK(self)
        self._osd = None
        self.powered_off = False
        self.account_form = None
        self.setup_state = None
        self._outside = []
        self.tray_buttons = [self.ribbon.bell, self.ribbon.quick]
        self.bus.on('wm', lambda _a: self._on_wm())
        self.bus.on('fs', lambda _a: self.desktop.icons())
        self.bus.on('notif', lambda _a: self.bell_update())
        self.bus.on('storage-full', lambda _a: self.notify_once(
            'full', 'Storage is full', 'Quill could not save. Delete or export some large files in Atlas.'))
        register_xapps(self, self.xstore)
        self._bind_global()
        self.keyboard = Keyboard(self, use_evdev=self.fullscreen or bool(os.environ.get('QUILL_EVDEV')))
        install_touch_scroll(root)
        self.desk_frame.bind('<Configure>', self._desk_resized, add='+')
        self._fit_job = None

    def _desk_resized(self, _e=None):
        if self._fit_job:
            self.root.after_cancel(self._fit_job)
        self._fit_job = self.root.after(80, self._fit)

    def _fit(self):
        self._fit_job = None
        self.wm.fit()
        self.spine.render()

    def _on_wm(self):
        self.spine.render()
        self.ribbon.paint_chapters()

    def ribbon_update(self):
        wm = self.wm
        a = wm.active
        self.ribbon.set_title(a.title if a is not None and a.ch == wm.ch and not a.min else 'Quill.OS')
        self.ribbon.paint_chapters()

    def tray_paint(self):
        self.ribbon.paint_tray()

    def bell_update(self):
        self.ribbon.bell_update(self.core.unread_count())

    def _look_settings(self):
        """The settings the colours are made from. A screen whose backlight Quill can set (such as the
        official Raspberry Pi touchscreen) is dimmed by its backlight, so the colours stay full."""
        s = self.S['set']
        if self.backlight is None:
            return s
        return dict(s, bright=100)

    def apply_look(self):
        hide_tip()
        if self.backlight is not None:
            self.backlight.set(self.S['set'].get('bright', 100))
        self.theme.apply(self._look_settings())
        self.sound.volume = max(0, min(100, self.S['set'].get('volume', 70))) / 100
        self.desktop.apply()
        self.ribbon.tray_icons(self.S['set'].get('volume', 70), self.cloud_state)
        self.ribbon.paint_chapters()

    def set_theme(self, t):
        if t not in THEME_WALL:
            return
        s = self.S['set']
        if s.get('wall') == THEME_WALL.get(s.get('theme')):
            s['wall'] = THEME_WALL[t]
        s['theme'] = t
        self.touch()
        self.apply_look()
        self.bus.emit('look')

    def toggle_dnd(self):
        self.S['set']['dnd'] = not self.S['set']['dnd']
        self.touch()
        self.toast('Do Not Disturb is on' if self.S['set']['dnd'] else 'Do Not Disturb is off', '🔕')

    def empty_state(self, parent, big, text, small=None, buttons=(), bg='bg1'):
        T = self.theme
        f = tk.Frame(parent, bd=0)
        T.style(f, bg=bg)
        inner = tk.Frame(f, bd=0)
        T.style(inner, bg=bg)
        inner.pack(expand=True, pady=30)
        b = tk.Label(inner, text=big, font=T.font('sans', 42))
        T.style(b, bg=bg, fg='fg2')
        b.pack(pady=(0, 6))
        t = tk.Label(inner, text=text, font=T.font('sans', 14), wraplength=380, justify='center')
        T.style(t, bg=bg, fg='fg2')
        t.pack()
        if small:
            s = tk.Label(inner, text=small, font=T.font('sans', 12), wraplength=380, justify='center')
            T.style(s, bg=bg, fg='fg2')
            s.pack(pady=(4, 0))
        if buttons:
            from .ui.widgets import Btn
            row = tk.Frame(inner, bd=0)
            T.style(row, bg=bg)
            row.pack(pady=(10, 0))
            for label, fn in buttons:
                Btn(row, T, label, fn, bg=bg).pack(side='left', padx=4)
        f.pack(fill='both', expand=True)
        return f

    # ------------------------------------------------------------------ global input
    def _bind_global(self):
        root = self.root
        aqua = root.tk.call('tk', 'windowingsystem') == 'aqua'
        mods = ['Control'] + (['Command'] if aqua else [])
        for m in mods:
            for k in ('k', 'K', 'space'):
                root.bind_all('<%s-%s>' % (m, k), self._key_ink)
        alt = ['Alt'] + (['Option'] if aqua else [])
        for a in alt:
            try:
                root.bind_all('<%s-space>' % a, self._key_ink)
                for i in range(1, 5):
                    root.bind_all('<%s-Key-%d>' % (a, i), lambda e, i=i: self._alt(lambda: self.wm.switch_chapter(i - 1)))
                table = {'s': lambda: self.spread.open(), 'l': lambda: self.lock.show(), 't': lambda: self.wm.open('term'),
                         'e': lambda: self.wm.open('files'), 'n': lambda: self.wm.open('scribe', {'fresh': True}),
                         'j': lambda: self.wm.cycle(),
                         'w': lambda: self.wm.active and self.wm.close(self.wm.active),
                         'm': lambda: self.wm.active and self.wm.minimize(self.wm.active),
                         'q': lambda: self.panels.toggle('quick')}
                for key, fn in table.items():
                    root.bind_all('<%s-%s>' % (a, key), lambda e, fn=fn: self._alt(fn))
                    root.bind_all('<%s-%s>' % (a, key.upper()), lambda e, fn=fn: self._alt(fn))
                root.bind_all('<%s-Return>' % a,
                              lambda e: self._alt(lambda: self.wm.active and self.wm.toggle_max(self.wm.active)))
            except tk.TclError:
                continue
        root.bind_all('<Escape>', self._key_escape, add='+')
        root.bind_all('<MouseWheel>', self._wheel, add='+')
        root.bind_all('<Button-4>', self._wheel, add='+')
        root.bind_all('<Button-5>', self._wheel, add='+')
        root.bind_all('<ButtonPress>', self._press_any, add='+')
        root.bind_all('<KeyPress>', self._activity, add='+')
        root.bind_all('<Motion>', self._activity, add='+')

    def _blocked(self):
        return self.lock.active or self.dialogs.active or self.ink.el is not None

    def _key_ink(self, _e):
        if self.lock.active or self.dialogs.active:
            return 'break'
        self.ink.toggle()
        return 'break'

    def _alt(self, fn):
        if self._blocked():
            return 'break'
        self.safe(fn)
        return 'break'

    def _key_escape(self, _e):
        if self.panels.el is not None:
            self.panels.hide()
        elif self.spread.el is not None:
            self.spread.close()

    def _activity(self, _e=None):
        self.last_active = time.monotonic()

    def _wheel(self, e):
        self.last_active = time.monotonic()
        try:
            w = self.root.winfo_containing(e.x_root, e.y_root)
        except (tk.TclError, KeyError):
            return
        units = wheel_units(e)
        while w is not None:
            if isinstance(w, (tk.Text, tk.Listbox)) or w.winfo_class() in ('Text', 'Listbox', 'Treeview'):
                return
            fn = getattr(w, '_wheel', None)
            if fn is not None:
                self.safe(fn, units)
                return
            w = getattr(w, 'master', None)

    def outside_click(self, widget, close, alive, ignore=()):
        self._outside.append((widget, close, alive, tuple(ignore)))

    def _inside(self, w, container):
        while w is not None:
            if w is container:
                return True
            w = getattr(w, 'master', None)
        return False

    def _press_any(self, e):
        self.last_active = time.monotonic()
        w = e.widget
        if isinstance(w, str) or self.osk.owns(w):
            return
        keep = []
        for widget, close, alive, ignore in self._outside:
            try:
                if not alive() or not widget.winfo_exists():
                    continue
            except tk.TclError:
                continue
            if self._inside(w, widget) or any(self._inside(w, i) for i in ignore):
                keep.append((widget, close, alive, ignore))
                continue
            self.safe(close)
        self._outside = keep
        win = self.wm.window_of(w)
        if win is not None and self.wm.active is not win and win in self.wm.list:
            self.wm.focus(win)

    # ------------------------------------------------------------------ the keyboard's special keys
    def osd(self, icon, label, value=None):
        """A small box in the middle of the screen showing a level (volume, brightness) for a moment."""
        T = self.theme
        o = self._osd
        if o is None or not o['box'].winfo_exists():
            box = tk.Frame(self.root, bd=0, highlightthickness=1)
            ic = tk.Label(box, font=T.font('sans', 30), bd=0)
            ic.pack(padx=24, pady=(14, 2))
            name = tk.Label(box, font=T.font('sans', 13), bd=0)
            name.pack(padx=24)
            bar = tk.Canvas(box, width=160, height=8, bd=0, highlightthickness=0)
            bar.pack(padx=24, pady=(8, 16))
            o = self._osd = {'box': box, 'ic': ic, 'name': name, 'bar': bar, 'job': None, 'value': None}

            def paint():
                box.configure(bg=T['glass'], highlightbackground=T['line'])
                for w in (ic, name):
                    w.configure(bg=T['glass'], fg=T['fg'])
                bar.configure(bg=T['bg2'])
                bar.delete('all')
                if o['value'] is not None:
                    bar.create_rectangle(0, 0, int(160 * o['value'] / 100), 8, fill=T['acc'], outline='')
            o['paint'] = paint
            T.on(box, paint, now=False)
        o['value'] = None if value is None else max(0, min(100, int(value)))
        o['ic'].configure(text=icon)
        o['name'].configure(text=label + ('' if value is None else '  %d%%' % o['value']))
        if value is None:
            o['bar'].pack_forget()
        elif not o['bar'].winfo_ismapped():
            o['bar'].pack(padx=24, pady=(8, 16))
        o['paint']()
        o['box'].place(relx=0.5, rely=0.42, anchor='center')
        tk.Misc.lift(o['box'])
        if o['job'] is not None:
            self.root.after_cancel(o['job'])

        def gone():
            o['job'] = None
            try:
                o['box'].place_forget()
            except tk.TclError:
                pass
        o['job'] = self.root.after(1200, gone)

    def set_system_volume(self, vol):
        """Also set the Raspberry Pi's own volume (for sound from other programs), when it has a mixer."""
        import shutil
        import subprocess
        if not shutil.which('amixer'):
            return False
        for control in ('Master', 'PCM', 'Headphone'):
            try:
                r = subprocess.run(['amixer', '-q', 'sset', control, '%d%%' % vol] + (['mute'] if vol == 0 else ['unmute']),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except (OSError, subprocess.SubprocessError):
                return False
            if r.returncode == 0:
                return True
        return False

    def set_layout(self, code):
        """Change the keyboard layout of the whole screen (setxkbmap); '' leaves it alone."""
        import shutil
        import subprocess
        if not code:
            return True
        if code not in dict(LAYOUTS) or not shutil.which('setxkbmap'):
            return False
        try:
            return subprocess.run(['setxkbmap', code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=5).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def media(self, cmd):
        """The media keys control the music in Lyre's player (opening it when needed)."""
        win = next((w for w in self.wm.list if w.app == 'lyre'), None)
        if win is None:
            if cmd == 'stop':
                return
            win = self.wm.open('lyre', {'tab': 'player'})
        fn = getattr(win.inst, 'media', None) if win is not None else None
        if fn is None:
            return
        fn(cmd)
        icons = {'stop': '⏹', 'playpause': '⏯', 'next': '⏭', 'prev': '⏮'}
        names = {'stop': 'Stopped', 'playpause': 'Play / pause', 'next': 'Next track', 'prev': 'Previous track'}
        self.osd(icons[cmd], names[cmd])

    # ------------------------------------------------------------------ notifications and sounds
    def ui_sound(self, kind):
        if self.S['set'].get('uisnd'):
            self.sound.ui(kind)

    def toast(self, msg, icon='✒️'):
        self.toasts.show(msg, '', icon or '✒️', 2800)

    def notify(self, title='Quill', body='', icon='🔔', ms=None, silent=False, no_save=False):
        n = self.core.add_notification(title, body, icon, no_save)
        self.bus.emit('notif')
        if not self.S['set'].get('dnd'):
            self.toasts.show(n['title'], n['body'], n['icon'], ms or 5000)
            if not silent:
                self.ui_sound('notify')
        return n

    def notify_once(self, key, title, body):
        t = time.monotonic()
        if t - self._once.get(key, -1e9) < 60:
            return
        self._once[key] = t
        self.notify(title, body, '⚠️')

    _ring_job = None

    def ring(self, on):
        if self._ring_job:
            self.root.after_cancel(self._ring_job)
            self._ring_job = None
        if not on:
            return

        def beep():
            self.sound.beep()
            self._ring_job = self.root.after(1400, beep)
        beep()

    # ------------------------------------------------------------------ files
    def open_file(self, n, how=None):
        if n is None:
            return None
        if n['t'] == 'd':
            return self.wm.open('files', {'dir': n['id']})
        self.S['recent'] = ([n['id']] + [x for x in (self.S.get('recent') or []) if x != n['id']])[:8]
        k = kind_of(n)
        name = n['n'].lower()
        e = name.rsplit('.', 1)[1] if '.' in name else ''
        if how:
            return self.wm.open(how, {'file': n['id']})
        if k == 'image':
            return self.wm.open('lens', {'file': n['id']})
        if k == 'audio':
            return self.wm.open('lyre', {'file': n['id'], 'tab': 'player'})
        if k == 'bin':
            if self.dialogs.confirm('No app for this file', '“' + n['n'] + '” is a binary file Quill cannot open. '
                                    'Export it to your computer?', ok='Export'):
                self.export_file(n)
            return None
        if e in ('md', 'txt', 'log', 'csv', 'tsv', ''):
            return self.wm.open('scribe', {'file': n['id']})
        return self.wm.open('glyph', {'file': n['id']})

    def export_file(self, n):
        path = filedialog.asksaveasfilename(parent=self.root, title='Export ' + n['n'], initialfile=n['n'])
        if not path:
            return
        try:
            self.fs.export_file(n, path)
            self.toast('Exported ' + n['n'], '📥')
        except OSError as e:
            self.toast('Could not export: %s' % e, '⚠️')

    def upload_into(self, pid):
        paths = filedialog.askopenfilenames(parent=self.root, title='Add files to Quill')
        if not paths:
            return
        ok = 0
        for p in paths:
            try:
                self.fs.import_file(p, pid)
                ok += 1
            except Exception as e:  # FSError or OS errors: report and continue
                self.toast(str(e), '⚠️')
        if ok:
            self.toast('Added %d %s' % (ok, 'file' if ok == 1 else 'files'), '📥')

    def file_menu(self, n, extra=None):
        k = kind_of(n)
        items = [{'label': 'Open', 'icon': '↗', 'action': lambda: self.open_file(n)}]
        if n['t'] == 'f':
            if k == 'text':
                items += [{'label': 'Open in Scribe', 'icon': '✒️', 'action': lambda: self.open_file(n, 'scribe')},
                          {'label': 'Open in Glyph', 'icon': '⌨️', 'action': lambda: self.open_file(n, 'glyph')}]
            if k == 'image':
                def wall():
                    self.S['set']['wall'] = 'image'
                    self.S['set']['wallImg'] = n['id']
                    self.touch()
                    self.apply_look()
                    self.toast('Wallpaper changed', '🖼')
                items.append({'label': 'Set as wallpaper', 'icon': '🖼', 'action': wall})
            items.append({'label': 'Export to computer', 'icon': '📥', 'action': lambda: self.export_file(n)})

        def trash():
            self.fs.trash(n['id'])
            self.toast('Moved to Trash', '🗑')
        items += [{'sep': True}, {'label': 'Rename', 'icon': '✎', 'key': 'F2', 'action': lambda: self.rename_dialog(n)},
                  {'label': 'Move to Trash', 'icon': '🗑', 'danger': True, 'key': 'Del', 'action': trash}]
        if extra:
            items += extra
        return items

    @staticmethod
    def valid_name(s):
        if not s.strip():
            return 'Type a name.'
        if '/' in s or '\\' in s:
            return 'A name cannot contain / or \\.'
        return None

    def rename_dialog(self, n):
        v = self.dialogs.prompt('Rename', n['n'], ok='Rename', validate=self.valid_name)
        if v is not None and v.strip() and v != n['n']:
            self.fs.rename(n['id'], v)

    def new_item(self, pid, type_, name=None):
        v = self.dialogs.prompt('New folder' if type_ == 'd' else 'New file',
                                name or ('New folder' if type_ == 'd' else 'Untitled.txt'), ok='Create',
                                validate=self.valid_name)
        if v is None:
            return None
        return self.fs.mk(pid, v.strip(), type_, '' if type_ == 'f' else None)

    def empty_trash_confirm(self):
        if self.dialogs.confirm('Empty Trash?', 'Everything in the Trash is deleted for good.', ok='Empty', danger=True):
            self.fs.empty_trash()
            self.toast('Trash emptied', '🗑')

    def copy_text(self, t):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(t)
            return True
        except tk.TclError:
            return False

    def open_web(self, target):
        """Open a web page. OG sites, OG search and the site list open in OG Browser; plain web
        addresses open in a web window (or the computer's own browser when there is no web engine)."""
        ok, why = web.available()
        address = web.og_address(target)
        if address is not None:
            if ok:
                self.wm.open('ogb', {'open': address})
            else:
                self.toast('OG Browser needs the web engine, which is not installed.', '⚠️')
            return None
        url = target.get('url') if target.get('type') == 'url' else None
        if url:
            if ok:
                self.wm.open('webpage', {'url': url})
            else:
                try:
                    webbrowser.open(url)
                except Exception as e:
                    self.toast('Could not open the browser: %s' % e, '⚠️')
        return None

    # ---- pictures
    def thumb(self, n, size):
        key = (n['id'], n.get('m'), size)
        img = self._thumbs.get(key)
        if img is None:
            if len(n.get('c') or '') > 600000:
                return None
            img = photo_from_bytes(self.root, self.fs.file_bytes(n), (size, size))
            if img is None:
                return None
            if len(self._thumbs) > 200:
                self._thumbs.clear()
            self._thumbs[key] = img
        return img

    def photo_cover(self, n, w, h):
        data = self.fs.file_bytes(n)
        if HAVE_PIL:
            import io
            from PIL import Image, ImageOps, ImageTk
            try:
                im = Image.open(io.BytesIO(data))
                im.load()
                return ImageTk.PhotoImage(ImageOps.fit(im.convert('RGB'), (max(1, w), max(1, h))), master=self.root)
            except Exception:
                return None
        from .imaging import scaled_photo
        p = photo_from_bytes(self.root, data)
        if p is None:
            return None
        k = max(w / max(1, p.width()), h / max(1, p.height()))
        return scaled_photo(p, k)

    # ------------------------------------------------------------------ shell host interface
    def open_app(self, app_id, arg=None):
        return self.wm.open(app_id, arg)

    def windows(self):
        return list(self.wm.list)

    def close_window(self, w):
        self.wm.close(w)

    def run_code(self, code, lang, callback):
        from .runner import Runner
        r = Runner(code, lang, callback)

        def pump():
            if r.poll():
                self.root.after(30, pump)
        self.root.after(10, pump)
        return r

    def uptime_ms(self):
        return (time.monotonic() - self.started) * 1000

    @staticmethod
    def platform_name():
        return platform.system() or sys.platform

    def signed_in_user(self):
        return self.me

    # ------------------------------------------------------------------ alarms, timers, events
    def ring_dialog(self, title, text, snooze_label):
        v = self.dialogs.choose(title, text, [('Dismiss', 'ok', 'pri'), ('Snooze 5 min', 'snooze', 'btn')], sticky=True,
                                on_show=lambda: self.ring(True))
        self.ring(False)
        if v == 'snooze':
            self.S['timers'].append({'id': uid(), 'label': snooze_label or 'Snoozed', 'dur': 300000,
                                     'end': now_ms() + 300000, 'state': 'run'})
            self.touch()
            self.bus.emit('chrono')
            self.toast('Snoozed for 5 minutes', '💤')

    def sched_tick(self):
        S = self.S
        now = _dt.datetime.now()
        t = now_ms()
        key = '%d-%02d-%02d' % (now.year, now.month, now.day)
        changed = False
        rings = []
        for tm in S['timers']:
            if tm.get('state') == 'run' and t >= tm.get('end', 0):
                tm['state'] = 'done'
                changed = True
                self.notify('Timer finished', tm.get('label') or 'Time is up.', '⏱️')
                rings.append(('⏱️ ' + (tm.get('label') or 'Timer'), 'Your timer has finished.', 'Timer: ' + (tm.get('label') or '')))
        wd = (now.weekday() + 1) % 7
        for a in S['alarms']:
            tm_ = a.get('time') or ''
            if not a.get('on') or len(tm_) != 5 or tm_[2] != ':' or not (tm_[:2] + tm_[3:]).isdigit():
                continue
            hh, mm = int(tm_[:2]), int(tm_[3:])
            at = _dt.datetime(now.year, now.month, now.day, hh, mm)
            at_ms = int(at.timestamp() * 1000)
            days = a.get('days') or []
            if (not days or wd in days) and t >= at_ms and t - at_ms < 5 * 60000 and a.get('last') != key:
                a['last'] = key
                changed = True
                if not days:
                    a['on'] = False
                self.notify('Alarm', a.get('label') or a['time'], '⏰')
                rings.append(('⏰ ' + (a.get('label') or 'Alarm'),
                              'It is ' + fmt_time(at, clock24=S['set'].get('clock24', True)) + '.', 'Alarm: ' + (a.get('label') or '')))
        for ev in S['events'].get(key) or []:
            tm_ = ev.get('time') or ''
            if not tm_ or ev.get('last') == key or len(tm_) < 5:
                continue
            try:
                hh, mm = int(tm_[:2]), int(tm_[3:5])
            except ValueError:
                continue
            at_ms = int(_dt.datetime(now.year, now.month, now.day, hh, mm).timestamp() * 1000)
            if t >= at_ms and t - at_ms < 5 * 60000:
                ev['last'] = key
                changed = True
                self.notify(ev.get('title', ''), 'Almanac · ' + tm_, '📅')
        if changed:
            self.touch()
            self.bus.emit('chrono')
        for r in rings:
            self.ring_dialog(*r)

    def _sys_tick(self):
        if self.quitting:
            return
        self.root.after(1000, self._sys_tick)
        self.ribbon.clock_text()
        self.safe(self.sched_tick)
        al = self.S['set'].get('autolock') or 0
        if (al > 0 and not self.lock.active and self.boot.el is None
                and time.monotonic() - self.last_active > al * 60):
            self.lock.show()

    def _fast_tick(self):
        if self.quitting:
            return
        audio.run_pending_callbacks()
        self.root.after(100, self._fast_tick)

    # ------------------------------------------------------------------ power
    def restart(self):
        if self.wm.list and not self.dialogs.confirm('Restart Quill?', 'Open windows will be closed. Unsaved changes in '
                                                     'them may be lost.', ok='Restart'):
            return
        self.save(True)
        self.wm.close_all()
        self.spread.close()
        self.ink.close()
        self.panels.hide()
        self.menu.hide()
        self.boot.show('Restarting…')
        self.sleep(1400)
        self.wm.switch_chapter(0)
        self.boot.hide()
        if self.S['user']['pin']:
            self.lock.show()

    def power_off(self):
        if self.wm.list and not self.dialogs.confirm('Shut down?', 'Open windows will be closed. Unsaved changes in '
                                                     'them may be lost.', ok='Shut down', danger=True):
            return
        self.save(True)
        self.wm.close_all()
        self.spread.close()
        self.ink.close()
        self.panels.hide()
        self.menu.hide()
        self.powered_off = True
        self.eyes.hide()
        try:
            PowerOff(self).show()
        finally:
            self.powered_off = False
        if self.quitting:
            return
        self.boot.show()
        self.sleep(1300)
        self.wm.switch_chapter(0)
        self.boot.hide()
        if self.S['user']['pin']:
            self.lock.show()

    def reload_ui(self):
        self.wm.close_all()
        self._thumbs.clear()
        self.apply_look()
        self.spine.render()
        self.desktop.icons()
        self.notes.render()
        self.bell_update()
        self.ribbon.clock_text()
        self.eyes.apply()
        self.xstore.state = self.S['xapps']      # a restored backup brings its own list
        register_xapps(self, self.xstore)
        self.spine.render()

    def on_close(self):
        """The computer's close button: like Shut down, it asks first while windows are open."""
        if not self.quitting and self.wm.list and not self.dialogs.active and not self.lock.active:
            if not self.dialogs.confirm('Close Quill.OS?', 'Open windows will be closed. Unsaved changes in them may '
                                        'be lost.', ok='Close', danger=True):
                return
        if not self.quitting:
            try:
                for w in list(self.wm.list):
                    fn = getattr(w.inst, 'on_close', None)
                    if fn:
                        self.safe(fn)
            except Exception:
                pass
            self.core.save(True)
            self.quitting = True
            self.sound.close()
            self.eyes.close()
            self.keyboard.close()
            self.osk.hide()
        if self._waits:
            for v in list(self._waits):
                try:
                    v.set(1)
                except tk.TclError:
                    pass
            self.root.after(50, self.on_close)
            return
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ start-up
    def start(self):
        S = self.S
        t0 = time.monotonic()
        self.boot.show()
        S['meta']['boots'] = S['meta'].get('boots', 0) + 1
        if S['set'].get('kbLayout'):
            self.set_layout(S['set']['kbLayout'])
        self.root.update_idletasks()
        self.apply_look()
        self.spine.render()
        self.notes.render()
        self.bell_update()
        self.ribbon.clock_text()
        first = not S['meta'].get('setup')
        elapsed = (time.monotonic() - t0) * 1000
        self.boot.wait(350 if S['set'].get('fastBoot') else int(max(300, 1500 - elapsed)))
        self.boot.hide()
        if self.quitting:
            return
        if first:
            setup_wizard(self)
            if self.quitting:
                return
            self.apply_look()
            self.spine.render()
        else:
            if S['user']['pin']:
                self.lock.show()
            require_galau(self)         # signed out since last time: an account is needed again
            if self.quitting:
                return
        self.touch()
        self._sys_tick()
        self._fast_tick()
        self.eyes.apply()
        if self.load_error:
            self.dialogs.alert('Saved data could not be read',
                               'Quill could not read your saved files, so it started empty and will not overwrite them. '
                               'Fix or move the file and start Quill again:\n' + self.core.store.path)
        if first and not self.quitting:
            self.notify('Welcome' + (', ' + S['user']['name'] if S['user']['name'] else ''),
                        'Press Ctrl+K to open the Inkwell.', '✒️')
            self.wm.open('guide')

    def run(self):
        self.root.after(0, lambda: self.safe(self.start))
        self.root.mainloop()


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog='quill', description='Quill.OS — an operating system made of ink and glass.')
    p.add_argument('--data', help='folder for the save file (default: your user data folder)')
    p.add_argument('--fullscreen', action='store_true', help='fill the whole screen with no window frame')
    size = p.add_mutually_exclusive_group()
    size.add_argument('--compact', dest='compact', action='store_true', default=None,
                      help='small-screen layout: every window opens maximised (automatic on screens up to 1024 x 640)')
    size.add_argument('--no-compact', dest='compact', action='store_false', help='the normal layout on any screen')
    touch = p.add_mutually_exclusive_group()
    touch.add_argument('--touch', dest='touch', action='store_true', default=None,
                       help='touchscreen: press and hold for menus, drag to scroll (on with the small-screen layout)')
    touch.add_argument('--no-touch', dest='touch', action='store_false', help='turn touchscreen behaviour off')
    args = p.parse_args(argv)
    if args.data:
        os.environ['QUILL_OS_HOME'] = os.path.abspath(args.data)
    try:
        root = tk.Tk(className='QuillOS')
    except tk.TclError as e:
        print('Quill.OS needs a graphical display: %s' % e, file=sys.stderr)
        return 1
    QuillOS(root, compact=args.compact, touch=args.touch, fullscreen=args.fullscreen).run()
    return 0
