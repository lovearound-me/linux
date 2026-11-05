"""JSON over HTTPS with urllib; called on worker threads."""
import json
import urllib.error
import urllib.request

TIMEOUT = 20


class Unreachable(Exception):
    """No answer at all: offline, DNS, a timeout."""


def call(method, url, body=None, headers=None, form=None):
    """Returns (status, parsed JSON or {})."""
    headers = dict(headers or {})
    data = None
    if form is not None:
        data = form.encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    except (urllib.error.URLError, OSError) as error:
        raise Unreachable(str(error)) from error
    try:
        parsed = json.loads(raw) if raw else {}
    except ValueError:
        parsed = {}
    return status, parsed if isinstance(parsed, dict) else {}
