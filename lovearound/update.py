import os
import re
import signal
import subprocess
import time

from gi.repository import GLib

from . import config, tasks

CHECK_TIMEOUT = 60
INSTALL_TIMEOUT = 600
# The first check waits for the login rush to pass.
FIRST_CHECK_SECONDS = 120
CHECK_EVERY_SECONDS = 24 * 60 * 60
# GLib's timers stop while the machine sleeps, so the day is counted on the
# wall clock and looked at every hour of waking time.
LOOK_EVERY_SECONDS = 60 * 60


class Failed(Exception):
    """get.sh failed or printed something that is not a version."""


def parse(version):
    if not re.fullmatch(r"\d+(\.\d+)*", version):
        return None
    return tuple(int(part) for part in version.split("."))


def newer(latest, current):
    """False for a checkout's "dev" or an unparsable version."""
    a, b = parse(latest), parse(current)
    return a is not None and b is not None and a > b


def installed_get_sh():
    """The get.sh that install.sh --user puts beside the code; None for a package or a checkout."""
    path = os.path.join(config.ROOT, "get.sh")
    return path if os.path.isfile(path) else None


def _get_sh(path, args, timeout, stdout=None):
    """get.sh's output; get.sh runs in a process group of its own, so a timeout
    stops the curl and install.sh under it too, and no update goes on after "failed"."""
    try:
        process = subprocess.Popen(["sh", path, *args], stdout=stdout, text=True, start_new_session=True)
    except OSError as error:
        raise Failed from error
    try:
        out, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        process.wait()
        raise Failed from error
    if process.returncode != 0:
        raise Failed
    return out


def latest(path):
    version = _get_sh(path, ["--latest"], CHECK_TIMEOUT, stdout=subprocess.PIPE).strip()
    if parse(version) is None:
        raise Failed
    return version


def install(path, version):
    _get_sh(path, ["--version", version], INSTALL_TIMEOUT)


class Updater:
    """The update state and the get.sh runs behind it, one at a time.
    on_change() after every state change; on_installed() once a release is in place."""

    def __init__(self, path, current, on_change, on_installed):
        self.path = path
        self.current = current
        self.on_change = on_change
        self.on_installed = on_installed
        self.state = "idle"
        self.version = None
        self.busy = False
        self.asked = False
        self.checked_at = None

    def _set(self, state, version=None):
        self.state, self.version = state, version
        self.on_change()

    def start(self):
        GLib.timeout_add_seconds(FIRST_CHECK_SECONDS, self._first_check)

    def _first_check(self):
        self.check(asked=False)
        GLib.timeout_add_seconds(LOOK_EVERY_SECONDS, self._look)
        return False

    def _look(self):
        if self.checked_at is None or time.time() - self.checked_at >= CHECK_EVERY_SECONDS:
            self.check(asked=False)
        return True

    def _run(self, fn, *args, done, fail):
        self.busy = True
        tasks.run(fn, *args, done=lambda value: self._finish(done, value),
                  fail=lambda error: self._finish(fail, error))

    def _finish(self, callback, value):
        self.busy = False
        callback(value)

    def check(self, asked):
        """A check the user did not ask for changes nothing unless it finds a release;
        asking during one makes it the user's."""
        if asked and not self.installing:
            self.asked = True
            self._set("checking")
        if self.busy:
            return
        self.checked_at = time.time()

        def done(found):
            if newer(found, self.current):
                self._set("available", found)
            elif self.asked:
                self._set("latest")
            self.asked = False

        def fail(_):
            if self.asked:
                self._set("check-failed")
            self.asked = False
        self._run(latest, self.path, done=done, fail=fail)

    @property
    def installing(self):
        return self.state == "installing"

    def dismiss(self):
        """The answer to a check or a failed update lasts until it has been seen; the offer stays.
        A check still running when Settings closes reports only a release it finds."""
        if self.state == "checking":
            self.asked = False
            self._set("idle")
        elif self.state in ("latest", "check-failed"):
            self._set("idle")
        elif self.state == "install-failed":
            self._set("available", self.version)

    def install(self):
        if self.busy or not self.version:
            return
        self._set("installing", self.version)
        self._run(install, self.path, self.version, done=lambda _: self.on_installed(),
                  fail=lambda _: self._set("install-failed", self.version))
