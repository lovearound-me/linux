"""Sign in and adding someone by their link: in the popup, and the adding one
in the book window too."""
from gi.repository import Gtk

from .. import config, palette
from ..model import invite_id
from ..i18n import tr
from . import widgets as w


class SignInView(Gtk.Box):
    """One button: Google, Apple and email all happen on lovearound.me/signin in the browser."""

    def __init__(self, model, quit_app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.model = model
        self.quit_app = quit_app

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

        go = Gtk.Button()
        go.set_relief(Gtk.ReliefStyle.NONE)
        w.classes(go, "primary")
        inside = w.hbox(7, Gtk.Image.new_from_icon_name("web-browser-symbolic", Gtk.IconSize.BUTTON),
                        w.label(tr("Войти через браузер")))
        inside.set_halign(Gtk.Align.CENTER)
        go.add(inside)
        go.connect("clicked", lambda _: self.model.sign_in_in_browser())
        chips = w.hbox(6, w.chip("google", "Google"), w.chip("apple", "Apple"), w.chip("mail", tr("Почта")))
        chips.set_halign(Gtk.Align.CENTER)
        self.stack.add_named(w.vbox(10, go, chips), "choose")

        waiting = w.button(tr("Продолжи в браузере…"), "primary")
        waiting.set_sensitive(False)
        again = w.hbox(5, w.label(tr("Страница не открылась?"), "muted", "small"),
                       w.button(tr("Открыть ещё раз"), "textlink", "small", action=self.model.sign_in_in_browser))
        again.set_halign(Gtk.Align.CENTER)
        self.stack.add_named(w.vbox(8, waiting, again), "waiting")
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

    def refresh(self):
        self.stack.set_visible_child_name("waiting" if self.model.waiting_for_browser else "choose")
        text = self.model.problem
        self.note.set_text(text or "")
        self.note.set_visible(bool(text))

    def reset(self):
        """Each opening starts from the button."""
        self.refresh()


class AddForm(Gtk.Box):
    """"Новый человек": the invite link, a name, a color. The server never says
    whether a code belongs to anyone (so codes can't be probed): only its shape
    is checked here."""

    def __init__(self, model, invite=None, on_back=None, on_added=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.model = model
        self.on_added = on_added
        self.busy = False
        self.color = model.free_color
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
