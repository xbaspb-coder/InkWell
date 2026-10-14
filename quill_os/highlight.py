"""Small regex-based syntax highlighting (a port of the original, plus Python).

`spans(text, lang)` returns (start, end, class) triples, where class is one of
k (keyword), s (string), n (number), c (comment), f (function), t (tag), a (attribute).
"""

import keyword
import re

from .util import ext_of

KW_JS = ('const|let|var|function|return|if|else|for|while|do|switch|case|break|continue|new|class|extends|import|'
         'export|from|default|async|await|try|catch|finally|throw|typeof|instanceof|in|of|this|null|undefined|true|'
         'false|void|delete|yield|static|super')

RE_JS = re.compile(
    r'(//[^\n]*|/\*[\s\S]*?(?:\*/|\Z))'
    r'|("(?:[^"\\\n]|\\.)*"?|\'(?:[^\'\\\n]|\\.)*\'?|`(?:[^`\\]|\\[\s\S])*`?)'
    r'|(\b(?:' + KW_JS + r')\b)'
    r'|(\b0x[0-9a-fA-F]+\b|\b\d[\d_]*\.?\d*(?:e[+-]?\d+)?\b)'
    r'|(\b[A-Za-z_$][\w$]*(?=\())', re.ASCII)

RE_CSS = re.compile(
    r'(/\*[\s\S]*?(?:\*/|\Z))|("(?:[^"\\\n]|\\.)*"?|\'(?:[^\'\\\n]|\\.)*\'?)|(@[\w-]+)'
    r'|(#[0-9a-fA-F]{3,8}\b|\b\d+\.?\d*(?:px|em|rem|%|vh|vw|s|ms|deg|fr)?\b)|([a-zA-Z-]+(?=\s*:(?!:)))', re.ASCII)

RE_HTML = re.compile(r'(<!--[\s\S]*?(?:-->|\Z))|(</?[A-Za-z][^>]*>?)')

RE_QSH = re.compile(
    r'(#[^\n]*)|("(?:[^"\\\n]|\\.)*"?|\'[^\'\n]*\'?)'
    r'|(\b(?:if|then|fi|echo|cd|ls|cat|mkdir|touch|rm|cp|mv|open|run|sleep|notify)\b)|(\$[A-Za-z_?]+)', re.ASCII)

KW_PY = '|'.join(sorted(set(keyword.kwlist) | {'self'}, key=len, reverse=True))
RE_PY = re.compile(
    r'(#[^\n]*)'
    r'|((?:\b[rRbBuUfF]{1,2})?(?:"""[\s\S]*?(?:"""|\Z)|\'\'\'[\s\S]*?(?:\'\'\'|\Z)|"(?:[^"\\\n]|\\.)*"?|\'(?:[^\'\\\n]|\\.)*\'?))'
    r'|(\b(?:' + KW_PY + r')\b)'
    r'|(\b0x[0-9a-fA-F]+\b|\b\d[\d_]*\.?\d*(?:e[+-]?\d+)?j?\b)'
    r'|(\b[A-Za-z_]\w*(?=\())'
    r'|(@[A-Za-z_][\w.]*)', re.ASCII)

LANG_NAMES = {'js': 'JavaScript', 'html': 'HTML', 'css': 'CSS', 'qsh': 'Quill script', 'py': 'Python', 'text': 'Plain text'}

_TAG = re.compile(r'^(</?)([A-Za-z][\w:-]*)([\s\S]*?)(/?>?)$')
_ATTR = re.compile(r'("[^"]*"?|\'[^\']*\'?)|([\w:-]+)')


def lang_of(name):
    e = ext_of(name)
    if e in ('js', 'mjs', 'json'):
        return 'js'
    if e in ('html', 'htm', 'xml', 'svg'):
        return 'html'
    if e == 'css':
        return 'css'
    if e == 'qsh':
        return 'qsh'
    if e == 'py':
        return 'py'
    return 'text'


def _run(rx, text, classes):
    out = []
    for m in rx.finditer(text):
        if m.group(0) == '':
            continue
        for i, cls in enumerate(classes, start=1):
            if m.group(i) is not None:
                if cls == 'tag':
                    out.extend(_tag_spans(m.group(0), m.start()))
                else:
                    out.append((m.start(), m.end(), cls))
                break
    return out


def _tag_spans(t, base):
    if t.startswith('<!--'):
        return [(base, base + len(t), 'c')]
    m = _TAG.match(t)
    if not m:
        return []
    out = [(base + m.start(2), base + m.end(2), 't')]
    attrs_start = base + m.start(3)
    for a in _ATTR.finditer(m.group(3)):
        if a.group(1) is not None:
            out.append((attrs_start + a.start(), attrs_start + a.end(), 's'))
        elif a.group(2) is not None:
            out.append((attrs_start + a.start(), attrs_start + a.end(), 'a'))
    return out


def spans(text, lang):
    if len(text) > 200000:
        return []
    if lang == 'js':
        return _run(RE_JS, text, ['c', 's', 'k', 'n', 'f'])
    if lang == 'css':
        return _run(RE_CSS, text, ['c', 's', 'k', 'n', 'a'])
    if lang == 'html':
        return _run(RE_HTML, text, ['c', 'tag'])
    if lang == 'qsh':
        return _run(RE_QSH, text, ['c', 's', 'k', 'f'])
    if lang == 'py':
        return _run(RE_PY, text, ['c', 's', 'k', 'n', 'f', 'a'])
    return []
