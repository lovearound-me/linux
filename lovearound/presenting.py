"""The screen is likely being shown to others: something is full screen (a
slideshow, a shared window, a video), a display is mirrored (a projector, a
TV), or, on GNOME, the screen is being shared or recorded. The glow can't be
left out of screen sharing on Linux, and a glow in the middle of a talk is a
distraction all the same.

How it is known differs by desktop:
- GNOME Shell: our extension answers (full screen on any monitor, a screen
  cast or remote desktop session), mirroring comes from Mutter's DisplayConfig.
- KDE Plasma: a tiny KWin script reports the active window's full screen state;
  screen sharing there is not visible to apps.
- X11: the active window covers a whole monitor.
- Sway and the rest on Wayland: only mirroring.
"""
import os

from gi.repository import Gdk, Gio, GLib

from .overlay import ShellExtension, is_wayland

KWIN_IFACE = """
<node>
  <interface name="me.lovearound.KWin">
    <method name="SetFullScreen"><arg type="b" direction="in" name="full"/></method>
  </interface>
</node>"""
KWIN_SCRIPT = "lovearound-fullscreen"


def kwin_script_path():
    # Beside the package, in a checkout and in an install alike.
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kwin", "fullscreen.js")
    return path if os.path.exists(path) else None


class Presenting:
    def __init__(self, shell=None):
        self.shell = shell or ShellExtension()
        self.kwin_fullscreen = False
        self.kwin_loaded = False
        self.bus = None
        self.registration = None

    # ---- KDE ------------------------------------------------------------------

    def start_kwin(self, connection, object_path_base="/me/lovearound/LoveAround"):
        """Exports SetFullScreen and loads the script, if KWin is there."""
        if "KDE" not in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
            return
        path = kwin_script_path()
        if path is None or connection is None:
            return
        self.bus = connection
        info = Gio.DBusNodeInfo.new_for_xml(KWIN_IFACE)
        try:
            self.registration = connection.register_object(object_path_base + "/KWin", info.interfaces[0],
                                                           self._kwin_call, None, None)
        except GLib.Error:
            return
        try:
            self._scripting("unloadScript", GLib.Variant("(s)", (KWIN_SCRIPT,)))
            self._scripting("loadScript", GLib.Variant("(ss)", (path, KWIN_SCRIPT)))
            self._scripting("start", None)
            self.kwin_loaded = True
        except GLib.Error:
            pass

    def _scripting(self, method, args):
        return self.bus.call_sync("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", method, args,
                                  None, Gio.DBusCallFlags.NO_AUTO_START, 2000, None)

    def _kwin_call(self, connection, sender, path, iface, method, params, invocation):
        if method == "SetFullScreen":
            self.kwin_fullscreen = params.unpack()[0]
        invocation.return_value(None)

    def stop(self):
        if self.kwin_loaded:
            try:
                self._scripting("unloadScript", GLib.Variant("(s)", (KWIN_SCRIPT,)))
            except GLib.Error:
                pass
            self.kwin_loaded = False

    # ---- all ------------------------------------------------------------------

    def now(self):
        return self.mirrored() or self.fullscreen() or (self.shell.version() > 0 and self.shell.presenting())

    def fullscreen(self):
        if self.kwin_loaded:
            return self.kwin_fullscreen
        if is_wayland():
            return False
        return x11_active_fullscreen()

    def mirrored(self):
        return mutter_mirrored() or same_geometry_monitors()


def same_geometry_monitors():
    """Two outputs showing the same area: one mirrors the other."""
    display = Gdk.Display.get_default()
    if display is None:
        return False
    seen = set()
    for i in range(display.get_n_monitors()):
        g = display.get_monitor(i).get_geometry()
        key = (g.x, g.y, g.width, g.height)
        if key in seen:
            return True
        seen.add(key)
    return False


def mutter_mirrored():
    """GNOME shows mirrored monitors as one logical monitor with several monitors in it."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        state = bus.call_sync("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
                              "org.gnome.Mutter.DisplayConfig", "GetCurrentState", None, None,
                              Gio.DBusCallFlags.NO_AUTO_START, 500, None)
    except GLib.Error:
        return False
    _, _, logical, _ = state.unpack()
    return any(len(entry[5]) > 1 for entry in logical)


def x11_active_fullscreen():
    """The active window covers a whole monitor (a maximized one leaves the panel out)."""
    screen = Gdk.Screen.get_default()
    display = Gdk.Display.get_default()
    if screen is None or display is None:
        return False
    try:
        window = screen.get_active_window()
    except Exception:  # noqa: BLE001 - not supported by this window manager
        return False
    if window is None:
        return False
    frame = window.get_frame_extents()
    for i in range(display.get_n_monitors()):
        g = display.get_monitor(i).get_geometry()
        if (frame.x, frame.y, frame.width, frame.height) == (g.x, g.y, g.width, g.height):
            return True
    return False
