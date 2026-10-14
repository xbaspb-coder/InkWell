"""What every app looks like to the window manager."""


class AppSpec:
    id = ''
    name = ''
    icon = '?'
    bg = ('#555555', '#333333')   # the two colours of the icon's gradient
    w = 720
    h = 480
    single = False                # only one window at a time
    hidden = False                # left out of the app lists (opened by other means)
    kw = ''                       # extra words the Inkwell matches
    about = ''

    def build(self, ctx):
        """Fill ctx.body and return an object with any of: on_arg(arg), on_focus(), on_resize(),
        before_close() -> bool, on_close(), mem() -> bytes."""
        raise NotImplementedError


class Inst:
    """A convenient return value for build(): pass the callbacks you need as keywords."""

    def __init__(self, **callbacks):
        for k, v in callbacks.items():
            setattr(self, k, v)
