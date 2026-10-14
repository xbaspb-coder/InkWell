"""The built-in apps, in the same order as the original Quill.OS (plus Iris, the camera, and XApps, the app store)."""

from collections import OrderedDict


def load_apps():
    from . import files, scribe, glyph, term, calc, brush, chrono, lyre, lens, iris, loom, pulse, almanac, arcade, \
        portal, compass, guide, ogb, store
    apps = OrderedDict()
    for mod in (files, scribe, glyph, term, calc, brush, chrono, lyre, lens, iris, loom, pulse, almanac, arcade, portal,
                compass, guide, ogb, store):
        spec = mod.App()
        apps[spec.id] = spec
    apps[ogb.WebPage.id] = ogb.WebPage()
    return apps
