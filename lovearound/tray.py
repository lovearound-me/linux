"""The heart in the panel: a StatusNotifierItem with a com.canonical.dbusmenu menu.

KDE Plasma shows it as is. Ubuntu's GNOME shows it through the AppIndicator
extension (on by default), which opens the menu on a left click too and sends
Activate only on a double click; that is why the menu itself sends signals.
Plain GNOME without that extension has no tray: the app opens its window when
launched again from the app grid.
"""
import os
import time

from gi.repository import Gio, GLib

from . import icons
from .i18n import tr

WATCHER = "org.kde.StatusNotifierWatcher"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg name="status" type="s"/></signal>
  </interface>
</node>"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" name="events" direction="in"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="ai" name="updatesNeeded" direction="out"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})" name="updatedProps"/>
      <arg type="a(ias)" name="removedProps"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg type="u" name="revision"/>
      <arg type="i" name="parent"/>
    </signal>
    <signal name="ItemActivationRequested">
      <arg type="i" name="id"/>
      <arg type="u" name="timestamp"/>
    </signal>
  </interface>
</node>"""

ICON_SIZES = (16, 22, 24, 32, 48, 64)


class Item:
    """One menu entry; `key` keeps its id stable between rebuilds."""

    def __init__(self, key, label=None, action=None, enabled=True, separator=False, icon=None, children=None):
        self.key = key
        self.label = label
        self.action = action
        self.enabled = enabled
        self.separator = separator
        self.icon = icon
        self.children = children or []

    def props(self):
        if self.separator:
            return {"type": GLib.Variant("s", "separator")}
        props = {"label": GLib.Variant("s", self.label.replace("_", "__")),
                 "enabled": GLib.Variant("b", self.enabled)}
        if self.icon:
            props["icon-data"] = GLib.Variant("ay", self.icon)
        if self.children:
            props["children-display"] = GLib.Variant("s", "submenu")
        return props


def menu_items(model, actions):
    """What the heart's menu shows; `actions` are the app's own (open popup, book…)."""
    items = []
    if not model.signed_in:
        items.append(Item("signin", tr("Войти…"), actions["popup"]))
    else:
        if model.offline:
            items.append(Item("offline", tr("Нет связи с сервером"), enabled=False))
        items.append(Item("open", tr("О ком ты сейчас думаешь?…"), actions["popup"]))
        items.append(Item("sep-people", separator=True))
        wait = model.anyone_wait()
        if model.anyone_just_sent():
            anyone = tr("Улетело кому-то ♥")
        elif wait is not None:
            anyone = tr("Кому-нибудь — через {n} мин", n=wait)
        else:
            anyone = tr("Кому-нибудь на свете")
        items.append(Item("anyone", anyone, model.send_to_anyone, enabled=wait is None and not model.anyone_sending,
                          icon=icons.star_png(on=wait is None)))
        people = list(model.close_contacts)
        others = model.other_contacts
        # A short book fits whole; a long one shows the recent few.
        shown = others if len(others) <= 5 else others[:4]
        for contact in people + shown:
            color = model.color_for(contact)
            label = tr("{name} — улетело ♥", name=contact.label) if model.sent == contact.id else contact.label
            letter = contact.label[:1].upper() or "♥"
            items.append(Item("c:" + contact.id, label, (lambda c=contact: model.send(c)),
                              icon=icons.dot_png(color, letter)))
        if len(shown) < len(others):
            items.append(Item("book-all", tr("Вся книга · {n}", n=len(model.contacts)), actions["book"]))
        if not model.contacts:
            items.append(Item("add", tr("Добавить по ссылке…"), actions["add"]))
        items.append(Item("sep-pause", separator=True))
        if model.is_paused:
            # No action: shown greyed, as a status line.
            items.append(Item("pause-text", model.pause_text(), enabled=False))
            items.append(Item("resume", tr("Снять паузу"), model.resume))
        else:
            items.append(Item("pause-hour", tr("Пауза на час"), lambda: model.pause("hour")))
            items.append(Item("pause-morning", tr("Пауза до утра"), lambda: model.pause("morning")))
            items.append(Item("pause-forever", tr("Пауза, пока не сниму"), lambda: model.pause("forever")))
        items.append(Item("sep-windows", separator=True))
        items.append(Item("book", tr("Книга…"), actions["book"]))
        items.append(Item("settings", tr("Настройки…"), actions["settings"]))
    items.append(Item("sep-app", separator=True))
    items.append(Item("updates", tr("Проверить обновления…"), actions["updates"]))
    items.append(Item("quit", tr("Закрыть приложение"), actions["quit"]))
    return items


class Tray:
    def __init__(self, model, actions):
        """actions: toggle(x, y), popup(), book(), settings(), add(), updates(), quit()."""
        self.model = model
        self.actions = actions
        self.connection = None
        # A restart after an update exec()s in place, keeping the pid: a name
        # of its own each time, or the watcher may take the new item for the
        # old one and then drop it when the old connection goes away.
        self.name = "org.kde.StatusNotifierItem-%d-%d" % (os.getpid(), time.time_ns() // 1000000 % 10**9)
        self.ids = {}
        self.items = {}
        self.revision = 1
        self.root = []
        self.tint = None
        self.flash_source = None
        self.rebuild_source = None
        self.registered = False
        self.watcher_seen = False
        self.on_watcher = lambda present: None
        self.pixmaps = None

    def start(self, connection):
        self.connection = connection
        sni = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
        menu = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        connection.register_object(ITEM_PATH, sni, self._sni_call, self._sni_get, None)
        connection.register_object(MENU_PATH, menu, self._menu_call, self._menu_get, None)
        self._build()
        Gio.bus_own_name_on_connection(connection, self.name, Gio.BusNameOwnerFlags.NONE, None, None)
        Gio.bus_watch_name_on_connection(connection, WATCHER, Gio.BusNameWatcherFlags.NONE,
                                         self._watcher_appeared, self._watcher_vanished)
        connection.signal_subscribe(None, WATCHER, "StatusNotifierItemUnregistered", "/StatusNotifierWatcher",
                                    None, Gio.DBusSignalFlags.NONE, self._unregistered)
        self.model.connect("changed", lambda *_: self.schedule_rebuild())
        self.model.connect("icon-changed", lambda *_: self.update_icon())
        self.model.connect("received", lambda _, color: self.flash(color))
        # "Кому-нибудь — через N мин" counts down while the menu is closed too.
        GLib.timeout_add_seconds(30, lambda: self.schedule_rebuild() or True)

    # ---- registration --------------------------------------------------------

    def _watcher_appeared(self, connection, name, owner):
        self.watcher_seen = True
        connection.call(WATCHER, "/StatusNotifierWatcher", WATCHER, "RegisterStatusNotifierItem",
                        GLib.Variant("(s)", (self.name,)), None, Gio.DBusCallFlags.NONE, 5000, None,
                        self._registered)

    def _registered(self, connection, result):
        try:
            connection.call_finish(result)
            self.registered = True
        except GLib.Error:
            self.registered = False
        self.on_watcher(self.registered)

    def _unregistered(self, connection, sender, path, iface, signal, params):
        """The watcher let our item go while we're still here (it does that
        when it mixes us up with an item that went away): register again."""
        service = params.unpack()[0]
        ours = (self.name, connection.get_unique_name())
        if self.registered and service.split("/")[0].split("@")[0] in ours:
            self.registered = False
            GLib.timeout_add_seconds(1, lambda: self._watcher_appeared(connection, WATCHER, None) and False)

    def _watcher_vanished(self, connection, name):
        self.registered = False
        self.on_watcher(False)

    # ---- the item ------------------------------------------------------------

    def _sni_get(self, connection, sender, path, iface, prop):
        tooltip = self.model.pause_text() if self.model.is_paused else ""
        values = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", "lovearound"),
            "Title": GLib.Variant("s", "Love Around"),
            "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("i", 0),
            "IconName": GLib.Variant("s", ""),
            "IconPixmap": GLib.Variant("a(iiay)", self._pixmaps()),
            "IconThemePath": GLib.Variant("s", ""),
            "OverlayIconName": GLib.Variant("s", ""),
            "AttentionIconName": GLib.Variant("s", ""),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", ("", [], "Love Around", tooltip)),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", MENU_PATH),
        }
        return values.get(prop)

    def _pixmaps(self):
        if self.pixmaps is None:
            paused = self.model.is_paused and self.tint is None
            self.pixmaps = [(px, px, icons.argb_bytes(icons.tray_surface(px, self.tint, paused))) for px in ICON_SIZES]
        return self.pixmaps

    def _sni_call(self, connection, sender, path, iface, method, params, invocation):
        if method in ("Activate", "SecondaryActivate", "ContextMenu"):
            x, y = params.unpack()
            self.actions["toggle"](x, y)
        invocation.return_value(None)

    def _emit(self, path, iface, signal, params=None):
        if self.connection is not None:
            try:
                self.connection.emit_signal(None, path, iface, signal, params)
            except GLib.Error:
                pass

    def update_icon(self):
        self.pixmaps = None
        self._emit(ITEM_PATH, "org.kde.StatusNotifierItem", "NewIcon")
        self._emit(ITEM_PATH, "org.kde.StatusNotifierItem", "NewToolTip")

    def flash(self, color):
        """The icon briefly takes the signal color when a signal arrives."""
        self.tint = color
        self.update_icon()
        if self.flash_source:
            GLib.source_remove(self.flash_source)

        def back():
            self.flash_source = None
            self.tint = None
            self.update_icon()
            return False
        self.flash_source = GLib.timeout_add(1400, back)

    # ---- the menu ------------------------------------------------------------

    def schedule_rebuild(self):
        if self.rebuild_source is None:
            self.rebuild_source = GLib.idle_add(self._rebuild_now)

    def _rebuild_now(self):
        self.rebuild_source = None
        self._build()
        self._emit(MENU_PATH, "com.canonical.dbusmenu", "LayoutUpdated", GLib.Variant("(ui)", (self.revision, 0)))
        return False

    def _build(self):
        self.revision += 1
        self.root = menu_items(self.model, self.actions)
        self.items = {}

        def index(items):
            for item in items:
                if item.key not in self.ids:
                    self.ids[item.key] = len(self.ids) + 1
                self.items[self.ids[item.key]] = item
                index(item.children)
        index(self.root)

    def _layout(self, item_id, item, depth):
        props = {"children-display": GLib.Variant("s", "submenu")} if item is None else item.props()
        children = self.root if item is None else item.children
        nested = []
        if depth != 0:
            for child in children:
                nested.append(GLib.Variant("(ia{sv}av)", self._layout(self.ids[child.key], child, depth - 1)))
        return item_id, props, nested

    def _menu_get(self, connection, sender, path, iface, prop):
        return {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }.get(prop)

    def _menu_call(self, connection, sender, path, iface, method, params, invocation):
        args = params.unpack()
        if method == "GetLayout":
            parent, depth, _ = args
            item = None if parent == 0 else self.items.get(parent)
            if parent != 0 and item is None:
                invocation.return_dbus_error("com.canonical.dbusmenu.UnknownId", "no such item")
                return
            layout = self._layout(parent, item, depth)
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (self.revision, layout)))
        elif method == "GetGroupProperties":
            ids, _ = args
            out = [(i, self.items[i].props()) for i in (ids or self.items.keys()) if i in self.items]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (out,)))
        elif method == "GetProperty":
            item_id, name = args
            value = self.items[item_id].props().get(name) if item_id in self.items else None
            if value is None:
                invocation.return_dbus_error("com.canonical.dbusmenu.UnknownId", "no such property")
            else:
                invocation.return_value(GLib.Variant("(v)", (value,)))
        elif method == "Event":
            item_id, event, _, _ = args
            invocation.return_value(None)
            if event == "clicked":
                self._clicked(item_id)
        elif method == "EventGroup":
            errors = []
            for item_id, event, _, _ in args[0]:
                if item_id not in self.items:
                    errors.append(item_id)
                elif event == "clicked":
                    self._clicked(item_id)
            invocation.return_value(GLib.Variant("(ai)", (errors,)))
        elif method == "AboutToShow":
            # The minutes to the next signal to anyone, the pause line: fresh on every opening.
            self._build()
            invocation.return_value(GLib.Variant("(b)", (True,)))
            self._emit(MENU_PATH, "com.canonical.dbusmenu", "LayoutUpdated", GLib.Variant("(ui)", (self.revision, 0)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _clicked(self, item_id):
        item = self.items.get(item_id)
        if item is not None and item.action is not None and item.enabled:
            # After the menu has closed, so a window it opens gets the focus.
            GLib.idle_add(lambda: item.action() and False)

