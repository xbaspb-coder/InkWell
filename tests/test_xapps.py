"""Tests for the Galau client and XApps (against a local stand-in server)."""

import os
import shutil
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fake_galau import FakeGalau  # noqa: E402
from quill_os import web  # noqa: E402
from quill_os.galau import Galau, GalauError  # noqa: E402
from quill_os.xapps import Store, XAppsError, check_app, search  # noqa: E402


class GalauTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeGalau()

    @classmethod
    def tearDownClass(cls):
        cls.fake.close()

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.g = Galau(self.dir, url=self.fake.url)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_sign_in_with_username_and_keep_it(self):
        self.assertEqual(self.g.sign_in('Tester', 'secret'), 'tester@gla.ml')
        self.assertTrue(self.g.signed_in)
        path = os.path.join(self.dir, 'galau-session.json')
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        again = Galau(self.dir, url=self.fake.url)
        self.assertEqual(again.address, 'tester@gla.ml')

    def test_wrong_password_and_unknown_user(self):
        with self.assertRaisesRegex(GalauError, 'address or password is wrong'):
            self.g.sign_in('tester@gla.ml', 'nope')
        with self.assertRaisesRegex(GalauError, 'no Galau Mail account called ghost@gla.ml'):
            self.g.sign_in('ghost', 'x')
        self.assertFalse(self.g.signed_in)

    def test_expired_token_is_renewed(self):
        self.g.sign_in('tester', 'secret')
        old = self.g.session['access_token']
        self.g.session['expires_at'] = 0
        self.g.rpc('is_verified')
        self.assertNotEqual(self.g.session['access_token'], old)

    def test_sign_out(self):
        self.g.sign_in('tester', 'secret')
        self.g.sign_out()
        self.assertFalse(self.g.signed_in)
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'galau-session.json')))


class XAppsTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGalau()
        self.dir = tempfile.mkdtemp()
        self.g = Galau(self.dir, url=self.fake.url)
        self.state = {}
        self.store = Store(self.g, self.dir, self.state)
        self.a = self.fake.add_app('tester@gla.ml', 'Clock', '<h1>clock</h1>', installs=5, description='A clock')
        self.b = self.fake.add_app('newbie@gla.ml', 'Notes', '<h1>notes</h1>', installs=9)
        self.hidden = self.fake.add_app('tester@gla.ml', 'Secret', '<h1>s</h1>', published=False)

    def tearDown(self):
        self.fake.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_check_app(self):
        row = check_app('  Clock ', 'd', '', 'bad', '<p>x</p>')
        self.assertEqual((row['name'], row['icon'], row['color']), ('Clock', '✨', '#4d7cff'))
        for args, msg in [(('', '', '', '', '<p>'), 'name'), (('x' * 41, '', '', '', '<p>'), 'at most 40'),
                          (('a', 'd' * 601, '', '', '<p>'), 'description'), (('a', '', '', '', ''), 'empty'),
                          (('a', '', '', '', 'x' * 1000001), 'too large'), (('a', '', '123456789', '', '<p>'), 'icon')]:
            with self.assertRaisesRegex(XAppsError, msg):
                check_app(*args)

    def test_search(self):
        rows = [{'name': 'Clock', 'description': 'tells time', 'owner_name': 'tester'}, {'name': 'Notes'}]
        self.assertEqual([r['name'] for r in search(rows, 'TIME tester')], ['Clock'])
        self.assertEqual(len(search(rows, '')), 2)

    def test_browse_without_signing_in_shows_published_only(self):
        rows = self.store.browse()
        self.assertEqual([r['name'] for r in rows], ['Notes', 'Clock'])
        self.assertNotIn('html', rows[0])

    def test_install_open_file_update_and_uninstall(self):
        row = self.store.download(self.a['id'])
        meta = self.store.install(row)
        self.assertTrue(self.store.installed(self.a['id']))
        with open(self.store.path(self.a['id']), encoding='utf-8') as f:
            self.assertEqual(f.read(), '<h1>clock</h1>')
        self.assertEqual(meta['version'], 1)
        self.assertEqual(self.state[self.a['id']]['name'], 'Clock')
        self.store.count_install(self.a['id'])           # signed out: not counted, no error
        self.assertEqual(self.fake.rows[self.a['id']]['installs'], 5)
        self.g.sign_in('tester', 'secret')
        self.store.count_install(self.a['id'])
        self.assertEqual(self.fake.rows[self.a['id']]['installs'], 6)
        self.store.change(self.a['id'], name='Clock', description='', icon='⏰', color='#2fb67c', html='<h1>v2</h1>')
        self.assertEqual(self.store.latest([self.a['id']]), {self.a['id']: 2})
        self.store.install(self.store.download(self.a['id']))
        self.assertEqual(self.state[self.a['id']]['version'], 2)
        self.store.uninstall(self.a['id'])
        self.assertFalse(self.store.installed(self.a['id']))
        self.assertFalse(os.path.exists(self.store.path(self.a['id'])))

    def test_download_rejects_bad_ids(self):
        with self.assertRaises(XAppsError):
            self.store.download('../../etc/passwd')
        with self.assertRaises(XAppsError):
            self.store.install({'id': '../evil', 'html': 'x'})

    def test_publishing_rules(self):
        with self.assertRaisesRegex(XAppsError, 'Sign in'):
            self.store.publish('Mine', '', '', '', '<p>x</p>')
        self.g.sign_in('newbie', 'secret')
        with self.assertRaisesRegex(XAppsError, 'not verified'):
            self.store.publish('Mine', '', '', '', '<p>x</p>')
        with self.assertRaisesRegex(XAppsError, 'Only the person'):
            self.store.change(self.a['id'], published=False)
        with self.assertRaisesRegex(XAppsError, 'Only the person'):
            self.store.remove(self.a['id'])
        self.g.sign_out()
        self.g.sign_in('tester', 'secret')
        row = self.store.publish('Mine', 'mine', '🎈', '#e5534b', '<p>mine</p>')
        self.assertEqual(row['owner_name'], 'tester')
        mine = [r['name'] for r in self.store.mine()]
        self.assertEqual(sorted(mine), ['Clock', 'Mine', 'Secret'])
        self.store.change(row['id'], published=False)
        self.assertNotIn('Mine', [r['name'] for r in Store(Galau(tempfile.mkdtemp(), url=self.fake.url), self.dir,
                                                              {}).browse()])
        self.store.remove(row['id'])
        self.assertNotIn(row['id'], self.fake.rows)


class WebAddressTest(unittest.TestCase):
    def test_og_address(self):
        self.assertEqual(web.og_address({'type': 'og', 'host': 'reminder.og', 'path': '/'}), 'reminder.og')
        self.assertEqual(web.og_address({'type': 'og', 'host': 'galau3.og', 'path': '/feed'}), 'galau3.og/feed')
        self.assertEqual(web.og_address({'type': 'search', 'q': 'life craft'}), 'browser://search?q=life%20craft')
        self.assertEqual(web.og_address({'type': 'directory'}), 'browser://sites')
        self.assertIsNone(web.og_address({'type': 'url', 'url': 'https://example.com'}))


if __name__ == '__main__':
    unittest.main()
