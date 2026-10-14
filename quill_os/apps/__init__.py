"""The built-in apps, in the same order as the original Quill.OS (plus Iris, the camera)."""

from collections import OrderedDict


def load_apps():
    from . import files, scribe, glyph, term, calc, brush, chrono, lyre, lens, iris, loom, pulse, almanac, arcade, \
        portal, compass, guide, ogb
    apps = OrderedDict()
    for mod in (files, scribe, glyph, term, calc, brush, chrono, lyre, lens, iris, loom, pulse, almanac, arcade, portal,
                compass, guide, ogb):
        spec = mod.App()
        apps[spec.id] = spec
    return apps
