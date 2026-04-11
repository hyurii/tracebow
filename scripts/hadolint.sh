#!/usr/bin/env bash
# Resolve hadolint: PATH, then Docker, then cached binary from GitHub releases.
set -euo pipefail

HADOLINT_VERSION="${HADOLINT_VERSION:-v2.14.0}"

if command -v hadolint >/dev/null 2>&1; then
  exec hadolint "$@"
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  exec docker run --rm -i -v "$PWD:$PWD" -w "$PWD" "hadolint/hadolint:${HADOLINT_VERSION#v}" hadolint "$@"
fi

cache_bin() {
  local base="${XDG_CACHE_HOME:-$HOME/.cache}/tracebow-hadolint"
  local dir="${base}/${HADOLINT_VERSION}"
  mkdir -p "$dir"
  echo "${dir}/hadolint"
}

download_url() {
  local os arch asset
  os=$(uname -s)
  arch=$(uname -m)
  case "${os}-${arch}" in
    Darwin-arm64) asset=hadolint-macos-arm64 ;;
    Darwin-x86_64) asset=hadolint-macos-x86_64 ;;
    Linux-x86_64) asset=hadolint-linux-x86_64 ;;
    Linux-aarch64 | Linux-arm64) asset=hadolint-linux-arm64 ;;
    *)
      echo "hadolint: unsupported platform ${os}-${arch}" >&2
      return 1
      ;;
  esac
  echo "https://github.com/hadolint/hadolint/releases/download/${HADOLINT_VERSION}/${asset}"
}

bin=$(cache_bin)
if [[ ! -x "$bin" ]]; then
  url=$(download_url) || exit 1
  echo "hadolint: downloading ${HADOLINT_VERSION} to ${bin}..." >&2
  curl -fsSL "$url" -o "$bin"
  chmod +x "$bin"
fi

exec "$bin" "$@"
