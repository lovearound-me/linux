"""The heart, drawn with cairo: for the tray, the menu's color dots and the app icon.
And the marks of the ways to sign in: Google, Apple, an envelope."""
import io
import math
import re

import cairo

from . import palette


def heart_path(cr, cx, cy, size):
    """A heart centered on (cx, cy), `size` wide."""
    s = size / 2
    cr.move_to(cx, cy + s * 0.85)
    cr.curve_to(cx - s * 0.2, cy + s * 0.65, cx - s, cy + s * 0.15, cx - s, cy - s * 0.3)
    cr.curve_to(cx - s, cy - s * 0.8, cx - s * 0.45, cy - s * 0.95, cx, cy - s * 0.5)
    cr.curve_to(cx + s * 0.45, cy - s * 0.95, cx + s, cy - s * 0.8, cx + s, cy - s * 0.3)
    cr.curve_to(cx + s, cy + s * 0.15, cx + s * 0.2, cy + s * 0.65, cx, cy + s * 0.85)
    cr.close_path()


# Apple's logo in a 24×24 box, the same path as the web app's: only M, relative c and z.
APPLE = ("M16.37 12.6c-.02-2.3 1.88-3.4 1.96-3.46-1.07-1.56-2.73-1.78-3.32-1.8-1.41-.14-2.76.83-3.47.83-.72 0-1.82-.81"
         "-2.99-.79-1.54.02-2.96.9-3.75 2.27-1.6 2.78-.41 6.88 1.15 9.13.76 1.1 1.67 2.33 2.86 2.29 1.15-.05 1.58-.74 2.97"
         "-.74 1.38 0 1.78.74 2.99.72 1.24-.02 2.02-1.12 2.77-2.22.87-1.28 1.23-2.52 1.25-2.58-.03-.01-2.4-.92-2.42-3.65z"
         "M14.1 5.86c.63-.77 1.06-1.83.94-2.89-.91.04-2.02.61-2.67 1.37-.58.67-1.1 1.76-.96 2.8 1.02.08 2.06-.52 2.69-1.28z")


def apple_path(cr, x, y, size):
    """Apple's logo in the size×size box at (x, y), as a path to fill."""
    cr.save()
    cr.translate(x, y)
    cr.scale(size / 24, size / 24)
    command, numbers = None, []
    for token in re.findall(r"[Mcz]|-?(?:\d+\.?\d*|\.\d+)", APPLE):
        if token in "Mcz":
            command, numbers = token, []
            if token == "z":
                cr.close_path()
            continue
        numbers.append(float(token))
        if command == "M" and len(numbers) == 2:
            cr.move_to(*numbers)
            numbers = []
        elif command == "c" and len(numbers) == 6:
            cr.rel_curve_to(*numbers)
            numbers = []
    cr.restore()


def google_mark(cr, cx, cy, size):
    """Google's "G" in its four colors, centered on (cx, cy)."""
    line = size * 0.22
    r = (size - line) / 2
    cr.set_line_width(line)
    # Clockwise from three o'clock, in turns: blue, green, yellow, red, and the gap.
    for start, end, color in ((0, 0.12, 0x4285F4), (0.12, 0.40, 0x34A853), (0.40, 0.60, 0xFBBC05), (0.60, 0.875, 0xEA4335)):
        cr.new_path()
        cr.arc(cx, cy, r, start * 2 * math.pi, end * 2 * math.pi)
        cr.set_source_rgb(*palette.rgb(color))
        cr.stroke()
    cr.rectangle(cx, cy - line / 2, size / 2, line)
    cr.set_source_rgb(*palette.rgb(0x4285F4))
    cr.fill()


def mail_mark(cr, x, y, size):
    """An envelope in the size×size box at (x, y), as a path to stroke."""
    k = size / 24
    w, h, r = 20 * k, 16 * k, 2.5 * k
    left, top = x + 2 * k, y + 4 * k
    cr.new_sub_path()
    cr.arc(left + w - r, top + r, r, -math.pi / 2, 0)
    cr.arc(left + w - r, top + h - r, r, 0, math.pi / 2)
    cr.arc(left + r, top + h - r, r, math.pi / 2, math.pi)
    cr.arc(left + r, top + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()
    cr.move_to(x + 2.5 * k, y + 6.5 * k)
    cr.line_to(x + 12 * k, y + 13 * k)
    cr.line_to(x + 21.5 * k, y + 6.5 * k)


def arrow_mark(cr, x, y, size):
    """↗, a link that opens in the browser, as a path to stroke."""
    k = size / 24
    cr.move_to(x + 7 * k, y + 17 * k)
    cr.line_to(x + 17 * k, y + 7 * k)
    cr.move_to(x + 8 * k, y + 7 * k)
    cr.line_to(x + 17 * k, y + 7 * k)
    cr.line_to(x + 17 * k, y + 16 * k)


def update_mark(cr, cx, cy, r):
    """A new release to install: a white arrow down onto a line, "download", in a green circle."""
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.set_source_rgb(*palette.rgb(palette.UPDATE))
    cr.fill()
    a = r * 0.55
    cr.set_source_rgb(1, 1, 1)
    cr.set_line_width(max(1.2, r * 0.29))
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.move_to(cx, cy - a)
    cr.line_to(cx, cy + a * 0.35)
    cr.stroke()
    cr.move_to(cx - a * 0.6, cy - a * 0.2)
    cr.line_to(cx, cy + a * 0.4)
    cr.line_to(cx + a * 0.6, cy - a * 0.2)
    cr.stroke()
    cr.move_to(cx - a * 0.75, cy + a * 0.95)
    cr.line_to(cx + a * 0.75, cy + a * 0.95)
    cr.stroke()


def update_png(px=32):
    """The update mark alone, for the menu's "Обновить до …"."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
    update_mark(cairo.Context(surface), px / 2, px / 2, px / 2 - 1)
    surface.flush()
    return png_bytes(surface)


def tray_surface(px, color=None, paused=False, update=False):
    """Pink by default, the signal color for a moment, grey and crossed out on pause;
    `update` puts the update mark on its lower right corner."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
    cr = cairo.Context(surface)
    fill = 0x9C8F88 if paused else (color if color is not None else 0xE0596B)
    heart_path(cr, px / 2, px / 2 + px * 0.04, px * 0.86)
    cr.set_source_rgb(*palette.rgb(fill))
    cr.fill_preserve()
    # A light rim keeps it visible on a dark panel and a light one alike.
    cr.set_line_width(max(1.0, px / 22))
    cr.set_source_rgba(1, 1, 1, 0.55)
    cr.stroke()
    if paused:
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_width(max(1.5, px / 11))
        cr.set_source_rgba(1, 1, 1, 0.95)
        cr.move_to(px * 0.2, px * 0.2)
        cr.line_to(px * 0.8, px * 0.8)
        cr.stroke()
    if update:
        r = px * 0.25
        c = px - r - px * 0.01
        # A light ring keeps the mark apart from the heart, whatever its color.
        cr.arc(c, c, r + max(1.0, px / 22), 0, 2 * math.pi)
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.fill()
        update_mark(cr, c, c, r)
    surface.flush()
    return surface


def argb_bytes(surface):
    """Cairo's native premultiplied pixels as StatusNotifierItem wants them:
    A, R, G, B bytes per pixel, not premultiplied."""
    width, height, stride = surface.get_width(), surface.get_height(), surface.get_stride()
    data = bytes(surface.get_data())
    out = bytearray(width * height * 4)
    little = memoryview(b"\x01\x00").cast("H")[0] == 1
    o = 0
    for y in range(height):
        row = y * stride
        for x in range(width):
            i = row + x * 4
            if little:
                b, g, r, a = data[i], data[i + 1], data[i + 2], data[i + 3]
            else:
                a, r, g, b = data[i], data[i + 1], data[i + 2], data[i + 3]
            if a and a < 255:
                r, g, b = (min(255, c * 255 // a) for c in (r, g, b))
            out[o:o + 4] = bytes((a, r, g, b))
            o += 4
    return bytes(out)


def png_bytes(surface):
    buf = io.BytesIO()
    surface.write_to_png(buf)
    return buf.getvalue()


def dot_png(color, letter="", px=32):
    """A contact's color as a ringed circle with the first letter, for the tray menu."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
    cr = cairo.Context(surface)
    cr.arc(px / 2, px / 2, px / 2 - 1.5, 0, 2 * math.pi)
    cr.set_source_rgb(*palette.rgb(color.tint))
    cr.fill_preserve()
    cr.set_line_width(3)
    cr.set_source_rgb(*palette.rgb(color.color))
    cr.stroke()
    if letter:
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(px * 0.45)
        ext = cr.text_extents(letter)
        cr.move_to(px / 2 - ext.x_bearing - ext.width / 2, px / 2 - ext.y_bearing - ext.height / 2)
        cr.set_source_rgb(*palette.rgb(color.deep))
        cr.show_text(letter)
    surface.flush()
    return png_bytes(surface)


def star_png(px=32, on=True):
    """"Кому-нибудь на свете": sparkles on peach."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
    cr = cairo.Context(surface)
    gradient = cairo.LinearGradient(0, 0, px, px)
    for offset, hex_ in ((0, 0xFBE3D2), (0.5, 0xFCE6EA), (1, 0xF3E4F3)):
        gradient.add_color_stop_rgb(offset, *palette.rgb(hex_))
    cr.arc(px / 2, px / 2, px / 2 - 1.5, 0, 2 * math.pi)
    cr.set_source(gradient)
    cr.fill_preserve()
    star = 0xD99A1E if on else 0xB9A596
    cr.set_line_width(3)
    cr.set_source_rgb(*palette.rgb(star))
    cr.stroke()
    sparkle(cr, px * 0.46, px * 0.54, px * 0.3, star)
    sparkle(cr, px * 0.7, px * 0.3, px * 0.14, star)
    surface.flush()
    return png_bytes(surface)


def sparkle(cr, cx, cy, r, color):
    """A four-pointed star."""
    w = r * 0.28
    cr.move_to(cx, cy - r)
    cr.curve_to(cx + w * 0.3, cy - w, cx + w, cy - w * 0.3, cx + r, cy)
    cr.curve_to(cx + w, cy + w * 0.3, cx + w * 0.3, cy + w, cx, cy + r)
    cr.curve_to(cx - w * 0.3, cy + w, cx - w, cy + w * 0.3, cx - r, cy)
    cr.curve_to(cx - w, cy - w * 0.3, cx - w * 0.3, cy - w, cx, cy - r)
    cr.close_path()
    cr.set_source_rgb(*palette.rgb(color))
    cr.fill()


def app_icon(px):
    """A warm rounded square with a white heart, like the Mac icon."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
    cr = cairo.Context(surface)
    inset, radius = px * 100 / 1024, px * 185 / 1024
    x0, y0, x1, y1 = inset, inset, px - inset, px - inset
    cr.new_sub_path()
    cr.arc(x1 - radius, y0 + radius, radius, -math.pi / 2, 0)
    cr.arc(x1 - radius, y1 - radius, radius, 0, math.pi / 2)
    cr.arc(x0 + radius, y1 - radius, radius, math.pi / 2, math.pi)
    cr.arc(x0 + radius, y0 + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()
    gradient = cairo.LinearGradient(0, y0, 0, y1)
    gradient.add_color_stop_rgb(0, 0.96, 0.52, 0.47)
    gradient.add_color_stop_rgb(1, 0.85, 0.30, 0.43)
    cr.set_source(gradient)
    cr.fill()
    heart_path(cr, px / 2, px / 2 + px * 0.01, px * 0.46)
    cr.set_source_rgb(1, 0.98, 0.96)
    cr.fill()
    surface.flush()
    return surface
