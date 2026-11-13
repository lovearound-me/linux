"""The incoming-signal effect on every screen, above everything, never taking a click.

Which way depends on the desktop, chosen at each signal:
- GNOME Shell (Wayland or X11): our Shell extension draws it inside the
  compositor; Mutter has no layer-shell, and an ordinary window can neither
  cover the top bar nor stay above a full-screen one.
- KDE Plasma, Sway and other wlroots compositors: a wlr-layer-shell surface
  on the overlay layer, one per screen, with an empty input region.
- Other X11 desktops: an override-redirect RGBA window per screen with an
  empty input shape, if a compositor makes it transparent.
- Nothing of the above: a quiet notification and the tray icon flash.
"""
import os
import time

import cairo
import gi
from gi.repository import Gdk, Gio, GLib, Gtk

from . import effect
from .i18n import tr

try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell
except (ImportError, ValueError):
    GtkLayerShell = None

SHELL_PATH = "/me/lovearound/Overlay"
SHELL_IFACE = "me.lovearound.Overlay"
# The extension's D-Bus interface this app speaks.
SHELL_VERSION = 1


def is_wayland():
    display = Gdk.Display.get_default()
    return display is not None and type(display).__name__.startswith("GdkWayland")


def is_gnome_shell():
    desktops = os.environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":")
    return "GNOME" in desktops or "UNITY" in desktops


class ShellExtension:
    """Our GNOME Shell extension, over the session bus."""

    def __init__(self):
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error:
            self.bus = None

    def _call(self, method, args, reply, timeout=500):
        return self.bus.call_sync("org.gnome.Shell", SHELL_PATH, SHELL_IFACE if method != "Get" else
                                  "org.freedesktop.DBus.Properties", method, args, reply,
                                  Gio.DBusCallFlags.NO_AUTO_START, timeout, None)

    def version(self):
        """The extension's interface version, or 0 when it is not running."""
        if self.bus is None:
            return 0
        try:
            value = self._call("Get", GLib.Variant("(ss)", (SHELL_IFACE, "Version")), GLib.VariantType("(v)"))
            return value.unpack()[0]
        except GLib.Error:
            return 0

    def play(self, color, emoji, count, calm):
        chars = effect.SETS[emoji] if isinstance(emoji, str) else emoji
        self.bus.call("org.gnome.Shell", SHELL_PATH, SHELL_IFACE, "Play",
                      GLib.Variant("(sasib)", ("#%06x" % color, chars, count, calm)),
                      None, Gio.DBusCallFlags.NO_AUTO_START, 2000, None, None)

    def presenting(self):
        """Something full screen or the screen being shared or recorded."""
        try:
            return self._call("Presenting", None, GLib.VariantType("(b)")).unpack()[0]
        except GLib.Error:
            return False


class Surfaces:
    """One transparent, click-through window per screen, drawn with cairo."""

    def __init__(self, layer):
        self.layer = layer
        self.windows = []
        self.effects = []
        self.started = 0.0
        self.cache = effect.EmojiCache()
        self.hide = None

    def play(self, color, emoji, count, calm):
        self.clear()
        display = Gdk.Display.get_default()
        self.started = time.monotonic()
        longest = effect.GLOW_DURATION
        for i in range(display.get_n_monitors()):
            monitor = display.get_monitor(i)
            area = monitor.get_geometry()
            fx = effect.Effect(color, emoji, count, calm, area.width, area.height)
            longest = max(longest, fx.duration)
            window = self._window(monitor, area)
            window.connect("draw", self._draw, fx, monitor.get_scale_factor())
            window.add_tick_callback(lambda w, clock: w.queue_draw() or True)
            window.show_all()
            # Clicks pass through: an empty input region.
            window.input_shape_combine_region(cairo.Region())
            self.windows.append(window)
        self.hide = GLib.timeout_add(int((longest + 0.3) * 1000), self.clear)

    def _window(self, monitor, area):
        if self.layer:
            window = Gtk.Window()
            GtkLayerShell.init_for_window(window)
            GtkLayerShell.set_namespace(window, "lovearound")
            GtkLayerShell.set_layer(window, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_monitor(window, monitor)
            for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                         GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
                GtkLayerShell.set_anchor(window, edge, True)
            # Over panels too, not pushed aside by them.
            GtkLayerShell.set_exclusive_zone(window, -1)
            GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.NONE)
        else:
            window = Gtk.Window(type=Gtk.WindowType.POPUP)
            window.move(area.x, area.y)
            window.set_keep_above(True)
            window.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
            window.set_accept_focus(False)
        window.set_default_size(area.width, area.height)
        window.set_size_request(area.width, area.height)
        window.set_title("Love Around")
        window.set_decorated(False)
        window.set_app_paintable(True)
        visual = window.get_screen().get_rgba_visual()
        if visual is not None:
            window.set_visual(visual)
        return window

    def _draw(self, window, cr, fx, scale):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        alloc = window.get_allocation()
        effect.draw(cr, fx, time.monotonic() - self.started, alloc.width, alloc.height, self.cache, scale)
        return True

    def clear(self):
        if self.hide:
            GLib.source_remove(self.hide)
            self.hide = None
        for window in self.windows:
            window.destroy()
        self.windows = []
        return False


class Overlay:
    def __init__(self, app=None):
        self.app = app
        self.shell = ShellExtension()
        self.layer = Surfaces(layer=True)
        self.x11 = Surfaces(layer=False)
        self.withdraw = None
        # Set by the app: the tray flashes when nothing can glow.
        self.on_fallback = lambda color: None

    def kind(self):
        """"shell", "layer", "x11" or "notify"."""
        if self.shell.version() >= SHELL_VERSION:
            return "shell"
        if is_wayland():
            return "layer" if GtkLayerShell is not None and GtkLayerShell.is_supported() else "notify"
        screen = Gdk.Screen.get_default()
        return "x11" if screen is not None and screen.is_composited() else "notify"

    def play(self, color, emoji, count, calm, incoming=False):
        """`incoming`: a signal to this person, not the echo of one they sent."""
        kind = self.kind()
        if kind == "shell":
            self.shell.play(color, emoji, count, calm)
        elif kind == "layer":
            self.layer.play(color, emoji, count, calm)
        elif kind == "x11":
            self.x11.play(color, emoji, count, calm)
        elif incoming:
            self.notify(color)

    def notify(self, color):
        """No way to glow here: a notification that says no more than the glow would."""
        self.on_fallback(color)
        if self.app is None:
            return
        note = Gio.Notification.new("Love Around")
        note.set_body(tr("Кто-то сейчас думает о тебе ♥"))
        note.set_priority(Gio.NotificationPriority.LOW)
        self.app.send_notification("signal", note)
        if self.withdraw:
            GLib.source_remove(self.withdraw)

        def gone():
            self.withdraw = None
            self.app.withdraw_notification("signal")
            return False
        # About the moment: not left in the list for later.
        self.withdraw = GLib.timeout_add_seconds(60, gone)
