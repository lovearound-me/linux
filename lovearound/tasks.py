"""Network calls run on worker threads; their results come back on the GTK main loop."""
import queue
import threading

from gi.repository import GLib


def _deliver(callback, value):
    if callback:
        callback(value)
    return False


def _work(fn, args, done, fail):
    try:
        result = fn(*args)
    except Exception as error:  # noqa: BLE001 - handed to the caller as is
        GLib.idle_add(_deliver, fail, error)
    else:
        GLib.idle_add(_deliver, done, result)


def run(fn, *args, done=None, fail=None):
    """fn(*args) on a thread; done(result) or fail(error) on the main loop."""
    threading.Thread(target=_work, args=(fn, args, done, fail), daemon=True).start()


class Serial:
    """Saves go to the server one after another, in the order made."""

    def __init__(self):
        self._queue = queue.Queue()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            _work(*self._queue.get())

    def submit(self, fn, *args, done=None, fail=None):
        self._queue.put((fn, args, done, fail))

    def after(self, callback):
        """callback() on the main loop once everything submitted so far is through."""
        self.submit(lambda: None, done=lambda _: callback())
