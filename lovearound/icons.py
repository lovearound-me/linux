"""The heart, drawn with cairo: for the tray, the menu's color dots and the app icon."""
import io
import math

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


def tray_surface(px, color=None, paused=False):
    """Pink by default, the signal color for a moment, grey and crossed out on pause."""
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
