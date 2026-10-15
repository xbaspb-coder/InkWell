"""Inkwell's keyboard: the special keys (brightness, search, camera, on-screen keyboard, media,
volume, lock …) and the CMD key.

Special keys are read in two ways:
  * through the Linux input devices (python3-evdev), which sees every key, even the ones
    the X window system cannot pass on (key numbers above 255, such as the keyboard key);
  * otherwise through X, by their XF86 key names.
Only one of the two is used at a time, so a key never acts twice.

What each key does can be changed in Loom → Keyboard, which also shows what a key sends.
"""

import queue
import select
import threading
from collections import OrderedDict

# What a key can do (shown in Loom).
ACTIONS = OrderedDict([
    ('none', 'Nothing'), ('bright_down', 'Brightness down'), ('bright_up', 'Brightness up'),
    ('search', 'Search (open the Inkwell)'), ('camera', 'Camera (open Iris)'), ('osk', 'On-screen keyboard'),
    ('stop', 'Stop music'), ('prev', 'Previous track'), ('playpause', 'Play or pause'), ('next', 'Next track'),
    ('mute', 'Mute'), ('vol_down', 'Volume down'), ('vol_up', 'Volume up'), ('lock', 'Lock the screen'),
    ('spread', 'Spread (all windows)'), ('inkwell', 'Open the Inkwell'), ('files', 'Open Atlas (files)'),
    ('browser', 'Open OG Browser'), ('xapps', 'Open XApps'), ('settings', 'Open Loom (settings)'),
])

# Keyboard layouts Loom offers (X names); '' leaves the computer's own setting alone.
LAYOUTS = [('', 'Unchanged'), ('pt', 'Portuguese (Portugal)'), ('br', 'Portuguese (Brazil)'),
           ('us', 'English (US)'), ('gb', 'English (UK)'), ('es', 'Spanish'), ('fr', 'French'), ('de', 'German')]

# Linux key numbers (linux/input-event-codes.h) of the special keys, with Quill's name for each.
EV_KEYS = {
    113: 'MUTE', 114: 'VOLUMEDOWN', 115: 'VOLUMEUP', 120: 'SCALE', 128: 'STOP', 136: 'FIND', 142: 'SLEEP',
    150: 'WWW', 152: 'SCREENLOCK', 163: 'NEXTSONG', 164: 'PLAYPAUSE', 165: 'PREVIOUSSONG', 166: 'STOPCD',
    172: 'HOMEPAGE', 200: 'PLAYCD', 201: 'PAUSECD', 204: 'DASHBOARD', 212: 'CAMERA', 217: 'SEARCH',
    224: 'BRIGHTNESSDOWN', 225: 'BRIGHTNESSUP', 228: 'KBDILLUMTOGGLE', 374: 'KEYBOARD', 442: 'IMAGES',
    587: 'CAMERA_ACCESS_TOGGLE',
}

# The same keys as X names them.
X_KEYS = {
    'XF86AudioMute': 'MUTE', 'XF86AudioLowerVolume': 'VOLUMEDOWN', 'XF86AudioRaiseVolume': 'VOLUMEUP',
    'XF86AudioStop': 'STOP', 'XF86AudioPrev': 'PREVIOUSSONG', 'XF86AudioPlay': 'PLAYPAUSE',
    'XF86AudioPause': 'PLAYPAUSE', 'XF86AudioNext': 'NEXTSONG', 'XF86MonBrightnessDown': 'BRIGHTNESSDOWN',
    'XF86MonBrightnessUp': 'BRIGHTNESSUP', 'XF86Search': 'SEARCH', 'XF86Find': 'FIND', 'XF86WebCam': 'CAMERA',
    'XF86Pictures': 'IMAGES', 'XF86KbdLightOnOff': 'KBDILLUMTOGGLE', 'XF86ScreenSaver': 'SCREENLOCK',
    'XF86Sleep': 'SLEEP', 'XF86HomePage': 'HOMEPAGE', 'XF86LaunchA': 'SCALE', 'XF86LaunchB': 'DASHBOARD',
    'XF86WWW': 'WWW',
}

# What each key does unless it is changed in Loom.
DEFAULTS = {
    'MUTE': 'mute', 'VOLUMEDOWN': 'vol_down', 'VOLUMEUP': 'vol_up', 'STOP': 'stop', 'STOPCD': 'stop',
    'PREVIOUSSONG': 'prev', 'PLAYPAUSE': 'playpause', 'PLAYCD': 'playpause', 'PAUSECD': 'playpause',
    'NEXTSONG': 'next', 'BRIGHTNESSDOWN': 'bright_down', 'BRIGHTNESSUP': 'bright_up', 'SEARCH': 'search',
    'FIND': 'search', 'CAMERA': 'camera', 'CAMERA_ACCESS_TOGGLE': 'camera', 'IMAGES': 'camera',
    'KEYBOARD': 'osk', 'KBDILLUMTOGGLE': 'osk', 'SCREENLOCK': 'lock', 'SLEEP': 'lock', 'HOMEPAGE': 'spread',
    'SCALE': 'spread', 'DASHBOARD': 'spread', 'WWW': 'browser',
}


# The keys of Inkwell's keyboard, as Loom lists them: (where it is, what is drawn on it, the names it may send).
KEYBOARD_KEYS = [
    ('F1', '☀ − (sun, small)', ['BRIGHTNESSDOWN']),
    ('F2', '☀ + (sun, big)', ['BRIGHTNESSUP']),
    ('F3', '🔍 (magnifier)', ['SEARCH', 'FIND']),
    ('F4', '📷 (camera)', ['CAMERA', 'CAMERA_ACCESS_TOGGLE', 'IMAGES']),
    ('F5', '⌨ (keyboard)', ['KEYBOARD', 'KBDILLUMTOGGLE']),
    ('F6', '⏹ (stop)', ['STOPCD', 'STOP']),
    ('F7', '⏮ (previous)', ['PREVIOUSSONG']),
    ('F8', '⏯ (play / pause)', ['PLAYPAUSE', 'PLAYCD', 'PAUSECD']),
    ('F9', '⏭ (next)', ['NEXTSONG']),
    ('F10', '🔇 (mute)', ['MUTE']),
    ('F11', '🔉 (volume down)', ['VOLUMEDOWN']),
    ('F12', '🔊 (volume up)', ['VOLUMEUP']),
    ('Top left', '▭ (windows)', ['HOMEPAGE', 'SCALE', 'DASHBOARD']),
    ('Top right', '🔒 (padlock)', ['SCREENLOCK', 'SLEEP']),
]
KNOWN = {n for _w, _d, names in KEYBOARD_KEYS for n in names} | set(DEFAULTS)


def action_for(name, overrides):
    a = overrides.get(name) if isinstance(overrides, dict) else None
    return a if a in ACTIONS else DEFAULTS.get(name, 'none')


def key_name(code, ecodes=None):
    """Quill's name for a Linux key number: KEY_F4 -> 'F4', KEY_CAMERA -> 'CAMERA'."""
    if code in EV_KEYS:
        return EV_KEYS[code]
    n = (ecodes.KEY.get(code) if ecodes is not None else None) or str(code)
    if isinstance(n, (list, tuple)):     # several names for one number: take the first
        n = n[0]
    return n[4:] if n.startswith('KEY_') else n


_X_EXTRA = {'Print', 'Pause', 'Scroll_Lock', 'Menu', 'Cancel', 'Help', 'Find', 'Execute', 'Redo', 'Undo'}
_EV_TYPING = {117, 118, 121, 122, 123, 124, 125, 126, 127}   # keypad =, ±, keypad comma, Hangul, Hanja, Yen, CMD keys, Compose


def assignable(source, name, code):
    """True for a key that may be given an action in Loom: function and special keys, never a key
    used for typing (letters, numbers, punctuation, Enter, Shift, the arrows …)."""
    if name in KNOWN:
        return True
    if source == 'X':
        return name.startswith('XF86') or name in _X_EXTRA or (name[:1] == 'F' and name[1:].isdigit())
    try:
        code = int(code)
    except (TypeError, ValueError):
        return False
    return (59 <= code <= 68 or code in (70, 87, 88, 99, 119) or 183 <= code <= 194
            or (113 <= code < 0x100 and code not in _EV_TYPING) or 0x160 <= code < 0x2c0)


def x_name(keysym):
    """Quill's name for an X key: XF86WebCam -> 'CAMERA', F4 -> 'F4', a -> 'A'."""
    if keysym in X_KEYS:
        return X_KEYS[keysym]
    return keysym.upper() if len(keysym) == 1 else keysym


class EvdevReader:
    """Reads key presses from every keyboard in /dev/input on a background thread."""

    def __init__(self):
        import evdev       # python3-evdev; ImportError when it is missing
        self.evdev = evdev
        self.devices = []
        for path in evdev.list_devices():
            try:
                d = evdev.InputDevice(path)
                keys = d.capabilities().get(evdev.ecodes.EV_KEY, [])
            except (OSError, PermissionError):
                continue
            # A keyboard (it has letter keys) or a media-key device (it has one of our keys).
            if evdev.ecodes.KEY_A in keys or any(k in EV_KEYS for k in keys):
                self.devices.append(d)
            else:
                d.close()
        if not self.devices:
            raise OSError('no keyboard could be read (is this user in the "input" group?)')
        self.events = queue.Queue()
        self._stop = threading.Event()
        threading.Thread(target=self._run, name='quill-keys', daemon=True).start()

    def _run(self):
        fds = {d.fd: d for d in self.devices}
        while not self._stop.is_set() and fds:
            try:
                ready, _w, _x = select.select(list(fds), [], [], 0.5)
            except (OSError, ValueError):
                break
            for fd in ready:
                d = fds[fd]
                try:
                    for ev in d.read():
                        # pressed (not held, not released); 0x100-0x15f are mouse and touch buttons
                        if ev.type == self.evdev.ecodes.EV_KEY and ev.value == 1 and not 0x100 <= ev.code < 0x160:
                            self.events.put(ev.code)
                except OSError:                                                      # unplugged
                    fds.pop(fd, None)

    def poll(self):
        out = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out

    def close(self):
        self._stop.set()
        for d in self.devices:
            try:
                d.close()
            except OSError:
                pass


class Keyboard:
    """Connects the special keys and the CMD key to Quill."""

    POLL_MS = 40

    def __init__(self, os_, use_evdev=True):
        self.os = os_
        self.reader = None
        self.last = None             # (source, name, number) of the last key, for Loom's tester
        self._job = None
        self._super = {'down': False, 'used': False}
        if use_evdev:
            try:
                self.reader = EvdevReader()
            except Exception as e:   # no evdev, no permission, no keyboard: X still works
                self.reader_error = str(e)
            else:
                self.reader_error = ''
        else:
            self.reader_error = 'not used'
        root = os_.root
        for xname, name in X_KEYS.items():
            try:
                root.bind_all('<KeyPress-%s>' % xname, lambda e, n=name: self._from_x(n), add='+')
            except Exception:        # this X server does not know the key name
                pass
        root.bind_all('<KeyPress>', self._note, add='+')
        self._bind_super(root)
        if self.reader is not None:
            self._job = root.after(self.POLL_MS, self._poll)

    @property
    def source(self):
        return 'evdev' if self.reader is not None else 'x'

    # ---------------------------------------------------------- receiving keys
    def _note(self, e):
        name = x_name(e.keysym)
        if self.reader is None:
            self.last = ('X', name, e.keycode)
            # A key given an action in Loom although Quill does not know it (such as F4 when the
            # keyboard sends a plain F4): do that action.
            if (e.keysym not in X_KEYS and name not in KNOWN and assignable('X', name, e.keycode)
                    and self._custom(name)):
                self.press(name)

    def _from_x(self, name):
        if self.reader is None:      # otherwise evdev already handles it
            self.press(name)

    def _poll(self):
        self._job = None
        if self.os.quitting or self.reader is None:
            return
        for code in self.reader.poll():
            name = key_name(code, self.reader.evdev.ecodes)
            self.last = ('Linux', name, code)
            if code in EV_KEYS or (assignable('Linux', name, code) and self._custom(name)):
                self.press(name)
        self._job = self.os.root.after(self.POLL_MS, self._poll)

    def _custom(self, name):
        keys = self.os.S['set'].get('keys')
        return isinstance(keys, dict) and keys.get(name, 'none') in ACTIONS and keys.get(name, 'none') != 'none'

    def close(self):
        if self.reader is not None:
            self.reader.close()
            self.reader = None

    # ---------------------------------------------------------- doing what the key means
    def press(self, name):
        os_ = self.os
        if os_.quitting or getattr(os_, 'powered_off', False):
            return
        action = action_for(name, os_.S['set'].get('keys'))
        busy = os_.lock.active or getattr(getattr(os_, 'dialogs', None), 'active', False)
        if busy and action not in ('mute', 'vol_down', 'vol_up', 'bright_down', 'bright_up', 'osk'):
            return               # on the lock screen and in a dialog only volume, brightness and the on-screen keyboard work
        os_.safe(self.do, action)

    def do(self, action):
        os_ = self.os
        s = os_.S['set']
        if action == 'none':
            return
        if action in ('bright_down', 'bright_up'):
            s['bright'] = max(20, min(100, int(s.get('bright', 100)) + (10 if action == 'bright_up' else -10)))
            os_.touch()
            os_.apply_look()
            os_.osd('☀', 'Brightness', s['bright'])
        elif action in ('vol_down', 'vol_up', 'mute'):
            vol = int(s.get('volume', 70))
            if action == 'mute':
                if vol > 0:
                    s['volMuted'] = vol
                    vol = 0
                else:
                    vol = int(s.get('volMuted') or 50)
            else:
                vol = max(0, min(100, vol + (10 if action == 'vol_up' else -10)))
                s.pop('volMuted', None)     # turned by hand: Mute starts afresh
            s['volume'] = vol
            os_.touch()
            os_.apply_look()
            os_.set_system_volume(vol)
            os_.osd('🔇' if vol == 0 else '🔊', 'Volume', vol)
        elif action == 'search' or action == 'inkwell':
            os_.ink.toggle()
        elif action == 'camera':
            os_.wm.open('iris')
        elif action == 'osk':
            os_.osk.toggle()
        elif action in ('stop', 'prev', 'playpause', 'next'):
            os_.media(action)
        elif action == 'lock':
            os_.root.after(10, os_.lock.show)
        elif action == 'spread':
            os_.spread.close() if os_.spread.el is not None else os_.spread.open()
        elif action == 'files':
            os_.wm.open('files')
        elif action == 'browser':
            os_.wm.open('ogb')
        elif action == 'xapps':
            os_.wm.open('xapps')
        elif action == 'settings':
            os_.wm.open('loom')

    # ---------------------------------------------------------- the CMD key
    def _bind_super(self, root):
        """CMD (the Super key) works like a Mac's Command key: alone it opens the Inkwell,
        and with another key it does what Ctrl with that key does (copy, paste, save …)."""
        sup = self._super

        def down(_e):
            sup['down'], sup['used'] = True, False

        def up(_e):
            if sup['down'] and not sup['used'] and not self.os.lock.active and not self.os.dialogs.active:
                self.os.ink.toggle()
            sup['down'] = False

        def combo(e):
            if e.keysym in ('Super_L', 'Super_R'):
                return None
            sup['used'] = True
            widget = e.widget if not isinstance(e.widget, str) else None
            target = widget or self.os.root.focus_get() or self.os.root
            key = e.keysym if len(e.keysym) > 1 else e.keysym.lower()
            try:
                target.event_generate('<Control-KeyPress-%s>' % key)
            except Exception:
                pass
            return 'break'       # the letter itself is not typed
        for side in ('Super_L', 'Super_R'):
            try:
                root.bind_all('<KeyPress-%s>' % side, down, add='+')
                root.bind_all('<KeyRelease-%s>' % side, up, add='+')
            except Exception:
                pass
        # Text fields type the letter in their class bindings, which run before bind_all: catch it there.
        for cls in ('Entry', 'Text'):
            root.bind_class(cls, '<Mod4-KeyPress>', combo)
        root.bind_all('<Mod4-KeyPress>', combo)
