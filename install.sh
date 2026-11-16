#!/bin/bash
# Installs Love Around on any distro: ./install.sh --user puts it in ~/.local,
# and --user --uninstall removes it. Packagers pass --prefix /usr --destdir
# <staging>. A release archive, which has no git history, passes --as-version.
# Dependencies are checked, not installed: their package names differ by distro.
set -euo pipefail

PKG=lovearound
APP_ID=me.lovearound.LoveAround
EXTENSION=lovearound@lovearound.me
MODE=
PREFIX=
DESTDIR=
UNINSTALL=
VERSION=

usage() {
    echo "usage: $0 --user [--uninstall] [--as-version X.Y.Z]" >&2
    echo "       $0 --prefix DIR --destdir DIR [--as-version X.Y.Z]" >&2
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --user) MODE=user ;;
        --prefix) [ $# -ge 2 ] || usage; PREFIX="$2"; shift ;;
        --destdir) [ $# -ge 2 ] || usage; DESTDIR="$2"; shift ;;
        --as-version) [ $# -ge 2 ] || usage; VERSION="$2"; shift ;;
        --uninstall) UNINSTALL=1 ;;
        *) usage ;;
    esac
    shift
done

# A user install updates itself (get.sh); a package is updated by its package manager.
if [ "$MODE" = user ]; then
    [ -z "$PREFIX$DESTDIR" ] || usage
elif [ -n "$PREFIX" ] && [ -n "$DESTDIR" ] && [ -z "$UNINSTALL" ]; then
    MODE=package
else
    usage
fi

absolute() {
    case "$1" in /*) echo "$1" ;; *) echo "$PWD/$1" ;; esac
}
if [ "$MODE" = user ]; then
    PREFIX="$HOME/.local"
    # GNOME Shell and the desktop look for a user's files in XDG_DATA_HOME, not under the prefix.
    share="${XDG_DATA_HOME:-$HOME/.local/share}"
else
    PREFIX="$(absolute "$PREFIX")"
    DESTDIR="$(absolute "$DESTDIR")"
    share="$DESTDIR$PREFIX/share"
fi
cd "$(dirname "$0")"

P="$DESTDIR$PREFIX"
lib="$P/lib/$PKG"

# Everything installed but the code, which a reinstall swaps instead.
remove_files() {
    rm -rf "$share/gnome-shell/extensions/$EXTENSION"
    rm -f "$P/bin/$PKG" "$share/applications/$APP_ID.desktop" "$share/metainfo/$APP_ID.metainfo.xml" \
        "$share"/icons/hicolor/*/apps/$APP_ID.png
}

refresh_caches() {
    # Packages leave this to their own triggers.
    [ "$MODE" = user ] || return 0
    if command -v update-desktop-database >/dev/null; then
        update-desktop-database -q "$share/applications" || true
    fi
    if command -v gtk-update-icon-cache >/dev/null && [ -f "$share/icons/hicolor/index.theme" ]; then
        gtk-update-icon-cache -q -t "$share/icons/hicolor" || true
    fi
}

if [ -n "$UNINSTALL" ]; then
    rm -rf "$lib" "$lib.new" "$lib.old"
    remove_files
    # The app adds itself to autostart on its first launch.
    rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/$APP_ID.desktop"
    refresh_caches
    exit 0
fi

if [ -z "$VERSION" ]; then
    if [ "$(git rev-parse --is-shallow-repository 2>/dev/null)" != false ]; then
        echo "lovearound: the version is counted from git history; install from a full clone or pass --as-version" >&2
        exit 1
    fi
    # 0.2.<commit count of this repository>. 0.2 because the 0.1 builds came from
    # the old shared repository, whose count reached 0.1.92.
    VERSION="0.2.$(git rev-list --count HEAD)"
fi

# Checked before anything is removed. make_icons.py imports lovearound, whose
# __init__ requires every typelib, so a package build needs them too. The
# launcher's interpreter is /usr/bin/python3, whatever python3 is on PATH.
/usr/bin/python3 - <<'CHECK'
import importlib
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("deps", "lovearound/deps.py")
deps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deps)
missing = []
try:
    import gi
except ImportError:
    missing.append("python module gi")
else:
    for namespace, version in deps.TYPELIBS:
        try:
            gi.require_version(namespace, version)
        except ValueError:
            missing.append("typelib %s-%s" % (namespace, version))
    try:
        gi.require_foreign("cairo")
    except ImportError:
        missing.append("gi's cairo integration")
for module in deps.MODULES:
    try:
        importlib.import_module(module)
    except ImportError:
        missing.append("python module " + module)
if missing:
    print("lovearound: missing " + ", ".join(missing) + "; install them with your package manager (see README.md)",
          file=sys.stderr)
    sys.exit(1)
CHECK

# The running app imports from $lib, which must never be visible half-written.
staged="$lib.new"
rm -rf "$staged" "$lib.old"
mkdir -p "$staged/kwin" "$staged/lovearound/i18n"
# The code, without caches; VERSION is what the running app watches for an upgrade.
tar --exclude=__pycache__ -cf - lovearound | tar -xf - -C "$staged"
echo "$VERSION" > "$staged/lovearound/VERSION"
# The dictionaries (i18n.py).
cp i18n/*.json "$staged/lovearound/i18n/"
install -m 644 kwin/fullscreen.js "$staged/kwin/"
[ "$MODE" = package ] || install -m 644 tools/get.sh "$staged/get.sh"

# A reinstall must leave no file a newer version dropped.
remove_files
mkdir -p "$P/bin" "$share/applications" "$share/metainfo" "$share/gnome-shell/extensions"
install -m 755 bin/lovearound "$P/bin/$PKG"
# The menu entry and lovearound:// links run the launcher by its full path, so
# ~/.local/bin needn't be on the session's PATH. A path the Exec key would have
# to quote keeps the bare name (config.launcher does the same for autostart).
case "$PREFIX/bin/$PKG" in
    *[!A-Za-z0-9/._+-]*) install -m 644 data/$APP_ID.desktop "$share/applications/" ;;
    *) sed "s|^Exec=$PKG |Exec=$PREFIX/bin/$PKG |" data/$APP_ID.desktop > "$share/applications/$APP_ID.desktop"
       chmod 644 "$share/applications/$APP_ID.desktop" ;;
esac
install -m 644 data/$APP_ID.metainfo.xml "$share/metainfo/"
cp -r gnome-extension/$EXTENSION "$share/gnome-shell/extensions/"
/usr/bin/python3 tools/make_icons.py "$share/icons/hicolor"
[ ! -d "$lib" ] || mv "$lib" "$lib.old"
mv "$staged" "$lib"
# A running app watches VERSION in the directory it started from, now $lib.old:
# the new version written there tells it to restart into $lib.
[ ! -f "$lib.old/lovearound/VERSION" ] || cp "$lib/lovearound/VERSION" "$lib.old/lovearound/VERSION"
rm -rf "$lib.old"
refresh_caches

[ "$MODE" = user ] || exit 0
echo "Love Around $VERSION installed to $PREFIX"
case ":$PATH:" in
    *":$PREFIX/bin:"*) ;;
    *) echo "Add $PREFIX/bin to PATH to run lovearound from a terminal; the menu entry and autostart work without it." ;;
esac
