#!/bin/sh
# ai-router — build-on-first-use launcher with a stable, content-hashed build cache.
#
# Plugins have no install hook, so the server is built from source the first time
# a given source revision runs, then exec'd. The compiled binary is cached in
#   ${XDG_CACHE_HOME:-~/.cache}/ai-router/<os>-<arch>-<srchash>/ai-router
# keyed by a hash of the build inputs (*.go, go.mod, go.sum, models.json) — so it
# is reused across plugin updates, reinstalls, and Claude Code restarts whenever
# the source is unchanged. Only a genuine code change produces a new key (one
# rebuild), and that build can be primed ahead of time by running this script
# from any checkout of the same revision. Requires the Go toolchain.
#
# All wrapper output goes to STDERR — stdout is the MCP JSON-RPC stream.

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)   # the go/ dir

hasher() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256
  elif command -v sha256sum >/dev/null 2>&1; then sha256sum
  else cksum; fi | awk '{print $1}'
}

# Hash of the build inputs. run.sh itself is intentionally excluded — changing
# the launcher must not force a server rebuild.
src_hash() {
  ( cd "$here" \
      && find . -maxdepth 2 \
           \( -name '*.go' -o -name 'go.mod' -o -name 'go.sum' -o -name 'models.json' \) -type f \
      | LC_ALL=C sort \
      | while IFS= read -r f; do cat "$f"; done ) 2>/dev/null | hasher
}

# MCP servers get a minimal PATH, so locate the Go toolchain explicitly.
find_go() {
  if command -v go >/dev/null 2>&1; then command -v go; return 0; fi
  for g in /opt/homebrew/bin/go /usr/local/go/bin/go /usr/local/bin/go \
           "${HOME:-/nonexistent}/go/bin/go" "${HOME:-/nonexistent}/.local/bin/go" \
           "${GOROOT:-/nonexistent}/bin/go" /snap/bin/go; do
    [ -x "$g" ] && { echo "$g"; return 0; }
  done
  return 1
}

os=$(uname -s 2>/dev/null || echo unknown)
arch=$(uname -m 2>/dev/null || echo unknown)
cache_root="${XDG_CACHE_HOME:-$HOME/.cache}/ai-router"
key="$os-$arch-$(src_hash)"
bin="$cache_root/$key/ai-router"

if [ ! -x "$bin" ]; then
  go=$(find_go) || {
    echo "ai-router: Go toolchain not found (PATH or common install locations)." >&2
    echo "  This plugin builds its server from source on first use — install Go: https://go.dev/dl/" >&2
    exit 127
  }
  echo "ai-router: building server from source (new revision)…" >&2
  mkdir -p "$cache_root/$key"
  # Build to a temp path then atomically rename: a killed/partial build never
  # looks complete, so the next launch simply rebuilds.
  tmp="$bin.tmp.$$"
  if ! ( cd "$here" && "$go" build -o "$tmp" . ) 1>&2; then
    rm -f "$tmp"
    echo "ai-router: 'go build' failed (see errors above)." >&2
    exit 1
  fi
  mv -f "$tmp" "$bin"
  # Keep the cache small: drop older builds for this platform.
  for d in "$cache_root/$os-$arch-"*; do
    [ -d "$d" ] && [ "$d" != "$cache_root/$key" ] && rm -rf "$d"
  done
  echo "ai-router: build OK." >&2
fi

exec "$bin" "$@"
