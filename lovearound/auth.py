"""Firebase Auth over its REST API. Signing in happens in the browser, on the
site's /signin/ page (Google, Apple or email), which hands the session back via
lovearound://signin, sealed to a one-time key of ours (signinbox.py).

Only the refresh token is kept, in the Secret Service (GNOME Keyring,
KWallet); ID tokens live in memory.
"""
import base64
import json
import threading
import time
import urllib.parse
import uuid
from dataclasses import asdict, dataclass

from . import config, http
from .i18n import N_, tr
from .signinbox import SignInKey

# Translated when shown: the language can change while the app runs.
MESSAGES = {
    "TOO_MANY_ATTEMPTS_TRY_LATER": N_("Слишком много попыток, попробуй чуть позже"),
    "USER_DISABLED": N_("Этот аккаунт отключён"),
    "BAD_CALLBACK": N_("Вход не завершился, попробуй ещё раз"),
}

# Errors after which the stored session is useless.
ENDS_SESSION = ("TOKEN_EXPIRED", "USER_DISABLED", "USER_NOT_FOUND", "INVALID_REFRESH_TOKEN", "INVALID_GRANT_TYPE")


class AuthError(Exception):
    """A Firebase Auth error code, e.g. "TOKEN_EXPIRED", or None for signed out."""

    def __init__(self, code=None):
        super().__init__(code or "SIGNED_OUT")
        self.code = code

    @property
    def ends_session(self):
        return self.code is None or self.code.startswith(ENDS_SESSION)

    def __str__(self):
        if self.code is None:
            return tr("Нужно войти заново")
        code = self.code.split(" ")[0]
        return tr(MESSAGES[code]) if code in MESSAGES else tr("Не получилось войти ({code})", code=code)


@dataclass
class Session:
    uid: str
    email: str
    refreshToken: str


def load_plan(flag, locked):
    """The keyring step for the keyringSession flag and the lock state of the
    default collection: "lookup", "unlock" first, "skip", or "delete" a session
    the user signed out of while the keyring was locked."""
    if locked:
        return "skip" if flag in ("none", "signedOut") else "unlock"
    return "delete" if flag == "signedOut" else "lookup"


class SecretStore:
    """The session in the Secret Service. With no service running (a bare
    window manager, no keyring) it is kept in memory only: never in a plain file."""

    def __init__(self, settings=None):
        self.settings = settings if settings is not None else {}
        self.available = True
        try:
            import gi
            gi.require_version("Secret", "1")
            from gi.repository import Secret
            self.Secret = Secret
            self.schema = Secret.Schema.new(config.APP_ID + ".Session", Secret.SchemaFlags.NONE,
                                            {"app": Secret.SchemaAttributeType.STRING})
        except (ImportError, ValueError):
            self.available = False

    def _attrs(self):
        return {"app": config.APP_ID}

    def _set_flag(self, value):
        # Each assignment saves the settings file, and a token refresh calls this from a worker thread.
        if self.settings.get("keyringSession") != value:
            self.settings["keyringSession"] = value

    def _locked_default(self):
        """(service, collection) when the default collection is locked, else None."""
        Secret = self.Secret
        try:
            service = Secret.Service.get_sync(Secret.ServiceFlags.NONE, None)
            collection = Secret.Collection.for_alias_sync(
                service, Secret.COLLECTION_DEFAULT, Secret.CollectionFlags.NONE, None)
        except Exception:  # noqa: BLE001 - no service on the bus
            return None
        if collection is None or not collection.get_locked():
            return None
        return service, collection

    def _unlock(self, service, collection):
        try:
            return service.unlock_sync([collection], None)[0] > 0
        except Exception:  # noqa: BLE001 - a D-Bus error, taken as a refusal
            return False

    def load(self):
        if not self.available:
            return None
        locked = self._locked_default()
        plan = load_plan(self.settings.get("keyringSession"), locked is not None)
        if plan == "skip" or (plan == "unlock" and not self._unlock(*locked)):
            return None
        try:
            if plan == "delete":
                self.Secret.password_clear_sync(self.schema, self._attrs(), None)
                self._set_flag("none")
                return None
            text = self.Secret.password_lookup_sync(self.schema, self._attrs(), None)
        except Exception:  # noqa: BLE001 - no service on the bus
            self.available = False
            return None
        self._set_flag("stored" if text else "none")
        if not text:
            return None
        try:
            return Session(**json.loads(text))
        except (ValueError, TypeError):
            return None

    def save(self, session):
        if not self.available:
            return
        try:
            stored = self.Secret.password_store_sync(self.schema, self._attrs(), self.Secret.COLLECTION_DEFAULT,
                                                     "Love Around", json.dumps(asdict(session)), None)
        except Exception:  # noqa: BLE001
            self.available = False
            return
        # False is a store that didn't happen: the flag must not claim a session
        # (a pending sign-out would then load the old one instead of deleting it).
        if stored:
            self._set_flag("stored")

    def clear(self):
        if not self.available:
            return
        locked = self._locked_default()
        if locked is not None and not self._unlock(*locked):
            self._set_flag("signedOut")
            return
        try:
            self.Secret.password_clear_sync(self.schema, self._attrs(), None)
        except Exception:  # noqa: BLE001
            return
        self._set_flag("none")


class MemoryStore:
    """For tests."""

    available = True

    def __init__(self, session=None):
        self.session = session

    def load(self):
        return self.session

    def save(self, session):
        self.session = session

    def clear(self):
        self.session = None


class Auth:
    """Thread-safe: API calls ask for tokens from worker threads."""

    def __init__(self, store=None):
        self.store = store or SecretStore()
        self.session = self.store.load()
        self._id_token = None
        self._expires_at = 0.0
        self._lock = threading.Lock()
        # (url, state, key) of the sign-in page opened in the browser and not answered yet.
        self._pending = None

    def token(self, force_refresh=False):
        """A valid ID token, refreshed when it is about to expire."""
        with self._lock:
            if not force_refresh and self._id_token and self._expires_at - time.time() > 300:
                return self._id_token
            return self._refresh()

    def _refresh(self):
        session = self.session
        if session is None:
            raise AuthError()
        form = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": session.refreshToken})
        status, json_ = http.call("POST", "%s?key=%s" % (config.FIREBASE_TOKEN, config.FIREBASE_API_KEY), form=form)
        _check(status, json_)
        id_token, refresh = json_.get("id_token"), json_.get("refresh_token")
        if not id_token or not refresh:
            raise AuthError("BAD_RESPONSE")
        if self.session is not session:
            # Signed out (or in again) while this was on its way.
            raise AuthError()
        self._id_token = id_token
        self._expires_at = time.time() + _seconds(json_.get("expires_in"))
        if refresh != session.refreshToken:
            session.refreshToken = refresh
            self.store.save(session)
        return id_token

    # ---- sign-in, through the site --------------------------------------------

    def sign_in_url(self):
        """The page that signs in (Google, Apple or email) and returns to
        lovearound://signin, with the session sealed to our one-time key.
        Opening it again gives the same page, so a tab already open still works."""
        if self._pending is None:
            state, key = str(uuid.uuid4()).upper(), SignInKey()
            self._pending = ("%s/signin?state=%s&key=%s" % (config.SITE, state, key.public), state, key)
        return self._pending[0]

    def complete_sign_in(self, url):
        """lovearound://signin?state=…&epk=…&box=…, the box holding uid, email
        and the refresh token. The site before the box sent them in the clear
        (needed://signin?state=…&uid=…&email=…&rt=…); that is still accepted
        until the site with the box is published."""
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        # The state proves the callback answers our own request, so a crafted
        # link cannot sign the app into someone else's account.
        pending = self._pending
        if pending is None or q.get("state") != pending[1]:
            raise AuthError("BAD_CALLBACK")
        if q.get("box"):
            try:
                q = pending[2].open(q.get("epk", ""), q["box"], pending[1])
            except ValueError:
                raise AuthError("BAD_CALLBACK") from None
        uid, rt = q.get("uid"), q.get("rt")
        if not isinstance(uid, str) or not uid or not isinstance(rt, str) or not rt:
            raise AuthError("BAD_CALLBACK")
        self._pending = None
        with self._lock:
            self._adopt(Session(uid, q.get("email") or "", rt))
        self.token(force_refresh=True)

    @property
    def provider(self):
        """How this session signed in: "google.com", "apple.com" or "password",
        read from the ID token (a refreshed token keeps it). None before the first token."""
        try:
            payload = self._id_token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            return claims["firebase"]["sign_in_provider"]
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return None

    # ---- session ---------------------------------------------------------------

    def sign_out(self):
        self._pending = None
        with self._lock:
            had_session = self.session is not None
            self.session = None
            self._id_token = None
            self._expires_at = 0.0
        if had_session:
            self.store.clear()

    def _adopt(self, session):
        self.session = session
        self._id_token = None
        self._expires_at = 0.0
        self.store.save(session)


def _seconds(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 3600.0


def _check(status, json_):
    if not 200 <= status < 300:
        error = json_.get("error")
        code = error.get("message") if isinstance(error, dict) else None
        raise AuthError(code or "HTTP_%d" % status)

