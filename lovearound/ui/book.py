"""The book window: everyone on the left, «Рядом» first in their menu order
(those are the circles), the rest by name; the chosen one on the right.
Dragging a row over the line moves someone in or out of the circles."""
from gi.repository import Gdk, GLib, Gtk

from .. import model as m
from .. import palette
from ..i18n import tr
from . import forms
from . import widgets as w

DRAG_TARGET = "application/x-lovearound-row"


class PersonPage(Gtk.Box):
    """One person: the name to type over, the color, and removing. Changes
    save by themselves, so there is no Save button."""

    def __init__(self, model, contact, on_removed):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.model = model
        self.contact = contact
        self.on_removed = on_removed
        self.color = model.color_index(contact)
        self.typing = None
        self.status_reset = None
        self.set_border_width(28)
        self.set_size_request(380, -1)
        self.set_halign(Gtk.Align.START)

        top = Gtk.Box(spacing=14)
        self.avatar = w.Circle(52, contact.label, palette.at(self.color), ring=2.5)
        top.pack_start(self.avatar, False, False, 0)
        self.name = Gtk.Entry(text=contact.label, placeholder_text=tr("Имя"), hexpand=True, valign=Gtk.Align.CENTER)
        self.name.get_style_context().add_class("name")
        self.name.connect("changed", self._typed)
        self.name.connect("activate", lambda _: self.save())
        top.pack_start(self.name, True, True, 0)
        self.pack_start(top, False, False, 0)

        colors = Gtk.Box()
        colors.pack_start(w.caption(tr("Цвет")), False, False, 0)
        self.color_name = w.label("", "small")
        colors.pack_end(self.color_name, False, False, 0)
        self.pack_start(w.vbox(10, colors, w.SwatchPicker(self.color, 26, self._pick)), False, False, 0)

        self.note = w.note("")
        self.pack_start(self.note, False, False, 0)

        self.error = w.label("", "danger", "small", wrap=True)
        self.error.set_no_show_all(True)
        self.pack_end(self._bottom(), False, False, 0)
        self.pack_end(self.error, False, False, 0)
        self._update()
        self.connect("destroy", self._leave)

    def _bottom(self):
        row = Gtk.Box(spacing=8)
        self.delete_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        ask = w.button(tr("Удалить из книги"), "textlink", "danger", "small",
                       action=lambda: self.delete_stack.set_visible_child_name("confirm"))
        ask.get_child().set_text("🗑  " + tr("Удалить из книги"))
        confirm = w.hbox(8, w.label(tr("Удалить из книги?"), "muted", "small"),
                         w.button(tr("Отмена"), "pill", action=lambda: self.delete_stack.set_visible_child_name("ask")),
                         w.button(tr("Удалить"), "pill", "danger", action=self.remove))
        self.delete_stack.add_named(w.hbox(0, ask), "ask")
        self.delete_stack.add_named(confirm, "confirm")
        row.pack_start(self.delete_stack, False, False, 0)
        self.status = w.label("", "faint", "small")
        row.pack_end(self.status, False, False, 0)
        return row

    @property
    def label(self):
        return self.name.get_text().strip()

    def _update(self):
        color = palette.at(self.color)
        self.avatar.update(text=self.label or self.contact.label, color=color)
        self.color_name.set_text(color.name)
        context = self.color_name.get_style_context()
        for name in [n for n in context.list_classes() if n.startswith("c") and n[1:].isdigit()]:
            context.remove_class(name)
        context.add_class("deep")
        context.add_class("c%d" % self.color)
        self.note.set_text(tr("{name} не увидит ни имя, ни цвет: их видишь только ты.", name=self.label or self.contact.label))

    def _typed(self, _):
        self._update()
        if self.typing:
            GLib.source_remove(self.typing)

        def later():
            self.typing = None
            self.save()
        self.typing = w.later(700, later)

    def _pick(self, index):
        self.color = index
        self._update()
        self.save()

    def save(self):
        current = self.model.contact(self.contact.id)
        label, color = self.label, self.color
        if current is None or not 1 <= len(label) <= 64:
            return
        if label == current.label and color == self.model.color_index(current):
            return
        self.status.set_text(tr("Сохраняем…"))
        self.error.hide()

        def done(_):
            if self.status_reset is False:
                return
            self.status.set_text("✓ " + tr("Сохранено"))
            self.status_reset = w.later(1500, lambda: self.status.set_text(""))

        def fail(_):
            if self.status_reset is False:
                return
            self.status.set_text("")
            self.error.set_text(tr("Не получилось сохранить"))
            self.error.show()
        self.model.update_contact(current, label, color, done, fail)

    def remove(self):
        current = self.model.contact(self.contact.id)
        if current is None:
            return
        if self.typing:
            GLib.source_remove(self.typing)
            self.typing = None

        def fail(_):
            self.error.set_text(tr("Не получилось удалить"))
            self.error.show()
        self.model.remove(current, lambda _: self.on_removed(), fail)

    def _leave(self, _):
        # Another person, or the window closed: what was typed is saved.
        if self.typing:
            GLib.source_remove(self.typing)
            self.typing = None
            self.save()
        if self.status_reset:
            GLib.source_remove(self.status_reset)
        self.status_reset = False


class BookWindow(Gtk.Window):
    def __init__(self, app, model):
        super().__init__(title=tr("Книга"), application=app)
        self.model = model
        self.set_default_size(700, 540)
        self.set_size_request(620, 440)
        self.get_style_context().add_class("la")
        self.selected = None
        self.adding = False
        self.page = None
        self.filling = False
        self.dragged = None
        self.deferred = None

        paned = Gtk.Box()
        self.add(paned)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sidebar.set_size_request(260, -1)
        sidebar.set_margin_top(10)
        self.search = w.search_entry("")
        self.search.set_margin_start(12)
        self.search.set_margin_end(12)
        self.search.connect("search-changed", lambda _: self.fill())
        sidebar.pack_start(self.search, False, False, 0)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.connect("row-selected", self._row_selected)
        self.list.set_margin_start(6)
        self.list.set_margin_end(6)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.add(self.list)
        sidebar.pack_start(scroll, True, True, 0)

        bottom = w.vbox(4, w.link_row("list-add-symbolic", tr("Добавить по ссылке"), self.start_adding),
                        w.note(tr("Перетаскивай людей между «Рядом» и «Остальные». Порядок в «Рядом» — порядок кружков в меню.")))
        bottom.set_margin_start(12)
        bottom.set_margin_end(12)
        bottom.set_margin_bottom(12)
        sidebar.pack_start(bottom, False, False, 0)
        paned.pack_start(sidebar, False, False, 0)
        paned.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        self.detail = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        paned.pack_start(self.detail, True, True, 0)

        self.connect("delete-event", lambda *_: self.hide() or True)
        self.connect("hide", lambda _: self._leave_page())
        self.changed_id = model.connect("changed", lambda _: self.refresh())
        self.refresh()

    # ---- the list

    def fill(self):
        self.filling = True
        scroll = self.list.get_adjustment().get_value() if self.list.get_adjustment() else 0
        w.clear(self.list)
        query = self.search.get_text().strip()
        model = self.model
        self.search.set_placeholder_text(tr("Найти — {people}", people=m.people_count(len(model.contacts))))
        if query:
            found = model.find(query)
            for contact in found:
                self.list.add(self._person(contact, None))
            if not found:
                row = Gtk.ListBoxRow(selectable=False, activatable=False)
                row.add(w.label(tr("Никого с таким именем"), "muted", "small"))
                self.list.add(row)
        else:
            close = model.close_contacts
            self.list.add(self._heading(True))
            for index, contact in enumerate(close):
                self.list.add(self._person(contact, index))
            self.list.add(self._heading(False))
            for contact in model.contacts_by_name:
                if not contact.close:
                    self.list.add(self._person(contact, None))
        self.list.show_all()
        for row in self.list.get_children():
            if getattr(row, "contact_id", None) == self.selected:
                self.list.select_row(row)
        if self.list.get_adjustment():
            self.list.get_adjustment().set_value(scroll)
        self.filling = False

    def _heading(self, near):
        model = self.model
        row = Gtk.ListBoxRow(selectable=False, activatable=False)
        row.get_style_context().add_class("heading")
        line = Gtk.Box(spacing=5)
        if near:
            line.pack_start(w.label("♥", "link", "small"), False, False, 0)
            line.pack_start(w.label(tr("Рядом"), "near"), False, False, 0)
            line.pack_start(w.label(tr("кружки в меню"), "faint", "small"), False, False, 0)
        else:
            line.pack_start(w.label(tr("Остальные"), "caption"), False, False, 0)
        box = w.vbox(3, line)
        empty = not model.close_contacts if near else all(c.close for c in model.contacts)
        if empty and model.contacts:
            box.pack_start(w.label(tr("Перетащи сюда тех, кому хочешь нажимать в один клик") if near else
                                   tr("Перетащи сюда, чтобы убрать кружок из меню"), "note", wrap=True, width_chars=28),
                           False, False, 0)
        box.set_margin_top(2 if near else 12)
        box.set_margin_bottom(2)
        row.add(box)
        row.near = near
        self._drop_target(row)
        return row

    def _person(self, contact, close_index):
        row = Gtk.ListBoxRow()
        row.contact_id = contact.id
        row.close_index = close_index
        line = Gtk.Box(spacing=10)
        line.pack_start(w.Circle(24, contact.label, self.model.color_for(contact), ring=2.5), False, False, 0)
        line.pack_start(w.label(contact.label, ellipsize=True), True, True, 0)
        line.set_margin_top(3)
        line.set_margin_bottom(3)
        events = Gtk.EventBox()
        events.add(line)
        row.add(events)
        if close_index is not None or not self.search.get_text().strip():
            target = [Gtk.TargetEntry.new(DRAG_TARGET, Gtk.TargetFlags.SAME_APP, 0)]
            events.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, target, Gdk.DragAction.MOVE)
            events.connect("drag-begin", lambda *_: setattr(self, "dragged", contact.id))
            events.connect("drag-data-get", lambda wd, ctx, data, *_: data.set(data.get_target(), 8, contact.id.encode()))
            events.connect("drag-end", lambda *_: setattr(self, "dragged", None))
            self._drop_target(row)
        return row

    def _drop_target(self, row):
        target = [Gtk.TargetEntry.new(DRAG_TARGET, Gtk.TargetFlags.SAME_APP, 0)]
        row.drag_dest_set(Gtk.DestDefaults.ALL, target, Gdk.DragAction.MOVE)
        row.connect("drag-motion", self._motion)
        row.connect("drag-leave", lambda r, *_: self.list.drag_unhighlight_row())
        row.connect("drag-data-received", self._dropped)

    def _motion(self, row, context, x, y, time_):
        self.list.drag_highlight_row(row)
        return False

    def _dropped(self, row, context, x, y, data, info, time_):
        """Where the row ended up decides it: above «Остальные» it is a circle,
        at that place among them; below, it leaves the menu."""
        person = self.model.contact(data.get_data().decode())
        if person is None:
            return
        if hasattr(row, "near"):
            self.model.place(person, 0 if row.near else None)
        elif row.close_index is None:
            self.model.place(person, None)
        else:
            others = [c.id for c in self.model.close_contacts if c.id != person.id]
            at = others.index(row.contact_id) if row.contact_id in others else len(others)
            if y > row.get_allocated_height() / 2:
                at += 1
            self.model.place(person, at)

    def _row_selected(self, listbox, row):
        if self.filling or row is None or not hasattr(row, "contact_id"):
            return
        if row.contact_id != self.selected or self.adding:
            self.selected = row.contact_id
            self.adding = False
            self.show_detail()

    # ---- the chosen one

    def _leave_page(self):
        # The page sits in a Gtk.Viewport the scrolled window added around it.
        child = self.detail.get_child()
        if child:
            child.destroy()
        self.page = None

    def show_detail(self):
        self._leave_page()
        model = self.model
        contact = model.contact(self.selected) if self.selected else None
        if self.adding:
            self.page = forms.AddForm(model, None, on_added=self._added)
            self.page.set_border_width(28)
            self.page.set_size_request(400, -1)
            self.page.set_halign(Gtk.Align.START)
        elif contact:
            self.page = PersonPage(model, contact, self._removed)
        else:
            empty = not model.contacts
            self.page = w.vbox(10)
            self.page.set_valign(Gtk.Align.CENTER)
            self.page.set_border_width(24)
            image = Gtk.Image.new_from_icon_name("x-office-address-book-symbolic", Gtk.IconSize.DIALOG)
            image.get_style_context().add_class("faint")
            self.page.pack_start(image, False, False, 0)
            self.page.pack_start(w.label(tr("Пока никого нет") if empty else tr("Выбери человека слева"), "title", xalign=0.5),
                                 False, False, 0)
            self.page.pack_start(w.label(tr("Добавь людей по их ссылке или поделись своим Love ID.") if empty else
                                         tr("Здесь меняются имя и цвет."), "muted", xalign=0.5, wrap=True), False, False, 0)
        self.detail.add(self.page)
        self.page.show_all()
        if self.adding:
            self.page.focus()

    def _added(self, contact):
        self.adding = False
        self.selected = contact.id
        self.fill()
        self.show_detail()

    def _removed(self):
        self.selected = None
        self.show_detail()

    def start_adding(self):
        self.selected = None
        self.adding = True
        self.list.unselect_all()
        self.show_detail()

    def refresh(self):
        if self.dragged:
            # Not under the pointer mid-drag: the list fills again after the drop.
            if not self.deferred:
                self.deferred = GLib.timeout_add(200, self._deferred)
            return
        self.fill()
        if self.adding:
            return
        gone = self.selected and self.model.contact(self.selected) is None
        if gone:
            self.selected = None
        # A person's page stays while they are there, not to lose what is being typed.
        if gone or not isinstance(self.page, PersonPage):
            self.show_detail()

    def _deferred(self):
        if self.dragged:
            return True
        self.deferred = None
        self.refresh()
        return False

    def open(self, contact_id=None):
        if contact_id:
            self.selected = contact_id
            self.adding = False
            self.fill()
            self.show_detail()
        elif self.page is None:
            self.show_detail()
        self.present()
