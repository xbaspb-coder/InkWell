"""OG Browser — inside Quill when the device build embeds it; otherwise an explanation."""

from .base import AppSpec, Inst


class App(AppSpec):
    id = 'ogb'
    name = 'OG Browser'
    icon = '🌐'
    bg = ('#4d7cff', '#1a2f8f')
    w, h = 1000, 640
    single = True
    kw = 'og browser web internet sites search tabs mail ferret lifecraft lifegames'
    about = 'The OG Browser, inside Quill'

    def build(self, ctx):
        ctx.os.empty_state(ctx.body, '🌐', 'OG Browser is not part of this program.',
                           'This copy of Quill.OS runs on its own. Open it inside OG Browser, or use the build that has '
                           'OG Browser included.')
        return Inst()
