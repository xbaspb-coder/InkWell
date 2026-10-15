"""Small helpers shared by every part of Quill.OS.

These mirror the helper functions at the top of the original Quill.OS page
(uid, pad2, clamp, fmtBytes, fmtDate, ago, fmtTime, dayKey, hashStr, hashPin)
so that saved data stays compatible between the HTML and Python versions.
"""

import base64
import datetime as _dt
import hashlib
import hmac
import os
import random
import re
import string
import time
import urllib.parse

DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
          'August', 'September', 'October', 'November', 'December']

_B36 = string.digits + string.ascii_lowercase


def now_ms():
    """Milliseconds since the Unix epoch, like JavaScript's Date.now()."""
    return int(time.time() * 1000)


def _base36(n):
    if n == 0:
        return '0'
    out = []
    while n:
        n, r = divmod(n, 36)
        out.append(_B36[r])
    return ''.join(reversed(out))


def uid():
    """A short random identifier (7 random characters + 4 from the clock)."""
    rnd = ''.join(random.choice(_B36) for _ in range(7))
    return rnd + _base36(now_ms())[-4:]


def pad2(n):
    return str(int(n)).rjust(2, '0')


def clamp(v, a, b):
    return a if v < a else b if v > b else v


def js_weekday(d):
    """JavaScript's getDay(): 0 = Sunday … 6 = Saturday."""
    return (d.weekday() + 1) % 7


def from_ms(t):
    return _dt.datetime.fromtimestamp((t or 0) / 1000)


def fmt_bytes(n):
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        n = 0.0
    if n < 1024:
        return '%d B' % n
    if n < 1048576:
        return '%.1f KB' % (n / 1024)
    return '%.2f MB' % (n / 1048576)


def fmt_date(t):
    d = from_ms(t)
    return '%d-%s-%s %s:%s' % (d.year, pad2(d.month), pad2(d.day), pad2(d.hour), pad2(d.minute))


def ago(t):
    s = max(0, (now_ms() - (t or 0)) / 1000)
    if s < 60:
        return 'just now'
    if s < 3600:
        return '%d min ago' % (s // 60)
    if s < 86400:
        return '%d h ago' % (s // 3600)
    return '%d d ago' % (s // 86400)


def fmt_time(d=None, sec=False, clock24=True):
    d = d or _dt.datetime.now()
    hh = d.hour
    m = pad2(d.minute)
    s = ':' + pad2(d.second) if sec else ''
    if clock24 is False:
        ap = ' PM' if hh >= 12 else ' AM'
        hh = hh % 12 or 12
        return '%d:%s%s%s' % (hh, m, s, ap)
    return '%s:%s%s' % (pad2(hh), m, s)


def day_key(d=None):
    d = d or _dt.datetime.now()
    return '%d-%s-%s' % (d.year, pad2(d.month), pad2(d.day))


def hash_str(s):
    """32-bit FNV-1a of the UTF-16 code units, in hex (same as the original)."""
    a = 0x811c9dc5
    for unit in _utf16_units(s):
        a ^= unit
        a = (a * 16777619) & 0xFFFFFFFF
    return format(a, 'x')


def _utf16_units(s):
    data = str(s).encode('utf-16-le', 'surrogatepass')
    for i in range(0, len(data), 2):
        yield data[i] | (data[i + 1] << 8)


def hash_pin(pin):
    """SHA-256 of 'quill:' + PIN, so PINs from the HTML version keep working."""
    return hashlib.sha256(('quill:' + str(pin)).encode('utf-8')).hexdigest()


PASSWORD_ROUNDS = 60000   # about half a second on a Raspberry Pi 3


def hash_password(password):
    """A salted, slow hash of Quill's password (PBKDF2-SHA256), stored as 'pbkdf2$rounds$salt$hash'."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac('sha256', str(password).encode('utf-8'), salt, PASSWORD_ROUNDS)
    return 'pbkdf2$%d$%s$%s' % (PASSWORD_ROUNDS, salt.hex(), digest.hex())


def check_password(password, stored):
    """Whether password matches what hash_password() (or an older PIN hash) stored."""
    stored = stored or ''
    if stored.startswith('pbkdf2$'):
        try:
            _, rounds, salt, digest = stored.split('$')
            got = hashlib.pbkdf2_hmac('sha256', str(password).encode('utf-8'), bytes.fromhex(salt), int(rounds))
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(got.hex(), digest)
    return bool(stored) and hmac.compare_digest(hash_pin(password), stored)


def fmt_dur(ms, tenth=False):
    ms = max(0, ms)
    t = int(ms // 1000)
    hh, mm, ss = t // 3600, t % 3600 // 60, t % 60
    out = ('%d:%s' % (hh, pad2(mm)) if hh else pad2(mm)) + ':' + pad2(ss)
    if tenth:
        out += '.' + str(int(ms % 1000 // 10)).rjust(2, '0')
    return out


def parse_duration(s):
    """'90' (minutes), '90s', '5m', '1h30m' → milliseconds, or None."""
    s = str(s).strip().lower()
    if re.fullmatch(r'\d+(\.\d+)?', s):
        return float(s) * 60000
    total, found = 0.0, False
    for num, unit in re.findall(r'(\d+(?:\.\d+)?)\s*(h|m|s)', s):
        found = True
        total += float(num) * {'h': 3600000, 'm': 60000, 's': 1000}[unit]
    return total if found else None


# ---------------------------------------------------------------- data URLs

_DATA_URL = re.compile(r'^data:([^;,]*)(;base64)?,(.*)$', re.S)


def data_url_to_bytes(u):
    """Return (bytes, mime) for a data: URL; (b'', '') when it is not one."""
    m = _DATA_URL.match(u or '')
    if not m:
        return b'', ''
    mime = m.group(1) or 'application/octet-stream'
    if m.group(2):
        try:
            return base64.b64decode(m.group(3)), mime
        except (ValueError, TypeError):
            return b'', mime
    return urllib.parse.unquote_to_bytes(m.group(3)), mime


def bytes_to_data_url(data, mime):
    return 'data:%s;base64,%s' % (mime or 'application/octet-stream',
                                  base64.b64encode(data).decode('ascii'))


MIME_BY_EXT = {
    'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif',
    'webp': 'image/webp', 'bmp': 'image/bmp', 'svg': 'image/svg+xml', 'ico': 'image/x-icon',
    'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg': 'audio/ogg', 'oga': 'audio/ogg',
    'm4a': 'audio/mp4', 'flac': 'audio/flac', 'aac': 'audio/aac', 'opus': 'audio/opus',
    'json': 'application/json', 'pdf': 'application/pdf', 'zip': 'application/zip',
}


def mime_for(name):
    m = re.search(r'\.([a-z0-9]+)$', name or '', re.I)
    return MIME_BY_EXT.get(m.group(1).lower(), 'application/octet-stream') if m else 'application/octet-stream'


# ---------------------------------------------------------------- colours

def hex_to_rgb(h):
    m = re.fullmatch(r'#?([0-9a-fA-F]{6})', (h or '').strip())
    if not m:
        m3 = re.fullmatch(r'#?([0-9a-fA-F]{3})', (h or '').strip())
        if not m3:
            return (232, 176, 74)
        s = ''.join(c * 2 for c in m3.group(1))
    else:
        s = m.group(1)
    n = int(s, 16)
    return (n >> 16, (n >> 8) & 255, n & 255)


def rgb_to_hex(rgb):
    r, g, b = (int(round(clamp(c, 0, 255))) for c in rgb)
    return '#%02x%02x%02x' % (r, g, b)


def mix(c1, c2, t):
    """Blend two colours: t = 0 gives c1, t = 1 gives c2."""
    a, b = hex_to_rgb(c1), hex_to_rgb(c2)
    return rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def luminance(hex_color):
    r, g, b = hex_to_rgb(hex_color)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def ext_of(name):
    m = re.search(r'\.([a-z0-9]+)$', name or '', re.I)
    return m.group(1).lower() if m else ''
