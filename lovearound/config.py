import os
import re

# The server (Cloud Run behind api.lovearound.me): REST + WS /v1/stream.
API_BASE = "https://api.lovearound.me"
# Firebase Web API key: public, identifies the project to Firebase Auth.
FIREBASE_API_KEY = "AIzaSyBZJfln_KXsxRxo3fvVaV1ePmiVUIn5YXY"
# The site: install page, invite links /i/<code>, the sign-in page /signin/.
SITE = "https://lovearound.me"
URL_SCHEME = "lovearound"
# The old name: the site still sends needed:// links, the Mac and Windows apps take them.
OLD_URL_SCHEMES = ("needed",)
URL_SCHEMES = (URL_SCHEME,) + OLD_URL_SCHEMES

APP_ID = "me.lovearound.LoveAround"
# The web app's «Способы входа»: adding Google, Apple or email to the account.
SIGN_IN_METHODS = "https://app.lovearound.me/#/settings/signin"

# Tests point the app at a fake server.
API_BASE = os.environ.get("LOVEAROUND_API", API_BASE)
FIREBASE_TOKEN = os.environ.get("LOVEAROUND_TOKEN", "https://securetoken.googleapis.com/v1/token")

# The lovearound package's parent: the checkout, or install.sh's <prefix>/lib/lovearound.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Written by install.sh; a checkout runs as "dev".
VERSION_FILE = os.path.join(os.path.dirname(__file__), "VERSION")


def read_version():
    try:
        with open(VERSION_FILE) as f:
            return f.read().strip() or "dev"
    except OSError:
        return "dev"


VERSION = read_version()
# Sent as X-Client with every request, so the server logs which version sent what.
CLIENT = "linux/" + VERSION


def launcher():
    """The installed <prefix>/bin/lovearound by its full path, for autostart: the
    session's PATH may lack ~/.local/bin. A checkout, or a path a .desktop Exec
    would have to quote, gets the bare name."""
    if os.path.basename(ROOT) == "lovearound" and os.path.basename(os.path.dirname(ROOT)) == "lib":
        path = os.path.join(os.path.dirname(os.path.dirname(ROOT)), "bin", "lovearound")
        if os.path.isfile(path) and re.fullmatch(r"[A-Za-z0-9/._+-]+", path):
            return path
    return "lovearound"


def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "lovearound")


def is_link(text):
    """One of the app's own links, lovearound://… (or the old needed://…)."""
    return text.startswith(tuple(scheme + ":" for scheme in URL_SCHEMES))
