"""Guide — how to use Quill.OS."""

from .base import AppSpec, Inst
from ..ui.mdview import make_view, render

GUIDE_MD = """# Quill.OS Guide

An operating system made of ink and glass. This guide covers everything.

## The desktop
- **The Spine** (left bar): your apps. Click to open, click again to minimise. Right-click for more, or to pin and unpin.
- **The Inkwell** (the quill at the top of the Spine, or **Ctrl+K**): type to launch apps, find files, run quick sums (`= 12*(3+4)`), search OG, or run a terminal command with `>`.
- **Chapters**: the I II III IV buttons in the ribbon are four separate desktops. **Alt+1** to **Alt+4** switch. Right-click a title bar to send a window to another chapter.
- **Spread** (**Alt+S**): a card for every window.
- **Margin notes**: right-click the desktop to pin a sticky note. They are saved for you.
- **Snapping**: drag a window to the left or right edge to fill half the screen, or to the top to maximise.

## The apps
| App | What it does |
| --- | --- |
| **Atlas** | Files and folders. Drag and drop, copy, cut, paste, rename, Trash, upload, export |
| **Scribe** | Notes with Markdown and a live preview |
| **Glyph** | Code editor with highlighting, find and replace, and **Run** for JavaScript, Python, HTML and JSON |
| **OG Browser** | The OG Browser, in its own window. **◀ Quill.OS** comes back here and keeps it open |
| **Quill Shell** | A command line with pipes, redirects and over 70 commands |
| **Abacus** | Calculator with a scientific mode and history |
| **Brush** | Paint with pencil, brush, spray, shapes, fill and undo |
| **Chrono** | Clock, stopwatch, timers and alarms that ring even when the window is closed |
| **Lyre** | Piano, a beat maker and a music player for your own files |
| **Lens** | Image viewer: zoom, rotate, wallpaper |
| **Iris** | The camera: live picture and photos into Pictures |
| **XApps** | The app store: install apps people made, or publish your own HTML app |
| **Almanac** | Calendar with events and reminders |
| **Arcade** | Snake, 2048 and Minesweeper |
| **Pulse** | Task manager, performance graphs and services |
| **Portal** | Jump to Galau Mail, Ferret, LifeCraft, LifeGames and the other OG sites |
| **Compass** | Opens web pages in a web window, and .og sites in OG Browser |
| **Loom** | Settings: themes, wallpapers, your Galau account, your password, storage |

## Your files
Everything lives in a private file system on this computer: Desktop, Documents, Pictures, Music, Downloads and Projects. Files you delete go to the **Trash** first. Each file can be up to 1.5 MB, and all of Quill together holds about 4 MB.

Use **Upload** in Atlas to bring files in from your computer, and **Export** to save them back out.

## The shell, in a nutshell
```
ls -l            list files
cd Documents     change folder
echo hi > a.txt  write a file
cat a.txt | grep -i hi
run hello.js     run JavaScript (needs Node.js)
run hello.py     run Python
open calc        open an app
theme aurora     change the look
neofetch         system summary
help             every command
```

## Tips
- Press **Ctrl+S** in any editor to save.
- In Glyph, **Ctrl+Enter** runs the file, **Ctrl+/** comments lines and **Ctrl+F** finds text.
- Your **password** (set when Quill first starts, changed in Loom → Security) unlocks the screen. Press **Alt+L** to lock.
"""


class App(AppSpec):
    id = 'guide'
    name = 'Guide'
    icon = '?'
    bg = ('#c9a56b', '#7a5a2a')
    w, h = 680, 560
    single = True
    kw = 'help guide manual docs documentation tutorial shortcuts how'
    about = 'Learn Quill.OS'

    def build(self, ctx):
        frame, text = make_view(ctx.os, ctx.body)
        frame.pack(fill='both', expand=True)
        render(ctx.os, text, GUIDE_MD)
        ctx.set_title('Guide')
        return Inst(mem=lambda: 70000)
