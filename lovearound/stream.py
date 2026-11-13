"""WS /v1/stream: incoming events, reconnecting with backoff."""
import json
import time
import urllib.parse

from gi.repository import Gio, GLib, Soup

from . import config, tasks
from .auth import AuthError

PING = 30
# A socket can die without an error (Wi-Fi gone, a router dropped it): TCP
# would notice only minutes later, so no pong in this long means reconnect.
STALE = 75


class Stream:
    def __init__(self, auth):
        self.auth = auth
        self.on_signal = lambda: None
        # Take signals to anyone too; set before start() or followed by restart().
        self.anyone = True
        self.on_auth_lost = lambda: None
        # The address book may have changed: on every (re)connect, since events
        # could be missed while offline, and on a "sync" hint from the server.
        self.on_sync = lambda: None
        # True once the server said "ready" on the current socket, false when it is gone.
        self.on_online = lambda up: None

        self.session = Soup.Session(timeout=30)
        self.session.set_user_agent("LoveAround/" + config.VERSION)
        self.conn = None
        self.cancellable = None
        # Bumped on every (re)connect; callbacks of an older socket are ignored.
        self.generation = 0
        self.backoff = 1
        self.running = False
        # The server turned the last handshake down: the cached token is stale.
        self.refresh_token = False
        self.online = False
        self.last_heard = 0.0
        self.watchdog = None
        self.retry = None
        self.monitor = Gio.NetworkMonitor.get_default()
        self.monitor.connect("network-changed", self._network_changed)

    def start(self):
        if self.running:
            return
        self.running = True
        self.backoff = 1
        self._connect()

    def stop(self):
        self.running = False
        self._teardown()

    def restart(self):
        """After sleep or a network change the old socket is likely dead."""
        if not self.running:
            return
        self._teardown()
        self.backoff = 1
        self._connect()

    def _set_online(self, up):
        if up != self.online:
            self.online = up
            self.on_online(up)

    def _teardown(self):
        self.generation += 1
        self._set_online(False)
        for source in (self.watchdog, self.retry):
            if source:
                GLib.source_remove(source)
        self.watchdog = self.retry = None
        if self.cancellable:
            self.cancellable.cancel()
            self.cancellable = None
        if self.conn is not None:
            conn, self.conn = self.conn, None
            if conn.get_state() == Soup.WebsocketState.OPEN:
                conn.close(Soup.WebsocketCloseCode.GOING_AWAY, None)

    def _connect(self):
        self.generation += 1
        gen = self.generation
        force = self.refresh_token

        def got_token(token):
            self.refresh_token = False
            if self.running and gen == self.generation:
                self._open(token, gen)

        def failed(error):
            if isinstance(error, AuthError) and error.ends_session:
                self.on_auth_lost()
            else:
                self._schedule_reconnect(gen)

        tasks.run(self.auth.token, force, done=got_token, fail=failed)

    def _open(self, token, gen):
        url = config.API_BASE.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/v1/stream"
        if not self.anyone:
            url += "?" + urllib.parse.urlencode({"anyone": "false"})
        msg = Soup.Message.new("GET", url)
        headers = msg.get_request_headers()
        headers.append("Authorization", "Bearer " + token)
        headers.append("X-Client", config.CLIENT)
        self.cancellable = Gio.Cancellable()
        self.session.websocket_connect_async(msg, None, None, GLib.PRIORITY_DEFAULT, self.cancellable,
                                             self._connected, (gen, msg))

    def _connected(self, session, result, data):
        gen, msg = data
        try:
            conn = session.websocket_connect_finish(result)
        except GLib.Error:
            if gen != self.generation:
                return
            if msg.get_status() == 401:
                self.refresh_token = True
            self._schedule_reconnect(gen)
            return
        if gen != self.generation or not self.running:
            conn.close(Soup.WebsocketCloseCode.GOING_AWAY, None)
            return
        self.conn = conn
        conn.set_keepalive_interval(PING)
        conn.connect("message", self._message, gen)
        conn.connect("closed", lambda c: self._schedule_reconnect(gen))
        conn.connect("error", lambda c, e: self._schedule_reconnect(gen))
        self.last_heard = time.monotonic()
        try:
            conn.connect("pong", lambda c, d: self._heard(gen))
        except TypeError:
            return  # no pong signal in this libsoup: TCP keepalive only
        self.watchdog = GLib.timeout_add_seconds(15, self._check, gen)

    def _heard(self, gen):
        if gen == self.generation:
            self.last_heard = time.monotonic()

    def _check(self, gen):
        if gen != self.generation:
            return False
        if time.monotonic() - self.last_heard > STALE:
            self.watchdog = None
            self._schedule_reconnect(gen)
            return False
        return True

    def _message(self, conn, kind, data, gen):
        if gen != self.generation or kind != Soup.WebsocketDataType.TEXT:
            return
        self._heard(gen)
        self.handle(data.get_data().decode("utf-8", "replace"))

    def handle(self, text):
        try:
            msg = json.loads(text)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        kind = msg.get("type")
        if kind == "ready":
            self.backoff = 1
            self._set_online(True)
            self.on_sync()
        elif kind == "sync":
            self.on_sync()
        elif kind == "event":
            # Unknown types and versions are ignored, so old apps survive new events.
            event = msg.get("event")
            if isinstance(event, dict) and event.get("type") == "signal" and event.get("v") == 1:
                self.on_signal()

    def _network_changed(self, monitor, available):
        # A live socket is checked by the pings; a dead one waiting out its
        # backoff tries again right away once there is a network.
        if available and self.running and not self.online:
            self.restart()

    def _schedule_reconnect(self, gen):
        if not self.running or gen != self.generation:
            return
        self._teardown()
        nxt = self.generation
        delay = self.backoff
        self.backoff = min(self.backoff * 2, 60)

        def again():
            self.retry = None
            if self.running and self.generation == nxt:
                self._connect()
            return False

        self.retry = GLib.timeout_add(int(delay * 1000), again)
