"""A small, safe Markdown parser (a port of the original md() / mdInline()).

`parse(src)` returns a list of blocks.  Inline text is returned as a list of
segments: (text, styles, href) where styles is a frozenset drawn from
{'b', 'i', 's', 'code', 'a', 'img'} and href is a link or image source.
The user interface turns these blocks into styled text.
"""

import html
import re

# JavaScript's \w and \d are ASCII-only, so they are spelled out here.
_W = '[A-Za-z0-9_]'


def _esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;').replace("'", '&#39;'))


def inline_html(t):
    """The exact HTML the original mdInline() produced."""
    stash = []

    def keep(m):
        stash.append('<code>' + _esc(m.group(1)) + '</code>')
        return '\u0001' + str(len(stash) - 1) + '\u0001'

    t = re.sub(r'`([^`]+)`', keep, str(t))
    t = _esc(t)
    t = re.sub(r'!\[([^\]]*)\]\((https?:[^)\s]+|data:image/[^)\s]+)\)', r'<img alt="\1" src="\2">', t)
    t = re.sub(r'\[([^\]]+)\]\((https?:[^)\s]+)\)', r'<a href="\2">\1</a>', t)
    t = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', t)
    t = re.sub(r'(^|[^*A-Za-z0-9_])\*([^*\n]+)\*(?!' + _W + ')', r'\1<i>\2</i>', t)
    t = re.sub(r'(^|[^A-Za-z0-9_])_([^_\n]+)_(?!' + _W + ')', r'\1<i>\2</i>', t)
    t = re.sub(r'~~([^~]+)~~', r'<s>\1</s>', t)
    return re.sub('\u0001([0-9]+)\u0001', lambda m: stash[int(m.group(1))], t)


_TAG = re.compile(r'<(/?)(b|i|s|code|a)(?: href="([^"]*)")?>|<img alt="([^"]*)" src="([^"]*)">|([^<]+)|(<)')


def inline(t):
    """Markdown inline text → list of (text, styles, href) segments."""
    out = []
    stack = []
    href = None
    for m in _TAG.finditer(inline_html(t)):
        close, tag, ahref, alt, src, text, lt = m.groups()
        if tag:
            if close:
                if tag in stack:
                    # Remove the most recent matching tag.
                    idx = len(stack) - 1 - stack[::-1].index(tag)
                    stack.pop(idx)
                if tag == 'a':
                    href = None
            else:
                stack.append(tag)
                if tag == 'a':
                    href = html.unescape(ahref or '')
        elif src is not None:
            out.append((html.unescape(alt or ''), frozenset(stack) | {'img'}, html.unescape(src)))
        elif text is not None:
            out.append((html.unescape(text), frozenset(stack), href))
        elif lt:
            out.append(('<', frozenset(stack), href))
    return out


def _is_table(lines, k):
    return (k + 1 < len(lines) and '|' in lines[k]
            and re.match(r'^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$', lines[k + 1]) is not None)


def _cells(s):
    return [x.strip() for x in re.sub(r'^\||\|$', '', s.strip()).split('|')]


def parse(src):
    """Markdown source → list of blocks.

    Block shapes:
      ('h', level, segments)      ('hr',)
      ('quote', segments)         ('ul', [segments, …])   ('ol', [segments, …])
      ('table', [head segs], [[row segs], …])
      ('pre', text)               ('p', segments)
    """
    lines = str(src).replace('\r', '').split('\n')
    out = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        if re.match(r'^\s*```', ln):
            buf = []
            i += 1
            while i < n and not re.match(r'^\s*```', lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append(('pre', '\n'.join(buf)))
            continue
        m = re.match(r'^(#{1,3})\s+(.*)$', ln)
        if m:
            out.append(('h', len(m.group(1)), inline(m.group(2))))
            i += 1
            continue
        if re.match(r'^\s*([-*_])\s*\1\s*\1[\s\-*_]*$', ln):
            out.append(('hr',))
            i += 1
            continue
        if re.match(r'^\s*>', ln):
            buf = []
            while i < n and re.match(r'^\s*>', lines[i]):
                buf.append(re.sub(r'^\s*>\s?', '', lines[i]))
                i += 1
            out.append(('quote', inline(' '.join(buf))))
            continue
        if re.match(r'^\s*[-*+]\s+', ln):
            items = []
            while i < n and re.match(r'^\s*[-*+]\s+', lines[i]):
                item = re.sub(r'^\s*[-*+]\s+', '', lines[i])
                item = re.sub(r'^\[( |x)\]\s', lambda q: '☑ ' if q.group(1) == 'x' else '☐ ', item)
                items.append(inline(item))
                i += 1
            out.append(('ul', items))
            continue
        if re.match(r'^\s*[0-9]+[.)]\s+', ln):
            items = []
            while i < n and re.match(r'^\s*[0-9]+[.)]\s+', lines[i]):
                items.append(inline(re.sub(r'^\s*[0-9]+[.)]\s+', '', lines[i])))
                i += 1
            out.append(('ol', items))
            continue
        if _is_table(lines, i):
            head = _cells(lines[i])
            i += 2
            rows = []
            while i < n and '|' in lines[i] and lines[i].strip():
                rows.append(_cells(lines[i]))
                i += 1
            out.append(('table', [inline(c) for c in head], [[inline(c) for c in r] for r in rows]))
            continue
        if not ln.strip():
            i += 1
            continue
        buf = []
        while (i < n and lines[i].strip()
               and not re.match(r'^\s*(```|#{1,3}\s|>|[-*+]\s|[0-9]+[.)]\s)', lines[i])
               and not _is_table(lines, i)):
            buf.append(lines[i])
            i += 1
        if not buf:
            buf.append(lines[i])
            i += 1
        out.append(('p', inline('\n'.join(buf))))
    return out
