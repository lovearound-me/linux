import time

from gi.repository import GLib


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
