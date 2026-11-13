#!/bin/bash
# Installs Love Around on any distro: ./install.sh --user puts it in ~/.local,
# sudo ./install.sh in /usr/local. Packagers pass --prefix /usr --destdir
# <staging>. --uninstall removes the same files. A release archive, which has
# no git history, passes --as-version.
# Dependencies are checked, not installed: their package names differ by distro.
set -euo pipefail

PKG=lovearound
APP_ID=me.lovearound.LoveAround
EXTENSION=lovearound@lovearound.me
PREFIX=/usr/local
DESTDIR=
UNINSTALL=
DATA=
VERSION=

usage() {
    echo "usage: $0 [--user | --prefix DIR] [--destdir DIR] [--as-version X.Y.Z] [--uninstall]" >&2
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --user) PREFIX="$HOME/.local"; DATA="${XDG_DATA_HOME:-$HOME/.local/share}" ;;
        --prefix) [ $# -ge 2 ] || usage; PREFIX="$2"; shift ;;
        --destdir) [ $# -ge 2 ] || usage; DESTDIR="$2"; shift ;;
        --as-version) [ $# -ge 2 ] || usage; VERSION="$2"; shift ;;
        --uninstall) UNINSTALL=1 ;;
        *) usage ;;
    esac
    shift
done

absolute() {
    case "$1" in /*|"") echo "$1" ;; *) echo "$PWD/$1" ;; esac
}
PREFIX="$(absolute "$PREFIX")"
DESTDIR="$(absolute "$DESTDIR")"
cd "$(dirname "$0")"
# Under sudo, bytecode written next to the checkout's sources would belong to root.
export PYTHONDONTWRITEBYTECODE=1

P="$DESTDIR$PREFIX"
lib="$P/lib/$PKG"
# GNOME Shell and the desktop look for a user's files in XDG_DATA_HOME, not under the prefix.
share="$DESTDIR${DATA:-$PREFIX/share}"

# Everything installed but the code, which a reinstall swaps instead.
remove_files() {
    rm -rf "$share/gnome-shell/extensions/$EXTENSION"
    rm -f "$P/bin/$PKG" "$share/applications/$APP_ID.desktop" "$share/metainfo/$APP_ID.metainfo.xml" \
        "$share"/icons/hicolor/*/apps/$APP_ID.png
}

refresh_caches() {
    # Packages leave this to their own triggers.
    [ -z "$DESTDIR" ] || return 0
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
    refresh_caches
    exit 0
fi

if [ -z "$VERSION" ]; then
    # Under sudo the checkout belongs to another user, which git refuses without safe.directory.
    git() { command git -c safe.directory="$PWD" "$@"; }
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

# A reinstall must leave no file a newer version dropped.
remove_files
mkdir -p "$P/bin" "$share/applications" "$share/metainfo" "$share/gnome-shell/extensions"
install -m 755 bin/lovearound "$P/bin/$PKG"
install -m 644 data/$APP_ID.desktop "$share/applications/"
install -m 644 data/$APP_ID.metainfo.xml "$share/metainfo/"
cp -r gnome-extension/$EXTENSION "$share/gnome-shell/extensions/"
/usr/bin/python3 tools/make_icons.py "$share/icons/hicolor"
[ ! -d "$lib" ] || mv "$lib" "$lib.old"
mv "$staged" "$lib"
rm -rf "$lib.old"
refresh_caches

[ -z "$DESTDIR" ] || exit 0
echo "Love Around $VERSION installed to $PREFIX"
case ":$PATH:" in
    *":$PREFIX/bin:"*) ;;
    *) echo "Add $PREFIX/bin to PATH for the menu entry, links and autostart to find it." ;;
esac
