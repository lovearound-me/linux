#!/bin/sh
# Installs the latest release into ~/.local:
#   curl -fsSL https://raw.githubusercontent.com/lovearound-me/linux/main/tools/get.sh | sh
# POSIX sh, because it runs piped from curl. GitHub publishes no checksum for a
# tag's source archive.
set -eu

usage() {
  echo "usage: get.sh [--latest | --version X.Y.Z]" >&2
  exit 2
}

# A truncated download must run nothing, so main is called only on the last line.
main() {
  repo="lovearound-me/linux"
  tag=
  print=
  case "$#:${1:-}" in
    0:) ;;
    1:--latest) print=1 ;;
    2:--version) tag="v$2" ;;
    *) usage ;;
  esac

  if [ -z "$tag" ]; then
    # The API is rate-limited without a token; the latest-release redirect is not.
    tag=$(curl -fsSI -o /dev/null -w '%{redirect_url}' "https://github.com/$repo/releases/latest" | sed 's#.*/##')
  fi
  case "$tag" in
    v[0-9]*) ;;
    *)
      echo "get.sh: could not resolve the latest release" >&2
      exit 1
      ;;
  esac
  version="${tag#v}"
  if [ -n "$print" ]; then
    echo "$version"
    exit 0
  fi

  command -v bash >/dev/null 2>&1 || { echo "get.sh: bash is required" >&2; exit 1; }

  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  curl -fsSL -o "$tmp/source.tar.gz" "https://github.com/$repo/archive/refs/tags/$tag.tar.gz"
  tar xzf "$tmp/source.tar.gz" -C "$tmp" --strip-components=1
  if [ ! -f "$tmp/install.sh" ]; then
    echo "get.sh: release $tag predates install.sh; install the .deb from https://github.com/$repo/releases/tag/$tag" >&2
    exit 1
  fi

  bash "$tmp/install.sh" --user --as-version "$version"
}

main "$@"
