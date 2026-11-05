"""The app: one instance per session (a second launch, or a lovearound:// link,
goes to the running one), a heart in the tray, and the windows behind it."""
import sys

from gi.repository import Gio, GLib, Gtk

from . import config, i18n, overlay, system
from .i18n import tr
from .model import AppModel
from .presenting import Presenting
from .tray import Tray

# How long a tray may take to show up after login before the popup is shown instead.
TRAY_GRACE_SECONDS = 4


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=config.APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.model = None
        self.popup = None
        self.book = None
        self.settings_window = None
        self.tray = None
        self.has_tray = None
        self.pending_restart = None
        self.add_main_option("background", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             tr("Только значок в трее, без окна"), None)
        self.add_main_option("quit", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, tr("Закрыть приложение"), None)
        self.add_main_option("show-signal", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             tr("Показать, как выглядит сигнал"), None)
        self.add_main_option("settings", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, tr("Открыть настройки"), None)

    # ---- start ----------------------------------------------------------------

    def do_startup(self):
        Gtk.Application.do_startup(self)
        from .ui import style
        from .ui.popup import Popup
        style.setup()
        # Runs with no window open.
        self.hold()

        self.system = system.System()
        self.model = model = AppModel()
        i18n.set_language(model.get("language"))
        self.overlay = overlay.Overlay(self)
        self.presenting = Presenting(self.overlay.shell)
        model.overlay = self.overlay
        model.presenting = self.presenting.now
        model.reduce_motion = self.system.reduce_motion
        model.play_sound = self.system.play_sound
        model.open_uri = self.system.open_uri
        model.clipboard_text = self.system.clipboard_text
        model.set_clipboard = self.system.set_clipboard

        self.popup = Popup(self, model)
        model.connect("show-menu", lambda _: self.popup.show_at(fresh=False))
        model.connect("open-book", lambda _, id_: self.show_book(id_ or None))
        model.connect("open-settings", lambda _: self.show_settings())
        model.connect("signed-out", lambda _: self._signed_out())
        model.connect("log-out", lambda _: self.system.log_out())
        log_out = Gio.SimpleAction.new("log-out", None)
        log_out.connect("activate", lambda *_: self.system.log_out())
        self.add_action(log_out)

        connection = self.get_dbus_connection()
        if connection is not None:
            self.tray = Tray(model, {
                "toggle": self.popup.toggle,
                "popup": lambda: self.popup.show_at(),
                "book": lambda: self.show_book(None),
                "settings": self.show_settings,
                "add": self.show_add,
                "updates": self.check_updates,
                "quit": self.quit_app,
            })
            self.tray.on_watcher = self._tray_changed
            self.overlay.on_fallback = self.tray.flash
            self.tray.start(connection)
            self.presenting.start_kwin(connection)

        self.system.on_wake(model.stream.restart)
        self._install_monitor = self.system.watch_install(self._new_version)

        # The first launch puts the app into autostart, like the Mac app's login
        # item; remembered only once the file is there (a home the user couldn't
        # write to used to swallow it), so turned off later by hand it stays off.
        if not model.get("autostartAdded") and self.system.set_autostart(True):
            model.set("autostartAdded", True)
        # And on GNOME the Shell extension that draws the glow, at every start
        # unless the user turned it off in Extensions (disabled-extensions).
        if overlay.is_gnome_shell() and self.system.enable_extension_at_login(system.EXTENSION):
            self.system.enable_extension(system.EXTENSION)
            self._check_relogin()
        model.start()

    def _check_relogin(self):
        """Installed after this login, the extension stays unknown to GNOME
        Shell until the next one: say so on the popup, and once in a
        notification, both with a way to log out."""
        model = self.model
        model.needs_relogin = (self.system.extension_installed(system.EXTENSION)
                               and self.system.extension_state(system.EXTENSION) is None)
        if model.needs_relogin and not model.get("reloginNoticeShown"):
            note = Gio.Notification.new(tr("Свечение включится после нового входа"))
            from .ui.popup import RELOGIN_TEXT
            note.set_body(tr(RELOGIN_TEXT))
            note.add_button(tr("Выйти из системы"), "app.log-out")
            self.send_notification("relogin", note)
            model.set("reloginNoticeShown", True)
        model.changed()

    def _tray_changed(self, present):
        self.has_tray = present
        if self.settings_window:
            self.settings_window.refresh()

    def do_command_line(self, command_line):
        options = command_line.get_options_dict().end().unpack()
        args = command_line.get_arguments()[1:]
        if options.get("quit"):
            self.quit_app()
            return 0
        links = [a for a in args if config.is_link(a)]
        for link in links:
            self.model.handle(link)
        if options.get("settings"):
            self.show_settings()
        elif options.get("show-signal"):
            self.model.play_effect()
        elif not links and not options.get("background"):
            # Opened by hand from the app list: the menu, wherever the tray is.
            self.popup.show_at()
        elif options.get("background") and not command_line.get_is_remote():
            # Started at login: the window only if there is nothing else to click.
            GLib.timeout_add_seconds(TRAY_GRACE_SECONDS, self._no_tray_check)
        return 0

    def _no_tray_check(self):
        if not self.has_tray and not self.model.signed_in:
            self.popup.show_at()
        return False

    # ---- windows ----------------------------------------------------------------

    def _signed_out(self):
        for window in (self.book, self.settings_window):
            if window:
                window.hide()
        self.popup.show_at()

    def show_book(self, contact_id=None):
        from .ui.book import BookWindow
        self.popup.hide()
        if self.book is None:
            self.book = BookWindow(self, self.model)
            self.book.show_all()
        self.book.open(contact_id)

    def show_settings(self):
        from .ui.settings import SettingsWindow
        self.popup.hide()
        if self.settings_window is None:
            self.settings_window = SettingsWindow(self, self.model, self.system, self.notes)
        self.settings_window.open()

    def set_language(self, code):
        """Every window and menu in the new language: the app starts again, back in Settings."""
        if code == self.model.get("language"):
            return
        self.model.set("language", code)
        self.system.restart("--settings")

    def show_add(self):
        if not self.model.signed_in:
            self.popup.show_at()
            return
        self.model.route = ("add", None)
        self.model.changed()
        self.popup.show_at(fresh=False)

    def check_updates(self):
        if not self.system.check_updates():
            self.system.open_uri(config.SITE)

    def quit_app(self):
        if self.presenting:
            self.presenting.stop()
        self.release()
        self.quit()

    # ---- what this desktop can't do -------------------------------------------------

    def notes(self):
        """For Settings → Сигнал: (text, button title, action)."""
        out = []
        kind = self.overlay.kind()
        gnome = overlay.is_gnome_shell()
        if kind == "notify":
            if gnome:
                state = self.system.extension_state(system.EXTENSION)
                if state is None:
                    out.append((tr("Свечение по краям экрана в GNOME рисует расширение Love Around. GNOME увидит его "
                                "после нового входа в систему, а пока сигнал приходит уведомлением."),
                                tr("Выйти из системы"), self.system.log_out))
                else:
                    out.append((tr("Свечение по краям экрана в GNOME рисует расширение Love Around, а оно выключено. "
                                "Пока сигнал приходит уведомлением."), tr("Включить"),
                                lambda: self.system.enable_extension(system.EXTENSION, self._refresh_settings)))
            elif overlay.is_wayland():
                out.append((tr("Этот рабочий стол не даёт рисовать поверх всех окон (нет wlr-layer-shell), "
                            "поэтому сигнал приходит уведомлением."), None, None))
            else:
                out.append((tr("Без композитора прозрачное свечение не нарисовать, поэтому сигнал приходит "
                            "уведомлением."), None, None))
        if self.has_tray is False or (self.has_tray is None and self.tray and not self.tray.watcher_seen):
            if gnome:
                state = self.system.extension_state(system.APPINDICATOR)
                if state is not None and state != system.ENABLED:
                    out.append((tr("Сердечко в верхней панели GNOME показывает расширение AppIndicator, а оно "
                                "выключено."), tr("Включить"),
                                lambda: self.system.enable_extension(system.APPINDICATOR, self._refresh_settings)))
                else:
                    out.append((tr("В GNOME значок в панели появляется с расширением AppIndicator "
                                "(пакет gnome-shell-extension-appindicator). Без него открывай Love Around "
                                "из списка приложений."), None, None))
            else:
                out.append((tr("Трея на этом рабочем столе нет: открывай Love Around из списка приложений."), None, None))
        return out

    def _refresh_settings(self):
        if self.settings_window:
            self.settings_window.refresh()

    # ---- updates ----------------------------------------------------------------------

    def _new_version(self, version):
        """apt put a new version in place: switch to it when nobody is looking."""
        if self.pending_restart:
            return

        def when_idle():
            busy = any(window.get_visible() for window in (self.popup, self.book, self.settings_window) if window)
            if busy:
                return True
            self.pending_restart = None
            self.presenting.stop()
            system.System.restart()
            return False
        self.pending_restart = GLib.timeout_add_seconds(5, when_idle)


def main(argv=None):
    app = App()
    return app.run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
