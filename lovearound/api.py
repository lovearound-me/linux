"""The server's REST API; see docs/schema.md. Called on worker threads."""
from dataclasses import dataclass

from . import config, http
from .i18n import tr


@dataclass
class Contact:
    """A contact from the server. Its color is not here: colors live on this computer."""

    # The server's id for this entry; the person's own id never leaves it.
    id: str
    label: str
    position: int = 0
    # A close person: a circle on top of the menu, first in the book.
    close: bool = False

    @classmethod
    def from_json(cls, j):
        return cls(str(j["id"]), j.get("label") or "", int(j.get("position") or 0), bool(j.get("close")))


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

    def add_contact(self, code, label, close):
        """Always answers the same whether or not the code belongs to anyone."""
        return Contact.from_json(self._request("POST", "v1/contacts", {"code": code, "label": label, "close": close}))

    def update_contact(self, id_, label=None, position=None, close=None):
        body = {k: v for k, v in (("label", label), ("position", position), ("close", close)) if v is not None}
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
