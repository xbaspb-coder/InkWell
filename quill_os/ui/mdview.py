"""Showing Markdown in a Tk Text widget (used by Scribe's preview and the Guide)."""

import tkinter as tk

from .. import markdown
from ..util import data_url_to_bytes
from .widgets import bar_width


def setup_tags(T, text):
    """Create the text styles once; they follow the theme automatically."""
    def fn():
        text.tag_configure('h1', font=T.font('serif', 27, 'bold', 'italic'), spacing1=14, spacing3=6, foreground=T['fg'])
        text.tag_configure('h2', font=T.font('serif', 21, 'bold', 'italic'), spacing1=12, spacing3=4, foreground=T['fg'])
        text.tag_configure('h3', font=T.font('serif', 17, 'bold', 'italic'), spacing1=10, spacing3=3, foreground=T['acc'])
        text.tag_configure('p', spacing1=4, spacing3=6)
        text.tag_configure('b', font=T.font('sans', 14, 'bold'))
        text.tag_configure('i', font=T.font('sans', 14, slant='italic'))
        text.tag_configure('bi', font=T.font('sans', 14, 'bold', 'italic'))
        text.tag_configure('s', overstrike=1)
        text.tag_configure('code', font=T.font('mono', 13), background=T['bg3'])
        text.tag_configure('pre', font=T.font('mono', 13), background=T['bg0'], lmargin1=12, lmargin2=12, rmargin=12,
                           spacing1=2, spacing3=2)
        text.tag_configure('quote', foreground=T['fg2'], lmargin1=18, lmargin2=18, spacing1=4, spacing3=6)
        text.tag_configure('li', lmargin1=10, lmargin2=28, spacing1=2, spacing3=2)
        text.tag_configure('a', foreground=T['acc'], underline=1)
        text.tag_configure('hr', font=T.font('sans', 4), overstrike=1, foreground=T['line'], spacing1=6, spacing3=6)
        text.tag_configure('th', font=T.font('sans', 14, 'bold'))
        text.tag_configure('table', spacing1=3, spacing3=3)
        text.tag_configure('img', foreground=T['fg2'])
    T.on(text, fn)
    text.tag_bind('a', '<Enter>', lambda e: text.configure(cursor='hand2'))
    text.tag_bind('a', '<Leave>', lambda e: text.configure(cursor=''))


def render(os_, text, src):
    """Replace the Text widget's content with rendered Markdown."""
    text.configure(state='normal')
    text.delete('1.0', 'end')
    text._links = {}
    text._images = []
    blocks = markdown.parse(src)
    first = True
    for b in blocks:
        if not first:
            text.insert('end', '\n')
        first = False
        kind = b[0]
        if kind == 'h':
            _inline(os_, text, b[2], ('h%d' % b[1],))
        elif kind == 'hr':
            text.insert('end', ' ' * 200, ('hr',))
        elif kind == 'quote':
            text.insert('end', '┃ ', ('quote',))
            _inline(os_, text, b[1], ('quote',))
        elif kind in ('ul', 'ol'):
            for i, item in enumerate(b[1]):
                if i:
                    text.insert('end', '\n')
                text.insert('end', ('•  ' if kind == 'ul' else '%d.  ' % (i + 1)), ('li',))
                _inline(os_, text, item, ('li',))
        elif kind == 'pre':
            text.insert('end', b[1] + '\n', ('pre',))
        elif kind == 'table':
            _table(os_, text, b[1], b[2])
        else:
            _inline(os_, text, b[1], ('p',))
        text.insert('end', '\n')
    text.configure(state='disabled')


def _inline(os_, text, segs, base):
    for t, styles, href in segs:
        tags = list(base)
        if 'code' in styles:
            tags.append('code')
        elif 'b' in styles and 'i' in styles:
            tags.append('bi')
        elif 'b' in styles:
            tags.append('b')
        elif 'i' in styles:
            tags.append('i')
        if 's' in styles:
            tags.append('s')
        if 'img' in styles:
            img = None
            if href and href.startswith('data:image/'):
                from ..imaging import photo_from_bytes
                data, _ = data_url_to_bytes(href)
                img = photo_from_bytes(os_.root, data, (600, 600))
            if img is not None:
                text._images.append(img)
                text.image_create('end', image=img)
            else:
                text.insert('end', '🖼 ' + (t or 'image'), tuple(tags) + ('img',))
            continue
        if href:
            tag = 'link%d' % len(text._links)
            text._links[tag] = href
            text.tag_bind(tag, '<Button-1>', lambda e, h=href: os_.open_web({'type': 'url', 'url': h}))
            tags += ['a', tag]
        text.insert('end', t, tuple(tags))


def _table(os_, text, head, rows):
    T = os_.theme
    font = T.font('sans', 14)
    bold = T.font('sans', 14, 'bold')

    def plain(segs):
        return ''.join(s[0] for s in segs)
    cols = max([len(head)] + [len(r) for r in rows]) if (head or rows) else 0
    widths = [0] * cols
    for i, c in enumerate(head):
        widths[i] = max(widths[i], bold.measure(plain(c)))
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], font.measure(plain(c)))
    stops, x = [], 0
    for w in widths[:-1]:
        x += w + 24
        stops.append(x)
    tag = 'tbl%d' % id(head)
    text.tag_configure(tag, tabs=tuple(stops) or None)
    for i, c in enumerate(head):
        if i:
            text.insert('end', '\t', (tag, 'table'))
        _inline(os_, text, c, (tag, 'table', 'th'))
    for r in rows:
        text.insert('end', '\n', (tag,))
        for i, c in enumerate(r):
            if i:
                text.insert('end', '\t', (tag, 'table'))
            _inline(os_, text, c, (tag, 'table'))


def make_view(os_, parent, bg='bg1', padx=24, pady=18):
    """A read-only, scrollable Markdown view."""
    T = os_.theme
    frame = tk.Frame(parent, bd=0)
    T.style(frame, bg=bg)
    text = tk.Text(frame, wrap='word', bd=0, highlightthickness=0, padx=padx, pady=pady, font=T.font('sans', 14),
                   cursor='arrow', spacing1=1, spacing3=1, width=1, height=1)
    bar = tk.Scrollbar(frame, orient='vertical', command=text.yview, width=bar_width(), bd=0, highlightthickness=0)
    text.configure(yscrollcommand=bar.set)
    T.on(text, lambda: text.configure(bg=T[bg], fg=T['fg'], selectbackground=T['acc'], selectforeground=T['acc_fg'],
                                      inactiveselectbackground=T['acc_soft']))
    T.on(bar, lambda: bar.configure(bg=T['bg3'], troughcolor=T[bg], activebackground=T['hover']))
    bar.pack(side='right', fill='y')
    text.pack(side='left', fill='both', expand=True)
    setup_tags(T, text)
    return frame, text
