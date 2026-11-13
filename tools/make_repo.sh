#!/usr/bin/env bash
#
# make_repo.sh DEB OUT — the index of the APT repository at
# https://lovearound.me/apt for one .deb, written to OUT: Packages,
# Packages.gz, Release, Release.gpg, InRelease, and lovearound.gpg (the
# public key, for anyone adding the repository by hand).
#
# A flat repository ("URIs: https://lovearound.me/", "Suites: apt/", so apt
# asks for /apt/InRelease: with "Suites: ./" it would ask for /apt/./InRelease,
# which Firebase answers with a redirect to its origin and a 404), and no file
# of it lives on the site:
# firebase.json in the site repo redirects /apt/<file> to the latest GitHub
# release of this repository, where publish.sh uploads these files, and
# /apt/pool/<version>/<deb> to the release v<version>, which is where the
# Filename in Packages points. The package itself adds the repository
# (data/lovearound.sources), so apt and the desktop's updater update it.
#
# Signed with the private key in $APT_SIGNING_KEY (ASCII-armored, no
# passphrase; GitHub secret APT_SIGNING_KEY) or, if that is unset, in the file
# $APT_SIGNING_KEY_FILE (default ~/.config/lovearound/apt_signing_key.asc).
# Its public half is data/lovearound.gpg; the two must match, or every
# installed app stops getting updates.
#
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
DEB="$1"
OUT="$2"
[[ -f "$DEB" ]] || { echo ">> no $DEB"; exit 1; }
VERSION="$(dpkg-deb -f "$DEB" Version)"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export GNUPGHOME="$WORK/gnupg"
mkdir -m 700 "$GNUPGHOME"
if [[ -n "${APT_SIGNING_KEY:-}" ]]; then
  printf '%s\n' "$APT_SIGNING_KEY" | gpg --batch --quiet --import
else
  KEY="${APT_SIGNING_KEY_FILE:-$HOME/.config/lovearound/apt_signing_key.asc}"
  [[ -f "$KEY" ]] || { echo ">> no APT_SIGNING_KEY and no $KEY"; exit 1; }
  gpg --batch --quiet --import "$KEY"
fi
FPR="$(gpg --batch --with-colons --list-secret-keys | awk -F: '/^fpr/ { print $10; exit }')"
gpg --batch --quiet --import data/lovearound.gpg
SHIPPED="$(gpg --batch --with-colons --show-keys data/lovearound.gpg | awk -F: '/^fpr/ { print $10; exit }')"
[[ "$FPR" == "$SHIPPED" ]] || { echo ">> the signing key $FPR is not data/lovearound.gpg ($SHIPPED)"; exit 1; }

# Filename is relative to the URI, the site's root: apt/pool/<version>/<deb>.
mkdir -p "$WORK/repo/apt/pool/$VERSION" "$OUT"
cp "$DEB" "$WORK/repo/apt/pool/$VERSION/lovearound_${VERSION}_all.deb"
(
  cd "$WORK/repo"
  apt-ftparchive packages apt/pool > Packages
  gzip -9n -k Packages
  apt-ftparchive \
    -o APT::FTPArchive::Release::Origin="Love Around" \
    -o APT::FTPArchive::Release::Label="Love Around" \
    -o APT::FTPArchive::Release::Suite=apt \
    -o APT::FTPArchive::Release::Architectures="all amd64 arm64 armhf i386 riscv64 ppc64el s390x" \
    -o APT::FTPArchive::Release::Description="Love Around for Ubuntu and Debian" \
    release . > "$WORK/Release"
  mv "$WORK/Release" Release
  gpg --batch --yes --local-user "$FPR" --digest-algo SHA512 --clearsign -o InRelease Release
  gpg --batch --yes --local-user "$FPR" --digest-algo SHA512 --detach-sign --armor -o Release.gpg Release
)
cp "$WORK/repo/"{Packages,Packages.gz,Release,Release.gpg,InRelease} "$OUT/"
cp data/lovearound.gpg "$OUT/lovearound.gpg"
echo ">> $OUT: apt index for $VERSION, signed by $FPR"
