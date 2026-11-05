"""What the desktop gives: autostart, links, the clipboard, a sound, sleep,
the extensions of GNOME Shell, and the package manager for updates."""
import os
import shutil
import subprocess
import sys

from gi.repository import Gdk, Gio, GLib, Gtk

from . import config

try:
    import gi
    gi.require_version("GSound", "1.0")
    from gi.repository import GSound
except (ImportError, ValueError):
    GSound = None

EXTENSION = "lovearound@lovearound.me"
OLD_EXTENSIONS = ("love-around@lovearound.me",)
APPINDICATOR = "ubuntu-appindicators@ubuntu.com"
# org.gnome.Shell.Extensions' ExtensionState.
ENABLED = 1


def autostart_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", config.APP_ID + ".desktop")


AUTOSTART = """[Desktop Entry]
Type=Application
Name=Love Around
Comment=A signal from those who think of you
Exec=lovearound --background
Icon=me.lovearound.LoveAround
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=3
NoDisplay=true
"""


class System:
    def __init__(self):
        self.sound = None
        if GSound is not None:
            try:
                self.sound = GSound.Context()
                self.sound.init()
            except GLib.Error:
                self.sound = None
        self.bus = None
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error:
            pass

    # ---- autostart --------------------------------------------------------------

    def autostart_enabled(self):
        try:
            keyfile = GLib.KeyFile()
            keyfile.load_from_file(autostart_path(), GLib.KeyFileFlags.NONE)
        except GLib.Error:
            return False
        for key in ("Hidden",):
            try:
                if keyfile.get_boolean("Desktop Entry", key):
                    return False
            except GLib.Error:
                pass
        try:
            return keyfile.get_boolean("Desktop Entry", "X-GNOME-Autostart-enabled")
        except GLib.Error:
            return True

    def set_autostart(self, on):
        """True when done."""
        path = autostart_path()
        try:
            if on:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(AUTOSTART)
            elif os.path.exists(path):
                os.remove(path)
            return True
        except OSError as error:
            print(f"lovearound: autostart: {error}", file=sys.stderr)
            return False

    # ---- small things -------------------------------------------------------------

    def open_uri(self, uri):
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except GLib.Error:
            subprocess.Popen(["xdg-open", uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def clipboard_text(self):
        """What is on the clipboard now; Wayland gives it only to a focused window, else None."""
        try:
            return Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
        except Exception:  # noqa: BLE001
            return None

    def set_clipboard(self, text):
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, -1)
        clipboard.store()

    def play_sound(self):
        if self.sound is None:
            return
        try:
            self.sound.play_simple({GSound.ATTR_EVENT_ID: "message-new-instant",
                                    GSound.ATTR_EVENT_DESCRIPTION: "Love Around"}, None)
        except GLib.Error:
            pass

    @staticmethod
    def reduce_motion():
        """GNOME's "Анимация" off (and KDE's animation speed at instant) reach GTK as this."""
        settings = Gtk.Settings.get_default()
        return settings is not None and not settings.props.gtk_enable_animations

    # ---- sleep ----------------------------------------------------------------------

    def on_wake(self, callback):
        """After sleep the socket is dead but may look alive for a minute: reconnect at once."""
        try:
            system = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error:
            return

        def signal(connection, sender, path, iface, name, params):
            if not params.unpack()[0]:
                callback()
        system.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Manager", "PrepareForSleep",
                                "/org/freedesktop/login1", None, Gio.DBusSignalFlags.NONE, signal)
        self._system = system

    # ---- GNOME Shell extensions -------------------------------------------------------

    def extension_state(self, uuid):
        """None when the Shell doesn't know the extension (not installed, or installed
        after this login), else its ExtensionState."""
        if self.bus is None:
            return None
        try:
            reply = self.bus.call_sync("org.gnome.Shell.Extensions", "/org/gnome/Shell/Extensions",
                                       "org.gnome.Shell.Extensions", "GetExtensionInfo",
                                       GLib.Variant("(s)", (uuid,)), GLib.VariantType("(a{sv})"),
                                       Gio.DBusCallFlags.NO_AUTO_START, 1000, None)
        except GLib.Error:
            return None
        info = reply.unpack()[0]
        return int(info["state"]) if "state" in info else None

    @staticmethod
    def extension_installed(uuid):
        """On disk, where GNOME Shell looks at login (the package puts ours in /usr/share)."""
        dirs = [GLib.get_user_data_dir()] + list(GLib.get_system_data_dirs())
        return any(os.path.isfile(os.path.join(d, "gnome-shell", "extensions", uuid, "metadata.json")) for d in dirs)

    def log_out(self):
        """GNOME's own "Log out?" dialog: the user confirms there (or cancels)."""
        if self.bus is not None:
            def finished(bus, result):
                try:
                    bus.call_finish(result)
                except GLib.Error:
                    self._log_out_command()
            # Mode 0: with the confirmation dialog.
            self.bus.call("org.gnome.SessionManager", "/org/gnome/SessionManager", "org.gnome.SessionManager",
                          "Logout", GLib.Variant("(u)", (0,)), None, Gio.DBusCallFlags.NONE, -1, None, finished)
        else:
            self._log_out_command()

    @staticmethod
    def _log_out_command():
        if shutil.which("gnome-session-quit"):
            subprocess.Popen(["gnome-session-quit", "--logout"], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def enable_extension(self, uuid, done=None):
        if self.bus is None:
            return

        def finished(bus, result):
            try:
                bus.call_finish(result)
            except GLib.Error:
                pass
            if done:
                GLib.timeout_add(600, lambda: done() and False)
        self.bus.call("org.gnome.Shell.Extensions", "/org/gnome/Shell/Extensions", "org.gnome.Shell.Extensions",
                      "EnableExtension", GLib.Variant("(s)", (uuid,)), None, Gio.DBusCallFlags.NONE, 5000, None,
                      finished)

    @staticmethod
    def enable_extension_at_login(uuid):
        """Into the Shell's list of enabled extensions: one installed after this login
        is unknown to the Shell (and EnableExtension refuses it) until the next one.
        Left alone when the user turned it off in Extensions (it is then in
        disabled-extensions). True when it is on the list."""
        source = Gio.SettingsSchemaSource.get_default()
        if source is None or source.lookup("org.gnome.shell", True) is None:
            return False
        shell = Gio.Settings.new("org.gnome.shell")
        enabled = shell.get_strv("enabled-extensions")
        # The extension's name before 0.1.82.
        stale = [u for u in enabled if u in OLD_EXTENSIONS]
        if stale:
            enabled = [u for u in enabled if u not in stale]
            shell.set_strv("enabled-extensions", enabled)
        if uuid in shell.get_strv("disabled-extensions"):
            return False
        if uuid not in enabled:
            shell.set_strv("enabled-extensions", enabled + [uuid])
        # dconf writes in the background; a failed write (a home the user can't
        # write to) is undone by then.
        Gio.Settings.sync()
        return uuid in shell.get_strv("enabled-extensions")

    # ---- updates ------------------------------------------------------------------------

    @staticmethod
    def check_updates():
        """The package comes from apt, so the desktop's own updater updates it."""
        for command in (["gnome-software", "--mode=updates"], ["plasma-discover", "--mode", "update"],
                        ["update-manager"], ["software-properties-gtk"]):
            if shutil.which(command[0]):
                subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                return True
        return False

    @staticmethod
    def watch_install(on_new_version):
        """apt replaced the files of this running app: `on_new_version(version)` once."""
        monitor = Gio.File.new_for_path(config.VERSION_FILE).monitor_file(Gio.FileMonitorFlags.NONE, None)

        def changed(monitor, file, other, event):
            if event not in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED,
                             Gio.FileMonitorEvent.MOVED_IN, Gio.FileMonitorEvent.RENAMED):
                return
            version = config.read_version()
            if version not in (config.VERSION, "dev"):
                on_new_version(version)
        monitor.connect("changed", changed)
        return monitor

    @staticmethod
    def restart(*extra):
        """The new version in this process's place, quietly in the tray."""
        args = [a for a in sys.argv[1:] if a not in ("--background", "--settings") and not config.is_link(a)]
        args += list(extra)
        start = ["-m", "lovearound"] if sys.argv[0].endswith("__main__.py") else [sys.argv[0]]
        os.execv(sys.executable, [sys.executable] + start + ["--background"] + args)
