"""The saved state of Quill.OS: defaults, the starter files and normalisation.

The structure is identical to the original page, so a backup exported from
the HTML version (Loom → Storage → Export) can be imported here and back.
"""

import copy

from .util import now_ms, uid

FIXED = {
    'root': 'root', 'desktop': 'd-desktop', 'documents': 'd-documents', 'pictures': 'd-pictures',
    'music': 'd-music', 'downloads': 'd-downloads', 'projects': 'd-projects',
}
# 'portal' takes the place of the OG Browser app because this build has no embedded browser.
DEFAULT_DOCK = ['files', 'scribe', 'glyph', 'term', 'calc', 'brush', 'lyre', 'chrono', 'almanac', 'arcade', 'portal', 'loom']
ACCENTS = ['#e8b04a', '#ff7a59', '#e0577e', '#a78bfa', '#5aa7ff', '#35c9b0', '#7ac74f', '#c9b08a']
DEFAULT_PATTERN = [
    [1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1],
    [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 1],
    [0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0],
]

# Storage limits from the original (kept so that backups move freely between
# the HTML and the Python version).
STORE_LIMIT = 4300000
FILE_LIMIT = 1600000

WELCOME_MD = """# Welcome to Quill.OS

Quill is a small operating system that lives inside **OG Browser**. Everything is built from scratch — the windows, the files, the apps.

## The basics
- Press **Ctrl+K** (or click the quill at the top of the left bar) to open the **Inkwell**: it launches apps, finds files and does maths.
- The left bar is the **Spine**. Right-click an app there to pin it or open another window.
- The numbers **I II III IV** at the top are your **Chapters** — four desktops. Move windows between them from the title bar menu.
- **Spread** (Alt+S) shows every window at a glance.

## Things to try
1. Open **Atlas** (files) and make a folder.
2. Write in **Scribe**; it saves to Documents. This file is Markdown, so it has a live preview.
3. Run code in **Glyph**: open `hello.js` in Projects and press Run.
4. Open the **terminal** and type `neofetch`.
5. Make music in **Lyre** — use the keyboard row A S D F G H J.
6. Right-click the desktop to add a **margin note**.

> Your files are saved on this device. Sign in with Galau services and turn on cloud sync in **Loom** (settings) to keep them in your account.
"""

HELLO_JS = ('// Press ▶ Run in Glyph to execute this file.\nconst names = ["Quill", "Ink", "Page"];\n'
            'for (const n of names) console.log("Hello, " + n + "!");\nconsole.log("2 ** 10 =", 2 ** 10);\n')

PAGE_HTML = ('<!doctype html>\n<html>\n<head>\n<meta charset="utf-8">\n<style>\n'
             '  body{font-family:Georgia,serif;display:grid;place-items:center;height:100vh;margin:0;background:#101420;color:#f3ead2}\n'
             '  h1{font-style:italic;font-weight:400;font-size:44px}\n'
             '  button{font-size:16px;padding:8px 18px;border-radius:10px;border:0;background:#e8b04a;cursor:pointer}\n'
             '</style>\n</head>\n<body>\n  <div style="text-align:center">\n    <h1>Hello from Quill</h1>\n'
             '    <button onclick="this.textContent=\'Clicked \'+(++n)+\'×\'">Click me</button>\n  </div>\n'
             '  <script>var n=0;</script>\n</body>\n</html>\n')

EMBLEM_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 200" width="320" height="200"><defs>'
              '<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1b2340"/>'
              '<stop offset="1" stop-color="#0a0c13"/></linearGradient></defs><rect width="320" height="200" rx="16" fill="url(#g)"/>'
              '<g transform="translate(110 30) scale(3.2)"><path fill="#e8b04a" d="M27 3C14.5 3.4 7.4 10.4 6.4 21.3L4 29l7.6-2.3C22.5 25.8 28.4 17.6 27 3z"/>'
              '<path d="M5.5 28.5 19 12.5" stroke="#0a0c13" stroke-opacity=".4" stroke-width="1.6" fill="none" stroke-linecap="round"/></g>'
              '<text x="160" y="178" text-anchor="middle" font-family="Georgia,serif" font-style="italic" font-size="22" fill="#f3ead2">Quill.OS</text></svg>')


def def_state():
    return {
        'v': 1,
        'meta': {'modified': 0, 'created': now_ms(), 'boots': 0, 'setup': False, 'synced': 0},
        'user': {'name': '', 'pin': ''},
        'set': {'theme': 'ink', 'accent': ACCENTS[0], 'wall': 'drift', 'wallColor': '#1b2340', 'wallImg': '',
                'clock24': True, 'volume': 70, 'bright': 100, 'uisnd': True, 'anim': True, 'fs': 14, 'autolock': 0,
                'autosync': False, 'dnd': False, 'dock': list(DEFAULT_DOCK), 'fastBoot': False,
                # Inkwell hardware: the distance sensor ("eyes") and the ESP32 camera
                'eyes': True, 'eyesCm': 30, 'eyesTrig': 23, 'eyesEcho': 24, 'camUrl': 'http://192.168.4.1',
                # the keyboard: what each special key does (when changed in Loom) and the layout ('' = as it is)
                'keys': {}, 'kbLayout': ''},
        'lyre': {'pat': copy.deepcopy(DEFAULT_PATTERN), 'bpm': 110, 'inst': 'triangle', 'oct': 4},
        'fs': {}, 'notes': [], 'events': {}, 'alarms': [], 'timers': [], 'notifs': [], 'scores': {}, 'hist': [], 'recent': [],
        'xapps': {},   # installed XApps: id -> name, icon, colour, version …
    }


def seed_fs(fs):
    now = now_ms()

    def mkdir(id_, name, parent):
        fs[id_] = {'id': id_, 'n': name, 't': 'd', 'p': parent, 'm': now, 'r': now}

    fs['root'] = {'id': 'root', 'n': '', 't': 'd', 'p': None, 'm': now, 'r': now}
    mkdir(FIXED['desktop'], 'Desktop', 'root')
    mkdir(FIXED['documents'], 'Documents', 'root')
    mkdir(FIXED['pictures'], 'Pictures', 'root')
    mkdir(FIXED['music'], 'Music', 'root')
    mkdir(FIXED['downloads'], 'Downloads', 'root')
    mkdir(FIXED['projects'], 'Projects', 'root')

    def f(name, parent, content):
        i = uid()
        fs[i] = {'id': i, 'n': name, 't': 'f', 'p': parent, 'c': content, 'm': now, 'r': now}

    f('Welcome.md', FIXED['documents'], WELCOME_MD)
    f('Ideas.txt', FIXED['documents'],
      'Ideas\n=====\n\n- Write something worth keeping.\n- Press Ctrl+K and type “calc 12*(3+4)” or just “= 12*(3+4)”.\n'
      '- Try the terminal: open it and type  neofetch\n')
    f('hello.js', FIXED['projects'], HELLO_JS)
    f('page.html', FIXED['projects'], PAGE_HTML)
    f('Quill emblem.svg', FIXED['pictures'], EMBLEM_SVG)
    f('README.md', FIXED['desktop'],
      '# Your desktop\n\nFiles you put in the **Desktop** folder show up here as icons. Right-click the desktop for more.\n')


def merge_deep(base, add):
    if not isinstance(add, dict):
        return base
    for k, v in add.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merge_deep(base[k], v)
        else:
            base[k] = v
    return base


def normalize_state(raw):
    s = def_state()
    if isinstance(raw, dict):
        for k in ('meta', 'user', 'set', 'lyre'):
            if raw.get(k):
                merge_deep(s[k], raw[k])
        pt = s['lyre'].get('pat')
        if (not isinstance(pt, list) or len(pt) != 4
                or any(not isinstance(r, list) or len(r) != 16 for r in pt)):
            s['lyre']['pat'] = copy.deepcopy(DEFAULT_PATTERN)
        for k in ('fs', 'scores', 'xapps'):
            if isinstance(raw.get(k), dict):
                s[k] = raw[k]
        for k in ('notes', 'alarms', 'timers', 'notifs', 'hist', 'recent'):
            if isinstance(raw.get(k), list):
                s[k] = raw[k]
        if isinstance(raw.get('events'), dict):
            s['events'] = raw['events']
    if not s['fs'].get('root'):
        seed_fs(s['fs'])
    else:
        now = now_ms()
        for key, id_ in FIXED.items():
            if key != 'root' and id_ not in s['fs']:
                s['fs'][id_] = {'id': id_, 'n': key[0].upper() + key[1:], 't': 'd', 'p': 'root', 'm': now, 'r': now}
    if not isinstance(s['set'].get('dock'), list):
        s['set']['dock'] = list(DEFAULT_DOCK)
    if not isinstance(s['set'].get('keys'), dict):
        s['set']['keys'] = {}
    return s
