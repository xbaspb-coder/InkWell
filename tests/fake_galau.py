"""A small stand-in for Galau's Supabase server, for testing XApps without the internet.

It follows the same rules as the real xapps table: anyone sees published apps, owners also
see their own, only verified accounts publish, only owners change or delete, and the
server (not the client) decides the author, version and install count.
"""

import http.server
import json
import threading
import urllib.parse
import uuid

USERS = {
    'tester@gla.ml': {'id': '11111111-1111-4111-8111-111111111111', 'password': 'secret', 'username': 'tester',
                      'verified': True},
    'newbie@gla.ml': {'id': '22222222-2222-4222-8222-222222222222', 'password': 'secret', 'username': 'newbie',
                      'verified': False},
}


class FakeGalau:
    def __init__(self):
        self.rows = {}
        self.tokens = {}
        self.log = []
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), self._handler())
        self.url = 'http://127.0.0.1:%d' % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def add_app(self, owner_email, name, html, published=True, **extra):
        u = USERS[owner_email]
        r = {'id': str(uuid.uuid4()), 'owner_id': u['id'], 'owner_name': u['username'], 'name': name,
             'description': extra.get('description', ''), 'icon': extra.get('icon', '✨'),
             'color': extra.get('color', '#4d7cff'), 'html': html, 'version': 1, 'installs': extra.get('installs', 0),
             'published': published, 'created_at': '2026-10-14T00:00:00Z', 'updated_at': '2026-10-14T00:00:00Z'}
        self.rows[r['id']] = r
        return r

    def _handler(self):
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=None):
                raw = b'' if body is None else json.dumps(body).encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _user(self):
                tok = (self.headers.get('Authorization') or '')[7:]
                return fake.tokens.get(tok)

            def _body(self):
                n = int(self.headers.get('Content-Length') or 0)
                return json.loads(self.rfile.read(n).decode('utf-8')) if n else {}

            def _route(self, method):
                u = urllib.parse.urlparse(self.path)
                q = dict(urllib.parse.parse_qsl(u.query))
                fake.log.append((method, u.path, q))
                if self.headers.get('apikey') is None:
                    return self._send(401, {'message': 'No API key'})
                if u.path == '/auth/v1/token':
                    b = self._body()
                    if q.get('grant_type') == 'password':
                        user = USERS.get(b.get('email'))
                        if not user or user['password'] != b.get('password'):
                            return self._send(400, {'error_description': 'Invalid login credentials'})
                        tok = 'tok-' + uuid.uuid4().hex
                        fake.tokens[tok] = (b['email'], user)
                        return self._send(200, {'access_token': tok, 'refresh_token': 'r-' + tok, 'expires_in': 3600,
                                                'user': {'id': user['id'], 'email': b['email']}})
                    if q.get('grant_type') == 'refresh_token':
                        old = b.get('refresh_token', '')[2:]
                        if old not in fake.tokens:
                            return self._send(400, {'error_description': 'Invalid Refresh Token'})
                        email, user = fake.tokens[old]
                        tok = 'tok-' + uuid.uuid4().hex
                        fake.tokens[tok] = (email, user)
                        return self._send(200, {'access_token': tok, 'refresh_token': 'r-' + tok, 'expires_in': 3600,
                                                'user': {'id': user['id'], 'email': email}})
                if u.path == '/auth/v1/logout':
                    fake.tokens.pop((self.headers.get('Authorization') or '')[7:], None)
                    return self._send(204)
                if u.path == '/rest/v1/rpc/login_email':
                    name = self._body().get('uname', '')
                    return self._send(200, name + '@gla.ml' if name + '@gla.ml' in USERS else None)
                me = self._user()
                if u.path == '/rest/v1/rpc/is_verified':
                    return self._send(200, bool(me and me[1]['verified']))
                if u.path == '/rest/v1/rpc/xapps_install':
                    r = fake.rows.get(self._body().get('app'))
                    if me is None:
                        return self._send(401, {'message': 'permission denied for function xapps_install'})
                    if r and r['published']:
                        r['installs'] += 1
                    return self._send(204)
                if u.path != '/rest/v1/xapps':
                    return self._send(404, {'message': 'not found'})
                uid = me[1]['id'] if me else None
                visible = [r for r in fake.rows.values() if r['published'] or r['owner_id'] == uid]
                for k, v in q.items():
                    if k in ('select', 'order', 'limit'):
                        continue
                    if v.startswith('eq.'):
                        want = v[3:]
                        visible = [r for r in visible if str(r.get(k)).lower() == want.lower()]
                    elif v.startswith('in.('):
                        ids = v[4:-1].split(',')
                        visible = [r for r in visible if r.get(k) in ids]
                cols = q.get('select', '*').split(',')

                def view(r):
                    return dict(r) if cols == ['*'] else {c: r.get(c) for c in cols}
                if method == 'GET':
                    return self._send(200, [view(r) for r in sorted(visible, key=lambda r: -r['installs'])])
                if me is None:
                    return self._send(401, {'message': 'new row violates row-level security policy'})
                if method == 'POST':
                    if not me[1]['verified']:
                        return self._send(403, {'message': 'new row violates row-level security policy for table "xapps"'})
                    b = self._body()
                    extra = {k: b[k] for k in ('description', 'icon', 'color') if k in b}
                    r = fake.add_app(me[0], b['name'], b['html'], b.get('published', True), **extra)
                    return self._send(201, [view(r)])
                own = [r for r in visible if r['owner_id'] == uid]
                if method == 'PATCH':
                    b = self._body()
                    for r in own:
                        if 'html' in b and b['html'] != r['html']:
                            r['version'] += 1
                        for k in ('name', 'description', 'icon', 'color', 'html', 'published'):
                            if k in b:
                                r[k] = b[k]
                    return self._send(200, [view(r) for r in own])
                if method == 'DELETE':
                    for r in own:
                        del fake.rows[r['id']]
                    return self._send(200, [view(r) for r in own])
                return self._send(405, {'message': 'method not allowed'})

            def do_GET(self):
                self._route('GET')

            def do_POST(self):
                self._route('POST')

            def do_PATCH(self):
                self._route('PATCH')

            def do_DELETE(self):
                self._route('DELETE')
        return H
