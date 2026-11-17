"""The server's REST API; see docs/schema.md. Called on worker threads."""
from dataclasses import dataclass

from . import config, http
from .i18n import tr


@dataclass
class Contact:
    """A contact from the server, with the owner's color for them."""

    # The server's id for this entry; the person's own id never leaves it.
    id: str
    label: str
    position: int = 0
    # A close person: a circle on top of the menu, first in the book.
    close: bool = False
    # The person's Love ID link, to pass on to people who know them; None for
    # contacts added before the server kept it, or by a wrong code.
    invite_url: str = None
    # An index into the palette, kept on the server so every device shows the
    # same one; None from a server older than the field.
    color: int = None

    @classmethod
    def from_json(cls, j):
        return cls(str(j["id"]), j.get("label") or "", int(j.get("position") or 0), bool(j.get("close")),
                   j.get("invite_url") or None, int(j["color"]) if j.get("color") is not None else None)


@dataclass
class Device:
    """One of the user's own devices (a toy, a lamp, a board) with its own token."""

    id: str
    name: str
    capabilities: list
    last_seen_at: str = None

    @classmethod
    def from_json(cls, j):
        return cls(str(j["id"]), j.get("name") or "", list(j.get("capabilities") or []), j.get("last_seen_at"))


class APIError(Exception):
    def __init__(self, status, message=""):
        super().__init__("%d %s" % (status, message))
        self.status = status
        self.message = message

    def __str__(self):
        if self.status == 400 and self.message == "that is your own invite":
            return tr("Это твоя собственная ссылка")
        if self.status == 400 and self.message == "not an invite code":
            return tr("Не похоже на ссылку-приглашение")
        if self.status == 400 and self.message == "too many contacts":
            return tr("В списке уже 200 человек")
        if self.status == 409 and self.message == "too many close":
            return tr("Рядом уже 12 человек: сначала убери кого-нибудь.")
        return {
            404: tr("Не нашли"),
            409: tr("Уже есть в списке"),
            429: tr("Слишком много попыток, попробуй через час"),
        }.get(self.status, tr("Сервер не ответил, попробуй ещё раз"))


class API:
    def __init__(self, auth):
        self.auth = auth

    def me(self):
        return self._request("GET", "v1/me")

    def contacts(self):
        return [Contact.from_json(j) for j in self._request("GET", "v1/contacts").get("contacts") or []]

    def add_contact(self, code, label, close, color):
        """Always answers the same whether or not the code belongs to anyone."""
        return Contact.from_json(self._request("POST", "v1/contacts",
                                               {"code": code, "label": label, "close": close, "color": color}))

    def update_contact(self, id_, label=None, position=None, close=None, color=None):
        body = {k: v for k, v in (("label", label), ("position", position), ("close", close), ("color", color))
                if v is not None}
        self._request("PATCH", "v1/contacts/" + id_, body)

    def delete_contact(self, id_):
        self._request("DELETE", "v1/contacts/" + id_)

    def signal(self, contact_id):
        self._request("POST", "v1/events", {"type": "signal", "to": {"contact": contact_id}})

    def signal_anyone(self):
        """202 even with nobody online to take it; 429 if one already went this hour."""
        self._request("POST", "v1/events", {"type": "signal", "to": {"anyone": True}})

    def devices(self):
        return [Device.from_json(j) for j in self._request("GET", "v1/devices").get("devices") or []]

    def add_device(self, name, capabilities):
        """The token comes back only here, once."""
        j = self._request("POST", "v1/devices", {"name": name, "kind": "custom", "capabilities": capabilities})
        return Device.from_json(j["device"]), j["token"]

    def delete_device(self, id_):
        self._request("DELETE", "v1/devices/" + id_)

    def delete_me(self):
        self._request("DELETE", "v1/me")

    def _request(self, method, path, body=None):
        for attempt in range(2):
            token = self.auth.token(force_refresh=attempt > 0)
            headers = {"Authorization": "Bearer " + token, "X-Client": config.CLIENT}
            status, json_ = http.call(method, config.API_BASE + "/" + path, body=body, headers=headers)
            if status == 401 and attempt == 0:
                continue
            if not 200 <= status < 300:
                raise APIError(status, json_.get("error") or "")
            return json_
        raise APIError(401, "unauthorized")
