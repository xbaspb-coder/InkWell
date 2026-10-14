"""Colours and fonts, and live re-theming of every widget.

Widgets register a small function with `theme.on(widget, fn)`; when the theme,
accent colour, brightness or text size changes, every registered function runs
again so open windows recolour themselves immediately.
"""

import sys
import tkinter as tk
import tkinter.font as tkfont

from ..util import hex_to_rgb, luminance, mix, rgb_to_hex

THEMES = {
    'ink': dict(bg0='#0a0c13', bg1='#11141e', bg2='#181c29', bg3='#232837', fg='#ebe7da', fg2='#a6a497',
                line_tint='#ffffff', line_amt=.1, paper='#f3ead2', paper_fg='#2b2418', dark=True),
    'parchment': dict(bg0='#e8dfc6', bg1='#f4ecd8', bg2='#fbf6e8', bg3='#e6dcc0', fg='#2b2418', fg2='#6d6247',
                      line_tint='#3c2d0a', line_amt=.16, paper='#fffaf0', paper_fg='#2b2418', dark=False),
    'aurora': dict(bg0='#070f17', bg1='#0d1b27', bg2='#13283a', bg3='#1d3a50', fg='#e4f4ee', fg2='#8fb3b0',
                   line_tint='#a0ffe6', line_amt=.13, paper='#e9f6f0', paper_fg='#10262d', dark=True),
    'ember': dict(bg0='#150a08', bg1='#201210', bg2='#2c1a16', bg3='#3d2620', fg='#f6e6d8', fg2='#b99c88',
                  line_tint='#ffc8a0', line_amt=.13, paper='#f7e9d6', paper_fg='#33201a', dark=True),
}
THEME_NAMES = {'ink': 'Ink', 'parchment': 'Parchment', 'aurora': 'Aurora', 'ember': 'Ember'}
THEME_BG = {'ink': '#11141e', 'parchment': '#f4ecd8', 'aurora': '#0d1b27', 'ember': '#201210'}
THEME_WALL = {'ink': 'drift', 'parchment': 'parch', 'aurora': 'aurora', 'ember': 'ember'}

TOKENS_DARK = {'tk_k': '#c586c0', 'tk_s': '#8fcf80', 'tk_n': '#e0a060', 'tk_c': '#7a8296', 'tk_f': '#7cc4ff',
               'tk_t': '#ff8b7a', 'tk_a': '#e8c06a'}
TOKENS_LIGHT = {'tk_k': '#8a2f9b', 'tk_s': '#2f7a28', 'tk_n': '#a6561a', 'tk_c': '#7a8296', 'tk_f': '#1a62a8',
                'tk_t': '#b02c1c', 'tk_a': '#8a6a10'}

SERIFS = ['Georgia', 'Iowan Old Style', 'Palatino Linotype', 'Palatino', 'Book Antiqua', 'DejaVu Serif',
          'Liberation Serif', 'Noto Serif', 'Times New Roman', 'Times']
MONOS = ['Consolas', 'SF Mono', 'Menlo', 'Cascadia Mono', 'DejaVu Sans Mono', 'Liberation Mono', 'Noto Sans Mono',
         'Ubuntu Mono', 'Courier New', 'Courier']
SANS = ['Segoe UI', 'SF Pro Text', 'Helvetica Neue', 'Inter', 'Cantarell', 'Ubuntu', 'Noto Sans', 'DejaVu Sans',
        'Liberation Sans', 'Arial', 'Helvetica']
HANDS = ['Segoe Print', 'Bradley Hand', 'Comic Neue', 'Chalkboard', 'Purisa']


class Theme:
    def __init__(self, root):
        self.root = root
        families = set(tkfont.families(root))
        default = tkfont.nametofont('TkDefaultFont', root).actual('family')
        self.fam = {
            'sans': next((f for f in SANS if f in families), default),
            'serif': next((f for f in SERIFS if f in families), 'Times'),
            'mono': next((f for f in MONOS if f in families), 'Courier'),
        }
        self.fam['hand'] = next((f for f in HANDS if f in families), self.fam['serif'])
        self.c = {}
        self.scale = 1.0
        self._fonts = {}
        self._subs = []
        self.settings = None
        self.dark = True

    # ---------------------------------------------------------- colours
    def compute(self, s):
        t = THEMES.get(s.get('theme'), THEMES['ink'])
        c = {k: t[k] for k in ('bg0', 'bg1', 'bg2', 'bg3', 'fg', 'fg2', 'paper', 'paper_fg')}
        c['line'] = mix(t['bg1'], t['line_tint'], t['line_amt'])
        c['line2'] = mix(t['bg2'], t['line_tint'], t['line_amt'])
        c['glass'] = mix(t['bg1'], t['bg0'], .25)
        c['hover'] = mix(t['bg3'], t['fg'], .12)
        acc = s.get('accent') or '#e8b04a'
        if len(acc) != 7:
            acc = rgb_to_hex(hex_to_rgb(acc))
        c['acc'] = acc
        c['acc_fg'] = '#1a1306' if luminance(acc) > 0.55 else '#ffffff'
        c['acc_soft'] = mix(t['bg1'], acc, .2)
        c['acc_soft2'] = mix(t['bg2'], acc, .2)
        c['acc_dark'] = mix(acc, '#000000', .45)
        c['acc_hover'] = mix(acc, '#ffffff', .12)
        c['acc_line'] = mix(c['line'], acc, .45)
        c['red'] = '#ff7a6b'
        c['danger'] = '#c0392b'
        c['dng'] = '#a93226'
        c['ok'] = '#7ac74f'
        c['warn'] = '#e8c06a'
        c['blue'] = '#7cc4ff'
        c['dim'] = '#7a8296'
        c['term_bg'] = '#0a0c10'
        c['term_fg'] = '#d8d8cf'
        c['white'] = '#ffffff'
        c['black'] = '#000000'
        c['disabled'] = mix(t['fg'], t['bg2'], .55)
        c['icon_text'] = '#ffffff' if t['dark'] else '#2b2418'
        c.update(TOKENS_DARK if t['dark'] else TOKENS_LIGHT)
        bright = s.get('bright', 100)
        if bright < 100:
            k = 0.35 + 0.65 * bright / 100
            c = {key: _dim(v, k) for key, v in c.items()}
        self.dark = t['dark']
        return c

    def __getitem__(self, key):
        if key and key.startswith('#'):
            return key
        return self.c[key]

    def apply(self, settings):
        """Recompute colours and fonts from the settings and update every widget."""
        self.settings = settings
        self.c = self.compute(settings)
        size = max(12, min(18, int(settings.get('fs', 14) or 14)))
        self.scale = size / 14.0
        for key, f in self._fonts.items():
            f.configure(size=-max(7, round(key[1] * self.scale)))
        self.root.configure(bg=self.c['bg0'])
        alive = []
        for w, fn in self._subs:
            try:
                if w is not None and not w.winfo_exists():
                    continue
                fn()
                alive.append((w, fn))
            except tk.TclError:
                continue
        self._subs = alive

    def on(self, widget, fn, now=True):
        """Run fn now and whenever the theme changes, while widget exists."""
        self._subs.append((widget, fn))
        if now and self.c:
            fn()
        return fn

    def style(self, widget, **opts):
        """Configure widget options from colour names, e.g. style(w, bg='bg1', fg='fg')."""
        def fn():
            widget.configure(**{k: (self[v] if isinstance(v, str) else v(self)) for k, v in opts.items()})
        return self.on(widget, fn)

    # ---------------------------------------------------------- fonts
    def font(self, family='sans', px=14, weight='normal', slant='roman', underline=False):
        """A shared font that follows the text-size setting. px is the size at 'Medium'."""
        key = (family, px, weight, slant, underline)
        f = self._fonts.get(key)
        if f is None:
            f = tkfont.Font(self.root, family=self.fam.get(family, family), size=-max(7, round(px * self.scale)),
                            weight=weight, slant=slant, underline=1 if underline else 0)
            self._fonts[key] = f
        return f

    def px(self, n):
        return int(round(n * self.scale))


def _dim(color, k):
    if not isinstance(color, str) or not color.startswith('#'):
        return color
    r, g, b = hex_to_rgb(color)
    return rgb_to_hex((r * k, g * k, b * k))


def is_mac():
    return sys.platform == 'darwin'
