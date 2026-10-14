"""Pictures: a PNG reader/writer, a drawing surface for Brush, and Tk helpers.

Everything here works with the standard library alone.  When the optional
Pillow package is installed it is used to open more formats (JPEG, WebP, BMP…)
and to scale pictures smoothly.
"""

import base64
import math
import random
import struct
import zlib

try:  # optional
    from PIL import Image as _PILImage  # noqa: F401
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False


class ImageError(Exception):
    pass


# ================================================================ PNG

_PNG_SIG = b'\x89PNG\r\n\x1a\n'


def png_size(data):
    if data[:8] == _PNG_SIG and data[12:16] == b'IHDR':
        return struct.unpack('>II', data[16:24])
    return None


def png_decode(data):
    """PNG bytes → (width, height, RGBA bytearray). Supports every standard PNG."""
    if data[:8] != _PNG_SIG:
        raise ImageError('not a PNG file')
    pos = 8
    idat = []
    plte = None
    trns = None
    w = h = depth = ctype = interlace = None
    while pos + 8 <= len(data):
        ln, typ = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b'IHDR':
            w, h, depth, ctype, _, _, interlace = struct.unpack('>IIBBBBB', body)
        elif typ == b'PLTE':
            plte = body
        elif typ == b'tRNS':
            trns = body
        elif typ == b'IDAT':
            idat.append(body)
        elif typ == b'IEND':
            break
    if w is None or not idat:
        raise ImageError('damaged PNG file')
    if w * h > 40_000_000:
        raise ImageError('picture is too large')
    try:
        raw = zlib.decompress(b''.join(idat))
    except zlib.error:
        raise ImageError('damaged PNG file')
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if channels is None:
        raise ImageError('unsupported PNG colour type')
    bpp_bits = channels * depth
    bpp = max(1, bpp_bits // 8)
    out = bytearray(w * h * 4)

    def unfilter(buf, offset, pw, ph):
        stride = (pw * bpp_bits + 7) // 8
        rows = []
        prev = bytearray(stride)
        for _ in range(ph):
            ft = buf[offset]
            line = bytearray(buf[offset + 1:offset + 1 + stride])
            offset += 1 + stride
            if ft == 1:
                for i in range(bpp, stride):
                    line[i] = (line[i] + line[i - bpp]) & 255
            elif ft == 2:
                for i in range(stride):
                    line[i] = (line[i] + prev[i]) & 255
            elif ft == 3:
                for i in range(stride):
                    left = line[i - bpp] if i >= bpp else 0
                    line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
            elif ft == 4:
                for i in range(stride):
                    a = line[i - bpp] if i >= bpp else 0
                    b = prev[i]
                    c = prev[i - bpp] if i >= bpp else 0
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                    line[i] = (line[i] + pr) & 255
            rows.append(line)
            prev = line
        return rows, offset

    def samples(line, pw):
        """Yield per-pixel channel values (0…255 scaled) for one unfiltered row."""
        if depth == 8:
            return line
        if depth == 16:
            return line[0::2]
        mask = (1 << depth) - 1
        vals = bytearray()
        for byte in line:
            for shift in range(8 - depth, -1, -depth):
                vals.append((byte >> shift) & mask)
        return vals[:pw * channels]

    scale = 255 // ((1 << depth) - 1) if depth < 8 else 1
    tr_key = None
    if trns is not None and ctype == 0 and len(trns) >= 2:
        tr_key = struct.unpack('>H', trns[:2])[0]
    elif trns is not None and ctype == 2 and len(trns) >= 6:
        tr_key = struct.unpack('>HHH', trns[:6])

    def put_row(line, pw, y, xs, xstep):
        s = samples(line, pw)
        for i in range(pw):
            x = xs + i * xstep
            o = (y * w + x) * 4
            if ctype == 0:
                v = s[i]
                g = v * scale if depth < 8 else v
                out[o:o + 4] = bytes((g, g, g, 0 if (tr_key is not None and _raw16(line, i, 1, 0) == tr_key) else 255))
            elif ctype == 2:
                r, g, b = s[i * 3], s[i * 3 + 1], s[i * 3 + 2]
                a = 255
                if tr_key is not None and (_raw16(line, i, 3, 0), _raw16(line, i, 3, 1), _raw16(line, i, 3, 2)) == tr_key:
                    a = 0
                out[o:o + 4] = bytes((r, g, b, a))
            elif ctype == 3:
                idx = s[i]
                if plte is None or idx * 3 + 2 >= len(plte):
                    out[o:o + 4] = b'\x00\x00\x00\xff'
                else:
                    a = trns[idx] if trns is not None and idx < len(trns) else 255
                    out[o:o + 4] = bytes((plte[idx * 3], plte[idx * 3 + 1], plte[idx * 3 + 2], a))
            elif ctype == 4:
                g, a = s[i * 2], s[i * 2 + 1]
                out[o:o + 4] = bytes((g, g, g, a))
            else:
                out[o:o + 4] = bytes(s[i * 4:i * 4 + 4])

    def _raw16(line, i, ch, k):
        if depth == 16:
            j = (i * ch + k) * 2
            return (line[j] << 8) | line[j + 1]
        if depth == 8:
            return line[i * ch + k]
        return samples(line, w)[i * ch + k]

    if not interlace:
        rows, _ = unfilter(raw, 0, w, h)
        if depth == 8 and ctype == 6:
            for y, line in enumerate(rows):
                out[y * w * 4:(y + 1) * w * 4] = line
        elif depth == 8 and ctype == 2 and tr_key is None:
            for y, line in enumerate(rows):
                row = bytearray(w * 4)
                row[0::4] = line[0::3]
                row[1::4] = line[1::3]
                row[2::4] = line[2::3]
                row[3::4] = b'\xff' * w
                out[y * w * 4:(y + 1) * w * 4] = row
        else:
            for y, line in enumerate(rows):
                put_row(line, w, y, 0, 1)
    else:
        offset = 0
        passes = [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]
        for x0, y0, dx, dy in passes:
            pw = (w - x0 + dx - 1) // dx if w > x0 else 0
            ph = (h - y0 + dy - 1) // dy if h > y0 else 0
            if pw == 0 or ph == 0:
                continue
            rows, offset = unfilter(raw, offset, pw, ph)
            for j, line in enumerate(rows):
                put_row(line, pw, y0 + j * dy, x0, dx)
    return w, h, out


def png_encode(w, h, rgb):
    """RGB bytes → PNG bytes (8-bit colour, no transparency)."""
    stride = w * 3
    raw = bytearray()
    mv = memoryview(rgb)
    for y in range(h):
        raw.append(0)
        raw += mv[y * stride:(y + 1) * stride]

    def chunk(t, body):
        return struct.pack('>I', len(body)) + t + body + struct.pack('>I', zlib.crc32(t + body) & 0xffffffff)

    return (_PNG_SIG + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b''))


def png_encode_rgba(w, h, rgba):
    """RGBA bytes → PNG bytes (8-bit colour with transparency)."""
    stride = w * 4
    raw = bytearray()
    mv = memoryview(rgba)
    for y in range(h):
        raw.append(0)
        raw += mv[y * stride:(y + 1) * stride]

    def chunk(t, body):
        return struct.pack('>I', len(body)) + t + body + struct.pack('>I', zlib.crc32(t + body) & 0xffffffff)

    return (_PNG_SIG + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(bytes(raw), 6)) + chunk(b'IEND', b''))


def ppm(w, h, rgb):
    return b'P6\n%d %d\n255\n' % (w, h) + bytes(rgb)


def rgba_to_rgb_on_white(rgba):
    n = len(rgba) // 4
    out = bytearray(n * 3)
    out[0::3] = rgba[0::4]
    out[1::3] = rgba[1::4]
    out[2::3] = rgba[2::4]
    alpha = rgba[3::4]
    if alpha.count(255) != n:
        for i in range(n):
            a = alpha[i]
            if a != 255:
                o = i * 3
                out[o] = (out[o] * a + 255 * (255 - a)) // 255
                out[o + 1] = (out[o + 1] * a + 255 * (255 - a)) // 255
                out[o + 2] = (out[o + 2] * a + 255 * (255 - a)) // 255
    return out


def decode_any(data, root=None):
    """Picture bytes → (w, h, RGB on white). Uses PNG support, Pillow, or Tk (GIF/PPM)."""
    if data[:8] == _PNG_SIG:
        w, h, rgba = png_decode(data)
        return w, h, rgba_to_rgb_on_white(rgba)
    if HAVE_PIL:
        import io
        from PIL import Image
        try:
            im = Image.open(io.BytesIO(data))
            im.load()
        except Exception as e:
            raise ImageError(str(e))
        im = im.convert('RGBA')
        bg = Image.new('RGBA', im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        return im.size[0], im.size[1], bytearray(bg.convert('RGB').tobytes())
    if root is not None and (data[:6] in (b'GIF87a', b'GIF89a') or data[:2] in (b'P6', b'P3')):
        import os
        import tempfile
        import tkinter as tk
        try:
            photo = tk.PhotoImage(master=root, data=base64.b64encode(data).decode('ascii'))
        except tk.TclError as e:
            raise ImageError(str(e))
        fd, path = tempfile.mkstemp(suffix='.ppm')
        os.close(fd)
        try:
            photo.write(path, format='ppm')
            with open(path, 'rb') as f:
                return parse_ppm(f.read())
        finally:
            os.unlink(path)
    raise ImageError('This kind of picture needs the Pillow package (pip install pillow).')


def parse_ppm(data):
    parts = []
    pos = 0
    while len(parts) < 4:
        while data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b'#':
            while data[pos:pos + 1] not in (b'\n', b''):
                pos += 1
            continue
        start = pos
        while not data[pos:pos + 1].isspace():
            pos += 1
        parts.append(data[start:pos])
    pos += 1
    if parts[0] != b'P6':
        raise ImageError('unsupported PPM')
    w, h = int(parts[1]), int(parts[2])
    return w, h, bytearray(data[pos:pos + w * h * 3])


# ================================================================ drawing surface (Brush)

def _hex(c):
    c = c.lstrip('#')
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


class Raster:
    """An RGB picture you can draw on. Strokes are anti-aliased and drawn into a
    coverage mask relative to the picture as it was when the stroke began, so a
    see-through brush stays even and shape previews can be redrawn cleanly."""

    def __init__(self, w, h, color=(255, 255, 255)):
        self.w, self.h = w, h
        self.buf = bytearray(bytes(color) * (w * h))
        self.dirty = None          # (x0, y0, x1, y1) needing a screen refresh
        self.base = None           # picture at the start of the current stroke
        self.cov = None            # coverage mask for the current stroke
        self.stroke_box = None

    # ---- whole picture
    def copy_buf(self):
        return bytes(self.buf)

    def load(self, w, h, rgb):
        self.w, self.h = w, h
        self.buf = bytearray(rgb)
        self.mark(0, 0, w, h)

    def fill_all(self, color):
        self.buf[:] = bytes(color) * (self.w * self.h)
        self.mark(0, 0, self.w, self.h)

    def get(self, x, y):
        o = (y * self.w + x) * 3
        return tuple(self.buf[o:o + 3])

    def mark(self, x0, y0, x1, y1):
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(self.w, int(math.ceil(x1))), min(self.h, int(math.ceil(y1)))
        if x1 <= x0 or y1 <= y0:
            return
        if self.dirty is None:
            self.dirty = (x0, y0, x1, y1)
        else:
            a = self.dirty
            self.dirty = (min(a[0], x0), min(a[1], y0), max(a[2], x1), max(a[3], y1))

    def take_dirty(self):
        d, self.dirty = self.dirty, None
        return d

    def region_ppm(self, box):
        x0, y0, x1, y1 = box
        rw = x1 - x0
        stride = self.w * 3
        rows = [self.buf[y * stride + x0 * 3:y * stride + x1 * 3] for y in range(y0, y1)]
        return b'P6\n%d %d\n255\n' % (rw, y1 - y0) + b''.join(rows)

    # ---- strokes
    def begin(self):
        self.base = bytes(self.buf)
        self.cov = bytearray(self.w * self.h)
        self.stroke_box = None

    def end(self):
        self.base = None
        self.cov = None
        self.stroke_box = None

    def reset_stroke(self):
        """Undo everything drawn since begin() (used for live shape previews)."""
        if self.base is None or self.stroke_box is None:
            return
        x0, y0, x1, y1 = self.stroke_box
        stride = self.w * 3
        for y in range(y0, y1):
            a, b = y * stride + x0 * 3, y * stride + x1 * 3
            self.buf[a:b] = self.base[a:b]
            self.cov[y * self.w + x0:y * self.w + x1] = bytes(x1 - x0)
        self.mark(x0, y0, x1, y1)
        self.stroke_box = None

    def _grow(self, x0, y0, x1, y1):
        if self.stroke_box is None:
            self.stroke_box = (x0, y0, x1, y1)
        else:
            a = self.stroke_box
            self.stroke_box = (min(a[0], x0), min(a[1], y0), max(a[2], x1), max(a[3], y1))
        self.mark(x0, y0, x1, y1)

    def _apply(self, x, y, c, color, alpha):
        """Raise coverage at (x, y) to c (0…1) and repaint that pixel from the base."""
        i = y * self.w + x
        v = int(c * 255)
        if v <= self.cov[i]:
            return
        self.cov[i] = v
        o = i * 3
        k = alpha * v / 255.0
        base = self.base
        r, g, b = color
        self.buf[o] = int(base[o] + (r - base[o]) * k + 0.5)
        self.buf[o + 1] = int(base[o + 1] + (g - base[o + 1]) * k + 0.5)
        self.buf[o + 2] = int(base[o + 2] + (b - base[o + 2]) * k + 0.5)

    def capsule(self, x0, y0, x1, y1, width, color, alpha=1.0, soft=0.0):
        """A thick line with round ends from (x0, y0) to (x1, y1)."""
        if self.base is None:
            self.begin()
        r = max(0.5, width / 2.0)
        pad = r + 1 + soft
        bx0, by0 = max(0, int(min(x0, x1) - pad)), max(0, int(min(y0, y1) - pad))
        bx1, by1 = min(self.w, int(max(x0, x1) + pad) + 1), min(self.h, int(max(y0, y1) + pad) + 1)
        if bx1 <= bx0 or by1 <= by0:
            return
        dx, dy = x1 - x0, y1 - y0
        ll = dx * dx + dy * dy
        apply = self._apply
        edge = 0.5 + soft
        for y in range(by0, by1):
            py = y + 0.5
            for x in range(bx0, bx1):
                px = x + 0.5
                if ll > 0:
                    t = ((px - x0) * dx + (py - y0) * dy) / ll
                    t = 0.0 if t < 0 else 1.0 if t > 1 else t
                    qx, qy = x0 + t * dx - px, y0 + t * dy - py
                else:
                    qx, qy = x0 - px, y0 - py
                d = math.sqrt(qx * qx + qy * qy)
                c = (r + 0.5 - d) / (2 * edge) + 0.5 if soft else r + 0.5 - d
                if c > 0:
                    apply(x, y, 1.0 if c > 1 else c, color, alpha)
        self._grow(bx0, by0, bx1, by1)

    def rect(self, x0, y0, x1, y1, width, color, filled):
        if self.base is None:
            self.begin()
        if filled:
            # a filled canvas rectangle covers its box; its outline is not stroked
            ax, ay, bx, by = min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
            ix0, iy0 = max(0, int(math.floor(ax))), max(0, int(math.floor(ay)))
            ix1, iy1 = min(self.w, int(math.ceil(bx))), min(self.h, int(math.ceil(by)))
            for y in range(iy0, iy1):
                cy = min(by, y + 1) - max(ay, y)
                for x in range(ix0, ix1):
                    cx = min(bx, x + 1) - max(ax, x)
                    c = cx * cy
                    if c > 0:
                        self._apply(x, y, min(1.0, c), color, 1.0)
            if ix1 > ix0 and iy1 > iy0:
                self._grow(ix0, iy0, ix1, iy1)
            return
        for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            self.capsule(a[0], a[1], b[0], b[1], width, color)

    def ellipse(self, x0, y0, x1, y1, width, color, filled):
        if self.base is None:
            self.begin()
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rx, ry = abs(x1 - x0) / 2, abs(y1 - y0) / 2
        if filled:
            if rx < 0.5 or ry < 0.5:
                return
            ix0, iy0 = max(0, int(cx - rx - 1)), max(0, int(cy - ry - 1))
            ix1, iy1 = min(self.w, int(cx + rx + 2)), min(self.h, int(cy + ry + 2))
            for y in range(iy0, iy1):
                ny = (y + 0.5 - cy) / ry
                for x in range(ix0, ix1):
                    nx = (x + 0.5 - cx) / rx
                    d = math.sqrt(nx * nx + ny * ny)
                    # distance from the edge, in pixels (approximately)
                    c = (1 - d) * min(rx, ry) + 0.5
                    if c > 0:
                        self._apply(x, y, min(1.0, c), color, 1.0)
            if ix1 > ix0 and iy1 > iy0:
                self._grow(ix0, iy0, ix1, iy1)
            return
        steps = max(16, int((rx + ry) * 0.6))
        pts = [(cx + rx * math.cos(TWO_PI * i / steps), cy + ry * math.sin(TWO_PI * i / steps)) for i in range(steps + 1)]
        for a, b in zip(pts, pts[1:]):
            self.capsule(a[0], a[1], b[0], b[1], width, color)

    def spray(self, x, y, size, color, rnd=random):
        n = int(math.ceil(size * 1.5))
        r, g, b = color
        stride = self.w * 3
        for _ in range(n):
            a = rnd.random() * 6.283
            d = rnd.random() * size * 1.4
            px, py = int(x + math.cos(a) * d), int(y + math.sin(a) * d)
            for qy in (py, py + 1):
                for qx in (px, px + 1):
                    if 0 <= qx < self.w and 0 <= qy < self.h:
                        o = qy * stride + qx * 3
                        self.buf[o:o + 3] = bytes((r, g, b))
        pad = size * 1.4 + 2
        self.mark(x - pad, y - pad, x + pad, y + pad)

    def flood_fill(self, x, y, color):
        x, y = int(x), int(y)
        w, h = self.w, self.h
        if not (0 <= x < w and 0 <= y < h):
            return
        buf = self.buf
        # Pack each pixel into one int for fast comparisons.
        px = [(buf[i] << 16) | (buf[i + 1] << 8) | buf[i + 2] for i in range(0, w * h * 3, 3)]
        r, g, b = color
        tgt = (r << 16) | (g << 8) | b
        frm = px[y * w + x]
        if frm == tgt:
            return
        trip = bytes((r, g, b))
        stack = [(x, y)]
        x0b, y0b, x1b, y1b = x, y, x, y
        while stack:
            sx, sy = stack.pop()
            row = sy * w
            if px[row + sx] != frm:
                continue
            lx = sx
            while lx > 0 and px[row + lx - 1] == frm:
                lx -= 1
            rx = sx
            while rx < w - 1 and px[row + rx + 1] == frm:
                rx += 1
            for k in range(lx, rx + 1):
                px[row + k] = tgt
            buf[(row + lx) * 3:(row + rx + 1) * 3] = trip * (rx - lx + 1)
            x0b, x1b = min(x0b, lx), max(x1b, rx)
            y0b, y1b = min(y0b, sy), max(y1b, sy)
            for ny in (sy - 1, sy + 1):
                if 0 <= ny < h:
                    nrow = ny * w
                    up = False
                    for k in range(lx, rx + 1):
                        hit = px[nrow + k] == frm
                        if hit and not up:
                            stack.append((k, ny))
                        up = hit
        self.mark(x0b, y0b, x1b + 1, y1b + 1)


TWO_PI = 2 * math.pi


def scale_rgb(w, h, rgb, nw, nh):
    """Nearest-neighbour resize (used when opening a big picture in Brush)."""
    if (nw, nh) == (w, h):
        return bytearray(rgb)
    out = bytearray(nw * nh * 3)
    xs = [min(w - 1, int(x * w / nw)) * 3 for x in range(nw)]
    for y in range(nh):
        sy = min(h - 1, int(y * h / nh))
        src = rgb[sy * w * 3:(sy + 1) * w * 3]
        row = bytearray(nw * 3)
        for i, sx in enumerate(xs):
            row[i * 3:i * 3 + 3] = src[sx:sx + 3]
        out[y * nw * 3:(y + 1) * nw * 3] = row
    return out


# ================================================================ Tk display helpers

def photo_from_bytes(root, data, max_size=None):
    """A Tk PhotoImage for picture bytes, or None if it cannot be shown.

    PNG and GIF load natively; other formats need Pillow. With max_size=(w, h)
    the picture is shrunk to fit (it is never enlarged).
    """
    import tkinter as tk
    if HAVE_PIL:
        import io
        from PIL import Image, ImageTk
        try:
            im = Image.open(io.BytesIO(data))
            im.load()
            if max_size:
                im.thumbnail(max_size)
            return ImageTk.PhotoImage(im, master=root)
        except Exception:
            pass
    try:
        photo = tk.PhotoImage(master=root, data=base64.b64encode(data).decode('ascii'))
    except tk.TclError:
        try:
            photo = tk.PhotoImage(master=root, data=base64.b64encode(data).decode('ascii'), format='svg')
        except tk.TclError:
            return None
    if max_size:
        photo = fit_photo(photo, max_size[0], max_size[1])
    return photo


def fit_photo(photo, mw, mh):
    w, h = photo.width(), photo.height()
    if w <= mw and h <= mh:
        return photo
    k = max(1, int(math.ceil(max(w / mw, h / mh))))
    return photo.subsample(k, k)


def scaled_photo(photo, zoom):
    """Scale a PhotoImage by a factor using Tk's integer zoom and subsample."""
    if abs(zoom - 1) < 1e-3:
        return photo
    best = (1, 1)
    best_err = 1e9
    for num in range(1, 17):
        den = max(1, int(round(num / zoom)))
        if den > 32:
            continue
        err = abs(num / den - zoom)
        if err < best_err - 1e-9:
            best, best_err = (num, den), err
    num, den = best
    out = photo
    if num > 1:
        out = out.zoom(num, num)
    if den > 1:
        out = out.subsample(den, den)
    return out
