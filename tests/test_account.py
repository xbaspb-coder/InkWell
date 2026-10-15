"""Tests for creating Galau accounts and for Quill's own password."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fake_galau  # noqa: E402
from quill_os.galau import Galau, GalauError  # noqa: E402
from quill_os.util import check_password, hash_password, hash_pin  # noqa: E402


class SignUpTest(unittest.TestCase):
    def setUp(self):
        self.users = dict(fake_galau.USERS)
        self.fake = fake_galau.FakeGalau()
        self.dir = tempfile.mkdtemp()
        self.g = Galau(self.dir, url=self.fake.url)

    def tearDown(self):
        self.fake.close()
        fake_galau.USERS.clear()
        fake_galau.USERS.update(self.users)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_sign_up_creates_profile_and_signs_in(self):
        self.assertEqual(self.g.sign_up('New.Person', 'secret1', 'secret1'), 'new.person@gla.ml')
        self.assertTrue(self.g.signed_in)
        self.assertEqual(fake_galau.USERS['new.person@gla.ml']['username'], 'new.person')
        paths = [p for _m, p, _q in self.fake.log]
        self.assertIn('/rest/v1/rpc/send_verification', paths)

    def test_sign_up_when_the_server_wants_a_separate_sign_in(self):
        self.fake.confirm_signups = True
        self.assertEqual(self.g.sign_up('other', 'secret1', 'secret1'), 'other@gla.ml')
        self.assertTrue(self.g.signed_in)

    def test_sign_up_checks(self):
        cases = [(('ab', 'secret1', 'secret1'), '3 to 30'), (('Bad Name', 'secret1', 'secret1'), '3 to 30'),
                 (('okname', '12345', '12345'), 'at least 6'), (('okname', 'secret1', 'secret2'), 'different'),
                 (('tester', 'secret1', 'secret1'), 'already taken'),
                 (('tester@gla.ml', 'secret1', 'secret1'), 'already taken')]
        for args, msg in cases:
            with self.assertRaisesRegex(GalauError, msg):
                self.g.sign_up(*args)
        self.assertFalse(self.g.signed_in)

    def test_failed_profile_does_not_stay_signed_in(self):
        # The address is free in auth, but the profile name was taken in the meantime.
        fake_galau.USERS['ghost@gla.ml'] = {'id': 'x', 'password': 'p', 'username': 'racer', 'verified': False}
        real_get = self.g._request

        def request(method, path, *a, **k):
            if method == 'GET' and path == '/rest/v1/profiles':
                return []      # as if nobody had the name when we checked
            return real_get(method, path, *a, **k)
        self.g._request = request
        with self.assertRaisesRegex(GalauError, 'already taken'):
            self.g.sign_up('racer', 'secret1', 'secret1')
        self.assertFalse(self.g.signed_in)
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'galau-session.json')))


class PasswordTest(unittest.TestCase):
    def test_hash_and_check(self):
        h = hash_password('ink & glass')
        self.assertTrue(h.startswith('pbkdf2$'))
        self.assertNotIn('ink', h)
        self.assertTrue(check_password('ink & glass', h))
        self.assertFalse(check_password('ink & glas', h))
        self.assertNotEqual(h, hash_password('ink & glass'))      # salted

    def test_old_pins_still_work(self):
        self.assertTrue(check_password('2468', hash_pin('2468')))
        self.assertFalse(check_password('2469', hash_pin('2468')))

    def test_nothing_stored_never_matches(self):
        self.assertFalse(check_password('', ''))
        self.assertFalse(check_password('x', None))
        self.assertFalse(check_password('x', 'pbkdf2$broken'))


if __name__ == '__main__':
    unittest.main()
