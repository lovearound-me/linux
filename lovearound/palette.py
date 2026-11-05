"""The twelve warm colors and the windows' paper and ink, light and dark.

`color` for rings and the glow, `tint` for row backgrounds, `deep` for text on
the tint. Colors may repeat between contacts: they are labels in the menu, a
signal never says who sent it.
"""
from collections import namedtuple

from .i18n import N_, tr


class PaletteColor(namedtuple("PaletteColor", "key color tint deep")):
    @property
    def name(self):
        """In the current language: it can change while the app runs."""
        return tr(self.key)

ALL = [
    PaletteColor(N_("Коралловый"), 0xF07A62, 0xFDE6E0, 0xA8402B),
    PaletteColor(N_("Розовый"), 0xE86A9A, 0xFBE2EC, 0xA3305E),
    PaletteColor(N_("Голубой"), 0x4E9BD8, 0xE0EEF9, 0x22679E),
    PaletteColor(N_("Шалфей"), 0x6FAE7C, 0xE3F1E6, 0x39744A),
    PaletteColor(N_("Лавандовый"), 0x9B83DD, 0xECE6FA, 0x5E45A3),
    PaletteColor(N_("Медовый"), 0xE5A93B, 0xFBF0DA, 0x8A5E0E),
    PaletteColor(N_("Бирюзовый"), 0x3FB3A8, 0xDDF3F0, 0x1D6F68),
    # Appended, not merged in: indices are what settings store.
    PaletteColor(N_("Вишнёвый"), 0xC94A5E, 0xF8E1E5, 0x8E2638),
    PaletteColor(N_("Карамельный"), 0xC98B5E, 0xF6E9DE, 0x7D4F2C),
    PaletteColor(N_("Оливковый"), 0x9DA24A, 0xEEF0DC, 0x5C601F),
    PaletteColor(N_("Индиго"), 0x6474D6, 0xE4E7F8, 0x3640A0),
    PaletteColor(N_("Грифельный"), 0x7E8C99, 0xE8ECEF, 0x46525E),
]

STAR = 0xF2C46B
DARK_PAPER = 0x2A211D


def at(index):
    return ALL[index % len(ALL)]


def mix(a, b, t):
    """`a` with `t` of it turned into `b`, channel by channel."""
    out = 0
    for shift in (16, 8, 0):
        x, y = (a >> shift) & 0xFF, (b >> shift) & 0xFF
        out |= round(x + (y - x) * t) << shift
    return out


def rgb(hex_):
    return ((hex_ >> 16) & 0xFF) / 255, ((hex_ >> 8) & 0xFF) / 255, (hex_ & 0xFF) / 255


def css_hex(hex_):
    return "#%06x" % hex_


# Warm paper and brown ink; at night, dark cocoa and cream.
UI = {
    "ink": (0x3B2A23, 0xF3E6DC),
    "muted": (0x6E554A, 0xC7B0A2),
    "faint": (0x7A6156, 0xA8917F),
    "paper": (0xFFFBF6, DARK_PAPER),
    "field": (0xF8EFE6, 0x372C27),
    "well": (0xF2E6DA, 0x40342E),
    "raised": (0xFFFBF6, 0x5A4A42),
    "input": (0xFFFFFF, 0x221B18),
    "link": (0xB83A4E, 0xF28C9B),
    "heart": (0xE0596B, 0xEC6F80),
    "heartSoft": (0xFDE3E6, 0x4A2B31),
    "heartDeep": (0x8E2537, 0xFFB8C2),
    "ok": (0x39744A, 0x8DCB9B),
    "danger": (0xB3261E, 0xFF8A80),
    "star": (0xD99A1E, 0xE8B54F),
    "starOff": (0xB9A596, 0x7D6A5E),
    "anyone0": (0xFBE3D2, 0x4A3226),
    "anyone1": (0xFCE6EA, 0x4A2C33),
    "anyone2": (0xF3E4F3, 0x3E2C40),
}


def ui(name, dark):
    return UI[name][1 if dark else 0]


def tint(color, dark):
    """The row background: the pastel tint on light paper, a dim wash of the color on dark."""
    return mix(color.color, DARK_PAPER, 0.3) if dark else color.tint


def deep(color, dark):
    """Text on the tint."""
    return mix(color.color, 0xFFFFFF, 0.45) if dark else color.deep
