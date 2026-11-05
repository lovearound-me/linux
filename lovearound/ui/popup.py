"""The window behind the heart: «О ком ты сейчас думаешь?», the circles, the
recent people and the Love ID; sign-in before that; adding someone by a link.

Where it opens: on KDE and wlroots a layer-shell surface next to the tray
(the click's coordinates come with Activate); on GNOME's Wayland a plain
undecorated window wherever the shell puts it (the Love Around extension, if
on, moves it under the top bar); on X11 a window moved to the click. It hides
on Escape and when it loses focus, like a menu."""
import time

import cairo
from gi.repository import Gdk, GLib, Gtk

from .. import model as m
from .. import overlay
from . import forms, style
from ..i18n import N_, tr
from . import widgets as w

try:
    import gi
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell
except (ImportError, ValueError):
    GtkLayerShell = None

WIDTH = 330
DRAG_TARGET = "application/x-lovearound-contact"
# The banner, and the body of the notification that says it once.
# Translated when shown (tr), as the language can change while the app runs.
RELOGIN_BANNER = N_("Свечение по краям экрана включится после нового входа в систему. Пока сигналы приходят уведомлением.")
RELOGIN_TEXT = N_("Чтобы сигналы светились по краям экрана, выйди из системы и войди снова. "
                  "Это нужно один раз после установки.")
SHARE_MESSAGE = N_("Добавь меня по этой ссылке и нажимай сердечко, когда думаешь обо мне ♥")


class MainView(Gtk.Box):
    def __init__(self, model):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.model = model
        self.hovered = None
        self.signature = None
        self.circles = {}
        self.anyone = None
        self.dragging = None

        header = Gtk.Box(spacing=2)
        header.pack_start(w.label(tr("О ком ты сейчас думаешь?"), "title"), False, False, 0)
        header.pack_end(w.icon_button("emblem-system-symbolic", tr("Настройки"),
                                      lambda: model.emit("open-settings")), False, False, 0)
        header.pack_end(w.icon_button("x-office-address-book-symbolic", tr("Книга"),
                                      lambda: model.emit("open-book", "")), False, False, 0)
        self.pack_start(header, False, False, 0)

        self.banners = w.vbox(6)
        self.pack_start(self.banners, False, False, 0)

        self.grid = Gtk.Grid(column_spacing=5, row_spacing=4, halign=Gtk.Align.CENTER)
        self.grid.set_margin_top(4)
        self.pack_start(self.grid, False, False, 0)
        self.caption = w.label(" ", xalign=0.5, ellipsize=True)
        self.caption.set_size_request(-1, 18)
        self.pack_start(self.caption, False, False, 0)

        self.empty = w.vbox(6, w.label(tr("Пока никого нет"), "title", xalign=0.5))
        hint = w.label(tr("Добавь людей по их ссылке или отправь им свой Love ID, чтобы они могли поддерживать тебя."),
                       "muted", wrap=True, xalign=0.5, width_chars=36)
        hint.set_justify(Gtk.Justification.CENTER)
        self.empty.pack_start(hint, False, False, 0)
        self.share = w.button(tr("Поделиться своим Love ID"), "primary", action=self._share)
        self.share.set_tooltip_text(tr("Скопирует ссылку с приглашением, чтобы вставить в чат"))
        self.empty.pack_start(self.share, False, False, 6)
        self.pack_start(self.empty, False, False, 0)

        self.search = w.search_entry("")
        self.search.connect("search-changed", lambda _: self._fill_list())
        self.pack_start(self.search, False, False, 0)
        self.list = w.vbox(2)
        self.pack_start(self.list, False, False, 0)

        self.separator = Gtk.Separator()
        self.separator.set_margin_top(2)
        self.separator.set_margin_bottom(2)
        self.pack_start(self.separator, False, False, 0)
        self.invite = w.vbox()
        self.pack_start(self.invite, False, False, 0)
        self.invite_url = None

        self.problem = w.label("", "danger", "small", wrap=True, width_chars=36)
        self.pack_start(self.problem, False, False, 0)
        for widget in (self.empty, self.search, self.list, self.separator, self.problem):
            widget.set_no_show_all(True)

    # ---- the pieces

    def refresh(self):
        model = self.model
        w.clear(self.banners)
        if model.offline:
            self.banners.pack_start(w.banner("network-offline-symbolic",
                                             tr("Нет связи с сервером, сигналы сейчас не приходят. Переподключаемся…")),
                                    False, False, 0)
        if model.needs_relogin:
            self.banners.pack_start(w.banner("system-log-out-symbolic", tr(RELOGIN_BANNER),
                                             w.button(tr("Выйти из системы"), "textlink",
                                                      action=lambda: model.emit("log-out"))), False, False, 0)
        if model.is_paused:
            self.banners.pack_start(w.banner("weather-clear-night-symbolic", tr("{pause}. Сигналы не придут.", pause=model.pause_text()),
                                             w.button(tr("Снять"), "textlink", action=model.resume)), False, False, 0)
        self.banners.show_all()

        self._fill_circles()
        self.tick()

        empty = not model.contacts
        self.empty.set_visible(empty)
        self.empty.show_all() if empty else None
        self.share.set_visible(empty and bool(model.invite_url))
        self.search.set_visible(not empty)
        self.search.set_placeholder_text(tr("Найти — {people}", people=m.people_count(len(model.contacts))))
        self._fill_list()

        self.separator.set_visible(not empty)
        if model.invite_url != self.invite_url or empty == bool(self.invite.get_children()):
            self.invite_url = model.invite_url
            w.clear(self.invite)
            if model.invite_url and not empty:
                self.invite.pack_start(w.InviteRow(model), False, False, 0)
                self.invite.show_all()
        self.problem.set_text(model.problem or "")
        self.problem.set_visible(bool(model.problem))

    def _fill_circles(self):
        model = self.model
        close = model.close_contacts
        signature = ([(c.id, c.label, model.color_index(c)) for c in close], bool(model.contacts), style.dark())
        if signature != self.signature:
            self.signature = signature
            w.clear(self.grid)
            self.circles = {}
            self.anyone = w.AnyoneCircle(50)
            cells = [w.circle_button(self.anyone, "", model.send_to_anyone)]
            self._hover(cells[0], m.ANYONE_ID)
            for contact in close:
                circle = w.Circle(50, contact.label, model.color_for(contact), filled=True)
                self.circles[contact.id] = circle
                button = w.circle_button(circle, contact.label, lambda c=contact: self._send(c))
                self._hover(button, contact.id)
                self._draggable(button, circle, contact)
                cells.append(button)
            plus = w.Circle(50)
            plus.dashed = True
            title = tr("Добавить по ссылке") if not model.contacts else tr("Добавить кружок")
            cells.append(w.circle_button(plus, title, self._plus))
            for index, cell in enumerate(cells):
                self.grid.attach(cell, index % 5, index // 5, 1, 1)
            self.grid.show_all()
        for id_, circle in self.circles.items():
            circle.update(sent=model.sent == id_)

    def _send(self, contact):
        # The contact may have changed under an old button.
        current = self.model.contact(contact.id)
        if current:
            self.model.send(current)

    def _plus(self):
        if self.model.contacts:
            self.model.emit("open-book", "")
        else:
            self.model.route = ("add", None)
            self.model.changed()

    def _hover(self, button, id_):
        def enter(*_):
            self.hovered = id_
            self.tick()

        def leave(*_):
            if self.hovered == id_:
                self.hovered = None
                self.tick()
        button.connect("enter-notify-event", enter)
        button.connect("leave-notify-event", leave)

    def _draggable(self, button, circle, contact):
        """A drag puts a circle elsewhere; the others shift."""
        target = [Gtk.TargetEntry.new(DRAG_TARGET, Gtk.TargetFlags.SAME_APP, 0)]
        button.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, target, Gdk.DragAction.MOVE)
        button.drag_dest_set(Gtk.DestDefaults.ALL, target, Gdk.DragAction.MOVE)

        def begin(widget, context):
            self.dragging = contact.id
            size = circle.size + 6
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
            cr = cairo.Context(surface)
            circle._draw(circle, cr)
            surface.set_device_offset(-size / 2, -size / 2)
            Gtk.drag_set_icon_surface(context, surface)

        def get(widget, context, data, info, time_):
            data.set(data.get_target(), 8, contact.id.encode())

        def received(widget, context, x, y, data, info, time_):
            dragged = self.model.contact(data.get_data().decode())
            target_contact = self.model.contact(contact.id)
            if dragged and target_contact:
                self.model.move(dragged, target_contact)

        def end(*_):
            self.dragging = None

        button.connect("drag-begin", begin)
        button.connect("drag-data-get", get)
        button.connect("drag-data-received", received)
        button.connect("drag-end", end)

    def tick(self):
        """The caption under the circles and the ring of the one for anyone."""
        model = self.model
        now = time.time()
        wait = model.anyone_wait(now)
        if self.anyone:
            self.anyone.update(wait=wait, sending=model.anyone_sending)
            parent = self.anyone.get_parent()
            parent.set_tooltip_text(tr("Кому-нибудь на свете: снова через {n} мин", n=wait) if wait else
                                    tr("Кому-нибудь на свете: сигнал уйдёт случайному человеку, раз в час. Он не узнает, от кого."))
        just = model.anyone_just_sent(now)
        close = model.close_contacts
        focus_id = model.sent or self.hovered
        focus = next((c for c in close if c.id == focus_id), None)
        if self.hovered == m.ANYONE_ID or (self.hovered is None and model.sent is None and just):
            text = tr("Улетело кому-то ♥") if just else \
                tr("Кому-нибудь — через {n} мин", n=wait) if wait else tr("Кому-нибудь на свете")
            names = ("caption-strong", "muted")
        elif focus:
            text = tr("{name} — улетело ♥", name=focus.label) if model.sent == focus.id else focus.label
            names = ("caption-strong", "deep", "c%d" % model.color_index(focus))
        elif not close and model.contacts:
            text, names = tr("Нажми «+», чтобы добавить кружки"), ("caption-strong", "faint")
        else:
            text, names = " ", ("caption-strong",)
        self.caption.set_text(text)
        context = self.caption.get_style_context()
        for name in list(context.list_classes()):
            context.remove_class(name)
        for name in names:
            context.add_class(name)

    def _fill_list(self):
        model = self.model
        w.clear(self.list)
        query = self.search.get_text().strip()
        if query:
            found = model.find(query)
            for contact in found:
                self.list.pack_start(self._row(contact), False, False, 0)
            if not found:
                nobody = w.label(tr("Никого с таким именем"), "muted", xalign=0.5)
                nobody.set_margin_top(14)
                nobody.set_margin_bottom(14)
                self.list.pack_start(nobody, False, False, 0)
        elif model.contacts and model.other_contacts:
            # A short book fits whole; a long one shows the recent few.
            others = model.other_contacts
            shown = others if len(others) <= 5 else others[:4]
            heading = w.caption(tr("Недавние") if len(shown) < len(others) else tr("Остальные"))
            heading.set_margin_start(10)
            heading.set_margin_bottom(2)
            self.list.pack_start(heading, False, False, 0)
            for contact in shown:
                self.list.pack_start(self._row(contact), False, False, 0)
            if len(shown) < len(others):
                book = w.link_row("x-office-address-book-symbolic", tr("Вся книга · {n}", n=len(model.contacts)),
                                  lambda: model.emit("open-book", ""))
                book.set_margin_start(6)
                self.list.pack_start(book, False, False, 0)
        self.list.set_visible(bool(self.list.get_children()))
        self.list.show_all()

    def _row(self, contact):
        """A person in the book: a row with a name, a click sends."""
        model = self.model
        index = model.color_index(contact)
        sent = model.sent == contact.id
        button = w.button("", "row", "c%d" % index, *(("sent",) if sent else ()),
                          action=lambda: self._send(contact))
        button.remove(button.get_child())
        box = Gtk.Box(spacing=12)
        box.pack_start(w.Circle(30, contact.label, model.color_for(contact), ring=2.5), False, False, 0)
        box.pack_start(w.label(contact.label, "name", ellipsize=True), True, True, 0)
        if sent:
            box.pack_end(w.label(tr("Улетело ♥"), "deep", "c%d" % index, "strong"), False, False, 0)
        button.add(box)
        return button

    def _share(self):
        """No share sheet here: the invite with a line of text goes to the clipboard, for a chat."""
        if not self.model.invite_url:
            return
        self.model.set_clipboard(tr(SHARE_MESSAGE) + " " + self.model.invite_url)
        self.share.set_label(tr("Скопировано — вставь в чат"))
        w.later(2000, lambda: self.share.set_label(tr("Поделиться своим Love ID")))

    def reset(self):
        """Each opening starts from an empty search."""
        self.search.set_text("")
        self.hovered = None


class Popup(Gtk.Window):
    def __init__(self, app, model):
        super().__init__(title="Love Around", application=app)
        self.model = model
        self.app = app
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_role("lovearound-popup")
        self.get_style_context().add_class("la")
        self.get_style_context().add_class("popup")
        self.layer = bool(GtkLayerShell and overlay.is_wayland() and GtkLayerShell.is_supported())
        if self.layer:
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_namespace(self, "lovearound-popup")
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
            GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
        elif not overlay.is_wayland():
            self.set_type_hint(Gdk.WindowTypeHint.UTILITY)

        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.root.set_border_width(14)
        self.root.set_size_request(WIDTH, -1)
        self.add(self.root)
        self.kind = None
        self.view = None
        self.was_active = False
        self.shown_at = 0.0
        self.ticker = None

        self.connect("key-press-event", self._key)
        self.connect("notify::is-active", self._active)
        self.connect("delete-event", lambda *_: self.hide() or True)
        model.connect("changed", lambda _: self.refresh())
        self.refresh()

    def _wanted(self):
        if not self.model.signed_in:
            return ("signin",)
        if self.model.route != "main":
            return self.model.route
        return ("main",)

    def refresh(self):
        wanted = self._wanted()
        if wanted != self.kind:
            self.kind = wanted
            if self.view:
                self.view.destroy()
            if wanted[0] == "signin":
                self.view = forms.SignInView(self.model, self.app.quit_app)
            elif wanted[0] == "add":
                self.view = forms.AddForm(self.model, wanted[1], on_back=self._back, on_added=lambda _: self._back())
            else:
                self.view = MainView(self.model)
            self.root.pack_start(self.view, True, True, 0)
            self.view.show_all()
            if hasattr(self.view, "focus") and self.get_visible():
                self.view.focus()
        if hasattr(self.view, "refresh"):
            self.view.refresh()
        # Shrinks back after a long list.
        self.resize(WIDTH, 1)

    def _back(self):
        self.model.route = "main"
        self.model.changed()

    def _key(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            if self.kind and self.kind[0] == "add":
                self._back()
            else:
                self.hide()
            return True
        return False

    def _active(self, *_):
        if self.is_active():
            self.was_active = True
        elif self.was_active and self.get_visible():
            # A menu closes when you click elsewhere; a drag from the window keeps it.
            if isinstance(self.view, MainView) and self.view.dragging:
                return
            # Focus can bounce right after mapping (a window manager settling,
            # focus-follows-mouse): not a click elsewhere.
            if time.monotonic() - self.shown_at < 0.6:
                self.was_active = False
                return
            self.hide()

    def do_hide(self):
        Gtk.Window.do_hide(self)
        self.was_active = False
        if self.ticker:
            GLib.source_remove(self.ticker)
            self.ticker = None

    def toggle(self, x=0, y=0):
        if self.get_visible():
            self.hide()
        else:
            self.show_at(x, y)

    def show_at(self, x=0, y=0, fresh=True):
        """`fresh`: opened by hand, so it starts from the menu unless adding
        someone is half done; a lovearound:// link opens where it led."""
        if self.get_visible():
            self.refresh()
            self.present()
            return
        if fresh:
            if isinstance(self.view, forms.AddForm) and not self.view.half_filled():
                self.model.route = "main"
            if hasattr(self.view, "reset"):
                self.view.reset()
        self.refresh()
        self.root.show_all()
        if self.layer:
            self._place_layer(x, y)
        elif not overlay.is_wayland():
            self._place_x11(x, y)
        self.shown_at = time.monotonic()
        self.show()
        self.present()
        if hasattr(self.view, "focus"):
            self.view.focus()
        self.ticker = GLib.timeout_add_seconds(10, self._tick)

    def _tick(self):
        if isinstance(self.view, MainView):
            self.view.tick()
        return True

    def _place_layer(self, x, y):
        """Next to the tray: the panel's side comes from where the click was."""
        display = Gdk.Display.get_default()
        edge = GtkLayerShell.Edge
        monitor = display.get_monitor_at_point(x, y) if (x or y) else None
        for side in (edge.TOP, edge.BOTTOM, edge.LEFT, edge.RIGHT):
            GtkLayerShell.set_anchor(self, side, False)
            GtkLayerShell.set_margin(self, side, 0)
        if monitor is None:
            # Nowhere said (some trays send 0, 0): Plasma's default panel is at the bottom, the tray on the right.
            GtkLayerShell.set_anchor(self, edge.BOTTOM, True)
            GtkLayerShell.set_anchor(self, edge.RIGHT, True)
            GtkLayerShell.set_margin(self, edge.BOTTOM, 6)
            GtkLayerShell.set_margin(self, edge.RIGHT, 6)
            return
        GtkLayerShell.set_monitor(self, monitor)
        area = monitor.get_geometry()
        vertical = edge.TOP if y - area.y < area.height / 2 else edge.BOTTOM
        GtkLayerShell.set_anchor(self, vertical, True)
        GtkLayerShell.set_margin(self, vertical, 6)
        GtkLayerShell.set_anchor(self, edge.LEFT, True)
        GtkLayerShell.set_margin(self, edge.LEFT, int(max(6, min(x - area.x - WIDTH / 2, area.width - WIDTH - 6))))

    def _place_x11(self, x, y):
        if not (x or y):
            self.set_position(Gtk.WindowPosition.MOUSE)
            return
        width, height = self.get_preferred_size()[1].width, self.get_preferred_size()[1].height
        monitor = Gdk.Display.get_default().get_monitor_at_point(x, y)
        area = monitor.get_workarea()
        left = max(area.x + 6, min(x - width // 2, area.x + area.width - width - 6))
        top = y + 12 if y - area.y < area.height / 2 else y - height - 12
        top = max(area.y + 6, min(top, area.y + area.height - height - 6))
        self.move(left, top)
