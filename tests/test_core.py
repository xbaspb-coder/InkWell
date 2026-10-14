"""Tests for the non-visual parts of Quill.OS: calculator, Markdown, file system, saving, shell."""

import json
import math
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quill_os import calc, markdown, shell, state  # noqa: E402
from quill_os.core import Core, Store, kind_of, icon_of  # noqa: E402
from quill_os.util import hash_pin, hash_str, parse_duration, fmt_bytes, fmt_dur  # noqa: E402


class CalcTests(unittest.TestCase):
    def ev(self, s, deg=False):
        return calc.fmt_num(calc.calc_eval(s, deg))

    def test_basic_arithmetic_and_precedence(self):
        self.assertEqual(self.ev('12*(3+4)'), '84')
        self.assertEqual(self.ev('2+3*4'), '14')
        self.assertEqual(self.ev('2^3^2'), '512')
        self.assertEqual(self.ev('2**10'), '1024')
        self.assertEqual(self.ev('-2^2'), '-4')
        self.assertEqual(self.ev('0.1+0.2'), '0.3')
        self.assertEqual(self.ev('10 mod 3'), '1')
        self.assertEqual(self.ev('5!'), '120')
        self.assertEqual(self.ev('50%'), '0.5')
        self.assertEqual(self.ev('2pi'), self.ev('2*pi'))
        self.assertEqual(self.ev('2(3)'), '6')
        self.assertEqual(self.ev('12×3−4÷2'), '34')
        self.assertEqual(self.ev('√(16)'), '4')

    def test_functions(self):
        self.assertEqual(self.ev('sqrt(2)'), '1.41421356237')
        self.assertEqual(self.ev('sin(90)', deg=True), '1')
        self.assertEqual(self.ev('cos(0)'), '1')
        self.assertEqual(self.ev('log(1000)'), '3')
        self.assertEqual(self.ev('ln(e)'), '1')
        self.assertEqual(self.ev('max(1, 5, 3)'), '5')
        self.assertEqual(self.ev('min()'), '∞')
        self.assertEqual(self.ev('round(2.5)'), '3')
        self.assertEqual(self.ev('round(-2.5)'), '-2')
        self.assertEqual(self.ev('cbrt(-27)'), '-3')
        self.assertEqual(self.ev('pow(2, 8)'), '256')
        self.assertEqual(self.ev('fact(5)'), '120')

    def test_js_number_behaviour(self):
        self.assertEqual(self.ev('1/0'), '∞')
        self.assertEqual(self.ev('-1/0'), '-∞')
        self.assertEqual(self.ev('0/0'), 'Not a number')
        self.assertEqual(self.ev('ln(0)'), '-∞')
        self.assertEqual(self.ev('asin(2)'), 'Not a number')
        self.assertEqual(self.ev('171!'), '∞')

    def test_formatting(self):
        self.assertEqual(calc.fmt_num(1e15), '1e15')
        self.assertEqual(calc.fmt_num(1234567890123456.0), '1.23456789e15')
        self.assertEqual(calc.fmt_num(1e-10), '1e-10')
        self.assertEqual(calc.fmt_num(5e-8), '5e-8')
        self.assertEqual(calc.fmt_num(123456789012.5), '123456789013')
        self.assertEqual(calc.fmt_num(-0.0), '0')
        self.assertEqual(calc.js_number_to_string(1e21), '1e+21')
        self.assertEqual(calc.js_number_to_string(123.0), '123')
        self.assertEqual(calc.js_number_to_string(0.000001), '0.000001')
        self.assertEqual(calc.js_number_to_string(1e-7), '1e-7')

    def test_errors(self):
        for src, msg in [('', 'Empty'), ('2+', 'Unexpected end'), ('(2', 'Missing )'), ('foo', 'Unknown name “foo”'),
                         ('sqrt(-1)', 'Square root of a negative number'), ('2.5!', 'Factorial needs a whole number'),
                         ('sin 2', 'Use sin(…)'), ('2)', 'Unexpected “)”'), ('P', 'Unexpected “P”')]:
            with self.assertRaises(calc.CalcError) as cm:
                calc.calc_eval(src)
            self.assertEqual(str(cm.exception), msg, src)


class MarkdownTests(unittest.TestCase):
    def test_blocks(self):
        b = markdown.parse('# Title\n\nSome *it* and **bold** and `code`.\n\n- a\n- [x] done\n\n1. one\n2. two\n\n> quote\n\n---\n\n```\nx < 1\n```\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n')
        kinds = [x[0] for x in b]
        self.assertEqual(kinds, ['h', 'p', 'ul', 'ol', 'quote', 'hr', 'pre', 'table'])
        self.assertEqual(b[0][1], 1)
        self.assertEqual(b[6][1], 'x < 1')
        segs = b[1][1]
        styled = {t: s for t, s, h in segs}
        self.assertIn('i', styled['it'])
        self.assertIn('b', styled['bold'])
        self.assertIn('code', styled['code'])
        self.assertEqual(b[2][1][1][0][0], '☑ done')
        self.assertEqual(len(b[7][2]), 1)

    def test_links_images_and_escaping(self):
        segs = markdown.inline('see [site](https://example.com/a_b) <tag> & ![pic](https://x.y/p.png)')
        link = [s for s in segs if 'a' in s[1]][0]
        self.assertEqual(link[0], 'site')
        self.assertEqual(link[2], 'https://example.com/a_b')
        self.assertTrue(any(s[0] == ' <tag> & ' for s in segs))
        img = [s for s in segs if 'img' in s[1]][0]
        self.assertEqual(img[2], 'https://x.y/p.png')

    def test_snake_case_is_not_italic(self):
        segs = markdown.inline('snake_case_name')
        self.assertEqual(segs, [('snake_case_name', frozenset(), None)])


class FakeScheduler:
    def __init__(self):
        self.jobs = []

    def schedule(self, ms, fn):
        self.jobs.append(fn)
        return fn

    def cancel(self, h):
        if h in self.jobs:
            self.jobs.remove(h)

    def run(self):
        jobs, self.jobs = self.jobs, []
        for j in jobs:
            j()


def make_core(tmp):
    core = Core(Store(tmp))
    core.load()
    return core


class FileSystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.core = make_core(self.tmp)
        self.fs = self.core.fs

    def test_seeded_tree(self):
        names = [n['n'] for n in self.fs.kids('root')]
        self.assertEqual(names, ['Desktop', 'Documents', 'Downloads', 'Music', 'Pictures', 'Projects'])
        self.assertIsNotNone(self.fs.resolve('/Documents/Welcome.md'))
        self.assertIsNotNone(self.fs.resolve('~/Projects/hello.js'))

    def test_unique_names_and_sorting(self):
        d = self.fs.mk('d-documents', 'x', 'd')
        a = self.fs.mk(d['id'], 'file.txt', 'f', 'a')
        b = self.fs.mk(d['id'], 'file.txt', 'f', 'b')
        c = self.fs.mk(d['id'], 'file.txt', 'f', 'c')
        self.assertEqual([a['n'], b['n'], c['n']], ['file.txt', 'file (2).txt', 'file (3).txt'])
        self.fs.mk(d['id'], 'item10', 'f')
        self.fs.mk(d['id'], 'Item2', 'f')
        self.fs.mk(d['id'], 'sub', 'd')
        order = [n['n'] for n in self.fs.kids(d['id'])]
        self.assertEqual(order[0], 'sub')
        self.assertLess(order.index('Item2'), order.index('item10'))

    def test_move_copy_trash_restore_purge(self):
        a = self.fs.mk('d-documents', 'A', 'd')
        b = self.fs.mk(a['id'], 'B', 'd')
        f = self.fs.mk(b['id'], 'f.txt', 'f', 'hello')
        self.assertFalse(self.fs.move(a['id'], b['id']), 'cannot move a folder into itself')
        self.assertTrue(self.fs.move(f['id'], a['id']))
        cp = self.fs.copy(a['id'], 'd-projects')
        self.assertEqual(self.fs.path(cp['id']), '/Projects/A')
        self.assertIsNotNone(self.fs.resolve('/Projects/A/B'))
        self.assertIsNotNone(self.fs.resolve('/Projects/A/f.txt'))
        self.assertTrue(self.fs.trash(a['id']))
        self.assertFalse(self.fs.live(self.fs.get(f['id'])))
        self.assertFalse(self.fs.trash('d-documents'), 'fixed folders cannot be trashed')
        self.fs.restore(a['id'])
        self.assertTrue(self.fs.live(self.fs.get(f['id'])))
        self.fs.trash(a['id'])
        self.fs.empty_trash()
        self.assertIsNone(self.fs.get(f['id']))
        self.assertIsNone(self.fs.get(b['id']))

    def test_resolve_dots(self):
        self.assertEqual(self.fs.resolve('../Projects', 'd-documents')['id'], 'd-projects')
        self.assertEqual(self.fs.resolve('/..')['id'], 'root')

    def test_kind_and_icon(self):
        self.assertEqual(kind_of({'t': 'f', 'n': 'a.png'}), 'image')
        self.assertEqual(kind_of({'t': 'f', 'n': 'a.mp3'}), 'audio')
        self.assertEqual(kind_of({'t': 'f', 'n': 'a.zip', 'b': 1}), 'bin')
        self.assertEqual(icon_of({'t': 'f', 'n': 'a.md', 'id': 'x'}), '📝')

    def test_save_and_reload_round_trip(self):
        self.fs.mk('d-documents', 'saved.txt', 'f', 'persist me ✒')
        self.core.save(now=True)
        again = make_core(self.tmp)
        n = again.fs.resolve('/Documents/saved.txt')
        self.assertEqual(n['c'], 'persist me ✒')
        with open(os.path.join(self.tmp, 'state.json'), encoding='utf-8') as f:
            json.load(f)

    def test_unreadable_save_is_never_overwritten(self):
        with open(os.path.join(self.tmp, 'state.json'), 'w') as f:
            f.write('{broken')
        core = make_core(self.tmp)
        self.assertTrue(core.nosave)
        core.fs.mk('d-documents', 'x.txt', 'f', '')
        core.save(now=True)
        with open(os.path.join(self.tmp, 'state.json')) as f:
            self.assertEqual(f.read(), '{broken')

    def test_debounced_save(self):
        sched = FakeScheduler()
        core = Core(Store(self.tmp), (sched.schedule, sched.cancel))
        core.load()
        core.touch()
        core.touch()
        self.assertEqual(len(sched.jobs), 1)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'state.json')))
        sched.run()
        self.assertTrue(os.path.exists(os.path.join(self.tmp, 'state.json')))

    def test_import_and_export_real_files(self):
        src = os.path.join(self.tmp, 'pic.png')
        with open(src, 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n' + b'\x00' * 20)
        n = self.fs.import_file(src, 'd-pictures')
        self.assertTrue(n['b'])
        self.assertTrue(n['c'].startswith('data:image/png;base64,'))
        out = os.path.join(self.tmp, 'out.png')
        self.fs.export_file(n, out)
        with open(out, 'rb') as f:
            self.assertEqual(f.read(), b'\x89PNG\r\n\x1a\n' + b'\x00' * 20)

    def test_backup_from_html_version_normalises(self):
        raw = {'set': {'theme': 'aurora', 'dock': ['files']}, 'lyre': {'pat': [[1]]},
               'fs': {'root': {'id': 'root', 'n': '', 't': 'd', 'p': None, 'm': 0, 'r': 0}}}
        s = state.normalize_state(raw)
        self.assertEqual(s['set']['theme'], 'aurora')
        self.assertEqual(len(s['lyre']['pat']), 4)
        self.assertIn('d-documents', s['fs'])
        self.assertEqual(s['set']['accent'], state.ACCENTS[0])


class UtilTests(unittest.TestCase):
    def test_hashes_match_the_html_version(self):
        self.assertEqual(hash_str(''), '811c9dc5')
        self.assertEqual(hash_str('a'), 'e40c292c')
        import hashlib
        self.assertEqual(hash_pin('1234'), hashlib.sha256(b'quill:1234').hexdigest())

    def test_durations_and_bytes(self):
        self.assertEqual(parse_duration('90s'), 90000)
        self.assertEqual(parse_duration('1h30m'), 5400000)
        self.assertEqual(parse_duration('5'), 300000)
        self.assertIsNone(parse_duration('soon'))
        self.assertEqual(fmt_bytes(512), '512 B')
        self.assertEqual(fmt_bytes(2048), '2.0 KB')
        self.assertEqual(fmt_dur(3723000), '1:02:03')
        self.assertEqual(fmt_dur(1234, True), '00:01.23')


class FakeApp:
    def __init__(self, name, about):
        self.name, self.about = name, about


class FakeHost:
    def __init__(self, core):
        self.core = core
        self.apps = {'files': FakeApp('Atlas', 'Files and folders'), 'calc': FakeApp('Abacus', 'Calculator')}
        self.opened = []
        self.web = []
        self.notes = []

    def open_app(self, id_, arg=None):
        self.opened.append((id_, arg))

    def open_file(self, n, how=None):
        self.opened.append(('file', n['n']))

    def open_web(self, target):
        self.web.append(target)

    def notify(self, title, body, icon):
        self.notes.append((title, body))

    def set_theme(self, t):
        self.core.S['set']['theme'] = t

    def apply_look(self):
        pass

    def later(self, ms, fn):
        pass

    def windows(self):
        return []

    def close_window(self, w):
        pass

    def upload_into(self, d):
        pass

    def export_file(self, n):
        pass

    def run_code(self, code, lang, cb):
        from quill_os.runner import Runner
        r = Runner(code, lang, cb)
        self._runners = getattr(self, '_runners', []) + [r]
        return r

    def wait(self, pred):
        # Tests have no event loop: poll runners directly.
        deadline = time.monotonic() + 30
        while not pred() and time.monotonic() < deadline:
            for r in list(getattr(self, '_runners', [])):
                r.poll()
            time.sleep(0.01)

    def uptime_ms(self):
        return 65000

    def platform_name(self):
        return 'test'

    def signed_in_user(self):
        return None


class ShellTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.core = make_core(self.tmp)
        self.host = FakeHost(self.core)
        self.out = []
        self.sh = shell.Session(self.host, 'tester', printer=lambda t, c=None: self.out.append((shell.unsty(t), c)))

    def run_line(self, line):
        self.out.clear()
        status = shell.execute(self.sh, line)
        return status, '\n'.join(t for t, c in self.out)

    def test_tokenizer_quotes_vars_and_errors(self):
        toks = shell.tokenize('echo "a $USER" \'$USER\' b\\ c', {'USER': 'me'})
        self.assertEqual([t[1] for t in toks], ['echo', 'a me', '$USER', 'b c'])
        with self.assertRaises(shell.ShellError):
            shell.tokenize('echo "open', {})
        with self.assertRaises(shell.ShellError):
            shell.tokenize('sleep 1 &', {})

    def test_navigation_and_files(self):
        self.assertEqual(self.run_line('pwd')[1], '/Documents')
        self.run_line('cd ../Projects')
        self.assertEqual(self.run_line('pwd')[1], '/Projects')
        self.run_line('cd -')
        self.assertEqual(self.run_line('pwd')[1], '/Documents')
        self.run_line('mkdir -p deep/er/est')
        self.assertIsNotNone(self.core.fs.resolve('/Documents/deep/er/est'))
        self.run_line('echo hello world > note.txt')
        self.assertEqual(self.core.fs.resolve('/Documents/note.txt')['c'], 'hello world\n')
        self.run_line('echo again >> note.txt')
        self.assertEqual(self.run_line('cat note.txt')[1], 'hello world\nagain')
        self.assertEqual(self.run_line('cat note.txt | wc -l')[1], '2')
        self.assertEqual(self.run_line('cat note.txt | grep -n again')[1], '2:again')
        self.run_line('cp note.txt copy.txt')
        self.run_line('mv copy.txt moved.txt')
        self.assertIsNotNone(self.core.fs.resolve('/Documents/moved.txt'))
        status, text = self.run_line('rm deep')
        self.assertEqual(status, 1)
        self.assertIn('is a folder', text)
        self.assertEqual(self.run_line('rm -r deep')[0], 0)
        self.assertIn('Welcome.md', self.run_line('ls *.md')[1])

    def test_sequences_and_status(self):
        self.assertEqual(self.run_line('false && echo no')[1], '')
        self.assertEqual(self.run_line('false || echo yes')[1], 'yes')
        self.assertEqual(self.run_line('true; echo $?')[1], '0')
        status, text = self.run_line('nosuch')
        self.assertEqual(status, 1)
        self.assertIn('command not found', text)

    def test_text_tools(self):
        self.run_line('seq 5 > n.txt')
        self.assertEqual(self.run_line('head -n 2 n.txt')[1], '1\n2')
        self.assertEqual(self.run_line('tail -n 2 n.txt')[1], '4\n5')
        self.assertEqual(self.run_line('sort -r -n n.txt | head -n 1')[1], '5')
        self.assertEqual(self.run_line('echo b a b | rev')[1], 'b a b')
        self.assertEqual(self.run_line('base64 hello')[1], 'aGVsbG8=')
        self.assertEqual(self.run_line('base64 -d aGVsbG8')[1], 'hello')
        self.assertEqual(self.run_line('calc 2^10')[1], '1024')
        self.assertEqual(self.run_line('hash a')[1], 'e40c292c')
        self.assertIn('Quill shell', self.run_line('help')[1])
        self.assertIn('Show commands', self.run_line('help man')[1])

    def test_timer_alarm_theme_open(self):
        self.run_line('timer 90s tea')
        self.assertEqual(self.core.S['timers'][-1]['label'], 'tea')
        self.assertEqual(self.run_line('alarm 25:00')[0], 1)
        self.run_line('alarm 7:05 wake')
        self.assertEqual(self.core.S['alarms'][-1]['time'], '07:05')
        self.run_line('theme ember')
        self.assertEqual(self.core.S['set']['theme'], 'ember')
        self.run_line('open Abacus')
        self.assertIn(('calc', None), self.host.opened)
        self.run_line('open https://example.com')
        self.assertEqual(self.host.web[-1], {'type': 'url', 'url': 'https://example.com'})

    def test_run_python(self):
        self.run_line('echo "print(6*7)" > six.py')
        status, text = self.run_line('run six.py')
        self.assertEqual(status, 0)
        self.assertIn('42', text)

    def test_completion(self):
        nv, cur = shell.complete(self.sh, 'neof', 4)
        self.assertEqual(nv, 'neofetch ')
        nv, cur = shell.complete(self.sh, 'cat Wel', 7)
        self.assertEqual(nv, 'cat Welcome.md')


if __name__ == '__main__':
    unittest.main()
