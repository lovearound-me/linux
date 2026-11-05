"""What needs no display and no server: links, pauses, the effect, the icons."""
import datetime
import random
import time
import unittest

import cairo

from lovearound import effect, i18n, icons, model, palette, signinbox

i18n.set_language("ru")


class InviteTest(unittest.TestCase):
    def test_links_and_codes(self):
        for text in ("GSSV7-A33HN", "gssv7a33hn", " https://lovearound.me/i/GSSV7-A33HN ",
                     "lovearound://add/GSSV7-A33HN", "needed://add/GSSV7-A33HN", "https://lovearound.me/i/GSSV7-A33HN?from=mail#x"):
            self.assertIsNotNone(model.invite_id(text), text)
            self.assertEqual(model.bare(model.invite_id(text)), "GSSV7A33HN")

    def test_typos(self):
        # Too short, too long, and the letters the server never uses.
        for text in ("", None, "GSSV7-A33H", "GSSV7-A33HNN", "GSSV0-A33HN", "GSSV7-A33HL", "https://lovearound.me/"):
            self.assertIsNone(model.invite_id(text), text)


class WordsTest(unittest.TestCase):
    def test_people_count(self):
        self.assertEqual(model.people_count(1), "1 человек")
        self.assertEqual(model.people_count(2), "2 человека")
        self.assertEqual(model.people_count(5), "5 человек")
        self.assertEqual(model.people_count(12), "12 человек")
        self.assertEqual(model.people_count(23), "23 человека")

    def test_gaps(self):
        self.assertEqual(model.gap_index(1), 0)
        self.assertEqual(model.gap_index(17), model.GAPS.index(15))
        self.assertEqual(model.gap_title(5), "5 с")
        self.assertEqual(model.gap_title(900), "15 мин")
        self.assertEqual(model.gap_title(3600), "1 ч")


class PauseTest(unittest.TestCase):
    def test_until_morning(self):
        night = datetime.datetime(2026, 10, 30, 23, 15)
        self.assertEqual(model.until_morning(night), datetime.datetime(2026, 10, 31, 8, 0))
        early = datetime.datetime(2026, 10, 30, 6, 0)
        self.assertEqual(model.until_morning(early), datetime.datetime(2026, 10, 30, 8, 0))
        eight = datetime.datetime(2026, 10, 30, 8, 0)
        self.assertEqual(model.until_morning(eight), datetime.datetime(2026, 10, 31, 8, 0))


class EffectTest(unittest.TestCase):
    def test_glow_flashes_and_ends_dark(self):
        self.assertAlmostEqual(effect.glow_alpha(0, False), 0)
        self.assertAlmostEqual(effect.glow_alpha(effect.GLOW_DURATION, False), 0)
        peak = max(effect.glow_alpha(t / 100, False) for t in range(int(effect.GLOW_DURATION * 100)))
        self.assertGreater(peak, 0.95)
        # Calm: one soft swell, never the full flash.
        calm = max(effect.glow_alpha(t / 100, True) for t in range(int(effect.GLOW_DURATION * 100)))
        self.assertLess(calm, 0.75)

    def test_particles(self):
        fx = effect.Effect(0xE86A9A, "warm", 30, False, 1920, 1080, random.Random(1))
        self.assertEqual(len(fx.particles), 30)
        self.assertGreaterEqual(fx.duration, effect.GLOW_DURATION)
        for p in fx.particles:
            self.assertIsNone(p.at(p.delay - 0.01))
            x, y, alpha, scale, angle = p.at(p.delay + 0.001)
            # Starts below the bottom edge, ends risen and gone.
            self.assertGreater(y, 1080)
            last = p.at(p.delay + p.duration * 0.99999)
            self.assertLess(last[1], 1080 - p.rise + 1)
            self.assertAlmostEqual(last[2], 0, places=3)
            self.assertIsNone(p.at(p.end + 0.01))
        self.assertEqual(effect.Effect(0, "warm", 30, True, 100, 100).particles, [])

    def test_draw_paints_the_edges_only(self):
        width, height = 400, 300
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        cr = cairo.Context(surface)
        effect.draw_glow(cr, width, height, 0xE86A9A, 1.0)
        surface.flush()
        data = surface.get_data()
        stride = surface.get_stride()

        def alpha(x, y):
            return data[y * stride + x * 4 + 3]
        self.assertGreater(alpha(0, height // 2), 200)
        self.assertGreater(alpha(width // 2, 0), 200)
        self.assertEqual(alpha(width // 2, height // 2), 0)


class IconsTest(unittest.TestCase):
    def test_argb_unpremultiplied(self):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 2, 1)
        cr = cairo.Context(surface)
        cr.set_source_rgba(1, 0, 0, 0.5)
        cr.paint()
        surface.flush()
        out = icons.argb_bytes(surface)
        self.assertEqual(len(out), 8)
        a, r, g, b = out[:4]
        self.assertIn(a, (127, 128))
        self.assertGreater(r, 250)
        self.assertEqual((g, b), (0, 0))

    def test_icons_draw(self):
        for px in (16, 22, 32, 48):
            self.assertEqual(icons.tray_surface(px).get_width(), px)
        self.assertTrue(icons.dot_png(palette.at(0), "М").startswith(b"\x89PNG"))
        self.assertTrue(icons.star_png(on=False).startswith(b"\x89PNG"))
        self.assertEqual(icons.app_icon(64).get_width(), 64)


if __name__ == "__main__":
    unittest.main()


class SignInBoxTest(unittest.TestCase):
    # Sealed by the site's own code (site/src/signin/index.html, run in Node)
    # to this test-only key; the Mac and Windows tests open the same box.
    VECTOR = {
        "private_hex": "4c2a58504a9ae04a67d8f4ea50fd1f79943658449178467b6854456604816a29",
        "state": "TEST-STATE-0001",
        "epk": "BPGVN5XMnukYvRdgRHgIG9npiQ9dDmJh93RUP-HARwZY8WpuEJ0p3M1s40BK0zyhmSBi_bC_d9PggnPnV9SvmUE",
        "box": "nJB8DhyMR8ozaHyBDHHt6iXCFnYqjbcs-b39tBZVSjYV8CoVjf6xMtk5VXeXAoSYb895DC4vCFBw1KgUPaM6chi1kCMRjCSuwqvWHBb-ls8bxc1ElvhJIBo3iPUIuV35",
    }

    def key(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        key = signinbox.SignInKey()
        key._private = ec.derive_private_key(int(self.VECTOR["private_hex"], 16), ec.SECP256R1())
        return key

    def test_opens_what_the_site_sealed(self):
        v = self.VECTOR
        self.assertEqual(self.key().open(v["epk"], v["box"], v["state"]),
                         {"uid": "uid-42", "email": "hleb@example.com", "rt": "AMf-refresh-token"})

    def test_rejects_another_state_or_a_changed_box(self):
        v = self.VECTOR
        with self.assertRaises(ValueError):
            self.key().open(v["epk"], v["box"], "OTHER")
        flipped = v["box"][:20] + ("A" if v["box"][20] != "A" else "B") + v["box"][21:]
        with self.assertRaises(ValueError):
            self.key().open(v["epk"], flipped, v["state"])
        with self.assertRaises(ValueError):
            signinbox.SignInKey().open(v["epk"], v["box"], v["state"])

    def test_round_trip(self):
        key = signinbox.SignInKey()
        self.assertEqual(len(key.public), 87)
        sealed = signinbox.seal(key.public, "S", {"uid": "u", "rt": "r"})
        self.assertEqual(key.open(sealed["epk"], sealed["box"], "S"), {"uid": "u", "rt": "r"})


class TrayRegistrationTest(unittest.TestCase):
    """The watcher dropping our item while we're alive makes us register again."""

    def test_registers_again_when_dropped(self):
        from gi.repository import GLib
        from lovearound import tray

        class Connection:
            calls = []

            def get_unique_name(self):
                return ":1.109"

            def call(self, *args):
                self.calls.append(args[3])

        class Model:
            pass

        t = tray.Tray(Model(), {})
        c = Connection()
        t.registered = True
        t._unregistered(c, None, None, None, None, GLib.Variant("(s)", ("org.kde.Other-1-1",)))
        self.assertTrue(t.registered)
        t._unregistered(c, None, None, None, None, GLib.Variant("(s)", (":1.109@/StatusNotifierItem",)))
        self.assertFalse(t.registered)
        context = GLib.MainContext.default()
        end = time.monotonic() + 2
        while not c.calls and time.monotonic() < end:
            context.iteration(False)
            time.sleep(0.01)
        self.assertEqual(c.calls, ["RegisterStatusNotifierItem"])
