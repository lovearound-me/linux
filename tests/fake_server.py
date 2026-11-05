"""A stand-in for Firebase Auth and the server on localhost, for tests and
for screenshots: REST under /v1, the stream at /v1/stream, and /test/* to
push a signal or look at what the app did.

    python3 tests/fake_server.py 8765
    LOVEAROUND_API=http://127.0.0.1:8765 LOVEAROUND_AUTH=http://127.0.0.1:8765/auth \
    LOVEAROUND_TOKEN=http://127.0.0.1:8765/token python3 -m lovearound
"""
import json
import sys
import urllib.parse

import gi

gi.require_version("Soup", "3.0")
from gi.repository import GLib, Soup  # noqa: E402

INVITE = "https://lovearound.me/i/GSSV7-A33HN"


class Fake:
    def __init__(self):
        self.contacts = []
        self.devices = []
        self.events = []
        self.patches = []
        self.sockets = []
        self.next_id = 1
        self.anyone_sent = False
        self.users = {"me@example.com": "password1"}

    def seed(self, names, close=5):
        for i, name in enumerate(names):
            self.contacts.append({"id": "c%d" % self.next_id, "label": name, "position": i, "close": i < close})
            self.next_id += 1


fake = Fake()


def reply(msg, status, body=None):
    msg.set_status(status, None)
    if body is not None:
        data = json.dumps(body).encode()
        msg.set_response("application/json", Soup.MemoryUse.COPY, data)


def body_of(msg):
    data = msg.get_request_body().flatten().get_data()
    return data


def handle(server, msg, path, query):
    method = msg.get_method()
    raw = body_of(msg)
    if path.startswith("/auth/accounts:"):
        call = path.split(":", 1)[1]
        j = json.loads(raw or b"{}")
        if call == "sendOobCode":
            return reply(msg, 200, {"email": j.get("email")})
        email, password = j.get("email"), j.get("password")
        if call == "signInWithPassword":
            if fake.users.get(email) != password:
                code = "INVALID_LOGIN_CREDENTIALS" if email in fake.users else "EMAIL_NOT_FOUND"
                return reply(msg, 400, {"error": {"message": code}})
        elif call == "signUp":
            if email in fake.users:
                return reply(msg, 400, {"error": {"message": "EMAIL_EXISTS"}})
            fake.users[email] = password
        return reply(msg, 200, {"localId": "uid-" + email, "email": email, "idToken": "id-token",
                                "refreshToken": "refresh-1", "expiresIn": "3600"})
    if path == "/token":
        form = dict(urllib.parse.parse_qsl(raw.decode()))
        if form.get("refresh_token", "").startswith("bad"):
            return reply(msg, 400, {"error": {"message": "TOKEN_EXPIRED"}})
        return reply(msg, 200, {"id_token": "id-token", "refresh_token": form.get("refresh_token"),
                                "expires_in": "3600", "user_id": "uid"})
    if path.startswith("/test/"):
        what = path[len("/test/"):]
        if what == "signal":
            for conn in fake.sockets:
                if conn.get_state() == Soup.WebsocketState.OPEN:
                    conn.send_text(json.dumps({"type": "event", "event": {"type": "signal", "v": 1}}))
            return reply(msg, 200, {"sockets": len(fake.sockets)})
        if what == "seed":
            fake.seed(json.loads(raw)["names"], json.loads(raw).get("close", 5))
            return reply(msg, 200, {})
        if what == "state":
            return reply(msg, 200, {"contacts": fake.contacts, "events": fake.events, "patches": fake.patches,
                                    "devices": fake.devices,
                                    "sockets": sum(c.get_state() == Soup.WebsocketState.OPEN for c in fake.sockets)})
    if not path.startswith("/v1/"):
        return reply(msg, 404, {"error": "not found"})
    if msg.get_request_headers().get_one("Authorization") != "Bearer id-token":
        return reply(msg, 401, {"error": "unauthorized"})
    route = path[len("/v1/"):]
    j = json.loads(raw) if raw else {}
    if route == "me":
        if method == "DELETE":
            fake.contacts.clear()
            return reply(msg, 204)
        return reply(msg, 200, {"uid": "uid", "invite_url": INVITE})
    if route == "contacts":
        if method == "POST":
            contact = {"id": "c%d" % fake.next_id, "label": j["label"], "position": len(fake.contacts),
                       "close": bool(j.get("close"))}
            fake.next_id += 1
            fake.contacts.append(contact)
            return reply(msg, 201, contact)
        return reply(msg, 200, {"contacts": sorted(fake.contacts, key=lambda c: c["position"])})
    if route.startswith("contacts/"):
        id_ = route.split("/", 1)[1]
        contact = next((c for c in fake.contacts if c["id"] == id_), None)
        if contact is None:
            return reply(msg, 404, {"error": "not found"})
        if method == "DELETE":
            fake.contacts.remove(contact)
            return reply(msg, 204)
        fake.patches.append({"id": id_, **j})
        contact.update(j)
        return reply(msg, 200, contact)
    if route == "events":
        fake.events.append(j)
        if j.get("to", {}).get("anyone"):
            if fake.anyone_sent:
                return reply(msg, 429, {"error": "rate limited"})
            fake.anyone_sent = True
        return reply(msg, 202, {})
    if route == "devices":
        if method == "POST":
            device = {"id": "d%d" % (len(fake.devices) + 1), "name": j["name"], "capabilities": j["capabilities"],
                      "last_seen_at": None}
            fake.devices.append(device)
            return reply(msg, 201, {"device": device, "token": "dev_" + "x" * 40})
        return reply(msg, 200, {"devices": fake.devices})
    if route.startswith("devices/"):
        id_ = route.split("/", 1)[1]
        fake.devices[:] = [d for d in fake.devices if d["id"] != id_]
        return reply(msg, 204)
    return reply(msg, 404, {"error": "not found"})


def on_request(server, msg, path, query):
    try:
        handle(server, msg, path, query)
    except Exception as error:  # noqa: BLE001
        reply(msg, 500, {"error": repr(error)})


def on_socket(server, msg, path, conn):
    fake.sockets.append(conn)
    conn.send_text(json.dumps({"type": "ready"}))


def make_server(port):
    server = Soup.Server()
    server.add_websocket_handler("/v1/stream", None, None, on_socket)
    server.add_handler(None, on_request)
    server.listen_local(port, Soup.ServerListenOptions.IPV4_ONLY)
    return server


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = make_server(port)
    if "--seed" in sys.argv:
        fake.seed(["Мама", "Папа", "Аня", "Миша", "Бабушка", "Катя", "Дима", "Лена", "Серёжа"])
    print("listening on", port, flush=True)
    GLib.MainLoop().run()
