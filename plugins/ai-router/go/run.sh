#!/bin/sh
# ai-router — build-on-first-use launcher.
#
# Plugins have no install hook, so the server is built from source the first
# time this runs (and rebuilt whenever a source file changes), then exec'd.
# Requires the Go toolchain on the target. Every line of wrapper output goes to
# STDERR — stdout is the MCP JSON-RPC stream and must stay clean.

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)   # the go/ dir
bin="$here/.bin/ai-router"

# MCP servers are spawned with a minimal PATH (e.g. `uv`/`go` often absent), so
# locate the Go toolchain explicitly across the usual install locations.
find_go() {
  if command -v go >/dev/null 2>&1; then command -v go; return 0; fi
  for g in /opt/homebrew/bin/go /usr/local/go/bin/go /usr/local/bin/go \
           "${HOME:-/nonexistent}/go/bin/go" "${HOME:-/nonexistent}/.local/bin/go" \
           "${GOROOT:-/nonexistent}/bin/go" /snap/bin/go; do
    [ -x "$g" ] && { echo "$g"; return 0; }
  done
  return 1
}

# Rebuild if the binary is missing or any source is newer than it.
stale=1
if [ -x "$bin" ]; then
  newer=$(find "$here" -maxdepth 1 \
    \( -name '*.go' -o -name 'go.mod' -o -name 'go.sum' -o -name 'models.json' \) \
    -newer "$bin" 2>/dev/null | head -n1)
  [ -z "$newer" ] && stale=0
fi

if [ "$stale" -ne 0 ]; then
  go=$(find_go) || {
    echo "ai-router: Go toolchain not found (PATH or common install locations)." >&2
    echo "  This plugin builds its server from source on first use — install Go: https://go.dev/dl/" >&2
    exit 127
  }
  echo "ai-router: building server from source (first run / sources changed)…" >&2
  mkdir -p "$here/.bin"
  if ! ( cd "$here" && "$go" build -o "$bin" . ) 1>&2; then
    echo "ai-router: 'go build' failed (see errors above)." >&2
    exit 1
  fi
  echo "ai-router: build OK." >&2
fi

exec "$bin" "$@"
