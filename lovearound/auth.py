"""Firebase Auth over its REST API: email+password directly, Google through
the site's /signin/ page, which hands the session back via lovearound://signin,
sealed to a one-time key of ours (signinbox.py).

Only the refresh token is kept, in the Secret Service (GNOME Keyring,
KWallet); ID tokens live in memory.
"""
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
    "INVALID_PASSWORD": N_("Неверный пароль. Если раньше вход был через Google, нажми «Назад» и «Войти через Google»"),
    "WEAK_PASSWORD": N_("Пароль слишком простой"),
    "INVALID_EMAIL": N_("Проверь адрес почты"),
    "MISSING_EMAIL": N_("Проверь адрес почты"),
    "MISSING_PASSWORD": N_("Введи пароль"),
    "TOO_MANY_ATTEMPTS_TRY_LATER": N_("Слишком много попыток, попробуй чуть позже"),
    "USER_DISABLED": N_("Этот аккаунт отключён"),
    "BAD_CALLBACK": N_("Вход не завершился, попробуй ещё раз"),
}

# Errors after which the stored session is useless.
ENDS_SESSION = ("TOKEN_EXPIRED", "USER_DISABLED", "USER_NOT_FOUND", "INVALID_REFRESH_TOKEN", "INVALID_GRANT_TYPE")


class AuthError(Exception):
    """A Firebase Auth error code, e.g. "EMAIL_EXISTS", or None for signed out."""

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


class SecretStore:
    """The session in the Secret Service. With no service running (a bare
    window manager, no keyring) it is kept in memory only: never in a plain file."""

    def __init__(self):
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

    def _ensure_unlocked(self):
        """False when the default collection is locked and the user refused to unlock it."""
        Secret = self.Secret
        try:
            service = Secret.Service.get_sync(Secret.ServiceFlags.NONE, None)
            collection = Secret.Collection.for_alias_sync(
                service, Secret.COLLECTION_DEFAULT, Secret.CollectionFlags.NONE, None)
            locked = collection is not None and collection.get_locked()
        except Exception:  # noqa: BLE001 - the lookup that follows reports a missing service
            return True
        if not locked:
            return True
        try:
            return service.unlock_sync([collection], None)[0] > 0
        except Exception:  # noqa: BLE001 - the prompt dismissed
            return False

    def load(self):
        if not self.available:
            return None
        try:
            # password_lookup_sync prompts again on a locked collection after a refusal.
            if not self._ensure_unlocked():
                return None
            text = self.Secret.password_lookup_sync(self.schema, self._attrs(), None)
        except Exception:  # noqa: BLE001 - no service on the bus
            self.available = False
            return None
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
            self.Secret.password_store_sync(self.schema, self._attrs(), self.Secret.COLLECTION_DEFAULT,
                                            "Love Around", json.dumps(asdict(session)), None)
        except Exception:  # noqa: BLE001
            self.available = False

    def clear(self):
        if not self.available or not self._ensure_unlocked():
            return
        try:
            self.Secret.password_clear_sync(self.schema, self._attrs(), None)
        except Exception:  # noqa: BLE001
            pass


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
        self._google_state = None
        self._google_key = None

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

    # ---- email + password ----------------------------------------------------

    def sign_in(self, email, password):
        """Signs in, or creates the account when the email is new."""
        try:
            self._email_call("signInWithPassword", email, password)
        except AuthError as error:
            # With email enumeration protection both cases look the same:
            # try to create the account, and an existing email means a wrong password.
            if not (error.code or "").startswith(("EMAIL_NOT_FOUND", "INVALID_LOGIN_CREDENTIALS")):
                raise
            try:
                self._email_call("signUp", email, password)
            except AuthError as again:
                if (again.code or "").startswith("EMAIL_EXISTS"):
                    raise AuthError("INVALID_PASSWORD") from None
                raise

    def send_password_reset(self, email):
        _post("accounts:sendOobCode", {"requestType": "PASSWORD_RESET", "email": email})

    def _email_call(self, method, email, password):
        json_ = _post("accounts:" + method, {"email": email, "password": password, "returnSecureToken": True})
        uid, id_token, refresh = json_.get("localId"), json_.get("idToken"), json_.get("refreshToken")
        if not uid or not id_token or not refresh:
            raise AuthError("BAD_RESPONSE")
        with self._lock:
            self._adopt(Session(uid, json_.get("email") or email, refresh))
            self._id_token = id_token
            self._expires_at = time.time() + _seconds(json_.get("expiresIn"))

    # ---- Google, through the site --------------------------------------------

    def google_sign_in_url(self):
        """The page that signs in with Google and returns to lovearound://signin,
        with the session sealed to our one-time key."""
        self._google_state = str(uuid.uuid4()).upper()
        self._google_key = SignInKey()
        return "%s/signin?state=%s&key=%s" % (config.SITE, self._google_state, self._google_key.public)

    def complete_google(self, url):
        """lovearound://signin?state=…&epk=…&box=…, the box holding uid, email
        and the refresh token. The site before the box sent them in the clear
        (needed://signin?state=…&uid=…&email=…&rt=…); that is still accepted
        until the site with the box is published."""
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        # The state proves the callback answers our own request, so a crafted
        # link cannot sign the app into someone else's account.
        if not self._google_state or q.get("state") != self._google_state:
            raise AuthError("BAD_CALLBACK")
        if q.get("box"):
            try:
                q = self._google_key.open(q.get("epk", ""), q["box"], self._google_state)
            except ValueError:
                raise AuthError("BAD_CALLBACK") from None
        uid, rt = q.get("uid"), q.get("rt")
        if not isinstance(uid, str) or not uid or not isinstance(rt, str) or not rt:
            raise AuthError("BAD_CALLBACK")
        self._google_state = self._google_key = None
        with self._lock:
            self._adopt(Session(uid, q.get("email") or "", rt))
        self.token(force_refresh=True)

    # ---- session ---------------------------------------------------------------

    def sign_out(self):
        with self._lock:
            self.session = None
            self._id_token = None
            self._expires_at = 0.0
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


def _post(method, body):
    status, json_ = http.call("POST", "%s/%s?key=%s" % (config.FIREBASE_AUTH, method, config.FIREBASE_API_KEY), body=body)
    _check(status, json_)
    return json_
