"""Sign in and adding someone by their link: in the popup, and the adding one
in the book window too."""
from gi.repository import Gtk

from .. import config, palette
from ..model import invite_id
from ..i18n import tr
from . import widgets as w


class SignInView(Gtk.Box):
    def __init__(self, model, quit_app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.model = model
        self.quit_app = quit_app
        self.message = None
        self.busy = False

        top = w.vbox(10)
        top.set_margin_top(8)
        dot = w.HeartDot(56, "heart", "heartSoft")
        dot.set_halign(Gtk.Align.CENTER)
        top.pack_start(dot, False, False, 0)
        top.pack_start(w.label(tr("Привет!"), "big", xalign=0.5), False, False, 0)
        hello = w.label(tr("Думаешь о ком-то? Нажми, и он почувствует, что его любят и он нужен. А от кого, не узнает."),
                        "muted", wrap=True, xalign=0.5, width_chars=36)
        hello.set_justify(Gtk.Justification.CENTER)
        top.pack_start(hello, False, False, 0)
        self.pack_start(top, False, False, 0)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, homogeneous=False)
        self.stack.set_vhomogeneous(False)
        self.stack.set_interpolate_size(True)

        self.google = w.button(tr("Войти через Google"), "primary", action=self._google)
        self.stack.add_named(w.vbox(8, self.google,
                                    w.button(tr("Войти по почте"), "secondary", action=lambda: self._mode(True))), "choose")

        self.email = w.entry("you@example.com")
        self.email.set_input_purpose(Gtk.InputPurpose.EMAIL)
        self.password = w.entry(tr("Не меньше 8 символов"), password=True)
        self.email.connect("activate", lambda _: self.password.grab_focus())
        self.password.connect("activate", lambda _: self._submit())
        self.submit = w.button(tr("Войти или создать аккаунт"), "primary", action=self._submit)
        links = Gtk.Box()
        links.pack_start(w.button(tr("← Назад"), "textlink", "muted", "small", action=lambda: self._mode(False)), False, False, 0)
        links.pack_end(w.button(tr("Забыли пароль?"), "textlink", "small", action=self._reset), False, False, 0)
        self.stack.add_named(w.vbox(10, w.field(tr("Почта"), self.email), w.field(tr("Пароль"), self.password),
                                    self.submit, links), "email")
        self.pack_start(self.stack, False, False, 0)

        self.note = w.label("", "muted", "small", wrap=True, xalign=0.5, width_chars=36)
        self.note.set_justify(Gtk.Justification.CENTER)
        self.note.set_no_show_all(True)
        self.pack_start(self.note, False, False, 0)

        self.pack_start(Gtk.Separator(), False, False, 0)
        footer = Gtk.Box()
        footer.pack_end(w.button(tr("Закрыть"), "textlink", "muted", "small", action=self.quit_app), False, False, 0)
        self.pack_start(footer, False, False, 0)
        self.refresh()

    def _mode(self, email):
        self.message = None
        self.stack.set_visible_child_name("email" if email else "choose")
        if email:
            self.email.grab_focus()
        self.refresh()

    def _google(self):
        self.message = None
        self.model.sign_in_with_google()

    def _submit(self):
        if self.busy:
            return
        email = self.email.get_text().strip()
        password = self.password.get_text()
        if not email:
            self.message = tr("Введи почту")
        elif len(password) < 8:
            self.message = tr("Пароль нужен не короче 8 символов")
        else:
            self.busy = True
            self.message = None

            def done(_):
                self.busy = False
                self.password.set_text("")
                self.refresh()

            def fail(error):
                self.busy = False
                self.message = self.model.error_text(error)
                self.refresh()
            self.model.sign_in(email, password, done, fail)
        self.refresh()

    def _reset(self):
        email = self.email.get_text().strip()
        if not email:
            self.message = tr("Сначала введи почту")
            self.refresh()
            return

        def done(_):
            self.message = tr("Письмо для нового пароля отправлено")
            self.refresh()

        def fail(error):
            self.message = self.model.error_text(error)
            self.refresh()
        self.model.send_password_reset(email, done, fail)

    def refresh(self):
        self.google.set_label(tr("Продолжи в браузере…") if self.model.waiting_for_browser else tr("Войти через Google"))
        self.submit.set_label(tr("Входим…") if self.busy else tr("Войти или создать аккаунт"))
        self.submit.set_sensitive(not self.busy)
        text = self.message or self.model.problem
        self.note.set_text(text or "")
        self.note.set_visible(bool(text))

    def reset(self):
        """Each opening starts from the two buttons, unless the email form is half filled."""
        if not self.email.get_text() and not self.password.get_text():
            self.stack.set_visible_child_name("choose")
        self.message = None


class AddForm(Gtk.Box):
    """"Новый человек": the invite link, a name, a color. The server never says
    whether a code belongs to anyone (so codes can't be probed): only its shape
    is checked here."""

    def __init__(self, model, invite=None, on_back=None, on_added=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.model = model
        self.on_added = on_added
        self.busy = False
        self.color = model.next_color
        self.close = model.new_contact_is_close
        self.code = None

        if on_back:
            self.pack_start(w.hbox(6, w.icon_button("go-previous-symbolic", tr("Назад"), on_back),
                                   w.label(tr("Новый человек"), "title")), False, False, 0)

        # Copied from a message a moment ago: no need to paste it.
        invite = invite or model.pasted_invite(model.clipboard_text())
        self.link = w.entry("lovearound.me/i/…", text="%s/i/%s" % (config.SITE, invite) if invite else "")
        self.lookup = w.label("", "small")
        link_box = w.vbox(4, w.field(tr("Ссылка-приглашение"), self.link), self.lookup)
        self.pack_start(link_box, False, False, 0)

        self.name = w.entry(tr("Например, Мама"))
        self.name.connect("activate", lambda _: self._save())
        self.pack_start(w.field(tr("Как назовёшь?"), self.name), False, False, 0)

        colors = Gtk.Box()
        colors.pack_start(w.caption(tr("Цвет")), False, False, 0)
        self.color_name = w.label("", "small")
        colors.pack_end(self.color_name, False, False, 0)
        self.swatches = w.SwatchPicker(self.color, 30, self._pick)
        self.pack_start(w.vbox(8, colors, self.swatches), False, False, 0)

        self.save = w.button(tr("Добавить"), "primary", action=self._save)
        self.pack_start(self.save, False, False, 0)
        self.error = w.label("", "danger", "small", wrap=True)
        self.error.set_no_show_all(True)
        self.pack_start(self.error, False, False, 0)
        self.note = w.note("")
        self.pack_start(self.note, False, False, 0)

        self.link.connect("changed", lambda _: self._update())
        self.name.connect("changed", lambda _: self._update())
        self._update()

    @property
    def label(self):
        return self.name.get_text().strip()

    def half_filled(self):
        return bool(self.label)

    def focus(self):
        (self.name if self.code else self.link).grab_focus()

    def _pick(self, index):
        self.color = index
        self._update()

    def _set_classes(self, widget, *names):
        context = widget.get_style_context()
        for name in list(context.list_classes()):
            context.remove_class(name)
        for name in names:
            context.add_class(name)

    def _update(self):
        text = self.link.get_text().strip()
        self.code = invite_id(text) if text else None
        if not text:
            self.lookup.set_text(tr("Вставь ссылку, которую тебе прислали"))
            self._set_classes(self.lookup, "small", "faint")
        elif self.code is None:
            self.lookup.set_text(tr("Не похоже на ссылку-приглашение"))
            self._set_classes(self.lookup, "small", "muted")
        else:
            self.lookup.set_text("✓ " + tr("Ссылка в порядке. Осталось подписать."))
            self._set_classes(self.lookup, "small", "ok")
        color = palette.at(self.color)
        self.color_name.set_text(color.name)
        self._set_classes(self.color_name, "small", "deep", "c%d" % self.color)
        self.save.set_label(tr("Сохраняем…") if self.busy else tr("Добавить"))
        self.save.set_sensitive(not self.busy and 1 <= len(self.label) <= 64 and self.code is not None)
        self.note.set_text(tr("{name} не увидит ни имя, ни цвет. Кружки можно переставлять перетаскиванием.",
                              name=self.label or tr("Человек")))

    def _save(self):
        if not self.save.get_sensitive():
            return
        self.busy = True
        self.error.hide()

        def done(contact):
            self.busy = False
            self._update()
            if self.on_added:
                self.on_added(contact)

        def fail(error):
            self.busy = False
            self.error.set_text(self.model.error_text(error))
            self.error.show()
            self._update()
        self.model.add_contact(self.code, self.label, self.color, self.close, done, fail)
        self._update()
