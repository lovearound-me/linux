"""App state behind the menu. Contact colors, the own signal color and all
settings stay on this computer: the server only knows contacts and labels."""
import datetime
import time
import urllib.parse

from gi.repository import GLib, GObject

from . import config, palette, tasks
from .i18n import tr, trn
from .api import API, APIError
from .auth import Auth, AuthError
from .http import Unreachable
from .settings import Settings
from .stream import Stream

# pausedUntil for "Пока не сниму".
FOREVER = 253402300799.0
# The right end of "Смайликов за раз".
MAX_EMOJI = 60
DEFAULT_EMOJI = 40
# The steps of "Свечение не чаще раза в".
GAPS = [1, 5, 15, 30, 60, 300, 900, 3600]
ANYONE_ID = "★anyone"
ALPHABET = set("23456789ABCDEFGHJKMNPQRSTVWXYZ")


def gap_index(gap):
    """The step nearest to `gap`, so the slider shows what is in effect."""
    return min(range(len(GAPS)), key=lambda i: abs(GAPS[i] - gap))


def gap_title(gap):
    if gap < 60:
        return tr("{n} с", n=int(gap))
    if gap < 3600:
        return tr("{n} мин", n=int(gap // 60))
    return tr("{n} ч", n=int(gap // 3600))


def people_count(n):
    """"23 человека", "2 человека", "5 человек"."""
    return trn("{n} человек", n)


def invite_id(text):
    """The code from an invite link (or the bare code), as typed."""
    text = (text or "").strip()
    for marker in ("/i/",) + tuple(s + "://add/" for s in config.URL_SCHEMES):
        at = text.rfind(marker)
        if at >= 0:
            text = text[at + len(marker):]
    for stop in "/?#":
        text = text.split(stop)[0]
    # 10 characters of the server's alphabet, dashes anywhere (`GSSV7-A33HN`).
    # The server never says whether a code is taken, so this is the only
    # check a typo gets: no 0, 1, I, L, O or U.
    code = text.upper().replace("-", "")
    if len(code) != 10 or not set(code) <= ALPHABET:
        return None
    return text


def bare(code):
    return code.upper().replace("-", "")


def sort_key(label):
    return label.casefold()


def until_morning(now):
    """8:00 today if still ahead, else tomorrow."""
    today8 = now.replace(hour=8, minute=0, second=0, microsecond=0)
    return today8 if today8 > now else today8 + datetime.timedelta(days=1)


class AppModel(GObject.Object):
    __gsignals__ = {
        # Anything the menu, the book or the settings show.
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "icon-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # A signal glowed here, in this color: the tray flashes it.
        "received": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "show-menu": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "open-book": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "open-settings": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "signed-out": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # "Выйти из системы" on the banner that asks for a new login.
        "log-out": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, auth=None, settings=None):
        super().__init__()
        self.auth = auth or Auth()
        self.api = API(self.auth)
        self.stream = Stream(self.auth)
        self.settings = settings or Settings()
        self.serial = tasks.Serial()
        # Set by the app: play(color, emoji, count, calm), presenting(), sound(), open_uri(uri).
        self.overlay = None
        self.presenting = lambda: False
        self.reduce_motion = lambda: False
        self.play_sound = lambda: None
        self.open_uri = lambda uri: None
        self.clipboard_text = lambda: None
        self.set_clipboard = lambda text: None

        self.signed_in = False
        self.email = None
        self.my_uid = None
        self.invite_url = None
        self.contacts = []
        # "main" or ("add", invite or None)
        self.route = "main"
        # The contact that was just sent a signal, for "Улетело ♥".
        self.sent = None
        self.problem = None
        self.waiting_for_browser = False
        self.online = False
        # No connection for a while (or none since launch): the menu says signals
        # won't arrive. Not just `not online`, which would flash on every launch.
        self.offline = False
        # GNOME hasn't seen the extension that draws the glow yet: it was
        # installed after this login. Set by the app.
        self.needs_relogin = False
        self.anyone_sending = False
        # The device just made in Settings → Устройства: its token is shown once.
        self.created_device = None
        self.last_shown = 0.0
        self.pending_add = None
        self._sent_reset = None
        self._going_offline = None
        self._reorder_save = None

        self.stream.anyone = self.settings["acceptAnyone"]
        self.stream.on_signal = self.receive
        self.stream.on_auth_lost = self.sign_out
        self.stream.on_online = self._connection_changed
        # Not halfway through saving a new order: that would show it half-applied.
        self.stream.on_sync = lambda: self.serial.after(self.reload)

        # A pause ends by itself.
        GLib.timeout_add_seconds(30, self._pause_tick)

    def changed(self):
        self.emit("changed")

    # ---- settings ---------------------------------------------------------------

    def get(self, key):
        return self.settings[key]

    def set(self, key, value):
        if self.settings[key] == value:
            return
        self.settings[key] = value
        if key == "acceptAnyone":
            self.stream.anyone = value
            self.stream.restart()
        self.changed()

    @property
    def min_gap(self):
        return GAPS[gap_index(self.settings["minGap"])]

    # ---- session ----------------------------------------------------------------

    def start(self):
        session = self.auth.session
        if session is None:
            return
        self.signed_in = True
        self.email = session.email
        self.my_uid = session.uid
        # The stream reloads the contacts once it is connected.
        self.stream.start()
        self._connection_changed(self.online)
        self.changed()

    def reload(self):
        def fetch():
            return self.api.me(), self.api.contacts()

        def done(result):
            me, contacts = result
            if not self.signed_in:
                return
            self.my_uid = me.get("uid") or self.my_uid
            self.invite_url = me.get("invite_url") or self.invite_url
            self.contacts = contacts
            self.problem = None
            self.changed()

        def fail(error):
            if isinstance(error, AuthError) and error.ends_session:
                self.sign_out()
            elif self.signed_in:
                self.problem = tr("Нет связи с сервером. Попробуем ещё раз чуть позже.")
                self.changed()

        tasks.run(fetch, done=done, fail=fail)

    def _connection_changed(self, up):
        if self._going_offline:
            GLib.source_remove(self._going_offline)
            self._going_offline = None
        if up:
            self.online = True
            self.offline = False
            self.changed()
        else:
            def gone():
                self._going_offline = None
                self.online = False
                self.offline = True
                self.changed()
                return False
            self._going_offline = GLib.timeout_add_seconds(5, gone)

    # ---- signals ----------------------------------------------------------------

    def send(self, contact):
        self.sent = contact.id
        last = dict(self.settings["lastSent"])
        last[contact.id] = time.time()
        self.settings["lastSent"] = last
        if self._sent_reset:
            GLib.source_remove(self._sent_reset)

        def reset():
            self._sent_reset = None
            self.sent = None
            self.changed()
            return False
        self._sent_reset = GLib.timeout_add(2000, reset)
        # The sender sees the glow too, in the contact's color: silent, and even on pause.
        if self.overlay:
            self.overlay.play(self.color_for(contact).color, "warm", self.settings["emojiCount"], self.calm_effect)
        self.changed()

        def ok(_):
            self.problem = None
            self.changed()

        def fail(error):
            self.sent = None
            if isinstance(error, AuthError) and error.ends_session:
                self.sign_out()
                self.problem = tr("Нужно войти заново")
            else:
                self.problem = tr("Не улетело, проверь интернет")
            self.changed()

        tasks.run(self.api.signal, contact.id, done=ok, fail=fail)

    def send_to_anyone(self):
        """"Кому-нибудь на свете": one random person online who takes them. The
        server spends the hour on the try and accepts it even with nobody
        online, so "Улетело" is all the sender ever learns."""
        if self.anyone_wait() is not None or self.anyone_sending:
            return
        self.anyone_sending = True
        self.changed()

        def ok(_):
            self.anyone_sending = False
            self.settings["anyoneSentAt"] = time.time()
            self.problem = None
            if self.overlay:
                self.overlay.play(palette.STAR, "stars", DEFAULT_EMOJI, self.calm_effect)
            self.changed()

        def fail(error):
            self.anyone_sending = False
            if isinstance(error, AuthError) and error.ends_session:
                self.sign_out()
                self.problem = tr("Нужно войти заново")
            elif isinstance(error, APIError) and error.status == 429:
                # Sent from another device this hour, at a time not known
                # here: wait a whole hour from now, a little longer than it has to.
                self.settings["anyoneSentAt"] = time.time() - 120
                self.problem = None
            else:
                self.problem = tr("Не улетело, проверь интернет")
            self.changed()

        tasks.run(self.api.signal_anyone, done=ok, fail=fail)

    def anyone_wait(self, now=None):
        """Whole minutes until the next signal to anyone, or None if it can go now."""
        sent_at = self.settings["anyoneSentAt"]
        if sent_at is None:
            return None
        left = sent_at + 3600 - (now or time.time())
        return -int(-left // 60) if left > 0 else None

    def anyone_just_sent(self, now=None):
        """"Улетело" only right after: later in the hour it would be stale."""
        sent_at = self.settings["anyoneSentAt"]
        return sent_at is not None and (now or time.time()) - sent_at < 120

    @property
    def signal_color(self):
        return palette.at(self.settings["myColor"]).color

    def receive(self):
        if self.is_paused:
            return
        # Not shown, and not saved for later: a signal is about the moment.
        if self.settings["quietWhenPresenting"] and self.presenting():
            return
        # The server lets one signal per sender through each second; a rarer
        # glow is this computer's own choice, and the ones in between are not shown.
        now = time.monotonic()
        if self.last_shown and now - self.last_shown < self.min_gap:
            return
        self.last_shown = now
        self.play_effect()

    def play_effect(self):
        """The incoming-signal effect, also used by "Показать, как это выглядит"."""
        if self.overlay:
            self.overlay.play(self.signal_color, "warm", self.settings["emojiCount"], self.calm_effect, incoming=True)
        self.emit("received", self.signal_color)
        if self.settings["sound"]:
            self.play_sound()

    @property
    def calm_effect(self):
        return self.settings["calm"] or self.reduce_motion()

    # ---- pause --------------------------------------------------------------------

    @property
    def is_paused(self):
        until = self.settings["pausedUntil"]
        return until is not None and until > time.time()

    def pause_text(self):
        until = self.settings["pausedUntil"]
        if not self.is_paused:
            return ""
        if until >= FOREVER:
            return tr("Пауза, пока не снимешь")
        when = datetime.datetime.fromtimestamp(until)
        time_ = when.strftime("%H:%M")
        return tr("Пауза до {time}", time=time_) if when.date() == datetime.date.today() \
            else tr("Пауза до завтра, {time}", time=time_)

    def pause(self, length):
        if length == "hour":
            until = time.time() + 3600
        elif length == "morning":
            until = until_morning(datetime.datetime.now()).timestamp()
        else:
            until = FOREVER
        self.settings["pausedUntil"] = until
        self.emit("icon-changed")
        self.changed()

    def resume(self):
        self.settings["pausedUntil"] = None
        self.emit("icon-changed")
        self.changed()

    def _pause_tick(self):
        until = self.settings["pausedUntil"]
        if until is not None and until <= time.time():
            self.resume()
        return True

    # ---- contacts -----------------------------------------------------------------

    @property
    def close_contacts(self):
        """Circles on top of the menu, in the order set by hand."""
        return [c for c in self.contacts if c.close]

    @property
    def other_contacts(self):
        """Everyone else, the most recently signalled first, then by name."""
        last = self.settings["lastSent"]
        return sorted((c for c in self.contacts if not c.close),
                      key=lambda c: (-last.get(c.id, 0), sort_key(c.label)))

    @property
    def contacts_by_name(self):
        return sorted(self.contacts, key=lambda c: sort_key(c.label))

    def find(self, query):
        q = query.strip().casefold()
        return [c for c in self.contacts_by_name if q in c.label.casefold()]

    @property
    def new_contact_is_close(self):
        """New contacts start among the close ones until there are a couple of rows of them."""
        return len(self.close_contacts) < 10

    def contact(self, id_):
        return next((c for c in self.contacts if c.id == id_), None)

    def color_index(self, contact):
        index = self.settings["contactColors"].get(contact.id)
        if index is not None:
            return index % len(palette.ALL)
        ids = [c.id for c in self.contacts]
        return (ids.index(contact.id) if contact.id in ids else 0) % len(palette.ALL)

    def color_for(self, contact):
        return palette.at(self.color_index(contact))

    @property
    def next_color(self):
        """The first color not yet used, for a new contact."""
        used = {self.settings["contactColors"].get(c.id, -1) for c in self.contacts}
        free = [i for i in range(len(palette.ALL)) if i not in used]
        return free[0] if free else len(self.contacts) % len(palette.ALL)

    def _set_color(self, id_, color):
        colors = dict(self.settings["contactColors"])
        if color is None:
            colors.pop(id_, None)
        else:
            colors[id_] = color
        self.settings["contactColors"] = colors

    def add_contact(self, code, label, color, close, done, fail):
        def added(contact):
            self._set_color(contact.id, color)
            self.contacts.append(contact)
            self.changed()
            done(contact)
        tasks.run(self.api.add_contact, code, label, close, done=added, fail=fail)

    def update_contact(self, contact, label, color, done=None, fail=None):
        """Name and color; where they are is the book's drag, not this."""
        self._set_color(contact.id, color)

        def saved(_):
            current = self.contact(contact.id)
            if current:
                current.label = label
            self.changed()
            if done:
                done(None)

        if label != contact.label:
            self.serial.submit(self.api.update_contact, contact.id, label, done=saved, fail=fail)
        else:
            saved(None)

    def set_close(self, contact, close):
        """Into "Рядом" or out of it: shown at once, saved behind."""
        current = self.contact(contact.id)
        if current is None or current.close == close:
            return
        current.close = close
        self.changed()
        self.serial.submit(self.api.update_contact, contact.id, None, None, close, fail=self._save_failed(tr("Не получилось сохранить")))

    def remove(self, contact, done, fail):
        def removed(_):
            self.contacts = [c for c in self.contacts if c.id != contact.id]
            self._set_color(contact.id, None)
            last = dict(self.settings["lastSent"])
            last.pop(contact.id, None)
            self.settings["lastSent"] = last
            self.changed()
            done(None)
        tasks.run(self.api.delete_contact, contact.id, done=removed, fail=fail)

    def move(self, contact, target):
        """Puts a close contact in the target's circle, the others shift."""
        close = self.close_contacts
        ids = [c.id for c in close]
        if contact.id == target.id or contact.id not in ids or target.id not in ids:
            return
        person = close.pop(ids.index(contact.id))
        close.insert(ids.index(target.id), person)
        self._reorder_close(close)

    def place(self, contact, close_at):
        """A drag in the book: into "Рядом" at this place among the circles, or out of it with None."""
        person = self.contact(contact.id)
        if person is None:
            return
        if close_at is None:
            self.set_close(person, False)
            return
        self.set_close(person, True)
        close = [c for c in self.close_contacts if c.id != person.id]
        close.insert(min(close_at, len(close)), person)
        self._reorder_close(close)

    def _reorder_close(self, close):
        """Shown at once; saved a moment after the last change, so a drag across
        several circles is one save."""
        # The close ones keep their slots in the whole list, in the new order.
        slots = [i for i, c in enumerate(self.contacts) if c.close]
        for slot, person in zip(slots, close):
            self.contacts[slot] = person
        self.changed()
        if self._reorder_save:
            GLib.source_remove(self._reorder_save)
        self._reorder_save = GLib.timeout_add(700, self._save_positions)

    def _save_positions(self):
        self._reorder_save = None
        updates = []
        for index, contact in enumerate(self.contacts):
            if contact.position != index:
                contact.position = index
                updates.append((contact.id, index))
        if updates:
            def save():
                for id_, position in updates:
                    self.api.update_contact(id_, position=position)
            self.serial.submit(save, fail=self._save_failed(tr("Не получилось сохранить порядок")))
        return False

    def _save_failed(self, text):
        def fail(error):
            self.problem = text
            self.changed()
            self.reload()
        return fail

    def copy_invite(self):
        """For the button of a board that sends to this person (/docs)."""
        if not self.invite_url:
            return False
        self.set_clipboard(self.invite_url)
        return True

    def pasted_invite(self, text):
        """The code of an invite link on the clipboard, unless it is this user's own."""
        code = invite_id(text) if text else None
        if code is None:
            return None
        own = invite_id(self.invite_url) if self.invite_url else None
        if own and bare(own) == bare(code):
            return None
        return code

    # ---- links --------------------------------------------------------------------

    def handle(self, url):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in config.URL_SCHEMES:
            return
        if parts.netloc == "add":
            # The whole link, not the path: its leading "/" would leave invite_id an empty id.
            invite = invite_id(url)
            if invite is None:
                return
            if self.signed_in:
                self.route = ("add", invite)
            else:
                self.pending_add = invite
            self.changed()
            self.emit("show-menu")
        elif parts.netloc == "signin":
            # The browser can hand over the same link twice (the page's own
            # redirect, then its "back" button, or a restored tab): the first
            # one signs in and uses up the state, so a late copy is no news.
            if self.signed_in and not self.waiting_for_browser:
                return

            def done(_):
                self.waiting_for_browser = False
                self.problem = None
                self._did_sign_in()
                self.emit("show-menu")

            def fail(error):
                self.waiting_for_browser = False
                if self.signed_in:  # a copy that lost the race to the first one
                    return
                self.problem = self.error_text(error)
                self.changed()
                self.emit("show-menu")

            tasks.run(self.auth.complete_google, url, done=done, fail=fail)

    # ---- account ------------------------------------------------------------------

    def sign_in(self, email, password, done, fail):
        def ok(_):
            self._did_sign_in()
            done(None)
        tasks.run(self.auth.sign_in, email, password, done=ok, fail=fail)

    def sign_in_with_google(self):
        self.waiting_for_browser = True
        self.problem = None
        self.open_uri(self.auth.google_sign_in_url())
        self.changed()

    def send_password_reset(self, email, done, fail):
        tasks.run(self.auth.send_password_reset, email, done=done, fail=fail)

    def _did_sign_in(self):
        self.problem = None
        self.start()
        if self.pending_add:
            self.route = ("add", self.pending_add)
            self.pending_add = None
        else:
            self.route = "main"
        self.changed()

    def sign_out(self):
        self.stream.stop()
        self.auth.sign_out()
        if self._going_offline:
            GLib.source_remove(self._going_offline)
            self._going_offline = None
        self.offline = False
        self.created_device = None
        self.signed_in = False
        self.email = None
        self.my_uid = None
        self.invite_url = None
        self.contacts = []
        self.route = "main"
        self.emit("signed-out")
        self.changed()

    def delete_account(self, done, fail):
        def deleted(_):
            self.settings["contactColors"] = {}
            self.settings["lastSent"] = {}
            self.sign_out()
            done(None)
        tasks.run(self.api.delete_me, done=deleted, fail=fail)

    @staticmethod
    def error_text(error):
        if isinstance(error, (AuthError, APIError)):
            return str(error)
        if isinstance(error, Unreachable):
            return tr("Нет связи с сервером, проверь интернет")
        return tr("Не получилось, попробуй ещё раз")
