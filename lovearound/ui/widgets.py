"""Small pieces the windows share: circles drawn by hand (cairo draws a ring
the same on every theme), captions, notes, switch rows, the swatch grid and
the Love ID card."""
import math

import cairo
from gi.repository import GLib, Gtk, Pango, PangoCairo

from .. import icons, palette
from . import style
from ..i18n import tr


def label(text="", *classes, wrap=False, xalign=0.0, ellipsize=False, selectable=False, width_chars=None):
    widget = Gtk.Label(label=text, xalign=xalign)
    for name in classes:
        widget.get_style_context().add_class(name)
    if wrap:
        widget.set_line_wrap(True)
        widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        widget.set_max_width_chars(width_chars or 40)
    if ellipsize:
        widget.set_ellipsize(Pango.EllipsizeMode.END if ellipsize is True else ellipsize)
    if selectable:
        widget.set_selectable(True)
    return widget


def caption(text):
    return label(text, "caption")


def note(text):
    """The small grey explanation under a setting."""
    return label(text, "note", wrap=True)


def classes(widget, *names):
    for name in names:
        widget.get_style_context().add_class(name)
    return widget


def button(text, *names, action=None, tooltip=None):
    widget = Gtk.Button(label=text)
    widget.set_relief(Gtk.ReliefStyle.NONE)
    widget.set_can_focus(True)
    classes(widget, *names)
    if tooltip:
        widget.set_tooltip_text(tooltip)
    if action:
        widget.connect("clicked", lambda _: action())
    return widget


def icon_button(icon, tooltip, action):
    widget = Gtk.Button()
    widget.set_relief(Gtk.ReliefStyle.NONE)
    widget.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU))
    widget.set_tooltip_text(tooltip)
    classes(widget, "icon")
    widget.connect("clicked", lambda _: action())
    return widget


def link_row(icon, title, action):
    widget = Gtk.Button()
    widget.set_relief(Gtk.ReliefStyle.NONE)
    box = Gtk.Box(spacing=8)
    image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)
    box.pack_start(image, False, False, 0)
    box.pack_start(label(title, "link"), False, False, 0)
    widget.add(box)
    classes(widget, "textlink")
    widget.set_size_request(-1, 28)
    widget.connect("clicked", lambda _: action())
    return widget


def vbox(spacing=0, *children):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    for child in children:
        if child is not None:
            box.pack_start(child, False, False, 0)
    return box


def hbox(spacing=0, *children):
    box = Gtk.Box(spacing=spacing)
    for child in children:
        if child is not None:
            box.pack_start(child, False, False, 0)
    return box


def clear(container):
    for child in container.get_children():
        child.destroy()


def first_letter(text):
    text = (text or "").strip()
    return text[0].upper() if text else "♥"


def later(ms, fn):
    """fn() once after ms; returns the source id."""
    def run():
        fn()
        return False
    return GLib.timeout_add(ms, run)


# ---- drawn circles -----------------------------------------------------------------

def _rgb(cr, hex_, alpha=1.0):
    r, g, b = palette.rgb(hex_)
    cr.set_source_rgba(r, g, b, alpha)


def _text(cr, widget, text, size_px, weight, hex_, cx, cy):
    layout = PangoCairo.create_layout(cr)
    font = Pango.FontDescription.from_string(widget.get_pango_context().get_font_description().get_family() or "Sans")
    font.set_absolute_size(size_px * Pango.SCALE)
    font.set_weight(weight)
    layout.set_font_description(font)
    layout.set_text(text, -1)
    _, logical = layout.get_pixel_extents()
    _rgb(cr, hex_)
    cr.move_to(cx - logical.width / 2 - logical.x, cy - logical.height / 2 - logical.y)
    PangoCairo.show_layout(cr, layout)


class Circle(Gtk.DrawingArea):
    """A ring of the palette color around a letter: avatars, the menu's
    circles (`filled` for the tinted fill), and the "+"."""

    def __init__(self, size, text="", color=None, filled=False, ring=3.0):
        super().__init__()
        self.size = size
        self.text = text
        self.color = color
        self.filled = filled
        self.ring = ring
        self.sent = False
        self.hover = False
        self.dashed = False
        self.set_size_request(size + 6, size + 6)
        self.connect("draw", self._draw)

    def update(self, **values):
        for key, value in values.items():
            setattr(self, key, value)
        self.queue_draw()

    def _draw(self, widget, cr):
        width, height = self.get_allocated_width(), self.get_allocated_height()
        cx, cy = width / 2, height / 2
        scale = 1.08 if (self.sent or self.hover) and self.filled else 1.0
        r = self.size / 2 * scale
        dark = style.dark()
        if self.dashed:
            cr.set_line_width(1.5)
            cr.set_dash([4, 3])
            _rgb(cr, palette.ui("starOff", dark))
            cr.arc(cx, cy, r - 0.75, 0, 2 * math.pi)
            cr.stroke()
            cr.set_dash([])
            _text(cr, widget, "+", self.size * 0.42, Pango.Weight.MEDIUM, palette.ui("faint", dark), cx, cy)
            return
        color = self.color
        if self.filled:
            fill = color.color if self.sent else palette.tint(color, dark)
        else:
            fill = palette.ui("paper", dark)
        _rgb(cr, fill)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.fill()
        cr.set_line_width(self.ring)
        _rgb(cr, color.color)
        cr.arc(cx, cy, r - self.ring / 2, 0, 2 * math.pi)
        cr.stroke()
        if self.sent:
            text, ink = "♥", palette.ui("paper", dark)
        else:
            text, ink = first_letter(self.text), palette.deep(color, dark)
        _text(cr, widget, text, self.size * (0.36 if self.filled else 0.41), Pango.Weight.BOLD, ink, cx, cy)


class AnyoneCircle(Gtk.DrawingArea):
    """"Кому-нибудь на свете": sparkles on a warm gradient; the ring fills back up over the hour."""

    def __init__(self, size=50):
        super().__init__()
        self.size = size
        self.wait = None
        self.hover = False
        self.sending = False
        self.set_size_request(size + 6, size + 6)
        self.connect("draw", self._draw)

    def update(self, **values):
        for key, value in values.items():
            setattr(self, key, value)
        self.queue_draw()

    def _draw(self, widget, cr):
        width, height = self.get_allocated_width(), self.get_allocated_height()
        cx, cy = width / 2, height / 2
        r = self.size / 2 * (1.08 if self.hover else 1.0)
        dark = style.dark()
        if self.sending:
            cr.push_group()
        gradient = cairo.LinearGradient(cx - r, cy - r, cx + r, cy + r)
        for stop, name in ((0, "anyone0"), (0.5, "anyone1"), (1, "anyone2")):
            gradient.add_color_stop_rgb(stop, *palette.rgb(palette.ui(name, dark)))
        cr.set_source(gradient)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.fill()
        star = palette.ui("star", dark)
        cr.set_line_width(3)
        _rgb(cr, star, 1.0 if self.wait is None else 0.25)
        cr.arc(cx, cy, r - 1.5, 0, 2 * math.pi)
        cr.stroke()
        if self.wait is not None:
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            _rgb(cr, star)
            cr.arc(cx, cy, r - 1.5, -math.pi / 2, -math.pi / 2 + 2 * math.pi * (60 - self.wait) / 60)
            cr.stroke()
        ink = star if self.wait is None else palette.ui("starOff", dark)
        s = self.size
        icons.sparkle(cr, cx - s * 0.04, cy + s * 0.05, s * 0.2, ink)
        icons.sparkle(cr, cx + s * 0.17, cy - s * 0.15, s * 0.09, ink)
        icons.sparkle(cr, cx - s * 0.17, cy - s * 0.17, s * 0.06, ink)
        if self.sending:
            cr.pop_group_to_source()
            cr.paint_with_alpha(0.6)


class Swatch(Gtk.DrawingArea):
    def __init__(self, index, size):
        super().__init__()
        self.index = index
        self.size = size
        self.selected = False
        self.set_size_request(size + 6, size + 6)
        self.connect("draw", self._draw)

    def _draw(self, widget, cr):
        width, height = self.get_allocated_width(), self.get_allocated_height()
        cx, cy = width / 2, height / 2
        color = palette.at(self.index).color
        _rgb(cr, color)
        cr.arc(cx, cy, self.size / 2, 0, 2 * math.pi)
        cr.fill()
        if self.selected:
            cr.set_line_width(2)
            cr.arc(cx, cy, self.size / 2 + 2, 0, 2 * math.pi)
            cr.stroke()


def circle_button(child, tooltip, action):
    widget = Gtk.Button()
    widget.set_relief(Gtk.ReliefStyle.NONE)
    widget.add(child)
    classes(widget, "bare")
    widget.set_tooltip_text(tooltip)
    widget.connect("clicked", lambda _: action())
    if hasattr(child, "hover"):
        widget.connect("enter-notify-event", lambda *_: child.update(hover=True))
        widget.connect("leave-notify-event", lambda *_: child.update(hover=False))
    return widget


class SwatchPicker(Gtk.Grid):
    """Twelve colors in two rows of six."""

    def __init__(self, selected, size, on_change):
        super().__init__(column_spacing=10, row_spacing=6)
        self.on_change = on_change
        self.swatches = []
        for index, color in enumerate(palette.ALL):
            swatch = Swatch(index, size)
            self.swatches.append(swatch)
            widget = circle_button(swatch, color.name, lambda i=index: self.select(i, notify=True))
            self.attach(widget, index % 6, index // 6, 1, 1)
        self.select(selected)

    def select(self, index, notify=False):
        self.selected = index
        for swatch in self.swatches:
            swatch.selected = swatch.index == index
            swatch.queue_draw()
        if notify:
            self.on_change(index)


def field(title, entry):
    entry.get_style_context().add_class("field")
    return vbox(6, caption(title), entry)


def entry(placeholder="", text="", password=False):
    widget = Gtk.Entry()
    widget.set_placeholder_text(placeholder)
    widget.set_text(text)
    if password:
        widget.set_visibility(False)
        widget.set_input_purpose(Gtk.InputPurpose.PASSWORD)
    widget.set_size_request(-1, 34)
    return widget


def search_entry(placeholder):
    widget = Gtk.SearchEntry()
    widget.set_placeholder_text(placeholder)
    widget.set_size_request(-1, 32)
    return widget


class SwitchRow(Gtk.Box):
    """Title on the left, switch on the right edge."""

    def __init__(self, title, active, on_toggle):
        super().__init__(spacing=8)
        classes(self, "switchrow")
        self.set_size_request(-1, 40)
        self.pack_start(label(title, wrap=True), True, True, 0)
        self.switch = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
        self.pack_end(self.switch, False, False, 0)
        self._handler = self.switch.connect("notify::active", lambda s, _: on_toggle(s.get_active()))

    def set_active(self, active):
        if self.switch.get_active() != active:
            self.switch.handler_block(self._handler)
            self.switch.set_active(active)
            self.switch.handler_unblock(self._handler)


def pad(widget, padding):
    """Inner space that a CSS background covers (a border width is left outside it)."""
    for side in ("top", "bottom", "start", "end"):
        widget.set_property("margin-" + side, padding)
    return widget


def card(*children, padding=0, spacing=0, cls="card"):
    box = vbox(spacing, *children)
    if not padding:
        classes(box, cls)
        return box
    outer = vbox(0, pad(box, padding))
    classes(outer, cls)
    return outer


def banner(icon, text, trailing=None):
    box = Gtk.Box(spacing=8)
    classes(box, "banner")
    image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)
    image.get_style_context().add_class("muted")
    image.set_valign(Gtk.Align.START)
    box.pack_start(image, False, False, 0)
    box.pack_start(label(text, "muted", "small", wrap=True, width_chars=30), True, True, 0)
    if trailing:
        trailing.set_valign(Gtk.Align.START)
        box.pack_end(trailing, False, False, 0)
    return box


def shown_link(link):
    """"lovearound.me/i/…" reads better than a URL."""
    return link.replace("https://", "").replace("http://", "")


class HeartDot(Gtk.DrawingArea):
    """The heart on a soft circle: the Love ID card's and the sign-in screen's."""

    def __init__(self, size, heart, soft, alpha=1.0):
        super().__init__()
        self.size, self.heart, self.soft, self.alpha = size, heart, soft, alpha
        self.set_size_request(size, size)
        self.connect("draw", self._draw)

    def _draw(self, widget, cr):
        width, height = self.get_allocated_width(), self.get_allocated_height()
        heart = palette.ui(self.heart, style.dark())
        if self.soft:
            _rgb(cr, palette.ui(self.soft, style.dark()))
        else:
            _rgb(cr, heart, 0.14)
        cr.arc(width / 2, height / 2, self.size / 2, 0, 2 * math.pi)
        cr.fill()
        icons.heart_path(cr, width / 2, height / 2 + self.size * 0.02, self.size * 0.46)
        _rgb(cr, heart)
        cr.fill()


class InviteRow(Gtk.Button):
    """The own link as one quiet card, copied on a click."""

    def __init__(self, model):
        super().__init__()
        self.model = model
        self.set_relief(Gtk.ReliefStyle.NONE)
        classes(self, "invite")
        self.set_tooltip_text(tr("Кто добавит тебя по этой ссылке, сможет нажимать, когда думает о тебе"))
        box = Gtk.Box(spacing=10)
        box.pack_start(HeartDot(28, "link", None), False, False, 0)
        text = vbox(1, label(tr("Твой Love ID"), "muted", "small"),
                    label(shown_link(model.invite_url or ""), ellipsize=Pango.EllipsizeMode.MIDDLE))
        box.pack_start(text, True, True, 0)
        self.action = label(tr("Скопировать"), "link", "small")
        box.pack_end(self.action, False, False, 0)
        self.add(box)
        self.connect("clicked", self._copy)
        self._reset = None

    def _copy(self, _):
        if not self.model.copy_invite():
            return
        self.action.set_text(tr("Скопировано ✓"))
        if self._reset:
            GLib.source_remove(self._reset)

        def back():
            self._reset = None
            self.action.set_text(tr("Скопировать"))
        self._reset = later(1500, back)
