#!/usr/bin/env bash
#
# publish.sh — release the newest dist/lovearound_<version>_all.deb (from
# build.sh) as the GitHub release v<version> of this repository, under its own
# name and as LoveAround.deb. lovearound.me/download/LoveAround.deb redirects
# to the latest release's LoveAround.deb (firebase.json in the site repo).
#
# The release also carries the signed index of the APT repository
# lovearound.me/apt (tools/make_repo.sh), which firebase.json redirects to the
# latest release; so the installed apps see a version only once it is
# released. Signing needs the key in APT_SIGNING_KEY, which only the release
# workflow has (its GitHub secret; the other copy is in the owner's password
# manager), so releases go through the workflow.
#
# Needs gh, logged in with write access to the repository; the release is
# tagged at HEAD, so push first. Needs the history and tags (for the notes).
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

# What changed, for the release page: each `Release-note: …` line in the
# messages of the commits since the last release, oldest first. One line per
# change, anywhere in the message; a commit nobody would notice has none.
PREV="$(git describe --tags --abbrev=0 --match 'v*' HEAD 2>/dev/null || true)"
NOTES="$(git log --reverse --format=%B "${PREV:+$PREV..}HEAD" \
  | sed -n -e 's/^Release-note:[[:space:]]*\(.*[^[:space:]]\)[[:space:]]*$/- \1/p')"
if [[ -z "$NOTES" ]]; then
  echo "::warning::no Release-note lines since ${PREV:-the first commit}"
  NOTES="Small fixes under the hood."
fi
printf '>> notes:\n%s\n' "$NOTES"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp "$DEB" "$STAGE/"
cp "$DEB" "$STAGE/LoveAround.deb"
tools/make_repo.sh "$DEB" "$STAGE/apt"

echo ">> releasing $TAG ($(du -h "$DEB" | cut -f1))"
gh release create "$TAG" -R "$REPO" --target "$(git rev-parse HEAD)" --latest \
  --title "Love Around $VERSION" --notes "$NOTES" \
  "$STAGE/$(basename "$DEB")" "$STAGE/LoveAround.deb" "$STAGE"/apt/*
echo ">> done: https://github.com/$REPO/releases/tag/$TAG"
