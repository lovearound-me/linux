#!/usr/bin/env bash
#
# publish.sh — release the newest dist/lovearound_<version>_all.deb (from
# build.sh) as the GitHub release v<version> of this repository, under its own
# name and as LoveAround.deb. lovearound.me/download/LoveAround.deb redirects
# to the latest release's LoveAround.deb (firebase.json in the site repo).
#
# Needs gh, logged in with write access to the repository; the release is
# tagged at HEAD, so push first.
#
#   REPO=…   the GitHub repository (default: lovearound-me/linux)
#
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
REPO="${REPO:-lovearound-me/linux}"

DEB="$(ls -t dist/lovearound_*_all.deb 2>/dev/null | head -1 || true)"
[[ -n "$DEB" ]] || { echo ">> no dist/lovearound_*_all.deb — run ./build.sh first"; exit 1; }
VERSION="$(basename "$DEB" | sed -E 's/^lovearound_(.*)_all\.deb$/\1/')"
TAG="v$VERSION"
if gh release view "$TAG" -R "$REPO" >/dev/null 2>&1; then
  echo ">> $TAG is already released"; exit 1
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp "$DEB" "$STAGE/"
cp "$DEB" "$STAGE/LoveAround.deb"

echo ">> releasing $TAG ($(du -h "$DEB" | cut -f1))"
gh release create "$TAG" -R "$REPO" --target "$(git rev-parse HEAD)" --latest \
  --title "Love Around $VERSION" --notes "" \
  "$STAGE/$(basename "$DEB")" "$STAGE/LoveAround.deb"
echo ">> done: https://github.com/$REPO/releases/tag/$TAG"
