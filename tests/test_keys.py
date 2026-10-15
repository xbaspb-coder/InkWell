"""Tests for the keyboard's special keys (no screen needed)."""

import os
import tempfile
import unittest

from quill_os.keys import (ACTIONS, DEFAULTS, EV_KEYS, KEYBOARD_KEYS, KNOWN, LAYOUTS, X_KEYS, Keyboard, action_for,
                           assignable, key_name, x_name)
from quill_os.system import Backlight, find_backlight
from quill_os.ui.osk import LETTERS, SYMBOLS, keysym_of


class FakeEcodes:
    KEY = {62: 'KEY_F4', 30: 'KEY_A', 113: ['KEY_MIN_INTERESTING', 'KEY_MUTE']}


class Calls(list):
    def __getattr__(self, name):
        return lambda *a: self.append((name,) + a)


class FakeOS:
    def __init__(self):
        self.S = {'set': {'volume': 70, 'bright': 100, 'keys': {}}}
        self.calls = Calls()
        self.quitting = False
        self.lock = type('L', (), {'active': False, 'show': lambda s: self.calls.append(('lock',))})()
        self.ink = type('I', (), {'toggle': lambda s: self.calls.append(('ink',))})()
        self.osk = type('K', (), {'toggle': lambda s: self.calls.append(('osk',))})()
        self.wm = type('W', (), {'open': lambda s, a: self.calls.append(('open', a))})()
        self.spread = type('P', (), {'el': None, 'open': lambda s: self.calls.append(('spread',)),
                                     'close': lambda s: None})()
        self.root = type('R', (), {'after': lambda s, ms, fn: fn()})()

    def touch(self):
        pass

    def apply_look(self):
        pass

    def osd(self, *a):
        self.calls.append(('osd',) + a)

    def set_system_volume(self, v):
        self.calls.append(('amixer', v))

    def media(self, cmd):
        self.calls.append(('media', cmd))

    def safe(self, fn, *a):
        return fn(*a)


def keyboard(os_):
    kb = Keyboard.__new__(Keyboard)          # without binding to a real screen
    kb.os = os_
    kb.reader = None
    kb.last = None
    return kb


class TestNames(unittest.TestCase):
    def test_every_default_is_an_action(self):
        for name, action in DEFAULTS.items():
            self.assertIn(action, ACTIONS, name)

    def test_every_key_name_has_a_default(self):
        for name in list(EV_KEYS.values()) + list(X_KEYS.values()):
            self.assertIn(name, DEFAULTS, name)
        for _where, _drawn, names in KEYBOARD_KEYS:
            for n in names:
                self.assertIn(n, DEFAULTS, n)

    def test_f4_is_the_camera(self):
        f4 = next(k for k in KEYBOARD_KEYS if k[0] == 'F4')
        self.assertEqual(action_for(f4[2][0], {}), 'camera')
        self.assertEqual(action_for('CAMERA', {}), 'camera')
        self.assertEqual(EV_KEYS[212], 'CAMERA')
        self.assertEqual(X_KEYS['XF86WebCam'], 'CAMERA')

    def test_overrides(self):
        self.assertEqual(action_for('CAMERA', {'CAMERA': 'files'}), 'files')
        self.assertEqual(action_for('CAMERA', {'CAMERA': 'rm -rf'}), 'camera')   # unknown actions are ignored
        self.assertEqual(action_for('CAMERA', 'broken'), 'camera')
        self.assertEqual(action_for('F4', {}), 'none')
        self.assertEqual(action_for('F4', {'F4': 'camera'}), 'camera')

    def test_key_names(self):
        self.assertEqual(key_name(212, FakeEcodes), 'CAMERA')
        self.assertEqual(key_name(62, FakeEcodes), 'F4')
        self.assertEqual(key_name(999, FakeEcodes), '999')
        self.assertEqual(key_name(62), '62')
        self.assertEqual(x_name('XF86WebCam'), 'CAMERA')
        self.assertEqual(x_name('F4'), 'F4')
        self.assertEqual(x_name('a'), 'A')

    def test_only_special_keys_are_assignable(self):
        self.assertTrue(assignable('X', 'F4', 70))
        self.assertTrue(assignable('X', 'XF86Tools', 191))
        self.assertTrue(assignable('Linux', 'F4', 62))
        self.assertTrue(assignable('Linux', 'CAMERA', 212))
        self.assertTrue(assignable('Linux', 'PROG1', 148))
        for name in ('a', 'A', 'ccedilla', 'Return', 'space', 'BackSpace', 'Shift_L', 'Super_L', 'Left', 'plus',
                     'guillemotleft'):
            self.assertFalse(assignable('X', name, 40), name)
        for code in (30, 28, 57, 14, 42, 105, 125, 126, 272, 330):     # A, Enter, Space, ⌫, Shift, ←, CMD, mouse, touch
            self.assertFalse(assignable('Linux', str(code), code), code)

    def test_layouts(self):
        self.assertEqual(LAYOUTS[0][0], '')
        self.assertIn('pt', dict(LAYOUTS))

    def test_known(self):
        self.assertIn('KEYBOARD', KNOWN)
        self.assertNotIn('F4', KNOWN)


class TestActions(unittest.TestCase):
    def setUp(self):
        self.os = FakeOS()
        self.kb = keyboard(self.os)

    def test_volume(self):
        s = self.os.S['set']
        self.kb.press('VOLUMEUP')
        self.assertEqual(s['volume'], 80)
        self.assertIn(('amixer', 80), self.os.calls)
        self.kb.press('MUTE')
        self.assertEqual((s['volume'], s['volMuted']), (0, 80))
        self.kb.press('MUTE')
        self.assertEqual(s['volume'], 80)
        for _ in range(20):
            self.kb.press('VOLUMEUP')
        self.assertEqual(s['volume'], 100)
        for _ in range(20):
            self.kb.press('VOLUMEDOWN')
        self.assertEqual(s['volume'], 0)
        self.kb.press('MUTE')                    # muted by turning it down: Mute gives 50 back
        self.assertEqual(s['volume'], 50)

    def test_brightness(self):
        s = self.os.S['set']
        for _ in range(20):
            self.kb.press('BRIGHTNESSDOWN')
        self.assertEqual(s['bright'], 20)
        self.kb.press('BRIGHTNESSUP')
        self.assertEqual(s['bright'], 30)
        self.assertEqual(self.os.calls[-1], ('osd', '☀', 'Brightness', 30))

    def test_each_key(self):
        cases = [('SEARCH', ('ink',)), ('CAMERA', ('open', 'iris')), ('KEYBOARD', ('osk',)), ('SCREENLOCK', ('lock',)),
                 ('HOMEPAGE', ('spread',)), ('PLAYPAUSE', ('media', 'playpause')), ('NEXTSONG', ('media', 'next')),
                 ('PREVIOUSSONG', ('media', 'prev')), ('STOPCD', ('media', 'stop')), ('WWW', ('open', 'ogb'))]
        for name, call in cases:
            self.os.calls.clear()
            self.kb.press(name)
            self.assertEqual(self.os.calls, [call], name)

    def test_lock_screen(self):
        self.os.lock.active = True
        for name in ('CAMERA', 'SEARCH', 'HOMEPAGE', 'PLAYPAUSE', 'SCREENLOCK'):
            self.kb.press(name)
        self.assertEqual(self.os.calls, [])
        self.kb.press('VOLUMEUP')
        self.kb.press('KEYBOARD')
        self.assertEqual(self.os.S['set']['volume'], 80)
        self.assertIn(('osk',), self.os.calls)

    def test_nothing_when_closing(self):
        self.os.quitting = True
        self.kb.press('CAMERA')
        self.assertEqual(self.os.calls, [])

    def test_reassigned(self):
        self.os.S['set']['keys'] = {'CAMERA': 'settings', 'SEARCH': 'none'}
        self.kb.press('CAMERA')
        self.kb.press('SEARCH')
        self.assertEqual(self.os.calls, [('open', 'loom')])


class TestEvdevReader(unittest.TestCase):
    """EvdevReader with a stand-in for python3-evdev: a pipe plays the keyboard."""

    def test_reads_presses_only(self):
        import sys
        import time
        import types
        r, w = os.pipe()
        Event = types.SimpleNamespace
        ecodes = types.SimpleNamespace(EV_KEY=1, KEY_A=30, KEY={374: 'KEY_KEYBOARD'})

        class Dev:
            def __init__(self, path):
                self.path = path
                self.fd = r if path == 'kbd' else -1
                self.closed = False

            def capabilities(self):
                return {1: [30, 31, 374]} if self.path == 'kbd' else {1: [272, 273]}     # a keyboard; a mouse

            def read(self):
                os.read(r, 1)
                return [Event(type=1, code=374, value=1),        # pressed
                        Event(type=1, code=374, value=2),        # held
                        Event(type=1, code=374, value=0),        # released
                        Event(type=1, code=272, value=1),        # a mouse button
                        Event(type=4, code=4, value=458823)]     # not a key

            def close(self):
                self.closed = True
        fake = types.SimpleNamespace(list_devices=lambda: ['kbd', 'mouse'], InputDevice=Dev, ecodes=ecodes)
        old = sys.modules.get('evdev')
        sys.modules['evdev'] = fake
        try:
            from quill_os.keys import EvdevReader
            reader = EvdevReader()
            self.assertEqual([d.path for d in reader.devices], ['kbd'])     # the mouse is left alone
            os.write(w, b'x')
            for _ in range(100):
                got = reader.poll()
                if got:
                    break
                time.sleep(0.01)
            self.assertEqual(got, [374])
            reader.close()
            self.assertTrue(reader.devices[0].closed)
            fake.list_devices = lambda: ['mouse']
            with self.assertRaises(OSError):
                EvdevReader()
        finally:
            if old is None:
                sys.modules.pop('evdev', None)
            else:
                sys.modules['evdev'] = old
            os.close(r)
            os.close(w)


class TestBacklight(unittest.TestCase):
    def test_backlight(self):
        base = tempfile.mkdtemp()
        self.assertIsNone(find_backlight(base))
        self.assertIsNone(find_backlight(os.path.join(base, 'missing')))
        d = os.path.join(base, 'rpi_backlight')
        os.mkdir(d)
        with open(os.path.join(d, 'max_brightness'), 'w') as f:
            f.write('255\n')
        with open(os.path.join(d, 'brightness'), 'w') as f:
            f.write('255\n')
        b = find_backlight(base)
        self.assertIsInstance(b, Backlight)
        self.assertTrue(b.set(50))
        with open(os.path.join(d, 'brightness')) as f:
            self.assertEqual(f.read(), '128')
        self.assertTrue(b.set(20))
        with open(os.path.join(d, 'brightness')) as f:
            self.assertEqual(f.read(), '51')


class TestOSK(unittest.TestCase):
    def test_rows(self):
        for plain, shifted in LETTERS:
            self.assertEqual(len(plain), len(shifted))
        for plain, _ in SYMBOLS:
            self.assertEqual(len(plain), len(plain.upper()))
        letters = ''.join(p + s for p, s in LETTERS)
        for ch in 'çÇºª«»':
            self.assertIn(ch, letters)
        self.assertIn('€', SYMBOLS[0][0])

    def test_keysyms(self):
        self.assertEqual(keysym_of('a'), 'a')
        self.assertEqual(keysym_of('7'), '7')
        self.assertEqual(keysym_of(' '), 'space')
        self.assertEqual(keysym_of('+'), 'plus')
        self.assertIsNone(keysym_of('ç'))


if __name__ == '__main__':
    unittest.main()
