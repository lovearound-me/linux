import os
import re
import subprocess

from gi.repository import GLib

from . import config, tasks

CHECK_TIMEOUT = 60
INSTALL_TIMEOUT = 600
# The first check waits for the login rush to pass.
FIRST_CHECK_SECONDS = 120
CHECK_EVERY_SECONDS = 24 * 60 * 60


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


def _get_sh(path, args, timeout, **run):
    try:
        done = subprocess.run(["sh", path, *args], timeout=timeout, **run)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Failed from error
    if done.returncode != 0:
        raise Failed
    return done


def latest(path):
    done = _get_sh(path, ["--latest"], CHECK_TIMEOUT, stdout=subprocess.PIPE, text=True)
    version = done.stdout.strip()
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

    def _set(self, state, version=None):
        self.state, self.version = state, version
        self.on_change()

    def start(self):
        GLib.timeout_add_seconds(FIRST_CHECK_SECONDS, self._scheduled_check)

    def _scheduled_check(self):
        self.check(asked=False)
        GLib.timeout_add_seconds(CHECK_EVERY_SECONDS, self._scheduled_check)
        return False

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
        """The answer to a check or a failed update lasts until it has been seen; the offer stays."""
        if self.state in ("latest", "check-failed"):
            self._set("idle")
        elif self.state == "install-failed":
            self._set("available", self.version)

    def install(self):
        if self.busy or not self.version:
            return
        self._set("installing", self.version)
        self._run(install, self.path, self.version, done=lambda _: self.on_installed(),
                  fail=lambda _: self._set("install-failed", self.version))
