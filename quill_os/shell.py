"""qsh — the Quill shell.

A port of the original shell: quoting, $VARS, * and ? wildcards, pipes (|),
redirects (> and >>), ; && || sequences, and every built-in command.

Commands talk to the rest of Quill through a *host* object (the running OS,
or a stand-in during tests).  The host provides:

    core                         the Core (state, file system, bus)
    apps                         {id: app} for the app list
    open_app(id, arg=None)       open_file(node, how=None)      open_web(target) -> str|None
    notify(title, body, icon)    set_theme(name)                apply_look()
    lock() / restart() / power_off()                             upload_into(dir_id)
    export_file(node)            windows() -> [win]             close_window(win)
    run_code(code, lang, callback) -> runner (stop(), running)
    wait(predicate)              keeps the program responsive until predicate() is true
    uptime_ms()                  platform_name()                signed_in_user() -> str|None
"""

import base64
import binascii
import datetime as _dt
import functools
import math
import random
import re
import time
import unicodedata
import uuid as _uuid

from . import calc
from .core import kind_of
from .util import (DAYS, MONTHS, clamp, fmt_bytes, fmt_date, hash_str, js_weekday, now_ms, pad2,
                   parse_duration, uid)

ROM = ['I', 'II', 'III', 'IV']
THEME_NAMES = {'ink': 'Ink', 'parchment': 'Parchment', 'aurora': 'Aurora', 'ember': 'Ember'}
WALL_IDS = ['drift', 'aurora', 'dunes', 'stars', 'parch', 'ember']
FORTUNES = ['A quill is a promise that the next page will be better.', 'Ink dries; ideas keep.',
            'Measure twice, commit once.', 'Every great program began as a cursor blinking in an empty file.',
            'Simple is not easy. Simple is earned.', 'The best backup is the one you tested.',
            'Fix the cause, not the symptom.', 'Today is a good day to delete some code.']


class ShellError(Exception):
    pass


def sty(cls, t):
    """Mark text with a colour class; the terminal turns these marks into colours."""
    return '\u0001' + cls + '\u0002' + str(t) + '\u0003'


def unsty(s):
    return re.sub('\u0001[A-Za-z0-9_]+\u0002([^\u0003]*)\u0003', r'\1', str(s))


def styled_parts(text):
    """Split marked text into (text, class-or-None) pieces."""
    out, last = [], 0
    for m in re.finditer('\u0001([A-Za-z0-9_]+)\u0002([^\u0003]*)\u0003', text):
        if m.start() > last:
            out.append((text[last:m.start()], None))
        out.append((m.group(2), m.group(1)))
        last = m.end()
    if last < len(text):
        out.append((text[last:], None))
    return out


# ================================================================ JavaScript-style conversions

def js_number(s):
    """Number(s) in JavaScript."""
    if s is None:
        return calc.NAN
    t = str(s).strip()
    if t == '':
        return 0.0
    try:
        if re.fullmatch(r'[+-]?0[xX][0-9a-fA-F]+', t):
            return float(int(t, 16))
        if re.fullmatch(r'0[bB][01]+', t):
            return float(int(t, 2))
        if re.fullmatch(r'0[oO][0-7]+', t):
            return float(int(t, 8))
        if t in ('Infinity', '+Infinity'):
            return calc.INF
        if t == '-Infinity':
            return -calc.INF
        if re.fullmatch(r'[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?', t):
            return float(t)
    except ValueError:
        pass
    return calc.NAN


def js_parse_int(s):
    m = re.match(r'\s*([+-]?\d+)', str(s if s is not None else ''))
    return int(m.group(1)) if m else None


def _truthy_num(v):
    return not (v == 0 or math.isnan(v))


def _locale_key(s):
    base = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
    return (base.casefold(), [c.isupper() for c in s], s)


# ================================================================ tokenizer and parser

_VAR = re.compile(r'\$\{([A-Za-z0-9_]+)\}|\$(\?|[A-Za-z0-9_]+)')


def tokenize(line, env):
    def expand(s):
        def rep(m):
            k = m.group(1) or m.group(2)
            v = env.get(k)
            if v is None:
                return ''
            if isinstance(v, bool):
                return 'true' if v else 'false'
            if isinstance(v, float):
                return calc.js_number_to_string(v)
            return str(v)
        return _VAR.sub(rep, s)

    toks = []
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c in ' \t':
            i += 1
            continue
        if c == '#':
            break
        if c == ';':
            toks.append(('op', ';'))
            i += 1
            continue
        if c == '|':
            if i + 1 < n and line[i + 1] == '|':
                toks.append(('op', '||'))
                i += 2
            else:
                toks.append(('op', '|'))
                i += 1
            continue
        if c == '&':
            if i + 1 < n and line[i + 1] == '&':
                toks.append(('op', '&&'))
                i += 2
                continue
            raise ShellError('syntax error: background jobs (&) are not supported')
        if c == '>':
            if i + 1 < n and line[i + 1] == '>':
                toks.append(('op', '>>'))
                i += 2
            else:
                toks.append(('op', '>'))
                i += 1
            continue
        word, quoted, glob = '', False, False
        while i < n and line[i] not in ' \t;|&>':
            ch = line[i]
            if ch == '\\' and i + 1 < n:
                word += line[i + 1]
                quoted = True
                i += 2
                continue
            if ch == "'":
                j = line.find("'", i + 1)
                if j < 0:
                    raise ShellError("syntax error: missing closing '")
                word += line[i + 1:j]
                quoted = True
                i = j + 1
                continue
            if ch == '"':
                j, buf = i + 1, ''
                while j < n and line[j] != '"':
                    if line[j] == '\\' and j + 1 < n:
                        buf += line[j + 1]
                        j += 2
                    else:
                        buf += line[j]
                        j += 1
                if j >= n:
                    raise ShellError('syntax error: missing closing "')
                word += expand(buf)
                quoted = True
                i = j + 1
                continue
            j, buf = i, ''
            while j < n and line[j] not in ' \t;|&>\'"\\':
                buf += line[j]
                j += 1
            if '*' in buf or '?' in buf:
                glob = True
            word += expand(buf)
            i = j
        toks.append(('w', word, quoted, glob))
    return toks


def parse(toks):
    seqs = []
    state = {'stages': [], 'words': [], 'redir': None, 'op': ';'}

    def end_stage():
        if not state['words']:
            if state['redir'] or state['stages']:
                raise ShellError('syntax error near unexpected token')
            return False
        state['stages'].append({'words': state['words'], 'redir': state['redir']})
        state['words'] = []
        state['redir'] = None
        return True

    def end_pipe(next_op):
        if not end_stage():
            if state['stages']:
                raise ShellError('syntax error near unexpected token')
        if state['stages']:
            seqs.append({'op': state['op'], 'stages': state['stages']})
        state['stages'] = []
        state['op'] = next_op

    for t in toks:
        if t[0] == 'w':
            r = state['redir']
            if r and r['pending']:
                r['target'] = t[1]
                r['pending'] = False
            else:
                state['words'].append(t)
            continue
        v = t[1]
        if v in ('>', '>>'):
            if state['redir']:
                raise ShellError('syntax error: only one redirection allowed')
            state['redir'] = {'mode': v, 'pending': True, 'target': None}
            continue
        if state['redir'] and state['redir']['pending']:
            raise ShellError('syntax error: expected a file name after ' + state['redir']['mode'])
        if v == '|':
            if not end_stage():
                raise ShellError('syntax error near |')
            continue
        end_pipe(v)
    if state['redir'] and state['redir']['pending']:
        raise ShellError('syntax error: expected a file name after ' + state['redir']['mode'])
    end_pipe(';')
    return seqs


def _glob_regex(pat, flags=0):
    out = re.sub(r'([.+^${}()|\[\]\\])', r'\\\1', pat).replace('*', '.*').replace('?', '.')
    return re.compile('^' + out + '$', flags)


def sh_glob(sh, w):
    if not w[3]:
        return [w[1]]
    fs = sh.fs
    v = w[1]
    slash = v.rfind('/')
    dir_part = v[:slash + 1] if slash >= 0 else ''
    pat = v[slash + 1:]
    d = fs.resolve(dir_part, sh.cwd) if dir_part else fs.get(sh.cwd)
    if d is None or d['t'] != 'd':
        return [v]
    try:
        rx = _glob_regex(pat)
    except re.error:
        return [v]
    hits = [dir_part + k['n'] for k in fs.kids(d['id'])
            if rx.match(k['n']) and (pat.startswith('.') or not k['n'].startswith('.'))]
    return hits or [v]


def sh_flags(args, with_val=''):
    f, rest = {}, []
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--':
            rest.extend(args[i + 1:])
            break
        if re.fullmatch(r'-\d+', a) and 'n' in with_val:
            f['n'] = a[1:]
        elif re.fullmatch(r'-[a-zA-Z]+', a):
            j = 1
            while j < len(a):
                ch = a[j]
                if ch in with_val:
                    val = a[j + 1:]
                    if not val:
                        i += 1
                        val = args[i] if i < len(args) else None
                    f[ch] = val
                    break
                f[ch] = True
                j += 1
        else:
            rest.append(a)
        i += 1
    return f, rest


def _split(t):
    lines = t.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    return lines


# ================================================================ the session

class Session:
    """One terminal's shell: working folder, variables and output."""

    def __init__(self, host, user='guest', printer=None, clearer=None, closer=None):
        self.host = host
        self.fs = host.core.fs
        self.cwd = 'd-documents'
        self.env = {'USER': user, 'HOME': '/', 'PWD': '/Documents', 'OLDPWD': '/', '?': 0}
        self.aborted = False
        self.cancel = None
        self.depth = 0
        self.strict = False
        self.inst = None
        self._print = printer or (lambda text, cls=None: None)
        self._clear = clearer or (lambda: None)
        self.close = closer or (lambda: None)

    def print(self, text, cls=None):
        self._print(str(text), cls)

    def clear(self):
        self._clear()


class Ctx:
    def __init__(self, args, stdin, sh, tty):
        self.args, self.stdin, self.sh, self.tty = args, stdin, sh, tty
        self.host = sh.host
        self.fs = sh.fs
        self.S = sh.host.core.S


CMDS = {}


def define(name, desc, usage=None):
    def deco(fn):
        CMDS[name] = {'desc': desc, 'usage': usage or name, 'fn': fn}
        return fn
    return deco


def _need(c, path, cmd):
    n = c.fs.resolve(path, c.sh.cwd)
    if n is None or not c.fs.live(n):
        raise ShellError(cmd + ': ' + path + ': No such file or directory')
    return n


def _read_text(n, cmd):
    if n['t'] == 'd':
        raise ShellError(cmd + ': ' + n['n'] + ': Is a directory')
    if n.get('b'):
        raise ShellError(cmd + ': ' + n['n'] + ': binary file')
    return n.get('c') or ''


def _input_of(c, files, cmd):
    if files:
        return ''.join(_read_text(_need(c, f, cmd), cmd) for f in files)
    return '' if c.stdin is None else c.stdin


def _parent_of(c, path, cmd):
    clean = re.sub(r'/+$', '', path)
    i = clean.rfind('/')
    dir_path = (clean[:i + 1] or '/') if i >= 0 else ''
    name = clean[i + 1:]
    p = c.fs.resolve(dir_path, c.sh.cwd) if dir_path else c.fs.get(c.sh.cwd)
    if p is None or p['t'] != 'd':
        raise ShellError(cmd + ': ' + dir_path + ': No such directory')
    if not name or name in ('.', '..'):
        raise ShellError(cmd + ': invalid name')
    return p, name


def _emit_fs(c):
    c.host.core.touch()
    c.host.core.bus.emit('fs')


# ---------------------------------------------------------------- commands

@define('help', 'Show commands', 'help [command]')
def _help(c):
    if c.args:
        k = CMDS.get(c.args[0])
        if not k:
            raise ShellError('help: no such command: ' + c.args[0])
        return sty('pr', k['usage']) + '\n  ' + k['desc']
    names = sorted(CMDS)
    w = max(len(x) for x in names) + 2
    return (sty('pr', 'Quill shell') + ' — ' + str(len(names)) +
            ' commands. Use pipes (|), redirects (> >>), ; && ||, $VARS and * wildcards.\n\n' +
            '\n'.join(sty('bl', n.ljust(w)) + CMDS[n]['desc'] for n in names) +
            '\n\nTab completes · ↑↓ history · Ctrl+C cancels · Ctrl+L clears')


CMDS['man'] = CMDS['help']


@define('clear', 'Clear the screen', 'clear')
def _clear(c):
    c.sh.clear()


@define('echo', 'Print text', 'echo [-n] text…')
def _echo(c):
    f, rest = sh_flags(c.args)
    return ' '.join(rest)


@define('pwd', 'Print the working folder', 'pwd')
def _pwd(c):
    return c.fs.path(c.sh.cwd) or '/'


@define('cd', 'Change folder', 'cd [path]')
def _cd(c):
    t = c.args[0] if c.args else None
    if t == '-':
        t = c.sh.env.get('OLDPWD') or '/'
    n = _need(c, t, 'cd') if t else c.fs.get('root')
    if n['t'] != 'd':
        raise ShellError('cd: ' + t + ': Not a directory')
    c.sh.env['OLDPWD'] = c.fs.path(c.sh.cwd) or '/'
    c.sh.cwd = n['id']
    c.sh.env['PWD'] = c.fs.path(n['id']) or '/'


@define('ls', 'List files', 'ls [-l] [-a] [path…]')
def _ls(c):
    f, rest = sh_flags(c.args)
    targets = rest or ['.']
    out = []
    for t in targets:
        n = _need(c, t, 'ls')
        lst = [k for k in c.fs.kids(n['id']) if f.get('a') or not k['n'].startswith('.')] if n['t'] == 'd' else [n]
        if len(targets) > 1:
            out.append(t + ':')
        if f.get('l'):
            for k in lst:
                size = '-' if k['t'] == 'd' else fmt_bytes(c.fs.size(k))
                name = k['n'] + ('/' if k['t'] == 'd' else '')
                out.append(('d' if k['t'] == 'd' else '-') + '  ' + size.rjust(9) + '  ' + fmt_date(k['m']) + '  ' +
                           (sty('bl' if k['t'] == 'd' else 'dm0', name) if c.tty else k['n']))
        elif c.tty:
            out.append('  '.join(sty('bl', k['n'] + '/') if k['t'] == 'd' else k['n'] for k in lst))
        else:
            out.extend(k['n'] for k in lst)
    return '\n'.join(out)


@define('tree', 'Show a folder tree', 'tree [path]')
def _tree(c):
    root = _need(c, c.args[0], 'tree') if c.args else c.fs.get(c.sh.cwd)
    counts = {'files': 0, 'dirs': 0}
    out = [sty('bl', '~' if root['id'] == 'root' else root['n'])]

    def walk(n, pre, depth):
        ks = c.fs.kids(n['id'])
        for i, k in enumerate(ks):
            last = i == len(ks) - 1
            out.append(pre + ('└── ' if last else '├── ') + (sty('bl', k['n']) if k['t'] == 'd' else k['n']))
            if k['t'] == 'd':
                counts['dirs'] += 1
                if depth < 6:
                    walk(k, pre + ('    ' if last else '│   '), depth + 1)
            else:
                counts['files'] += 1

    if root['t'] == 'd':
        walk(root, '', 0)
    out.append('\n%d folders, %d files' % (counts['dirs'], counts['files']))
    return '\n'.join(out)


@define('cat', 'Print files', 'cat [-n] [file…]')
def _cat(c):
    f, rest = sh_flags(c.args)
    t = _input_of(c, rest, 'cat')
    if f.get('n'):
        return '\n'.join(str(i + 1).rjust(4) + '  ' + l for i, l in enumerate(_split(t)))
    return re.sub(r'\n$', '', t)


def _count(f, default):
    """+f.n || default, as an integer slice bound (JavaScript truncates toward zero)."""
    v = js_number(f.get('n')) if f.get('n') is not None else calc.NAN
    if not _truthy_num(v):
        return default
    if math.isinf(v):
        return 10 ** 12 if v > 0 else -10 ** 12
    return int(v)


@define('head', 'First lines', 'head [-n N] [file]')
def _head(c):
    f, rest = sh_flags(c.args, 'n')
    return '\n'.join(_split(_input_of(c, rest, 'head'))[:_count(f, 10)])


@define('tail', 'Last lines', 'tail [-n N] [file]')
def _tail(c):
    f, rest = sh_flags(c.args, 'n')
    lines = _split(_input_of(c, rest, 'tail'))
    return '\n'.join(lines[-_count(f, 10):])


@define('wc', 'Count lines, words, characters', 'wc [-lwc] [file]')
def _wc(c):
    f, rest = sh_flags(c.args)
    t = _input_of(c, rest, 'wc')
    lines, words, chars = len(_split(t)), len(re.findall(r'\S+', t.strip())), len(t)
    if f.get('l'):
        return str(lines)
    if f.get('w'):
        return str(words)
    if f.get('c'):
        return str(chars)
    return ''.join(str(x).rjust(6) for x in (lines, words, chars))


@define('grep', 'Search for text', 'grep [-i] [-n] [-v] pattern [file…]')
def _grep(c):
    f, rest = sh_flags(c.args)
    if not rest:
        raise ShellError('usage: grep [-inv] pattern [file…]')
    flags = re.I if f.get('i') else 0
    try:
        rx = re.compile(rest[0], flags)
    except re.error:
        rx = re.compile(re.escape(rest[0]), flags)
    files, out = rest[1:], []

    def scan(text, label):
        for i, l in enumerate(_split(text)):
            if (rx.search(l) is not None) != bool(f.get('v')):
                out.append((sty('pr', label) + ':' if label else '') +
                           (sty('ok', str(i + 1)) + ':' if f.get('n') else '') + l)

    if files:
        for fl in files:
            scan(_read_text(_need(c, fl, 'grep'), 'grep'), fl if len(files) > 1 else '')
    else:
        scan('' if c.stdin is None else c.stdin, '')
    return '\n'.join(out)


@define('sort', 'Sort lines', 'sort [-r] [-n] [file]')
def _sort(c):
    f, rest = sh_flags(c.args)
    lines = _split(_input_of(c, rest, 'sort'))
    if f.get('n'):
        def cmp(a, b):
            d = calc.parse_float(a) - calc.parse_float(b)
            return 0 if math.isnan(d) else (1 if d > 0 else -1 if d < 0 else 0)
        lines.sort(key=functools.cmp_to_key(cmp))
    else:
        lines.sort(key=_locale_key)
    if f.get('r'):
        lines.reverse()
    return '\n'.join(lines)


@define('uniq', 'Remove repeated lines', 'uniq [-c] [file]')
def _uniq(c):
    f, rest = sh_flags(c.args)
    out = []
    for l in _split(_input_of(c, rest, 'uniq')):
        if out and out[-1][0] == l:
            out[-1][1] += 1
        else:
            out.append([l, 1])
    return '\n'.join((str(n).rjust(5) + ' ' if f.get('c') else '') + l for l, n in out)


@define('rev', 'Reverse each line', 'rev [file]')
def _rev(c):
    return '\n'.join(l[::-1] for l in _split(_input_of(c, c.args, 'rev')))


@define('tac', 'Print lines backwards', 'tac [file]')
def _tac(c):
    return '\n'.join(reversed(_split(_input_of(c, c.args, 'tac'))))


@define('mkdir', 'Make folders', 'mkdir [-p] name…')
def _mkdir(c):
    f, rest = sh_flags(c.args)
    if not rest:
        raise ShellError('usage: mkdir [-p] name…')
    for r in rest:
        if f.get('p'):
            cur = c.fs.get('root') if r.startswith('/') else c.fs.get(c.sh.cwd)
            for part in [x for x in r.split('/') if x]:
                k = c.fs.child(cur['id'], part)
                if k is None:
                    k = {'id': uid(), 'n': part, 't': 'd', 'p': cur['id'], 'm': now_ms(), 'r': now_ms()}
                    c.S['fs'][k['id']] = k
                elif k['t'] != 'd':
                    raise ShellError('mkdir: ' + part + ': not a directory')
                cur = k
            _emit_fs(c)
            continue
        p, name = _parent_of(c, r, 'mkdir')
        if c.fs.child(p['id'], name):
            raise ShellError('mkdir: ' + r + ': already exists')
        c.fs.mk(p['id'], name, 'd')


@define('touch', 'Create empty files', 'touch file…')
def _touch(c):
    for r in c.args:
        ex = c.fs.resolve(r, c.sh.cwd)
        if ex is not None:
            ex['m'] = now_ms()
            _emit_fs(c)
        else:
            p, name = _parent_of(c, r, 'touch')
            c.fs.mk(p['id'], name, 'f', '')


@define('rm', 'Move files to the Trash', 'rm [-r] file…')
def _rm(c):
    f, rest = sh_flags(c.args)
    if not rest:
        raise ShellError('usage: rm [-r] file…')
    for r in rest:
        n = _need(c, r, 'rm')
        if n['t'] == 'd' and not f.get('r') and not f.get('R') and not f.get('f'):
            raise ShellError('rm: ' + r + ': is a folder (use -r)')
        if not c.fs.trash(n['id']):
            raise ShellError('rm: ' + r + ': cannot remove')
    return sty('dm', 'moved %d item%s to the Trash' % (len(rest), '' if len(rest) == 1 else 's'))


@define('mv', 'Move or rename', 'mv source… destination')
def _mv(c):
    if len(c.args) < 2:
        raise ShellError('usage: mv source… destination')
    dest, srcs = c.args[-1], c.args[:-1]
    dn = c.fs.resolve(dest, c.sh.cwd)
    if dn is not None and dn['t'] == 'd':
        for s in srcs:
            n = _need(c, s, 'mv')
            if not c.fs.move(n['id'], dn['id']):
                raise ShellError('mv: cannot move ' + s)
        return None
    if len(srcs) > 1:
        raise ShellError('mv: target is not a folder')
    n = _need(c, srcs[0], 'mv')
    p, name = _parent_of(c, dest, 'mv')
    if dn is not None:
        raise ShellError('mv: ' + dest + ': already exists')
    if p['id'] != n['p']:
        if not c.fs.move(n['id'], p['id']):
            raise ShellError('mv: cannot move there')
    c.fs.rename(n['id'], name)


@define('cp', 'Copy files', 'cp [-r] source… destination')
def _cp(c):
    f, rest = sh_flags(c.args)
    if len(rest) < 2:
        raise ShellError('usage: cp [-r] source… destination')
    dest = rest[-1]
    dn = c.fs.resolve(dest, c.sh.cwd)
    for s in rest[:-1]:
        n = _need(c, s, 'cp')
        if n['t'] == 'd' and not f.get('r'):
            raise ShellError('cp: ' + s + ': is a folder (use -r)')
        if dn is not None and dn['t'] == 'd':
            c.fs.copy(n['id'], dn['id'])
        else:
            p, name = _parent_of(c, dest, 'cp')
            cpy = c.fs.copy(n['id'], p['id'])
            if cpy:
                c.fs.rename(cpy['id'], name)


@define('find', 'Find files by name', 'find [path] [-name pattern]')
def _find(c):
    a = list(c.args)
    pat = None
    if '-name' in a:
        ni = a.index('-name')
        pat = a[ni + 1] if ni + 1 < len(a) else None
        del a[ni:ni + 2]
    root = _need(c, a[0], 'find') if a else c.fs.get(c.sh.cwd)
    rx = _glob_regex(pat, re.I) if pat else None
    out = []

    def walk(n):
        for k in c.fs.kids(n['id']):
            if rx is None or rx.match(k['n']):
                out.append(c.fs.path(k['id']))
            if k['t'] == 'd':
                walk(k)

    if root['t'] == 'd':
        walk(root)
    else:
        out.append(c.fs.path(root['id']))
    return '\n'.join(out)


@define('stat', 'File details', 'stat file')
def _stat(c):
    n = _need(c, c.args[0] if c.args else '.', 'stat')
    return '\n'.join(['File: ' + (c.fs.path(n['id']) or '/'),
                      'Type: ' + ('folder' if n['t'] == 'd' else kind_of(n) + ' file'),
                      'Size: ' + fmt_bytes(c.fs.size(n)), 'Created: ' + fmt_date(n['r']), 'Modified: ' + fmt_date(n['m'])])


@define('du', 'Folder sizes', 'du [path]')
def _du(c):
    root = _need(c, c.args[0], 'du') if c.args else c.fs.get(c.sh.cwd)
    if root['t'] != 'd':
        return fmt_bytes(c.fs.size(root)) + '  ' + c.fs.path(root['id'])
    rows = [fmt_bytes(c.fs.size(k)).rjust(10) + '  ' + k['n'] + ('/' if k['t'] == 'd' else '') for k in c.fs.kids(root['id'])]
    rows.append(fmt_bytes(c.fs.size(root)).rjust(10) + '  total')
    return '\n'.join(rows)


@define('df', 'Storage use', 'df')
def _df(c):
    from .state import STORE_LIMIT
    u = c.fs.usage()
    return 'Used %s of %s (%d%%)' % (fmt_bytes(u), fmt_bytes(STORE_LIMIT), calc.js_round(u / STORE_LIMIT * 100))


@define('storage', 'Storage by folder', 'storage')
def _storage(c):
    rows = [k['n'].ljust(14) + fmt_bytes(c.fs.size(k)) for k in c.fs.kids('root')]
    return '\n'.join(rows) + '\n' + '—' * 24 + '\n' + 'total'.ljust(14) + fmt_bytes(c.fs.usage())


def _open_or_create(c, app, cmd):
    p = c.args[0] if c.args else None
    if not p:
        c.host.open_app(app, {'fresh': True} if app == 'scribe' else None)
        return
    n = c.fs.resolve(p, c.sh.cwd)
    if n is None:
        par, name = _parent_of(c, p, cmd)
        n = c.fs.mk(par['id'], name, 'f', '')
    c.host.open_app(app, {'file': n['id']})


@define('edit', 'Open a file in Scribe', 'edit file')
def _edit(c):
    _open_or_create(c, 'scribe', 'edit')


CMDS['nano'] = CMDS['edit']


@define('code', 'Open a file in Glyph', 'code file')
def _code(c):
    _open_or_create(c, 'glyph', 'code')


@define('view', 'Open an image in Lens', 'view image')
def _view(c):
    n = _need(c, c.args[0] if c.args else '', 'view')
    if kind_of(n) != 'image':
        raise ShellError('view: not an image')
    c.host.open_app('lens', {'file': n['id']})


@define('play', 'Play audio in Lyre', 'play file')
def _play(c):
    n = _need(c, c.args[0] if c.args else '', 'play')
    if kind_of(n) != 'audio':
        raise ShellError('play: not an audio file')
    c.host.open_app('lyre', {'file': n['id'], 'tab': 'player'})


@define('apps', 'List apps', 'apps')
def _apps(c):
    return '\n'.join(sty('bl', i.ljust(10)) + a.name.ljust(14) + (a.about or '') for i, a in c.host.apps.items())


_OG_HOST = re.compile(r'^[a-z0-9-]+(\.[a-z0-9-]+)*\.(og|gov|auth|roots|create|os)$', re.I)


def _web(c, target, note):
    c.host.open_web(target)
    return sty('dm', note)


@define('open', 'Open a file, app or site', 'open <file | app | site.og | https://…>')
def _open(c):
    t = ' '.join(c.args)
    if not t:
        raise ShellError('usage: open <file | app | site.og | url>')
    low = t.lower()
    app = next((i for i, a in c.host.apps.items() if i == low or a.name.lower() == low), None)
    n = c.fs.resolve(t, c.sh.cwd)
    if n is not None and c.fs.live(n):
        c.host.open_file(n)
        return None
    if app:
        c.host.open_app(app)
        return None
    if re.match(r'^https?://', t, re.I):
        return _web(c, {'type': 'url', 'url': t}, 'opening in a browser…')
    if _OG_HOST.match(t):
        m = re.match(r'^([^/]+)(/.*)?$', t)
        return _web(c, {'type': 'og', 'host': m.group(1).lower(), 'path': m.group(2) or '/'}, 'opening in a browser tab…')
    raise ShellError('open: ' + t + ': no such file, app or site')


@define('web', 'Search OG from the terminal', 'web <query>')
def _webcmd(c):
    if not c.args:
        raise ShellError('usage: web <query>')
    return _web(c, {'type': 'search', 'q': ' '.join(c.args)}, 'searching OG in a new tab…')


@define('site', 'Open an OG site', 'site <name.og>')
def _site(c):
    h0 = (c.args[0] if c.args else '').lower()
    if not h0:
        raise ShellError('usage: site <name.og>')
    return _web(c, {'type': 'og', 'host': h0, 'path': '/'}, 'opening ' + h0 + '…')


@define('run', 'Run a JavaScript or Python file', 'run file.js | file.py')
def _run(c):
    n = _need(c, c.args[0] if c.args else '', 'run')
    code = _read_text(n, 'run')
    lang = 'py' if n['n'].lower().endswith('.py') else 'js'
    t0 = time.perf_counter()
    state = {'done': False}

    def cb(kind, text=''):
        if kind in ('log', 'info'):
            c.sh.print(text)
        elif kind == 'warn':
            c.sh.print(text, 'w')
        elif kind == 'error':
            c.sh.print(text, 'er')
        elif kind == 'end':
            state['done'] = True

    runner = c.host.run_code(code, lang, cb)
    c.sh.cancel = runner.stop
    try:
        c.host.wait(lambda: state['done'] or c.sh.aborted)
        if not state['done']:
            runner.stop()
            c.host.wait(lambda: state['done'])
    finally:
        c.sh.cancel = None
    return sty('dm', '[exited after %d ms]' % round((time.perf_counter() - t0) * 1000))


@define('sh', 'Run a .qsh script', 'sh script.qsh')
def _sh(c):
    n = _need(c, c.args[0] if c.args else '', 'sh')
    text = _read_text(n, 'sh')
    if (c.sh.depth or 0) > 4:
        raise ShellError('sh: scripts are nested too deeply')
    c.sh.depth = (c.sh.depth or 0) + 1
    ln = 0
    try:
        for line in text.split('\n'):
            ln += 1
            if not line.strip() or line.strip().startswith('#'):
                continue
            if c.sh.aborted:
                raise ShellError('interrupted')
            status = execute(c.sh, line)
            if status != 0 and c.sh.strict:
                raise ShellError('script stopped at line %d' % ln)
    finally:
        c.sh.depth -= 1


def js_date_string(d=None):
    d = (d or _dt.datetime.now()).astimezone()
    off = d.utcoffset() or _dt.timedelta(0)
    mins = int(off.total_seconds() // 60)
    sign = '+' if mins >= 0 else '-'
    mins = abs(mins)
    name = d.tzname() or ''
    return '%s %s %s %d %s:%s:%s GMT%s%s%s%s' % (
        DAYS[js_weekday(d)], MONTHS[d.month - 1][:3], pad2(d.day), d.year, pad2(d.hour), pad2(d.minute),
        pad2(d.second), sign, pad2(mins // 60), pad2(mins % 60), (' (' + name + ')') if name else '')


@define('date', 'Show the date and time', 'date')
def _date(c):
    return js_date_string()


@define('cal', 'Show a calendar', 'cal [month year]')
def _cal(c):
    now = _dt.datetime.now()
    m = now.month - 1
    y = now.year
    if c.args:
        v = js_number(c.args[0])
        if not math.isnan(v):
            m = int(clamp(v - 1, 0, 11))
    if len(c.args) > 1:
        v = js_number(c.args[1])
        if not math.isnan(v) and 1 <= v <= 9999:
            y = int(v)
    first = js_weekday(_dt.date(y, m + 1, 1))
    nxt = _dt.date(y + (m == 11), 1 if m == 11 else m + 2, 1)
    days = (nxt - _dt.date(y, m + 1, 1)).days
    title = MONTHS[m] + ' ' + str(y)
    out = title.rjust(7 + len(title) // 2) + '\nSu Mo Tu We Th Fr Sa\n' + '   ' * first
    for d in range(1, days + 1):
        today = d == now.day and m == now.month - 1 and y == now.year
        cell = str(d).rjust(2)
        out += (sty('pr', cell) if today else cell) + ('\n' if (first + d) % 7 == 0 else ' ')
    return out


@define('uptime', 'How long Quill has been on', 'uptime')
def _uptime(c):
    s = int(c.host.uptime_ms() / 1000)
    return 'up ' + ('%d h ' % (s // 3600) if s >= 3600 else '') + '%d min %d s' % (s % 3600 // 60, s % 60)


@define('whoami', 'Your name', 'whoami')
def _whoami(c):
    return c.sh.env.get('USER')


@define('hostname', 'This computer', 'hostname')
def _hostname(c):
    return 'quill.os'


@define('uname', 'System name', 'uname [-a]')
def _uname(c):
    return ('Quill.OS 1.0 quill.os ' + c.host.platform_name() + ' Python') if '-a' in c.args else 'Quill.OS'


@define('version', 'Quill version', 'version')
def _version(c):
    return 'Quill.OS 1.0'


@define('env', 'Show variables', 'env')
def _env(c):
    def show(v):
        return calc.js_number_to_string(v) if isinstance(v, float) else str(v)
    return '\n'.join(k + '=' + show(v) for k, v in c.sh.env.items() if k != '?')


@define('set', 'Set a variable', 'set NAME=value')
def _set(c):
    for a in c.args:
        m = re.fullmatch(r'([A-Za-z0-9_]+)=(.*)', a, re.S)
        if not m:
            raise ShellError('usage: set NAME=value')
        c.sh.env[m.group(1)] = m.group(2)


CMDS['export'] = CMDS['set']


@define('neofetch', 'System summary', 'neofetch')
def _neofetch(c):
    from .state import STORE_LIMIT
    art = ['      .;;;;.   ', '    .;;;;;;;   ', '   ;;;;;;;;"  ', '  ;;;;;;;"    ', ' ;;;;;;"      ',
           ' ";;;;"  /    ', '   ""  /       ', '      /        ', '     /         ']
    nf = sum(1 for n in c.fs.all() if n['t'] == 'f')
    user = c.sh.env.get('USER', 'guest')
    up = int(c.host.uptime_ms() / 60000)
    info = [sty('pr', user) + '@' + sty('pr', 'quill'), '─' * (len(user) + 6),
            sty('pr', 'OS     ') + 'Quill.OS 1.0', sty('pr', 'Host   ') + 'Python (' + c.host.platform_name() + ')',
            sty('pr', 'Uptime ') + str(up) + ' min', sty('pr', 'Shell  ') + 'qsh', sty('pr', 'Apps   ') + str(len(c.host.apps)),
            sty('pr', 'Theme  ') + THEME_NAMES.get(c.S['set']['theme'], c.S['set']['theme']),
            sty('pr', 'Files  ') + str(nf), sty('pr', 'Disk   ') + fmt_bytes(c.fs.usage()) + ' / ' + fmt_bytes(STORE_LIMIT)]
    return '\n'.join(sty('pr', a) + (info[i] if i < len(info) else '') for i, a in enumerate(art)) + '\n\n' + ' '.join(['██'] * 7)


@define('ps', 'List windows', 'ps')
def _ps(c):
    rows = ['ID   APP        CH  TITLE']
    for w in c.host.windows():
        rows.append(str(w.id).ljust(5) + w.app.ljust(11) + ROM[w.ch].ljust(4) + w.title)
    return '\n'.join(rows)


@define('kill', 'Close a window', 'kill <id | all>')
def _kill(c):
    arg = c.args[0] if c.args else None
    if arg == 'all':
        for w in [w for w in c.host.windows() if w.inst is not c.sh.inst]:
            c.host.close_window(w)
        return None
    w = next((x for x in c.host.windows() if str(x.id) == arg), None)
    if w is None:
        raise ShellError('kill: no window with id ' + (arg or '?'))
    c.host.close_window(w)


@define('theme', 'Show or change the theme', 'theme [ink|parchment|aurora|ember]')
def _theme(c):
    if not c.args:
        return 'Current: ' + c.S['set']['theme'] + '\nAvailable: ' + ', '.join(THEME_NAMES)
    if c.args[0] not in THEME_NAMES:
        raise ShellError('theme: unknown theme “' + c.args[0] + '”')
    c.host.set_theme(c.args[0])


@define('wall', 'Change the wallpaper', 'wall [drift|aurora|dunes|stars|parch|ember]')
def _wall(c):
    if not c.args:
        return ', '.join(WALL_IDS)
    if c.args[0] not in WALL_IDS:
        raise ShellError('wall: unknown wallpaper')
    c.S['set']['wall'] = c.args[0]
    c.host.core.touch()
    c.host.apply_look()


@define('notify', 'Send a notification', 'notify message…')
def _notify(c):
    if not c.args:
        raise ShellError('usage: notify message…')
    c.host.notify('Terminal', ' '.join(c.args), '❯')


@define('calc', 'Calculate', 'calc expression')
def _calc(c):
    t = ' '.join(c.args) or (c.stdin or '').strip()
    try:
        return calc.fmt_num(calc.calc_eval(t))
    except calc.CalcError as e:
        raise ShellError('calc: ' + str(e))


@define('timer', 'Start a timer', 'timer 5m [label]')
def _timer(c):
    ms = parse_duration(c.args[0] if c.args else '')
    if not ms or ms <= 0:
        raise ShellError('usage: timer 90s | 5m | 1h30m [label]')
    c.S['timers'].append({'id': uid(), 'label': ' '.join(c.args[1:]), 'dur': ms, 'end': now_ms() + ms, 'state': 'run'})
    c.host.core.touch()
    c.host.core.bus.emit('chrono')
    return 'Timer set for %d s.' % calc.js_round(ms / 1000)


@define('alarm', 'Set an alarm', 'alarm HH:MM [label]')
def _alarm(c):
    m = re.fullmatch(r'(\d{1,2}):(\d\d)', c.args[0] if c.args else '')
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ShellError('usage: alarm HH:MM [label]')
    t = pad2(int(m.group(1))) + ':' + m.group(2)
    c.S['alarms'].append({'id': uid(), 'time': t, 'label': ' '.join(c.args[1:]), 'on': True, 'days': []})
    c.host.core.touch()
    c.host.core.bus.emit('chrono')
    return 'Alarm set for ' + t + '.'


@define('lock', 'Lock the screen', 'lock')
def _lock(c):
    c.host.later(50, c.host.lock)


@define('reboot', 'Restart Quill', 'reboot')
def _reboot(c):
    c.host.later(50, c.host.restart)


@define('shutdown', 'Turn Quill off', 'shutdown')
def _shutdown(c):
    c.host.later(50, c.host.power_off)


@define('history', 'Command history', 'history [-c]')
def _history(c):
    if c.args and c.args[0] == '-c':
        c.S['hist'] = []
        c.host.core.touch()
        return None
    return '\n'.join(str(i + 1).rjust(4) + '  ' + l for i, l in enumerate(c.S['hist']))


@define('export-file', 'Save a file to your computer', 'export-file file')
def _export_file(c):
    n = _need(c, c.args[0] if c.args else '', 'export-file')
    if n['t'] == 'd':
        raise ShellError('export-file: folders cannot be exported')
    c.host.export_file(n)


@define('upload', 'Add files from your computer', 'upload')
def _upload(c):
    c.host.upload_into(c.sh.cwd)


@define('sync', 'Sync with your Galau account', 'sync')
def _sync(c):
    if not c.host.signed_in_user():
        raise ShellError('sync: sign in with Galau services first')
    return 'Synced.'


@define('fortune', 'A thought for the day', 'fortune')
def _fortune(c):
    return random.choice(FORTUNES)


@define('cowsay', 'A talking quill', 'cowsay text')
def _cowsay(c):
    t = ' '.join(c.args) or 'Moo? No — quill.'
    return ' ' + '_' * (len(t) + 2) + '\n< ' + t + ' >\n ' + '-' * (len(t) + 2) + '\n    \\   ✒\n     \\ /|\n       ‾'


@define('sleep', 'Wait for a while', 'sleep seconds')
def _sleep(c):
    v = calc.parse_float(c.args[0]) if c.args else calc.NAN
    s = clamp(v if _truthy_num(v) else 1, 0, 30)
    end = time.monotonic() + s
    c.host.wait(lambda: c.sh.aborted or time.monotonic() >= end)
    if c.sh.aborted:
        raise ShellError('interrupted')


@define('seq', 'Print numbers', 'seq [first] last')
def _seq(c):
    a = [js_number(x) for x in c.args]
    lo, hi = (a[0], a[1]) if len(a) > 1 else (1.0, a[0] if a else calc.NAN)
    if math.isnan(lo) or math.isinf(lo) or math.isnan(hi) or math.isinf(hi) or hi - lo > 10000:
        raise ShellError('usage: seq [first] last')
    out = []
    i = lo
    while i <= hi:
        out.append(calc.js_number_to_string(i))
        i += 1
    return '\n'.join(out)


@define('base64', 'Encode or decode base64', 'base64 [-d] text')
def _base64(c):
    f, rest = sh_flags(c.args)
    t = ' '.join(rest) if rest else re.sub(r'\n$', '', c.stdin or '')
    try:
        if f.get('d'):
            s = re.sub(r'[\t\n\f\r ]', '', t)
            if len(s) % 4 == 1:
                raise ValueError
            s += '=' * (-len(s) % 4)
            return base64.b64decode(s, validate=True).decode('utf-8')
        return base64.b64encode(t.encode('utf-8')).decode('ascii')
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise ShellError('base64: invalid input')


@define('hash', 'Short hash of text', 'hash text')
def _hash(c):
    return hash_str(' '.join(c.args) or c.stdin or '')


@define('uuid', 'Random identifier', 'uuid')
def _uuid_cmd(c):
    return str(_uuid.uuid4())


@define('rand', 'Random number', 'rand [max]')
def _rand(c):
    mx = js_parse_int(c.args[0]) if c.args else None
    mx = mx if mx else 100
    return str(math.floor(random.random() * mx) + 1)


@define('sudo', 'Ask nicely', 'sudo …')
def _sudo(c):
    return 'Nice try. Everything here is already yours.'


@define('true', 'Do nothing, successfully', 'true')
def _true(c):
    return None


@define('false', 'Do nothing, unsuccessfully', 'false')
def _false(c):
    raise ShellError('')


@define('exit', 'Close the terminal', 'exit')
def _exit(c):
    c.host.later(30, c.sh.close)


# ================================================================ running a line

def _redirect_parent(sh, target):
    clean = re.sub(r'/+$', '', target)
    i = clean.rfind('/')
    dir_path = (clean[:i + 1] or '/') if i >= 0 else ''
    par = sh.fs.resolve(dir_path, sh.cwd) if dir_path else sh.fs.get(sh.cwd)
    if par is None or par['t'] != 'd':
        raise ShellError(target + ': No such directory')
    return par, clean[i + 1:]


def execute(sh, line):
    """Run one command line; returns the exit status (0 = success)."""
    try:
        seqs = parse(tokenize(line, sh.env))
    except ShellError as e:
        sh.print(str(e), 'er')
        sh.env['?'] = 2
        return 2
    status = 0
    for sq in seqs:
        if sq['op'] == '&&' and status != 0:
            continue
        if sq['op'] == '||' and status == 0:
            continue
        status = 0
        stdin = None
        for k, stage in enumerate(sq['stages']):
            last = k == len(sq['stages']) - 1
            words = []
            for w in stage['words']:
                words.extend(sh_glob(sh, w))
            name = words[0]
            cmd = CMDS.get(name)
            try:
                if cmd is None:
                    near = [x for x in CMDS if x.startswith(name[:2])][:3]
                    raise ShellError(name + ': command not found' +
                                     (' — did you mean ' + ', '.join(near) + '?' if near else '. Try help'))
                res = cmd['fn'](Ctx(words[1:], stdin, sh, last and not stage['redir']))
                text = '' if res is None else str(res)
                if last:
                    if stage['redir']:
                        target = stage['redir']['target']
                        p, nm = _redirect_parent(sh, target)
                        ex = sh.fs.child(p['id'], nm)
                        body = unsty(text) + ('\n' if text else '')
                        if ex is not None and ex['t'] == 'd':
                            raise ShellError(target + ': Is a directory')
                        if ex is not None and ex.get('b'):
                            raise ShellError(target + ': binary file')
                        if ex is not None:
                            sh.fs.write(ex['id'], (ex.get('c') or '') + body if stage['redir']['mode'] == '>>' else body)
                        else:
                            sh.fs.mk(p['id'], nm, 'f', body)
                    elif text:
                        sh.print(text)
                else:
                    stdin = unsty(text) + ('\n' if text else '')
            except ShellError as e:
                if str(e) != '':
                    sh.print(str(e), 'er')
                status = 1
                break
            except Exception as e:  # a bug in a command must not take the terminal down
                sh.print('%s: %s' % (name, e), 'er')
                status = 1
                break
        sh.env['?'] = status
    return status


def complete(sh, value, pos):
    """Tab completion. Returns (new_value, new_cursor) or (None, candidates)."""
    before = value[:pos]
    parts = re.split(r'\s+', before)
    cur = parts[-1]
    first = len(parts) == 1
    if first:
        cands = [k for k in CMDS if k.startswith(cur)]
    else:
        slash = cur.rfind('/')
        dir_part = cur[:slash + 1] if slash >= 0 else ''
        base = cur[slash + 1:]
        d = sh.fs.resolve(dir_part, sh.cwd) if dir_part else sh.fs.get(sh.cwd)
        cands = ([dir_part + k['n'] + ('/' if k['t'] == 'd' else '') for k in sh.fs.kids(d['id']) if k['n'].startswith(base)]
                 if d is not None and d['t'] == 'd' else [])
    if not cands:
        return None, []
    common = cands[0]
    for c in cands:
        while not c.startswith(common):
            common = common[:-1]
    done = common + ' ' if (first and len(cands) == 1) else common
    if len(done) > len(cur) or len(cands) == 1:
        nv = value[:pos - len(cur)] + done + value[pos:]
        return nv, pos - len(cur) + len(done)
    return None, cands
