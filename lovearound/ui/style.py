"""The windows' look: warm paper and brown ink, at night dark cocoa and cream,
following the desktop's light or dark style (the portal's color-scheme)."""
from gi.repository import Gdk, Gio, GLib, Gtk

from .. import palette

BASE = """
.la, .la.background { background-color: @paper; color: @ink; }
.la.popup { border: 1px solid @hairline; }
.la * { outline-color: alpha(@heart, 0.5); }
.la label { color: inherit; }
.la .title { font-size: 15px; font-weight: 600; }
.la .big { font-size: 17px; font-weight: 700; }
.la .muted { color: @muted; }
.la .faint { color: @faint; }
.la .danger { color: @danger; }
.la .ok { color: @ok; }
.la .link { color: @link; }
.la .small { font-size: 12px; }
.la .note { font-size: 11.5px; color: @faint; }
.la .caption { font-size: 12px; font-weight: 600; color: @muted; }
.la .caption-strong { font-size: 12.5px; font-weight: 600; }
.la .strong { font-size: 12.5px; font-weight: 600; }
.la .name { font-size: 14.5px; font-weight: 500; }
.la .card, .la .banner { background-color: @field; border-radius: 10px; }
.la .banner { padding: 9px 10px; }
.la separator { background-color: @hairline; min-height: 1px; }

.la button {
  background-color: transparent; background-image: none; border: none; box-shadow: none;
  text-shadow: none; -gtk-icon-shadow: none; color: @ink; border-radius: 9px; padding: 0;
  min-height: 0; min-width: 0;
}
.la button.primary { background-color: @ink; color: @paper; min-height: 40px; border-radius: 10px; font-size: 14px; font-weight: 600; padding: 0 14px; }
.la button.primary label { color: @paper; }
.la button.primary:hover { background-color: alpha(@ink, 0.9); }
.la button.primary:active { background-color: alpha(@ink, 0.85); }
.la button.primary:disabled { background-color: alpha(@ink, 0.45); }
.la button.secondary { background-color: @paper; border: 1px solid @hairline; min-height: 40px; border-radius: 10px;
  font-size: 14px; font-weight: 600; padding: 0 14px; }
.la button.secondary:hover, .la button.secondary:active { background-color: @field; }
.la button.small-button { background-color: @paper; border: 1px solid @hairline; min-height: 32px; border-radius: 8px;
  padding: 0 12px; font-size: 12.5px; }
.la button.small-button:hover, .la button.small-button:active { background-color: @field; }
.la button.pill { background-color: @field; border-radius: 999px; min-height: 26px; padding: 0 12px; font-size: 12.5px; font-weight: 500; }
.la button.pill.danger { background-color: @danger; }
.la button.pill.danger label { color: @paper; }
.la button.textlink { color: @link; padding: 0 2px; }
.la button.textlink label { color: @link; }
.la button.textlink.danger label { color: @danger; }
.la button.textlink.muted label { color: @muted; }
.la button.icon { min-width: 28px; min-height: 28px; border-radius: 8px; color: @muted; }
.la button.icon:hover { background-color: @field; }
.la button.play { background-color: @heartSoft; color: @heartDeep; min-height: 36px; border-radius: 9px; font-weight: 600; font-size: 13.5px; }
.la button.play label { color: @heartDeep; }
.la button.invite { background-color: @field; border-radius: 10px; padding: 8px 10px; }
.la button.invite:hover { background-color: mix(@field, @link, 0.06); }

.la entry {
  background-color: @input; background-image: none; color: @ink; border: 1px solid @hairline;
  border-radius: 8px; min-height: 32px; box-shadow: none; padding: 0 8px;
}
.la entry:focus { border-color: alpha(@heart, 0.7); }
.la entry.name { font-size: 22px; font-weight: 700; border: none; border-bottom: 1px solid @hairline;
  border-radius: 0; background-color: transparent; padding: 0; }
.la entry.name:focus { border-bottom: 2px solid @heart; }

.la button.row { min-height: 42px; border-radius: 11px; padding: 0 10px; }
.la button.bare { padding: 0; }

.la list, .la list row { background-color: transparent; }
.la list row { border-radius: 8px; padding: 3px 8px; }
.la list row:selected { background-color: @heartSoft; }
.la list row:selected label { color: @heartDeep; }
.la list row.heading, .la list row.heading:hover { background-color: transparent; }
.la .near { color: @heartDeep; font-weight: 600; font-size: 12px; }

.la stackswitcher button { background-color: @well; border-radius: 0; min-height: 30px; padding: 0 14px; font-size: 12.5px; }
.la stackswitcher button:first-child { border-radius: 8px 0 0 8px; }
.la stackswitcher button:last-child { border-radius: 0 8px 8px 0; }
.la stackswitcher button:checked { background-color: @raised; font-weight: 600; }
.la scale trough { background-color: @well; min-height: 4px; border-radius: 3px; }
.la scale highlight { background-color: @heart; border-radius: 3px; }
.la scale slider { background-color: #ffffff; background-image: none; border: 1px solid @hairline; min-width: 16px; min-height: 16px; border-radius: 999px; }
.la switch { background-color: @well; border: none; background-image: none; }
.la switch:checked { background-color: #3FA05A; }
.la switch slider { background-color: #ffffff; background-image: none; border: none; }
.la .switchrow { padding: 4px 12px; }
.la .anyone-card { background-color: @anyone2; border-radius: 10px; }
.la .tokenbox { background-color: @input; border: 1px solid @hairline; border-radius: 8px; }
.la .token { font-family: monospace; font-size: 12px; }
.la .device { padding: 0 6px 0 10px; }
"""


def _hex(value):
    return palette.css_hex(value)


def css(dark):
    lines = ["@define-color %s %s;" % (name, _hex(palette.ui(name, dark))) for name in palette.UI]
    lines.append("@define-color hairline %s;" % ("rgba(255,235,220,0.16)" if dark else "rgba(84,48,30,0.22)"))
    for i, color in enumerate(palette.ALL):
        tint, deep = _hex(palette.tint(color, dark)), _hex(palette.deep(color, dark))
        lines.append(f"""
.la button.row.c{i}:hover {{ background-color: alpha({tint}, 0.6); }}
.la button.row.c{i}.sent {{ background-color: {tint}; }}
.la .deep.c{i} {{ color: {deep}; }}
""")
    return "\n".join(lines) + BASE


class Theme:
    """Light or dark, and the CSS for it on the default screen."""

    def __init__(self):
        self.dark = False
        self.provider = Gtk.CssProvider()
        self.listeners = []
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.portal = None
        try:
            self.portal = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None, "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop", "org.freedesktop.portal.Settings", None)
            self.portal.connect("g-signal", self._portal_signal)
            value = self.portal.call_sync("Read", GLib.Variant("(ss)", ("org.freedesktop.appearance", "color-scheme")),
                                          Gio.DBusCallFlags.NONE, 1000, None)
            self.dark = _unwrap(value.unpack()[0]) == 1
        except GLib.Error:
            self.dark = self._theme_dark()
        self.apply()

    @staticmethod
    def _theme_dark():
        settings = Gtk.Settings.get_default()
        return bool(settings.props.gtk_application_prefer_dark_theme) or \
            (settings.props.gtk_theme_name or "").lower().endswith("-dark")

    def _portal_signal(self, proxy, sender, signal, params):
        if signal != "SettingChanged":
            return
        namespace, key, value = params.unpack()
        if namespace == "org.freedesktop.appearance" and key == "color-scheme":
            self.dark = _unwrap(value) == 1
            self.apply()

    def apply(self):
        self.provider.load_from_data(css(self.dark).encode())
        Gtk.Settings.get_default().props.gtk_application_prefer_dark_theme = self.dark
        for listener in self.listeners:
            listener()


def _unwrap(value):
    while isinstance(value, GLib.Variant):
        value = value.unpack()
    return value


# The one Theme of the app, made by setup() once there is a screen.
current = None


def setup():
    global current
    if current is None:
        current = Theme()
    return current


def dark():
    return bool(current and current.dark)


def color(name):
    """A UI color of the current style, as cairo's 0–1 floats."""
    return palette.rgb(palette.ui(name, dark()))
