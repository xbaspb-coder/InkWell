"""Tests for the PNG reader/writer and the Brush drawing surface."""

import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quill_os import imaging  # noqa: E402

try:
    from PIL import Image
except ImportError:  # Pillow is optional; some tests need it to make sample files
    Image = None


class PngTests(unittest.TestCase):
    def test_round_trip(self):
        w, h = 7, 5
        rgb = bytearray(os.urandom(w * h * 3))
        data = imaging.png_encode(w, h, rgb)
        self.assertEqual(imaging.png_size(data), (w, h))
        w2, h2, rgba = imaging.png_decode(data)
        self.assertEqual((w2, h2), (w, h))
        self.assertEqual(imaging.rgba_to_rgb_on_white(rgba), rgb)

    @unittest.skipIf(Image is None, 'Pillow not installed')
    def test_decodes_every_colour_type(self):
        base = Image.new('RGBA', (13, 9))
        for y in range(9):
            for x in range(13):
                base.putpixel((x, y), (x * 19 % 256, y * 28 % 256, (x * y) % 256, 255 if (x + y) % 3 else 128))
        for mode in ['RGB', 'RGBA', 'L', 'LA', 'P', '1', 'I;16']:
            im = base.convert(mode) if mode != 'I;16' else base.convert('L').convert('I;16')
            buf = io.BytesIO()
            im.save(buf, 'PNG')
            w, h, rgba = imaging.png_decode(buf.getvalue())
            ref = im.convert('RGBA').tobytes()
            self.assertEqual((w, h), (13, 9), mode)
            if mode == 'I;16':
                # 16-bit grey keeps the high byte of each sample
                vals = [im.getpixel((x, y)) >> 8 for y in range(9) for x in range(13)]
                self.assertEqual(list(rgba[0::4]), vals, mode)
                continue
            self.assertEqual(bytes(rgba), ref, mode)

    def test_raster_drawing(self):
        r = imaging.Raster(40, 30)
        r.begin()
        r.capsule(5, 5, 35, 5, 4, (255, 0, 0))
        r.end()
        self.assertEqual(r.get(20, 5), (255, 0, 0))
        self.assertEqual(r.get(20, 20), (255, 255, 255))
        r.begin()
        r.rect(2, 10, 12, 20, 2, (0, 0, 255), True)
        r.end()
        self.assertEqual(r.get(7, 15), (0, 0, 255))
        r.flood_fill(30, 25, (0, 255, 0))
        self.assertEqual(r.get(30, 25), (0, 255, 0))
        self.assertEqual(r.get(7, 15), (0, 0, 255))
        # a translucent brush stroke stays even where it overlaps itself
        r2 = imaging.Raster(30, 10)
        r2.begin()
        r2.capsule(5, 5, 15, 5, 6, (0, 0, 0), alpha=0.35)
        r2.capsule(15, 5, 25, 5, 6, (0, 0, 0), alpha=0.35)
        r2.end()
        self.assertEqual(r2.get(15, 5), r2.get(8, 5))
        # previews can be wiped back to the start of the stroke
        r3 = imaging.Raster(20, 20)
        r3.begin()
        r3.ellipse(2, 2, 18, 18, 2, (0, 0, 0), False)
        r3.reset_stroke()
        self.assertEqual(r3.buf, bytearray(b'\xff' * (20 * 20 * 3)))
        r3.end()

    def test_scale(self):
        out = imaging.scale_rgb(2, 1, bytearray(b'\x00\x00\x00\xff\xff\xff'), 4, 2)
        self.assertEqual(len(out), 4 * 2 * 3)
        self.assertEqual(out[:6], bytearray(b'\x00' * 6))


if __name__ == '__main__':
    unittest.main()
