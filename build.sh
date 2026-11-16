#!/bin/bash
# Builds dist/lovearound_<version>_all.deb for Ubuntu 24.04+ (GNOME
# and KDE Plasma). Python, so one package for every architecture. Only
# dpkg-deb is required; lintian runs if it is there.
set -euo pipefail
cd "$(dirname "$0")"

PKG=lovearound
OUT=dist
ROOT="$OUT/root"
rm -rf "$ROOT"
./install.sh --prefix /usr --destdir "$ROOT"
VERSION="$(cat "$ROOT/usr/lib/$PKG/lovearound/VERSION")"
mkdir -p "$ROOT/DEBIAN" "$ROOT/usr/share/doc/$PKG"
# The APT repository at lovearound.me/apt (tools/make_repo.sh), so apt and the
# desktop's updater update the package once it is installed from a download.
# The source is a plain file, not a conffile: removing the package must take it
# away with the keyring, or apt update fails on a missing Signed-By. (lintian
# flags both; they are rules for packages in the Debian archive.)
mkdir -p "$ROOT/usr/share/keyrings" "$ROOT/etc/apt/sources.list.d"
install -m 644 data/lovearound.gpg "$ROOT/usr/share/keyrings/lovearound.gpg"
install -m 644 data/lovearound.sources "$ROOT/etc/apt/sources.list.d/lovearound.sources"

cat > "$ROOT/usr/share/doc/$PKG/copyright" <<COPY
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: Love Around
Source: https://github.com/lovearound-me/linux

Files: *
Copyright: $(date +%Y) Love Around
License: Expat
 Permission is hereby granted, free of charge, to any person obtaining a copy
 of this software and associated documentation files (the "Software"), to deal
 in the Software without restriction, including without limitation the rights
 to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 copies of the Software, and to permit persons to whom the Software is
 furnished to do so, subject to the following conditions:
 .
 The above copyright notice and this permission notice shall be included in all
 copies or substantial portions of the Software.
 .
 THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 SOFTWARE.
COPY
gzip -9n -c > "$ROOT/usr/share/doc/$PKG/changelog.gz" <<LOG
$PKG ($VERSION) stable; urgency=low

  * Build ${VERSION##*.}.

 -- Love Around <hello@lovearound.me>  $(date -R)
LOG

find "$ROOT" -type d -exec chmod 755 {} +
find "$ROOT/usr" "$ROOT/etc" -type f ! -path "*/usr/bin/*" -exec chmod 644 {} +

SIZE="$(du -sk "$ROOT/usr" "$ROOT/etc" | awk '{ s += $1 } END { print s }')"
cat > "$ROOT/DEBIAN/control" <<CONTROL
Package: $PKG
Version: $VERSION
Architecture: all
Maintainer: Love Around <hello@lovearound.me>
Installed-Size: $SIZE
Depends: python3 (>= 3.10), python3-cryptography, python3-gi, python3-gi-cairo, python3-cairo, gir1.2-gtk-3.0, gir1.2-soup-3.0, gir1.2-secret-1, gir1.2-gtklayershell-0.1
Conflicts: love-around
Replaces: love-around
Recommends: gir1.2-gsound-1.0, fonts-noto-color-emoji, gnome-shell-extension-appindicator, gnome-keyring | libkf5wallet-bin, xdg-desktop-portal
Section: net
Priority: optional
Homepage: https://lovearound.me
Description: tap when you think of someone, and they feel it
 A heart in the tray. Tap someone's circle and the edges of their screen
 glow softly in a color of their choosing, with emoji floating up. They
 never learn who sent it.
 .
 On GNOME Shell the glow is drawn by a Shell extension that comes with the
 package; on KDE Plasma and wlroots compositors by a layer-shell overlay.
CONTROL

# Desktop and icon caches are refreshed by dpkg triggers on Ubuntu.
cat > "$ROOT/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
if [ "$1" = configure ] && command -v update-desktop-database >/dev/null; then
    update-desktop-database -q /usr/share/applications || true
fi
POST
chmod 755 "$ROOT/DEBIAN/postinst"
# Python leaves __pycache__ next to the code when root runs it; not ours to
# keep through an upgrade or a removal.
cat > "$ROOT/DEBIAN/prerm" <<'PRE'
#!/bin/sh
set -e
if [ -d /usr/lib/lovearound ]; then
    find /usr/lib/lovearound -depth -name __pycache__ -type d -exec rm -rf {} + || true
fi
PRE
chmod 755 "$ROOT/DEBIAN/prerm"

DEB="$OUT/${PKG}_${VERSION}_all.deb"
dpkg-deb --root-owner-group -Zxz --build "$ROOT" "$DEB" >/dev/null
rm -rf "$ROOT"
echo "$DEB"
if command -v lintian >/dev/null; then
    lintian --profile ubuntu --suppress-tags no-manual-page,extended-description-is-probably-too-short,file-in-etc-not-marked-as-conffile,package-installs-apt-sources "$DEB" || true
fi
