"""The incoming-signal effect as numbers and cairo: a glow along the screen
edges and emoji floating up. Shared by the layer-shell and X11 overlays; the
GNOME Shell extension has the same math in JavaScript."""
import random

import cairo

GLOW_DURATION = 2.6

# What floats up with every signal, all mixed: hearts among hugs, cats and
# the rest, so it reads as care from anyone close, not only love.
WARM = [
    "❤️", "🧡", "💛", "💚", "💙", "💜", "💖", "💕", "💗", "🩷", "🩵",  # hearts
    "🫂", "🤗", "🫶", "🥰", "😊", "☺️",  # hugs and smiles
    "😺", "😸", "😻", "😽", "🐈", "🐱",  # cats
    "🐶", "🐻", "🐼", "🦔", "🐰", "🦊", "🐥", "🧸",  # more animals
    "💪", "🙌", "👍", "✊", "👏",  # you've got this
    "☀️", "🌻", "🌷", "🌸", "🌼", "🌈", "🍀", "✨", "⭐️",  # sun and flowers
    "☕️", "🍵", "🍪", "🍰", "🍓", "🎈",  # tea and treats
]
# What the sender of a signal to anyone sees; the person who gets it sees the
# usual mix, as from someone close.
STARS = ["⭐️", "🌟", "✨", "💫"]
SETS = {"warm": WARM, "stars": STARS}

# Three flashes in 2.6 s, about 1 Hz: well below the 3 Hz flash limit.
FLASH = ([0, 1, 0.25, 1, 0.25, 1, 0], [0, 0.12, 0.28, 0.45, 0.61, 0.78, 1])
CALM = ([0, 0.7, 0.7, 0], [0, 0.3, 0.7, 1])
FADE = ([0, 1, 1, 0], [0, 0.1, 0.8, 1])


def ease_in_out(x):
    return cubic_bezier(0.42, 0, 0.58, 1, x)


def cubic_bezier(x1, y1, x2, y2, x):
    """CSS cubic-bezier timing: y for progress x."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lo, hi = 0.0, 1.0
    t = x
    for _ in range(30):
        cx = 3 * x1 * t * (1 - t) ** 2 + 3 * x2 * t * t * (1 - t) + t ** 3
        if abs(cx - x) < 1e-5:
            break
        if cx < x:
            lo = t
        else:
            hi = t
        t = (lo + hi) / 2
    return 3 * y1 * t * (1 - t) ** 2 + 3 * y2 * t * t * (1 - t) + t ** 3


def keyframes(values, times, x, ease=None):
    """The value at progress x, segment by segment."""
    if x <= times[0]:
        return values[0]
    for i in range(1, len(times)):
        if x <= times[i]:
            f = (x - times[i - 1]) / (times[i] - times[i - 1])
            if ease:
                f = ease(f)
            return values[i - 1] + (values[i] - values[i - 1]) * f
    return values[-1]


def glow_alpha(t, calm):
    values, times = CALM if calm else FLASH
    return keyframes(values, times, t / GLOW_DURATION, ease_in_out)


def rise_timing(x):
    return cubic_bezier(0.22, 0.7, 0.3, 1, x)


class Particle:
    """One emoji: where it starts, how far it rises, how it sways."""

    def __init__(self, width, height, glyph, rnd=random):
        self.glyph = glyph
        self.size = rnd.uniform(24, 46)
        self.duration = rnd.uniform(3, 4.6)
        self.delay = rnd.uniform(0, 1.3)
        self.x = rnd.uniform(width * 0.04, width * 0.92)
        self.rise = height * rnd.uniform(0.45, 0.9)
        self.drift = rnd.uniform(-60, 60)
        self.sway = rnd.uniform(14, 30) * rnd.choice((1, -1))
        self.tilt = rnd.uniform(0.1, 0.28)
        self.height = height

    @property
    def end(self):
        return self.delay + self.duration

    def at(self, t):
        """(x, y, alpha, scale, angle) at t seconds, y down from the top; None before and after."""
        local = (t - self.delay) / self.duration
        if local < 0 or local > 1:
            return None
        p = rise_timing(local)
        # Start below the bottom edge, rise on a smooth S.
        h, s = self.height, self.size
        p0 = (self.x, h + s)
        p1 = (self.x + self.sway, h - self.rise * 0.35)
        p2 = (self.x + self.drift - self.sway, h - self.rise * 0.7)
        p3 = (self.x + self.drift, h - self.rise)
        u = 1 - p
        x = u ** 3 * p0[0] + 3 * u * u * p * p1[0] + 3 * u * p * p * p2[0] + p ** 3 * p3[0]
        y = u ** 3 * p0[1] + 3 * u * u * p * p1[1] + 3 * u * p * p * p2[1] + p ** 3 * p3[1]
        alpha = keyframes(*FADE, p)
        scale = 0.6 + 0.4 * p
        angle = keyframes([0, self.tilt, -self.tilt, 0], [0, 0.35, 0.65, 1], p)
        return x, y, alpha, scale, angle


class Effect:
    """One signal on one screen."""

    def __init__(self, color, emoji, count, calm, width, height, rnd=random):
        self.color = color
        self.calm = calm
        chars = SETS.get(emoji, emoji) if isinstance(emoji, str) else emoji
        n = 0 if calm or not chars else max(0, int(count))
        self.particles = [Particle(width, height, rnd.choice(chars), rnd) for _ in range(n)]
        self.duration = max([GLOW_DURATION] + [p.end for p in self.particles])


def draw_glow(cr, width, height, color, alpha):
    """A soft haze fading inward from the edges, with no crisp frame line,
    like `box-shadow: inset 0 0 44px 12px color/.9`."""
    if alpha <= 0.001:
        return
    r, g, b = ((color >> 16) & 0xFF) / 255, ((color >> 8) & 0xFF) / 255, (color & 0xFF) / 255
    band = 60.0
    stops = ((0, 0.9), (0.2, 0.72), (0.55, 0.28), (1, 0))
    for x0, y0, x1, y1, rect in (
        (0, 0, 0, band, (0, 0, width, band)),
        (0, height, 0, height - band, (0, height - band, width, band)),
        (0, 0, band, 0, (0, 0, band, height)),
        (width, 0, width - band, 0, (width - band, 0, band, height)),
    ):
        gradient = cairo.LinearGradient(x0, y0, x1, y1)
        for offset, a in stops:
            gradient.add_color_stop_rgba(offset, r, g, b, a * alpha)
        cr.set_source(gradient)
        cr.rectangle(*rect)
        cr.fill()


class EmojiCache:
    """Each glyph drawn once per size into a small surface; color emoji come
    from the font (Noto Color Emoji on Ubuntu)."""

    def __init__(self):
        self.surfaces = {}

    def get(self, glyph, px):
        key = (glyph, int(px))
        surface = self.surfaces.get(key)
        if surface is None:
            surface = self.surfaces[key] = _render(glyph, int(px))
        return surface


def _render(glyph, px):
    from gi.repository import Pango, PangoCairo

    side = int(px * 1.5)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, side, side)
    cr = cairo.Context(surface)
    layout = PangoCairo.create_layout(cr)
    font = Pango.FontDescription.from_string("Noto Color Emoji")
    font.set_absolute_size(px * Pango.SCALE)
    layout.set_font_description(font)
    layout.set_text(glyph, -1)
    _, logical = layout.get_pixel_extents()
    cr.move_to((side - logical.width) / 2 - logical.x, (side - logical.height) / 2 - logical.y)
    PangoCairo.show_layout(cr, layout)
    surface.flush()
    return surface


def draw(cr, effect, t, width, height, cache, scale=1):
    """The whole frame at t seconds."""
    if t < GLOW_DURATION:
        draw_glow(cr, width, height, effect.color, glow_alpha(t, effect.calm))
    for particle in effect.particles:
        state = particle.at(t)
        if state is None:
            continue
        x, y, alpha, grow, angle = state
        surface = cache.get(particle.glyph, particle.size * scale)
        side = surface.get_width() / scale
        cr.save()
        cr.translate(x, y)
        cr.rotate(angle)
        cr.scale(grow / scale, grow / scale)
        cr.set_source_surface(surface, -side * scale / 2, -side * scale / 2)
        cr.paint_with_alpha(alpha)
        cr.restore()
