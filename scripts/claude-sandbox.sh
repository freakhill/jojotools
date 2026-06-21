#!/usr/bin/env bash
# claude-sandbox.sh — launch `claude --dangerously-skip-permissions`
# inside a macOS sandbox-exec jail.
#
# Usage:
#   cd /path/to/worktree
#   claude-sandbox.sh [extra claude args...]
#
# The current working directory is taken as the worktree. All file writes
# outside the worktree, the shared .git dir, ~/.claude, and standard
# cache/temp dirs are blocked. Reads and network are unrestricted.
#
# Run from inside a worktree. Running from the main checkout works but
# defeats the point of the sandbox — the main repo is the thing you're
# trying to protect.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
profile="$here/claude-sandbox.sb"

if [ ! -f "$profile" ]; then
  echo "claude-sandbox: profile not found at $profile" >&2
  exit 1
fi

worktree="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$worktree" ]; then
  echo "claude-sandbox: not inside a git repo (cd into your worktree first)" >&2
  exit 1
fi

git_dir_common="$(cd "$(git rev-parse --git-common-dir)" && pwd -P)"

worktree_real="$(cd "$worktree" && pwd -P)"
main_real="$(cd "$git_dir_common/.." && pwd -P)"
if [ "$worktree_real" = "$main_real" ]; then
  echo "claude-sandbox: WARNING — you are in the main checkout, not a linked worktree." >&2
  echo "  The sandbox will allow writes here. Consider:" >&2
  echo "  git worktree add .worktrees/<name> -b <name> && cd .worktrees/<name>" >&2
  read -r -p "  Continue anyway? [y/N] " ans
  case "$ans" in
    [yY]|[yY][eE][sS]) ;;
    *) exit 1 ;;
  esac
fi

# Render the profile: sandbox-exec does no env expansion, so substitute the
# __HOME__ placeholder with the real $HOME into a temp profile (keeps the .sb
# portable across machines/users instead of hard-coding a home path).
rendered="$(mktemp -t claude-sandbox.XXXXXX.sb)"
trap 'rm -f "$rendered"' EXIT
sed "s#__HOME__#$HOME#g" "$profile" > "$rendered"

sandbox-exec \
  -D WORKTREE="$worktree_real" \
  -D GIT_DIR_COMMON="$git_dir_common" \
  -f "$rendered" \
  claude --dangerously-skip-permissions "$@"
