"""A small client for Galau's online services (Supabase), used by XApps.

It signs in exactly as OG Browser does: a Galau Mail address or a username, and a
password. The sign-in is kept in its own file in Quill's data folder (readable only by
you), not in Quill's saved state, so a backup never contains it.

All calls block, so the apps run them on a background thread (see run_async).
"""

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# The same public address and key OG Browser uses (a "publishable" key: what each person may
# do is decided by the database's own rules, not by keeping this key secret).
URL = 'https://qdrxeepxlphnqzbghcwn.supabase.co'
KEY = ('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFkcnhlZXB4bHBobnF6YmdoY3duIiwicm9sZSI6'
       'ImFub24iLCJpYXQiOjE3OTE1NjQwNjksImV4cCI6MjEwNzE0MDA2OX0.v5WwwyMnnQ4JQBfJOQ5sKvOtLd3Doqar37k2M4s7vxU')
MAIL_DOMAIN = 'gla.ml'
TIMEOUT = 20


class GalauError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


def friendly(e):
    """A sentence for people, from any error."""
    if isinstance(e, GalauError):
        return str(e)
    if isinstance(e, (urllib.error.URLError, OSError)):
        return 'Could not connect. Check your internet connection.'
    return str(e) or 'Something went wrong.'


class Galau:
    def __init__(self, folder, url=URL, key=KEY):
        self.url = url.rstrip('/')
        self.key = key
        self.path = os.path.join(folder, 'galau-session.json')
        self.session = self._load()
        self._lock = threading.Lock()

    # ---------------------------------------------------------- the saved sign-in
    def _load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                s = json.load(f)
            return s if s.get('access_token') and s.get('refresh_token') else None
        except (OSError, ValueError):
            return None

    def _save(self):
        if self.session is None:
            try:
                os.remove(self.path)
            except OSError:
                pass
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + '.tmp'
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(self.session, f)
        os.replace(tmp, self.path)

    @property
    def signed_in(self):
        return self.session is not None

    @property
    def user_id(self):
        return (self.session or {}).get('user', {}).get('id')

    @property
    def address(self):
        return (self.session or {}).get('user', {}).get('email') or ''

    # ---------------------------------------------------------- HTTP
    def _request(self, method, path, body=None, params=None, token=None, prefer=None):
        url = self.url + path
        if params:
            url += '?' + urllib.parse.urlencode(params)
        headers = {'apikey': self.key, 'Authorization': 'Bearer ' + (token or self.key),
                   'Accept': 'application/json'}
        data = None
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        if prefer:
            headers['Prefer'] = prefer
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                info = json.loads(raw.decode('utf-8'))
            except ValueError:
                info = {}
            msg = (info.get('msg') or info.get('message') or info.get('error_description') or info.get('error')
                   or 'The server answered with error %d.' % e.code)
            raise GalauError(str(msg), e.code)
        if not raw:
            return None
        try:
            return json.loads(raw.decode('utf-8'))
        except ValueError:
            raise GalauError('The server sent an answer that could not be read.')

    def _token(self):
        """A valid access token for the signed-in account (renewed when it is about to end), or None."""
        with self._lock:
            s = self.session
            if s is None:
                return None
            if s.get('expires_at', 0) - time.time() > 60:
                return s['access_token']
            try:
                fresh = self._request('POST', '/auth/v1/token', {'refresh_token': s['refresh_token']},
                                      params={'grant_type': 'refresh_token'})
            except GalauError as e:
                if e.status in (400, 401, 403):
                    self.session = None     # the sign-in has ended (signed out elsewhere or expired)
                    self._save()
                    raise GalauError('Your sign-in has ended. Please sign in again.', 401)
                raise
            self._keep(fresh)
            return self.session['access_token']

    def _keep(self, s):
        if not s or not s.get('access_token'):
            raise GalauError('The server did not return a sign-in.')
        s = dict(s)
        s['expires_at'] = s.get('expires_at') or int(time.time()) + int(s.get('expires_in') or 3600)
        user = s.get('user') or {}
        s['user'] = {'id': user.get('id'), 'email': user.get('email')}
        self.session = s
        self._save()

    # ---------------------------------------------------------- signing in and out
    def sign_in(self, login, password):
        login = (login or '').strip().lower()
        if not login:
            raise GalauError('Please enter your Galau Mail address or username.')
        if not password:
            raise GalauError('Please enter your password.')
        email = login
        if '@' not in login:
            email = self._request('POST', '/rest/v1/rpc/login_email', {'uname': login})
            if not email:
                raise GalauError('There is no Galau Mail account called %s@%s.' % (login, MAIL_DOMAIN))
        try:
            s = self._request('POST', '/auth/v1/token', {'email': email, 'password': password},
                              params={'grant_type': 'password'})
        except GalauError as e:
            if e.status == 400:
                raise GalauError('The address or password is wrong.', 400)
            raise
        with self._lock:
            self._keep(s)
        return self.address

    def sign_out(self):
        token = (self.session or {}).get('access_token')
        with self._lock:
            self.session = None
            self._save()
        if token:
            try:   # ends this sign-in on the server too; other devices stay signed in
                self._request('POST', '/auth/v1/logout', {}, params={'scope': 'local'}, token=token)
            except Exception:
                pass

    # ---------------------------------------------------------- the database
    def select(self, table, params, auth=True):
        return self._request('GET', '/rest/v1/' + table, params=params, token=self._token() if auth else None) or []

    def insert(self, table, row):
        rows = self._request('POST', '/rest/v1/' + table, row, token=self._need(), prefer='return=representation')
        return rows[0] if rows else None

    def update(self, table, match, values):
        rows = self._request('PATCH', '/rest/v1/' + table, values, params=match, token=self._need(),
                             prefer='return=representation')
        return rows or []

    def delete(self, table, match):
        rows = self._request('DELETE', '/rest/v1/' + table, params=match, token=self._need(),
                             prefer='return=representation')
        return rows or []

    def rpc(self, name, args=None, auth=True):
        return self._request('POST', '/rest/v1/rpc/' + name, args or {}, token=self._token() if auth else None)

    def _need(self):
        token = self._token()
        if token is None:
            raise GalauError('Please sign in with your Galau account first.', 401)
        return token


def run_async(widget, work, done, poll_ms=60):
    """Run work() on a background thread, then done(result, error) on the Tk thread."""
    box = {}

    def go():
        try:
            box['r'] = work()
        except Exception as e:   # handed to done()
            box['e'] = e
    t = threading.Thread(target=go, daemon=True)
    t.start()

    def check():
        if t.is_alive():
            try:
                widget.after(poll_ms, check)
            except Exception:
                pass
            return
        try:
            if not widget.winfo_exists():
                return
        except Exception:
            return
        done(box.get('r'), box.get('e'))
    widget.after(poll_ms, check)
