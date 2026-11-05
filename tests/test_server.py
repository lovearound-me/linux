"""Sign-in, the API, the stream and the menu against tests/fake_server.py."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.parse
import urllib.request

from gi.repository import GLib

from lovearound import config, signinbox, tray
from lovearound.api import APIError
from lovearound.auth import Auth, AuthError, MemoryStore, Session
from lovearound.model import AppModel
from lovearound.settings import Settings

HERE = os.path.dirname(os.path.abspath(__file__))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def until(check, timeout=5):
    """Runs the main loop until check() is true."""
    context = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        context.iteration(False)
        time.sleep(0.01)
    return check()


class FakeOverlay:
    def __init__(self):
        self.played = []

    def play(self, color, emoji, count, calm, incoming=False):
        self.played.append((color, incoming))


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        port = free_port()
        cls.base = "http://127.0.0.1:%d" % port
        cls.server = subprocess.Popen([sys.executable, os.path.join(HERE, "fake_server.py"), str(port), "--seed"],
                                      stdout=subprocess.PIPE, text=True)
        cls.server.stdout.readline()
        cls.saved = config.API_BASE, config.FIREBASE_AUTH, config.FIREBASE_TOKEN
        config.API_BASE = cls.base
        config.FIREBASE_AUTH = cls.base + "/auth"
        config.FIREBASE_TOKEN = cls.base + "/token"

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait()
        config.API_BASE, config.FIREBASE_AUTH, config.FIREBASE_TOKEN = cls.saved

    def state(self):
        with urllib.request.urlopen(self.base + "/test/state") as r:
            return json.load(r)

    def push_signal(self):
        urllib.request.urlopen(urllib.request.Request(self.base + "/test/signal", data=b"{}")).close()

    # ---- sign-in ------------------------------------------------------------------

    def test_email_sign_in(self):
        store = MemoryStore()
        auth = Auth(store)
        auth.sign_in("me@example.com", "password1")
        self.assertEqual(store.session.uid, "uid-me@example.com")
        self.assertEqual(auth.token(), "id-token")
        with self.assertRaises(AuthError) as wrong:
            Auth(MemoryStore()).sign_in("me@example.com", "nope")
        self.assertEqual(wrong.exception.code, "INVALID_PASSWORD")
        # A new address makes an account.
        new = Auth(MemoryStore())
        new.sign_in("new@example.com", "password2")
        self.assertEqual(new.session.email, "new@example.com")

    def test_dead_refresh_token_ends_session(self):
        auth = Auth(MemoryStore(Session("uid", "me@example.com", "bad-token")))
        with self.assertRaises(AuthError) as error:
            auth.token()
        self.assertTrue(error.exception.ends_session)

    def test_google_callback_needs_our_state(self):
        auth = Auth(MemoryStore())
        url = auth.google_sign_in_url()
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        state = query["state"]
        sealed = signinbox.seal(query["key"], state, {"uid": "u", "email": "g@example.com", "rt": "refresh-1"})
        with self.assertRaises(AuthError):
            auth.complete_google("lovearound://signin?state=OTHER&uid=u&email=e&rt=refresh-1")
        # Sealed with the state as associated data: another state doesn't open it.
        with self.assertRaises(AuthError):
            auth.complete_google("lovearound://signin?" + urllib.parse.urlencode(
                {"state": state, **signinbox.seal(query["key"], "OTHER", {"uid": "u", "rt": "r"})}))
        # Sealed to someone else's key.
        with self.assertRaises(AuthError):
            auth.complete_google("lovearound://signin?" + urllib.parse.urlencode(
                {"state": state, **signinbox.seal(signinbox.SignInKey().public, state, {"uid": "u", "rt": "r"})}))
        self.assertIsNone(auth.session)
        auth.complete_google("lovearound://signin?" + urllib.parse.urlencode({"state": state, **sealed}))
        self.assertEqual(auth.session.email, "g@example.com")
        # Used once.
        with self.assertRaises(AuthError):
            auth.complete_google("lovearound://signin?" + urllib.parse.urlencode({"state": state, **sealed}))

    def test_google_callback_from_the_old_site(self):
        auth = Auth(MemoryStore())
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(auth.google_sign_in_url()).query))["state"]
        auth.complete_google("needed://signin?state=%s&uid=u&email=g@example.com&rt=refresh-1" % state)
        self.assertEqual(auth.session.email, "g@example.com")

    def test_the_same_google_link_twice_is_no_error(self):
        # The browser may hand the link over again (the page's redirect, then
        # its "back" button): signed in by the first, the second says nothing.
        with tempfile.TemporaryDirectory() as tmp:
            m = AppModel(Auth(MemoryStore()), Settings(os.path.join(tmp, "settings.json")))
            m.overlay = FakeOverlay()
            m.open_uri = lambda uri: None
            m.sign_in_with_google()
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(m.auth.google_sign_in_url()).query))
            link = "lovearound://signin?" + urllib.parse.urlencode(
                {"state": query["state"], **signinbox.seal(query["key"], query["state"], {"uid": "uid", "rt": "refresh-1"})})
            m.handle(link)
            m.handle(link)
            self.assertTrue(until(lambda: m.signed_in and not m.waiting_for_browser))
            self.assertTrue(until(lambda: m.online))
            m.handle(link)
            self.assertFalse(until(lambda: m.problem, timeout=1))
            self.assertTrue(m.signed_in)
            m.stream.stop()

    # ---- the app ------------------------------------------------------------------

    def test_model_menu_send_and_receive(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(os.path.join(tmp, "settings.json"))
            m = AppModel(Auth(MemoryStore(Session("uid", "me@example.com", "refresh-1"))), settings)
            m.overlay = FakeOverlay()
            m.start()
            self.assertTrue(until(lambda: m.online and m.contacts))
            self.assertEqual(m.invite_url, "https://lovearound.me/i/GSSV7-A33HN")

            actions = {k: (lambda: None) for k in ("popup", "book", "add", "updates", "quit", "settings", "toggle")}
            keys = [item.key for item in tray.menu_items(m, actions)]
            self.assertIn("anyone", keys)
            # Five close and four others: a short book fits whole.
            self.assertEqual(sum(k.startswith("c:") for k in keys), 5 + 4)
            self.assertNotIn("book-all", keys)

            papa = next(c for c in m.contacts if c.label == "Папа")
            m.send(papa)
            self.assertTrue(until(lambda: {"type": "signal", "to": {"contact": papa.id}} in self.state()["events"]))
            # The sender sees the glow in the contact's color, not as an incoming one.
            self.assertEqual(m.overlay.played[-1], (m.color_for(papa).color, False))
            self.assertIn("Папа — улетело ♥", [i.label for i in tray.menu_items(m, actions)])

            # Incoming: in the user's own color.
            m.overlay.played.clear()
            self.push_signal()
            self.assertTrue(until(lambda: m.overlay.played))
            self.assertEqual(m.overlay.played, [(m.signal_color, True)])

            # Paused: nothing shows.
            m.overlay.played.clear()
            m.pause("hour")
            self.push_signal()
            until(lambda: False, timeout=0.5)
            self.assertEqual(m.overlay.played, [])
            m.resume()
            m.stream.stop()

    def test_api_errors(self):
        from lovearound.api import API
        api = API(Auth(MemoryStore(Session("uid", "me@example.com", "refresh-1"))))
        with self.assertRaises(APIError) as missing:
            api.update_contact("nobody", label="x")
        self.assertEqual(str(missing.exception), "Не нашли")
        device, token = api.add_device("Лампа", ["signal"])
        self.assertTrue(token.startswith("dev_"))
        self.assertIn(device.id, [d.id for d in api.devices()])
        api.delete_device(device.id)


if __name__ == "__main__":
    unittest.main()
