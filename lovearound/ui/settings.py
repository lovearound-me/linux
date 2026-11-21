"""Settings: Сигнал, Когда, Устройства, Аккаунт. The window takes the height of
the tab shown."""
import datetime

from gi.repository import GLib, Gtk

from .. import config, palette, tasks
from .. import model as m
from .. import i18n
from ..api import APIError
from ..i18n import tr, trn
from . import widgets as w

WIDTH = 420


def ago(when, now=None):
    """"5 минут назад", "вчера"."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    seconds = (now - when).total_seconds()
    if seconds < 60:
        return tr("только что")
    minutes = int(seconds // 60)
    if minutes < 60:
        return trn("{n} минут назад", minutes)
    hours = minutes // 60
    if hours < 24:
        return trn("{n} часов назад", hours)
    days = hours // 24
    if days == 1:
        return tr("вчера")
    return trn("{n} дней назад", days)


def parse_time(text):
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def device_details(device, now=None):
    caps = device.capabilities
    if "receive" in caps and "send" in caps:
        text = tr("Принимает и отправляет")
    elif "receive" in caps:
        text = tr("Принимает")
    elif "send" in caps:
        text = tr("Отправляет")
    else:
        text = ""
    seen = parse_time(device.last_seen_at) if device.last_seen_at else None
    return text + (tr(" · был онлайн {ago}", ago=ago(seen, now)) if seen else tr(" · ещё не подключался"))


def signed_in_with(provider):
    return {
        "apple.com": tr("Вход через Apple"),
        "google.com": tr("Вход через Google"),
        "password": tr("Вход по почте"),
    }.get(provider) or tr("Книга хранится в аккаунте")


def section(spacing, *children):
    return w.vbox(spacing, *children)


def switch_card(*rows, cls="card"):
    box = w.vbox(0, *rows)
    w.classes(box, cls)
    return box


class LookPicker(Gtk.Box):
    """"Кружки в меню": two cards, bare circles or circles with names, each
    with a small picture of the menu."""

    DOTS = [palette.at(1), palette.at(3), palette.at(4), palette.at(5)]

    def __init__(self, named, on_change):
        super().__init__(spacing=8, homogeneous=True)
        self.on_change = on_change
        self.buttons = []
        for value, title in ((False, tr("Только кружки")), (True, tr("С именами"))):
            picture = Gtk.DrawingArea()
            picture.set_size_request(96, 30)
            picture.connect("draw", self._draw, value)
            button = Gtk.ToggleButton()
            button.set_relief(Gtk.ReliefStyle.NONE)
            w.classes(button, "look")
            button.add(w.vbox(6, picture, w.label(title, "strong", xalign=0.5)))
            button.connect("toggled", self._toggled, value)
            self.buttons.append((value, button))
            self.pack_start(button, True, True, 0)
        self.select(named)

    def _draw(self, area, cr, named):
        width = area.get_allocated_width()
        step, r = 23, 9
        x0 = (width - step * (len(self.DOTS) - 1)) / 2
        for i, color in enumerate(self.DOTS):
            x = x0 + i * step
            cr.set_source_rgb(*[(color.color >> s & 255) / 255 for s in (16, 8, 0)])
            cr.arc(x, r + 1, r, 0, 6.2832)
            cr.fill()
            if named:
                cr.set_source_rgba(0.5, 0.42, 0.38, 0.7)
                cr.rectangle(x - 8, 2 * r + 6, 16, 3)
                cr.fill()

    def select(self, named):
        self.updating = True
        for value, button in self.buttons:
            button.set_active(value == named)
        self.updating = False

    def _toggled(self, button, value):
        if self.updating:
            return
        if not button.get_active():
            # Clicking the chosen card again keeps it chosen.
            self.select(value)
            return
        self.select(value)
        self.on_change(value)


class DevicesTab(Gtk.Box):
    """A toy, a lamp or any board that receives signals or sends them; how to wire one up: SITE/docs."""

    def __init__(self, model):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.model = model
        self.devices = []
        self.busy = False
        self.confirm = None
        self.copied = False
        self.receive = True
        self.send = True
        self.top = w.vbox(10)
        self.pack_start(self.top, False, False, 0)
        self.listing = w.vbox(6)
        self.pack_start(self.listing, False, False, 0)
        self.error = w.label("", "danger", "small", wrap=True)
        self.error.set_no_show_all(True)
        self.pack_start(self.error, False, False, 0)
        self.pack_start(w.link_row("help-browser-symbolic", tr("Как подключить свою плату"),
                                   lambda: model.open_uri(config.SITE + "/docs")), False, False, 0)
        self.name = w.entry(tr("Например, Котик на полке"))
        self.name.connect("changed", lambda _: self._update_button())
        self.button = w.button(tr("Подключить устройство"), "primary", action=self.add)
        self.render()

    def load(self):
        def done(devices):
            self.devices = devices
            self.error.hide()
            self.render()

        def fail(_):
            self._fail(tr("Не получилось загрузить устройства"))
        tasks.run(self.model.api.devices, done=done, fail=fail)

    def _fail(self, text):
        self.error.set_text(text)
        self.error.show()

    def _update_button(self):
        name = self.name.get_text().strip()
        self.button.set_label(tr("Подключаем…") if self.busy else tr("Подключить устройство"))
        self.button.set_sensitive(not self.busy and 1 <= len(name) <= 64 and (self.receive or self.send))

    def _toggle(self, key, value):
        setattr(self, key, value)
        self._update_button()

    def render(self):
        for child in self.top.get_children():
            self.top.remove(child)
        created = self.model.created_device
        if created:
            # The token of the device just created: shown once, never again.
            name, token = created
            token_label = w.label(token, "token", wrap=True, selectable=True)
            token_label.set_line_wrap_mode(2)  # Pango.WrapMode.CHAR
            box = w.vbox(10, w.label("✓ " + tr("«{name}» подключено", name=name), "ok"),
                         w.card(token_label, padding=10, cls="tokenbox"),
                         w.note(tr("Это токен устройства. Мы покажем его только сейчас: скопируй и вставь в прошивку. "
                                "С ним можно отправлять сердечки от твоего имени, так что никому не показывай.")))
            buttons = Gtk.Box(spacing=8, homogeneous=True)
            buttons.pack_start(w.button(tr("Скопировано") if self.copied else tr("Скопировать токен"), "primary",
                                        action=lambda: self._copy(token)), True, True, 0)
            buttons.pack_start(w.button(tr("Готово"), "secondary", action=self._done), True, True, 0)
            box.pack_start(buttons, False, False, 0)
            self.top.pack_start(box, False, False, 0)
        else:
            self.top.pack_start(w.label(tr("Игрушка, лампа или своя плата, которая светится, когда о тебе думают, "
                                        "или отправляет сердечко по кнопке."), "muted", "small", wrap=True, width_chars=50),
                                False, False, 0)
            self.top.pack_start(w.field(tr("Название"), self.name), False, False, 0)
            self.top.pack_start(switch_card(w.SwitchRow(tr("Принимает сердечки"), self.receive, lambda v: self._toggle("receive", v)),
                                            w.SwitchRow(tr("Отправляет сердечки"), self.send, lambda v: self._toggle("send", v))),
                                False, False, 0)
            self.top.pack_start(self.button, False, False, 0)
            self._update_button()
        self.top.show_all()

        w.clear(self.listing)
        if self.devices:
            self.listing.pack_start(w.caption(tr("Подключены")), False, False, 0)
            for device in self.devices:
                self.listing.pack_start(self._row(device), False, False, 0)
        self.listing.show_all()

    def _row(self, device):
        row = Gtk.Box(spacing=8)
        w.classes(row, "card", "device")
        row.set_size_request(-1, 46)
        text = w.vbox(2, w.label(device.name, "strong", ellipsize=True),
                      w.label(device_details(device), "note", ellipsize=True))
        text.set_valign(Gtk.Align.CENTER)
        row.pack_start(text, True, True, 0)
        if self.confirm == device.id:
            row.pack_end(w.button(tr("Отключить"), "textlink", "danger", "small", action=lambda: self.remove(device)),
                         False, False, 0)
            row.pack_end(w.button(tr("Нет"), "textlink", "muted", "small", action=lambda: self._confirm(None)), False, False, 0)
        else:
            row.pack_end(w.icon_button("user-trash-symbolic", tr("Отключить"), lambda: self._confirm(device.id)),
                         False, False, 0)
        return row

    def _confirm(self, id_):
        self.confirm = id_
        self.render()

    def add(self):
        name = self.name.get_text().strip()
        capabilities = [c for c, on in (("receive", self.receive), ("send", self.send)) if on]
        self.busy = True
        self.error.hide()
        self._update_button()

        def done(result):
            device, token = result
            self.busy = False
            self.devices.append(device)
            self.model.created_device = (device.name, token)
            self.copied = False
            self.name.set_text("")
            self.render()

        def fail(error):
            self.busy = False
            self._update_button()
            if isinstance(error, APIError) and error.status == 409:
                self._fail(tr("Устройств уже много, отключи лишние"))
            else:
                self._fail(tr("Не получилось, попробуй ещё раз"))
        tasks.run(self.model.api.add_device, name, capabilities, done=done, fail=fail)

    def remove(self, device):
        def done(_):
            self.devices = [d for d in self.devices if d.id != device.id]
            self.confirm = None
            self.render()

        def fail(_):
            self._fail(tr("Не получилось отключить, попробуй ещё раз"))
        tasks.run(self.model.api.delete_device, device.id, done=done, fail=fail)

    def _copy(self, token):
        self.model.set_clipboard(token)
        self.copied = True
        self.render()

    def _done(self):
        self.model.created_device = None
        self.render()


class SettingsWindow(Gtk.Window):
    def __init__(self, app, model, system, notes):
        """`notes()`: what this desktop can't do and how to fix it, as (text, button, action)."""
        super().__init__(title=tr("Настройки"), application=app)
        self.model = model
        self.system = system
        self.notes = notes
        self.set_resizable(False)
        self.get_style_context().add_class("la")
        self.connect("delete-event", lambda *_: self.hide() or True)

        root = w.vbox(16)
        root.set_margin_start(20)
        root.set_margin_end(20)
        root.set_margin_top(12)
        root.set_margin_bottom(20)
        root.set_size_request(WIDTH, -1)
        self.add(root)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, homogeneous=False)
        self.stack.set_vhomogeneous(False)
        switcher = Gtk.StackSwitcher(stack=self.stack, homogeneous=True)
        root.pack_start(switcher, False, False, 0)
        root.pack_start(self.stack, False, False, 0)

        self.signal_tab = w.vbox(16)
        self.when_tab = w.vbox(16)
        self.devices_tab = DevicesTab(model)
        self.account_tab = w.vbox(16)
        self.account_body = w.vbox(16)
        self.account_tab.pack_start(self.account_body, False, False, 0)
        self.account_tab.pack_start(self._language_row(), False, False, 0)
        self.account_tab.pack_start(w.label("Love Around " + config.VERSION, "note", xalign=0.5, selectable=True),
                                    False, False, 0)
        self.updater = app.updater
        if self.updater:
            self.connect("hide", lambda _: self.updater.dismiss())
            self.update_box = w.vbox(6)
            self.update_box.set_halign(Gtk.Align.CENTER)
            self.account_tab.pack_start(self.update_box, False, False, 0)
        for page, name, title in ((self.signal_tab, "signal", tr("Сигнал")), (self.when_tab, "when", tr("Когда")),
                                  (self.devices_tab, "devices", tr("Устройства")), (self.account_tab, "account", tr("Аккаунт"))):
            self.stack.add_titled(page, name, title)
        self.stack.connect("notify::visible-child", self._tab)

        self._build_signal()
        self._build_when()
        self.confirm_delete = False
        self.account_error = None
        model.connect("changed", lambda _: self.refresh())
        root.show_all()
        self.refresh()

    def _tab(self, *_):
        if self.stack.get_visible_child() is self.devices_tab:
            self.devices_tab.load()
        self.resize(WIDTH, 1)

    def open(self, tab=None):
        # Back for a device token that is shown only once.
        if self.model.created_device:
            self.stack.set_visible_child(self.devices_tab)
        elif tab:
            self.stack.set_visible_child_name(tab)
        self.refresh()
        self.present()
        if self.stack.get_visible_child() is self.devices_tab:
            self.devices_tab.load()

    # ---- Сигнал: what an incoming signal looks like

    def _build_signal(self):
        model = self.model
        self.notes_box = w.vbox(8)
        self.signal_tab.pack_start(self.notes_box, False, False, 0)

        self.my_color = w.SwatchPicker(model.get("myColor"), 30, lambda i: model.set("myColor", i))
        self.signal_tab.pack_start(section(8, w.caption(tr("Мой цвет сигнала")), self.my_color,
                                           w.note(tr("Этим цветом светятся края экрана, когда кто-то о тебе думает."))),
                                   False, False, 0)

        head = Gtk.Box()
        head.pack_start(w.caption(tr("Смайликов за раз")), False, False, 0)
        self.emoji_value = w.label("", "strong")
        head.pack_end(self.emoji_value, False, False, 0)
        self.emoji = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, m.MAX_EMOJI, 2)
        self.emoji.set_draw_value(False)
        self.emoji.set_value(model.get("emojiCount"))
        self.emoji.connect("value-changed", self._emoji)
        self.calm_note = w.note(tr("С «Без мигания и полёта» смайлики не летают."))
        self.calm_note.set_no_show_all(True)
        self.signal_tab.pack_start(section(6, head, self.emoji, self.calm_note), False, False, 0)

        self.sound = w.SwitchRow(tr("Тихий звук"), model.get("sound"), lambda v: model.set("sound", v))
        self.calm = w.SwitchRow(tr("Без мигания и полёта"), model.get("calm"), lambda v: model.set("calm", v))
        self.signal_tab.pack_start(switch_card(self.sound, self.calm), False, False, 0)

        play = w.button("▶  " + tr("Показать, как это выглядит"), "play", action=model.play_effect)
        self.signal_tab.pack_start(play, False, False, 0)

        self.look = LookPicker(model.get("circleNames"), lambda v: model.set("circleNames", v))
        self.signal_tab.pack_start(section(8, w.caption(tr("Кружки в меню")), self.look), False, False, 0)

    def _emoji(self, scale):
        value = int(round(scale.get_value() / 2) * 2)
        self.model.set("emojiCount", value)

    # ---- Когда: when signals are shown at all

    def _build_when(self):
        model = self.model
        self.receive = w.SwitchRow(tr("Получать сердечки на этом компьютере"), model.get("receiveHere"),
                                   lambda v: model.set("receiveHere", v))
        self.when_tab.pack_start(section(6, switch_card(self.receive),
                                         w.note(tr("Выключишь, и этот компьютер не засветится. Телефон, часы и игрушки "
                                                "получают как раньше. Отправлять сердечки он может всегда."))),
                                 False, False, 0)

        self.pause_caption = w.caption(tr("Пауза"))
        self.pause_buttons = Gtk.Box(spacing=6, homogeneous=True)
        self.when_tab.pack_start(section(8, self.pause_caption, self.pause_buttons), False, False, 0)

        head = Gtk.Box()
        head.pack_start(w.caption(tr("Свечение не чаще раза в")), False, False, 0)
        self.gap_value = w.label("", "strong")
        head.pack_end(self.gap_value, False, False, 0)
        self.gap = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, len(m.GAPS) - 1, 1)
        self.gap.set_draw_value(False)
        self.gap.set_value(m.gap_index(model.get("minGap")))
        self.gap.connect("value-changed", lambda s: model.set("minGap", m.GAPS[int(round(s.get_value()))]))
        self.when_tab.pack_start(section(6, head, self.gap,
                                         w.note(tr("Если о тебе думают часто, сигналы между вспышками не покажутся."))),
                                 False, False, 0)

        self.quiet = w.SwitchRow(tr("Тихо, когда что-то на весь экран"), model.get("quietWhenPresenting"),
                                 lambda v: model.set("quietWhenPresenting", v))
        self.autostart = w.SwitchRow(tr("Запускать при входе в систему"), self.system.autostart_enabled(),
                                     self._autostart)
        self.when_tab.pack_start(switch_card(self.quiet, self.autostart), False, False, 0)

        self.anyone = w.SwitchRow(tr("Сердечки от кого-нибудь на свете"), model.get("acceptAnyone"),
                                  lambda v: model.set("acceptAnyone", v))
        self.when_tab.pack_start(section(6, switch_card(self.anyone, cls="anyone-card"),
                                         w.note(tr("Кто-то где-то нажал «Кому-нибудь на свете», и сердечко может прилететь "
                                                "тебе. Бывает редко, тем и приятнее."))), False, False, 0)

    def _autostart(self, on):
        self.system.set_autostart(on)
        self.autostart.set_active(self.system.autostart_enabled())

    def _pause_buttons(self):
        model = self.model
        w.clear(self.pause_buttons)
        if model.is_paused:
            self.pause_caption.set_text(model.pause_text())
            items = [(tr("Снять паузу"), model.resume)]
        else:
            self.pause_caption.set_text(tr("Пауза"))
            items = [(tr("На час"), lambda: model.pause("hour")), (tr("До утра"), lambda: model.pause("morning")),
                     (tr("Пока не сниму"), lambda: model.pause("forever"))]
        for title, action in items:
            self.pause_buttons.pack_start(w.button(title, "small-button", action=action), True, True, 0)
        self.pause_buttons.show_all()

    # ---- Аккаунт: who is signed in, the Love ID, and removing the account

    def _build_account(self):
        model = self.model
        w.clear(self.account_body)
        tab = self.account_body
        if not model.signed_in:
            tab.pack_start(w.label(tr("Ты не вошёл в аккаунт. Войти можно в меню у сердечка."), "muted", wrap=True),
                           False, False, 0)
        else:
            who = Gtk.Box(spacing=12)
            w.pad(who, 12)
            # Apple's "Hide my email" gives an address nobody would recognise.
            hidden = (model.email or "").endswith("@privaterelay.appleid.com")
            who.pack_start(w.Circle(40, model.email or "", palette.at(model.get("myColor")), ring=2.5, apple=hidden),
                           False, False, 0)
            methods = Gtk.Button()
            methods.set_relief(Gtk.ReliefStyle.NONE)
            w.classes(methods, "textlink", "note")
            methods.add(w.hbox(2, w.label(tr("Способы входа")), w.Mark("arrow", 11, ink="link")))
            methods.connect("clicked", lambda _: model.open_sign_in_methods())
            methods.set_halign(Gtk.Align.START)
            text = w.vbox(2, w.label("Apple ID" if hidden else model.email or "", "strong", ellipsize=True),
                          w.label(tr("Почту скрыл Apple") if hidden else signed_in_with(model.provider), "note"),
                          methods)
            text.set_valign(Gtk.Align.CENTER)
            who.pack_start(text, True, True, 0)
            out = w.button(tr("Выйти"), "small-button", action=model.sign_out)
            out.set_size_request(76, -1)
            out.set_valign(Gtk.Align.CENTER)
            who.pack_end(out, False, False, 0)
            tab.pack_start(w.card(who), False, False, 0)

            if not model.auth.store.available:
                tab.pack_start(w.banner("dialog-warning-symbolic",
                                        tr("Связка ключей недоступна, поэтому вход не сохранится: после перезапуска "
                                        "придётся войти снова. Поставь gnome-keyring или KWallet.")), False, False, 0)

            if model.invite_url:
                tab.pack_start(section(6, w.InviteRow(model),
                                       w.note(tr("Отправь его тем, кто хочет нажимать, когда думает о тебе."))),
                               False, False, 0)

            tab.pack_start(Gtk.Separator(), False, False, 0)
            if self.confirm_delete:
                buttons = Gtk.Box(spacing=8, homogeneous=True)
                buttons.pack_start(w.button(tr("Не удалять"), "small-button", action=lambda: self._confirm(False)),
                                   True, True, 0)
                really = w.button(tr("Удалить навсегда"), "small-button", action=self._delete)
                really.get_child().get_style_context().add_class("danger")
                buttons.pack_start(really, True, True, 0)
                tab.pack_start(section(8, w.label(tr("Удалить аккаунт и весь список? Это навсегда."), "strong"), buttons),
                               False, False, 0)
            else:
                row = Gtk.Box()
                row.pack_start(w.vbox(2, w.label(tr("Удалить аккаунт")), w.note(tr("Вместе с книгой, устройствами и Love ID."))),
                               True, True, 0)
                row.pack_end(w.button(tr("Удалить…"), "textlink", "danger", action=lambda: self._confirm(True)),
                             False, False, 0)
                tab.pack_start(row, False, False, 0)
            if self.account_error:
                tab.pack_start(w.label(self.account_error, "danger", "small", wrap=True), False, False, 0)
        tab.pack_start(Gtk.Separator(), False, False, 0)
        tab.show_all()

    def _language_row(self):
        """The app's language: the system's, or one picked by hand."""
        combo = Gtk.ComboBoxText()
        combo.append("", tr("Как в системе"))
        for code, name in i18n.LANGUAGES:
            combo.append(code, name)
        combo.set_active_id(self.model.get("language") or "")
        combo.connect("changed", lambda c: GLib.idle_add(self.get_application().set_language, c.get_active_id() or ""))
        row = Gtk.Box(spacing=12)
        row.pack_start(w.label(tr("Язык")), False, False, 0)
        row.pack_end(combo, False, False, 0)
        return row

    def _confirm(self, on):
        self.confirm_delete = on
        self.account_error = None
        self._build_account()

    def _delete(self):
        def done(_):
            self.confirm_delete = False
            self.hide()

        def fail(error):
            self.account_error = self.model.error_text(error)
            self._build_account()
        self.model.delete_account(done, fail)

    def refresh_update(self):
        if not self.updater:
            return
        w.clear(self.update_box)
        state, version = self.updater.state, self.updater.version
        text = {
            "checking": tr("Проверяю обновления…"),
            "available": tr("Доступна версия {version}", version=version),
            "latest": tr("Это последняя версия"),
            "check-failed": tr("Не получилось проверить обновления"),
            "installing": tr("Обновляю…"),
            "install-failed": tr("Не получилось обновить"),
        }.get(state)
        if text:
            self.update_box.pack_start(w.label(text, "note", xalign=0.5), False, False, 0)
            if state in ("available", "install-failed"):
                self.update_box.pack_start(w.button(tr("Обновить"), "small-button", action=self.updater.install),
                                           False, False, 0)
        self.update_box.show_all()
        self.update_box.set_visible(bool(text))

    # ---- everything shown from the model

    def refresh(self):
        model = self.model
        w.clear(self.notes_box)
        for text, title, action in self.notes():
            trailing = w.button(title, "textlink", "small", action=action) if title else None
            self.notes_box.pack_start(w.banner("dialog-information-symbolic", text, trailing), False, False, 0)
        self.notes_box.show_all()
        self.notes_box.set_visible(bool(self.notes_box.get_children()))

        self.my_color.select(model.get("myColor"))
        count = model.get("emojiCount")
        self.emoji_value.set_text(tr("только свет") if count == 0 else str(count))
        self.emoji.set_sensitive(not model.get("calm"))
        self.calm_note.set_visible(model.get("calm"))
        self.sound.set_active(model.get("sound"))
        self.calm.set_active(model.get("calm"))

        self._pause_buttons()
        self.gap_value.set_text(m.gap_title(model.min_gap))
        self.quiet.set_active(model.get("quietWhenPresenting"))
        self.anyone.set_active(model.get("acceptAnyone"))
        self.receive.set_active(model.get("receiveHere"))
        self.look.select(model.get("circleNames"))
        self.autostart.set_active(self.system.autostart_enabled())
        if self.stack.get_visible_child() is not self.devices_tab or not model.signed_in:
            self.devices_tab.set_sensitive(model.signed_in)
        self._build_account()
        self.refresh_update()
        if not model.signed_in:
            self.confirm_delete = False
