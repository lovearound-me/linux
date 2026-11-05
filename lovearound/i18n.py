"""The app's languages: the dictionaries in i18n/<lang>.json at the top of the
repository, keyed by the Russian text.

    tr("Пауза до {time}", time="08:00")
    trn("{n} человек", 5)        # plural forms by the CLDR rules of the language

The language is the one chosen in Settings, or the first of the system's
(LANGUAGE, LC_ALL, LC_MESSAGES, LANG) that the app has, or English.
"""
import json
import os

# Native names, in the order of the language menu (the site's order).
LANGUAGES = (("en", "English"), ("es", "Español"), ("pt", "Português"), ("de", "Deutsch"),
             ("fr", "Français"), ("it", "Italiano"), ("pl", "Polski"), ("tr", "Türkçe"),
             ("uk", "Українська"), ("ru", "Русский"), ("id", "Bahasa Indonesia"), ("ko", "한국어"),
             ("zh", "中文"))
CODES = tuple(code for code, _ in LANGUAGES)
FALLBACK = "en"

_HERE = os.path.dirname(os.path.abspath(__file__))
# The package carries a copy (build.sh); a checkout reads the repository's.
_DIRS = (os.path.join(_HERE, "i18n"), os.path.join(_HERE, "..", "i18n"))

_lang = FALLBACK
_table = {}
_fallback = {}


def _load(code):
    for folder in _DIRS:
        try:
            with open(os.path.join(folder, code + ".json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return {}


def system_languages(environ=None):
    """The system's languages, most preferred first, as two-letter codes."""
    env = os.environ if environ is None else environ
    names = []
    if env.get("LANGUAGE"):
        names += env["LANGUAGE"].split(":")
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        if env.get(var):
            names.append(env[var])
            break
    out = []
    for name in names:
        code = name.split(".")[0].split("@")[0].split("_")[0].split("-")[0].lower()
        if code and code not in ("c", "posix") and code not in out:
            out.append(code)
    return out


def resolve(choice, environ=None):
    """The language to show: the chosen one, else the system's, else English."""
    if choice in CODES:
        return choice
    for code in system_languages(environ):
        if code in CODES:
            return code
    return FALLBACK


def set_language(choice, environ=None):
    """`choice`: a code from LANGUAGES, or "" for the system's."""
    global _lang, _table, _fallback
    _lang = resolve(choice, environ)
    _table = _load(_lang)
    # Russian is the text itself; other languages fall back to English.
    _fallback = {} if _lang in ("ru", FALLBACK) else _load(FALLBACK)
    return _lang


def language():
    return _lang


def _fill(text, args):
    for key, value in args.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def tr(text, **args):
    value = _table.get(text)
    if not isinstance(value, str):
        value = _fallback.get(text)
    if not isinstance(value, str):
        value = text
    return _fill(value, args)


def plural_category(lang, n):
    """CLDR cardinal categories for whole numbers, for the app's languages."""
    n = abs(int(n))
    if lang in ("ru", "uk"):
        if n % 10 == 1 and n % 100 != 11:
            return "one"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return "few"
        return "many"
    if lang == "pl":
        if n == 1:
            return "one"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return "few"
        return "many"
    if lang in ("fr", "pt"):
        return "one" if n in (0, 1) else "other"
    if lang in ("id", "ko", "zh"):
        return "other"
    return "one" if n == 1 else "other"


def _forms(table, text):
    value = table.get(text)
    return value if isinstance(value, dict) else None


def trn(text, n, **args):
    """`text` with {n}: the form for `n` in the current language."""
    forms, lang = _forms(_table, text), _lang
    if forms is None and _fallback:
        forms, lang = _forms(_fallback, text), FALLBACK
    if forms is None:
        value = text
    else:
        category = plural_category(lang, n)
        value = forms.get(category) or forms.get("other") or forms.get("many") or text
    return _fill(value, dict(args, n=n))


set_language("")


def N_(text):
    """Marks text for the dictionaries where it is translated later, when shown."""
    return text
