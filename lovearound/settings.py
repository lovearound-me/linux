"""Local settings: colors, the signal look, the pause. They never leave this computer."""
import json
import os
import sys
import tempfile

from . import config

DEFAULTS = {
    "myColor": 1,
    "sound": False,
    "calm": False,
    "emojiCount": 40,
    "quietWhenPresenting": True,
    "minGap": 1,
    "acceptAnyone": True,
    "anyoneSentAt": None,
    "contactColors": {},
    "lastSent": {},
    "pausedUntil": None,
    "autostartAdded": False,
    "reloginNoticeShown": False,
    "language": "",
}


class Settings:
    def __init__(self, path=None):
        self.path = path or os.path.join(config.config_dir(), "settings.json")
        self.values = dict(DEFAULTS)
        try:
            with open(self.path) as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                self.values.update({k: v for k, v in stored.items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass

    def __getitem__(self, key):
        return self.values[key]

    def __setitem__(self, key, value):
        self.values[key] = value
        self.save()

    def save(self):
        """Writes the file; when it can't (a read-only or foreign home), the
        values stay in memory and the app goes on."""
        folder = os.path.dirname(self.path)
        tmp = None
        try:
            os.makedirs(folder, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=folder, prefix=".settings-")
            with os.fdopen(fd, "w") as f:
                json.dump(self.values, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError as error:
            print(f"lovearound: can't save {self.path}: {error}", file=sys.stderr)
            if tmp:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
