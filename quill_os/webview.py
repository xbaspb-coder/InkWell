"""Quill.OS's web window: shows OG Browser, an XApp or a web page with WebKitGTK.

It runs as its own program, started by Quill.OS (see web.py), because GTK and Tk
cannot share one program. The two talk through pipes, one JSON message per line:

    Quill → window (stdin):   {"cmd": "show"} {"cmd": "hide"} {"cmd": "open", "address": "…"} {"cmd": "quit"}
    window → Quill (stdout):  {"ev": "ready"} {"ev": "shown"} {"ev": "hidden"} {"ev": "title", "title": "…"} {"ev": "closed"}

Modes:
    og    OG Browser (the original OG_Browser.html), with camera, microphone and notifications allowed
    xapp  an app from XApps: one HTML file, with no special permissions and no pop-up windows
    url   a single web page or local file

Every mode keeps its saved data (sign-ins, localStorage, cookies) in its own folder,
so XApps cannot read OG Browser's sign-in or each other's data.
"""

import argparse
import json
import os
import sys

import gi

try:
    gi.require_version('Gtk', '3.0')
    try:
        gi.require_version('WebKit2', '4.1')
    except ValueError:
        gi.require_version('WebKit2', '4.0')
    gi.require_version('Pango', '1.0')
    from gi.repository import Gdk, GLib, Gtk, Pango, WebKit2
except (ValueError, ImportError) as e:   # pragma: no cover - reported to Quill, which explains it
    print(json.dumps({'ev': 'error', 'error': 'WebKitGTK is not installed: %s' % e}), flush=True)
    sys.exit(3)

CSS = b"""
.qbar { background: #12151f; border-bottom: 1px solid #2a3042; padding: 2px 6px; }
.qbar button { background: #232838; color: #ebe7da; border: 1px solid #343b50; border-radius: 6px;
               padding: 2px 12px; min-height: 26px; box-shadow: none; text-shadow: none; }
.qbar button:hover { background: #2e3448; }
.qbar label { color: #ebe7da; font-style: italic; }
"""


def send(**msg):
    try:
        sys.stdout.write(json.dumps(msg) + '\n')
        sys.stdout.flush()
    except (BrokenPipeError, ValueError, OSError):
        pass


def og_open_script(address):
    """JavaScript that opens an address in OG Browser's current tab, as if typed in its address bar."""
    a = json.dumps(address)
    return ("(function(){try{var e=parseInput(%s);if(e){if(typeof activeTab!=='undefined'&&activeTab){navigate(activeTab,e);}"
            "else{createTab(e);}}}catch(err){}})();" % a)


class WebWindow:
    def __init__(self, args):
        self.args = args
        self.mode = args.mode
        self.pending_open = args.open
        self.loaded = False
        self.quitting = False
        self.inbuf = b''
        self.windows = []

        os.makedirs(args.data, exist_ok=True)
        manager = WebKit2.WebsiteDataManager(base_data_directory=os.path.join(args.data, 'data'),
                                             base_cache_directory=os.path.join(args.data, 'cache'))
        proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
        if proxy and hasattr(manager, 'set_network_proxy_settings'):
            # Follow the computer's proxy setting, as other programs do (most networks have none).
            ignore = [h.strip() for h in (os.environ.get('no_proxy') or os.environ.get('NO_PROXY') or '').split(',')
                      if h.strip()]
            manager.set_network_proxy_settings(WebKit2.NetworkProxyMode.CUSTOM,
                                               WebKit2.NetworkProxySettings.new(proxy, ignore or None))
        self.context = WebKit2.WebContext.new_with_website_data_manager(manager)
        cookies = manager.get_cookie_manager()
        cookies.set_persistent_storage(os.path.join(args.data, 'cookies.sqlite'),
                                       WebKit2.CookiePersistentStorage.SQLITE)
        self.context.set_cache_model(WebKit2.CacheModel.DOCUMENT_BROWSER if self.mode == 'og'
                                     else WebKit2.CacheModel.DOCUMENT_VIEWER)

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.view = self._new_view()
        self.win = self._new_window(self.view, args.title or 'OG Browser', main=True)
        if args.file:
            self.view.load_uri(GLib.filename_to_uri(os.path.abspath(args.file), None))
        else:
            self.view.load_uri(args.url or 'about:blank')
        if not args.hidden:
            self.show()
        GLib.io_add_watch(GLib.IOChannel.unix_new(sys.stdin.fileno()), GLib.PRIORITY_DEFAULT,
                          GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR, self._stdin)
        send(ev='ready')

    # ---------------------------------------------------------- building
    def _settings(self):
        s = WebKit2.Settings()
        s.set_enable_developer_extras(False)
        s.set_enable_write_console_messages_to_stdout(False)   # stdout is the pipe to Quill
        s.set_javascript_can_open_windows_automatically(self.mode == 'og')
        s.set_enable_media_stream(self.mode == 'og')
        s.set_enable_webaudio(True)
        s.set_enable_webgl(True)
        s.set_allow_file_access_from_file_urls(False)
        s.set_allow_universal_access_from_file_urls(False)
        s.set_user_agent_with_application_details('QuillOS-Inkwell', '1')
        return s

    def _new_view(self, related=None):
        if related is not None:
            view = WebKit2.WebView.new_with_related_view(related)
        else:
            view = WebKit2.WebView.new_with_context(self.context)
        view.set_settings(self._settings())
        view.connect('permission-request', self._permission)
        view.connect('create', self._create)
        view.connect('decide-policy', self._policy)
        view.connect('load-changed', self._load_changed)
        view.connect('notify::title', self._title_changed)
        return view

    def _new_window(self, view, title, main=False):
        win = Gtk.Window(title=title)
        w, h = 1024, 600
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0) if display else None
        if monitor is not None:
            geo = monitor.get_geometry()
            w, h = geo.width, geo.height
        win.set_default_size(max(640, w), max(400, h))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.get_style_context().add_class('qbar')
        if main:
            back = Gtk.Button(label='◀ Quill.OS')
            back.set_tooltip_text('Go back to Quill.OS. This window stays open.')
            back.connect('clicked', lambda _b: self.hide())
            bar.pack_start(back, False, False, 0)
        label = Gtk.Label(label=title)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        bar.pack_start(label, True, True, 0)
        close = Gtk.Button(label='✕ Close')
        close.connect('clicked', lambda _b: self.quit() if main else win.destroy())
        bar.pack_end(close, False, False, 0)
        box.pack_start(bar, False, False, 0)
        box.pack_start(view, True, True, 0)
        win.add(box)
        win.label = label
        if main:
            win.connect('delete-event', self._delete)
        else:
            win.connect('destroy', lambda w: w in self.windows and self.windows.remove(w))
            self.windows.append(win)
        return win

    # ---------------------------------------------------------- showing and hiding
    def show(self):
        self.win.show_all()
        self.win.present()
        self.win.maximize()
        send(ev='shown')

    def hide(self):
        for w in list(self.windows):
            w.hide()
        self.win.hide()
        send(ev='hidden')

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        send(ev='closed')
        Gtk.main_quit()

    def _delete(self, *_a):
        self.quit()
        return True

    # ---------------------------------------------------------- messages from Quill
    def _stdin(self, _source, cond):
        try:
            chunk = os.read(sys.stdin.fileno(), 65536) if cond & GLib.IOCondition.IN else b''
        except OSError:
            chunk = b''
        if not chunk:
            self.quit()          # Quill has gone away
            return False
        self.inbuf += chunk
        while b'\n' in self.inbuf:
            line, self.inbuf = self.inbuf.split(b'\n', 1)
            try:
                msg = json.loads(line.decode('utf-8'))
            except ValueError:
                continue
            cmd = msg.get('cmd')
            if cmd == 'show':
                self.show()
            elif cmd == 'hide':
                self.hide()
            elif cmd == 'quit':
                self.quit()
                return False
            elif cmd == 'open' and msg.get('address'):
                self.open(msg['address'])
                self.show()
            elif cmd == 'eval' and isinstance(msg.get('js'), str):
                self.run_js(msg['js'], reply=msg.get('id', 0))   # used by Quill's own tests
        return True

    def run_js(self, js, reply=None):
        """Run JavaScript in the page; with reply set, send its result back to Quill."""
        def done(view, result, _data=None):
            if reply is None:
                return
            try:
                value = (view.evaluate_javascript_finish(result) if hasattr(view, 'evaluate_javascript_finish')
                         else view.run_javascript_finish(result).get_js_value())
                send(ev='result', id=reply, value=value.to_string() if value is not None else None)
            except GLib.Error as e:
                send(ev='result', id=reply, error=e.message)
        if hasattr(self.view, 'evaluate_javascript'):
            self.view.evaluate_javascript(js, -1, None, None, None, done, None)
        else:
            self.view.run_javascript(js, None, done, None)

    def open(self, address):
        if self.mode == 'og':
            if self.loaded:
                self.run_js(og_open_script(address))
            else:
                self.pending_open = address
        elif self.mode == 'url':
            self.view.load_uri(address)

    # ---------------------------------------------------------- the page
    def _load_changed(self, view, event):
        if view is self.view and event == WebKit2.LoadEvent.FINISHED and not self.loaded:
            self.loaded = True
            if self.mode == 'og' and self.pending_open:
                addr, self.pending_open = self.pending_open, None
                self.run_js(og_open_script(addr))

    def _title_changed(self, view, _p):
        title = view.get_title() or ''
        if view is self.view and title:
            if self.mode == 'url':
                self.win.label.set_text(title)
                self.win.set_title(title)
            send(ev='title', title=title)

    def _permission(self, _view, request):
        allowed = (WebKit2.UserMediaPermissionRequest, WebKit2.NotificationPermissionRequest)
        if self.mode == 'og' and isinstance(request, allowed):
            request.allow()
        else:
            request.deny()
        return True

    def _create(self, view, _action):
        if self.mode != 'og':
            return None      # XApps and plain pages may not open new windows
        new = self._new_view(related=view)
        win = self._new_window(new, 'OG Browser — pop-up')
        new.connect('ready-to-show', lambda v: win.show_all())
        new.connect('close', lambda v: win.destroy())
        return new

    def _policy(self, _view, decision, kind):
        if kind != WebKit2.PolicyDecisionType.NAVIGATION_ACTION or self.mode != 'xapp':
            return False
        uri = decision.get_navigation_action().get_request().get_uri() or ''
        own = GLib.filename_to_uri(os.path.abspath(self.args.file), None)
        if uri.split('#')[0] == own or uri.startswith(('http://', 'https://', 'about:', 'data:', 'blob:')):
            return False
        decision.ignore()    # an XApp may not open other files on the laptop
        return True


def main(argv=None):
    p = argparse.ArgumentParser(prog='quill-web')
    p.add_argument('--mode', choices=('og', 'xapp', 'url'), default='url')
    p.add_argument('--data', required=True, help='folder for this window\'s saved data')
    p.add_argument('--file', help='an HTML file to show')
    p.add_argument('--url', help='a web address to show')
    p.add_argument('--open', help='OG Browser: an address to open after it starts')
    p.add_argument('--title', default='')
    p.add_argument('--hidden', action='store_true', help='start without showing the window')
    args = p.parse_args(argv)
    Gtk.init(None)
    WebWindow(args)
    Gtk.main()
    return 0


if __name__ == '__main__':
    sys.exit(main())
