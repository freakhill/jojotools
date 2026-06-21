#!/bin/bash
# agent-mem.sh — agent-memory helper. Optional: README.md carries every block for plain-git use.
# Design: gen3-laneA (FLO-converged 2026-06-12). Repo: ~/.claude/agent-memory
# No `set -e` on purpose: every step degrades independently. `set -u` for typo safety.
set -u
REPO="${AGENT_MEM_REPO:-$HOME/.claude/agent-memory}"   # env override for testing
HOST=$(hostname -s)
LOCK="$REPO/.land.lock"
TOKEN="$$-$(date +%s)-$RANDOM"                 # fencing token, unique per script run (§6.1)
export LC_ALL=C                                # byte-exact awk length(); stable sort
export GIT_TERMINAL_PROMPT=0                   # never hang on credential prompts
export GIT_SSH_COMMAND="ssh -oBatchMode=yes -oConnectTimeout=5"  # bounded even without `timeout`
cd "$REPO" 2>/dev/null || { echo "agent-mem: no repo at $REPO" >&2; exit 0; }
# --- platform shim: macOS base has no `timeout`; declared dep is coreutils (gtimeout) ---
if ! command -v timeout >/dev/null 2>&1; then
  if command -v gtimeout >/dev/null 2>&1; then timeout() { gtimeout "$@"; }
  else timeout() { shift; "$@"; }   # remote ops stay bounded via ssh BatchMode+ConnectTimeout
  fi
fi
mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null || echo 0; }  # BSD then GNU

# ---------- §6.1 lock toolkit: steal / acquire / beat / alive ----------

steal() {  # ATOMIC stale-lock break: rename, then remove. Only one contender can win the mv.
  local G="$LOCK.stale.$$.$RANDOM"
  mv "$LOCK" "$G" 2>/dev/null && rm -rf "$G"
  # rename(2) is atomic: a contender that loses the race gets ENOENT and never touches the
  # NEW lock another contender may already have mkdir'ed at $LOCK.
}

acquire() {            # $1 = attempts, ~1s apart. Return 1 → caller defers, never waits on.
  local i AGE OP OL OCUR
  for i in $(seq 1 "$1"); do
    if mkdir "$LOCK" 2>/dev/null; then
      printf 'host=%s pid=%s lstart=%s token=%s\n' \
        "$HOST" "$$" "$(ps -p $$ -o lstart=)" "$TOKEN" > "$LOCK/owner"
      touch "$LOCK/hb"
      trap 'grep -qs "token=$TOKEN" "$LOCK/owner" && rm -rf "$LOCK"' EXIT INT TERM
      return 0
    fi
    if [ -e "$LOCK/hb" ]; then AGE=$(( $(date +%s) - $(mtime "$LOCK/hb") ))
    else AGE=$(( $(date +%s) - $(mtime "$LOCK") )); fi   # mid-mkdir race: dir mtime — a lock is never broken mid-birth
    OP=$(sed -n 's/.*pid=\([0-9]*\).*/\1/p' "$LOCK/owner" 2>/dev/null)
    OL=$(sed -n 's/.*lstart=\(.*\) token=.*/\1/p' "$LOCK/owner" 2>/dev/null)
    if [ "$AGE" -gt 90 ]; then steal; continue; fi       # heartbeat-stale → atomic steal
    if [ -n "$OP" ] && [ "$AGE" -gt 5 ]; then            # fast path: holder provably dead
      OCUR=$(ps -p "$OP" -o lstart= 2>/dev/null)
      if [ -z "$OCUR" ] || { [ -n "$OL" ] && [ "$OCUR" != "$OL" ]; }; then steal; continue; fi
    fi
    sleep 1
  done
  return 1
}

beat() {  # heartbeat + fencing: abort ALL master mutation if the lock was stolen under us
  grep -qs "token=$TOKEN" "$LOCK/owner" \
    || { echo "agent-mem: lock lost (fencing token gone) — aborting land" >&2; exit 75; }
  touch "$LOCK/hb"
}

alive() {  # $1 = pid, $2 = .who sidecar — true iff pid exists AND its start time matches
  local CUR; CUR=$(ps -p "$1" -o lstart= 2>/dev/null)
  [ -z "$CUR" ] && return 1                              # no such process → dead
  [ -f "$2" ] || { kill -0 "$1" 2>/dev/null; return; }   # no sidecar → plain pid-probe fallback
  [ "$CUR" = "$(sed -n 's/.*lstart=\(.*\)$/\1/p' "$2")" ]  # recycled pid → start time differs
}

# ---------- §6.2 merge recipe (lock holder only; always completes alone) ----------

merge_branch() {  # $1 = branch; deterministic; never leaves a conflicted state
  git merge --no-edit -q "$1" 2>/dev/null && return 0
  git diff --name-only --diff-filter=U | while read -r p; do
    HAS2=$(git ls-files -u -- "$p" | awk '$3==2'); HAS3=$(git ls-files -u -- "$p" | awk '$3==3')
    if [ -n "$HAS2" ] && [ -n "$HAS3" ]; then   # content (or add/add) conflict → keep BOTH sides
      git show ":1:$p" > /tmp/b.$$ 2>/dev/null || : > /tmp/b.$$
      git show ":2:$p" > /tmp/o.$$; git show ":3:$p" > /tmp/t.$$
      git merge-file --union -p /tmp/o.$$ /tmp/b.$$ /tmp/t.$$ > "$p"
    else                                        # delete/modify etc. → keep the side with content
      git checkout --theirs -- "$p" 2>/dev/null || git checkout --ours -- "$p"
    fi
    git add -- "$p"
  done
  rm -f /tmp/b.$$ /tmp/o.$$ /tmp/t.$$
  git commit --no-edit -q
}

# ---------- §6.3 adds-only land guard (mechanical append-only enforcement) ----------

guard_check() {  # $1 = branch; records protocol violations, never blocks landing
  BASE=$(git merge-base master "$1")
  git log --format=%s "$BASE..$1" | grep -q '^mem(hygiene):' && return 0
  VIOL=$(git diff "$BASE" "$1" --numstat -- '*.md' ':(exclude)*journal/*' ':(exclude)*INDEX.md' \
         | awk '$2 > 0 {print $3}')
  [ -z "$VIOL" ] && return 0
  TODAY=$(date +%F)
  for p in $VIOL; do
    mkdir -p "attic/$(dirname "$p")"
    git diff "$BASE" "$1" -- "$p" | grep '^-' | grep -v '^---' | cut -c2- \
      | sed "s/\$/ guard-restored:$TODAY/" >> "attic/$p"
  done
  echo "- guard: $1 removed/edited lines in: $VIOL [$TODAY] #guard" \
    >> "global/journal/$TODAY-guard.md"
  git add attic global/journal && git commit -qm "mem(land): guard — preserved lines edited by $1"
}

# ---------- §7 landing: salvage_all / do_land ----------

salvage_all() {   # PRE-LOCK, lock-free: branch commits + writer-branch pushes never need the lock.
  # Guarantees PreCompact/SessionEnd never lose notes even when the land below defers.
  git worktree list --porcelain | awk '/^worktree /{print $2}' | while read -r W; do
    case "$W" in */.wt/*) ;; *) continue ;; esac
    if [ -n "$(git -C "$W" status --porcelain 2>/dev/null)" ]; then
      { git -C "$W" add -A && git -C "$W" commit -qm "mem(salvage): snapshot $(basename "$W")"
        [ -f "$W.who" ] && touch "$W.who"; } 2>/dev/null
    fi
    BR="wt/$(basename "$W")"
    [ "$(git rev-list --count "master..$BR" 2>/dev/null || echo 0)" = 0 ] || \
      timeout 5 git push -q origin "$BR:$BR" 2>/dev/null || true   # off-machine backup
  done
  # Untracked strays → quarantine: the main checkout is read-only by protocol (writes go
  # via .wt/), and a stray committed in place reaches master + remote within minutes
  # (S13 decoy incident, 2026-06-12). Edits to tracked files keep the old salvage path.
  local TODAY p
  TODAY=$(date +%F)
  git status --porcelain | sed -n 's/^?? //p' | while read -r p; do
    p=${p%/}
    case "$p" in attic/*|.wt/*) continue ;; esac
    mkdir -p "attic/quarantine/$TODAY/$(dirname "$p")"
    mv "$p" "attic/quarantine/$TODAY/$p" 2>/dev/null || continue
    echo "- quarantined stray main-checkout file: $p [$TODAY] #guard" >> "global/journal/$TODAY-guard.md"
  done
  [ -n "$(git status --porcelain)" ] && git add -A && git commit -qm "mem(salvage): stray main-checkout edits (untracked quarantined to attic)"
}

do_land() {   # caller holds .land.lock with live TOKEN. Idempotent: re-running converges.
  PRE=$(git rev-parse HEAD)
  beat
  find .git -maxdepth 1 -name 'index.lock' -mmin +10 -delete 2>/dev/null
  rm -rf "$LOCK".stale.* 2>/dev/null   # step 0: leftovers of crashed steals (mv'ed dirs, never the live lock)

  # ---- 1. remote refresh — happens ONLY here, under the lock (start never touches the remote) --
  if timeout 10 git fetch -q origin 2>/dev/null; then
    beat; merge_branch origin/master
    # sweep writer branches other machines pushed at save/salvage — off-machine batching (§8)
    for RB in $(git branch -r --list 'origin/wt/*' --format='%(refname:short)'); do
      beat
      if [ "$(git rev-list --count "master..$RB")" != 0 ]; then
        guard_check "$RB"; merge_branch "$RB"
      fi
      timeout 5 git push -q origin --delete "${RB#origin/}" 2>/dev/null
    done
  fi

  # ---- 2. land every local wt/* branch ahead of master (ownership-blind sweep) ----
  for BR in $(git branch --list 'wt/*' --format='%(refname:short)'); do
    [ "$(git rev-list --count "master..$BR")" = 0 ] && continue
    beat; guard_check "$BR"; merge_branch "$BR"
  done

  # ---- 3. batch dedupe: exact-duplicate FACT lines in files this land touched ----
  beat
  git diff --name-only "$PRE..HEAD" -- '*.md' ':(exclude)*/journal/*' ':(exclude)attic/*' \
      ':(exclude)*INDEX.md' 2>/dev/null | while read -r p; do
    [ -f "$p" ] || continue
    awk '!/^- / || !seen[$0]++' "$p" > "$p.dd" && mv "$p.dd" "$p"
  done
  if ! git diff --quiet; then git add -A; git commit -qm "mem(land): batch dedupe"; fi

  # ---- 4. prune writers that are fully merged AND provably gone (pid+lstart identity) ----
  beat
  git worktree list --porcelain | awk '/^worktree /{print $2}' | while read -r W; do
    case "$W" in */.wt/*) ;; *) continue ;; esac
    ID=$(basename "$W"); BR="wt/$ID"
    [ "$(git rev-list --count "master..$BR" 2>/dev/null || echo 1)" = 0 ] || continue  # unmerged → keep
    WPID=${ID##*-}; WHOST=${ID%-*-*-*}            # host may contain '-'; strip 3 fields right
    WAGE=$(( $(date +%s) - $(mtime "$W.who") ))   # .who missing → treated as very old
    if [ "$WHOST" = "$HOST" ]; then
      alive "$WPID" "$W.who" && continue          # live (pid AND lstart match) → never removed
      [ "$WAGE" -lt 3600 ] && continue            # saved <1h ago → grace (pid-walk false-dead)
    else
      [ "$WAGE" -lt 86400 ] && continue           # renamed-host fallback: 24h heartbeat age
    fi
    git worktree remove --force "$W" 2>/dev/null && { git branch -D "$BR" 2>/dev/null; rm -f "$W.who"; }
  done
  git worktree prune 2>/dev/null
  git branch --list 'wt/*' --format='%(refname:short)' | while read -r BR; do
    git branch -d "$BR" 2>/dev/null   # removes only merged + not-checked-out stragglers
  done
  find .wt/.nudge -type f -mtime +7 -delete 2>/dev/null   # expire Stop-nudge markers

  # ---- 5. regenerate indexes (lander-only, priority-ordered, §3) ----
  beat; regen_all
  [ -n "$(git status --porcelain)" ] && { git add -A; git commit -qm "mem(land): reindex"; }

  # ---- 6. single best-effort push (hooks stay fast; land --sync adds the retry loop) ----
  beat; timeout 8 git push -q origin master 2>/dev/null || true
}

# ---------- index generation (§3) ----------
emit_line() { local s; s=$(grep -m1 '^summary:' "$1" | cut -d' ' -f2-); echo "- $1 — ${s:-NO SUMMARY LINE}"; }
regen() {   # $1 = scope dir (no trailing /), $2 = out file, $3 = title — PRIORITY order (§3)
  local PRI f
  case "$1" in
    global)     PRI="global/core.md global/preferences.md global/lessons.md global/failures.md" ;;
    projects/*) PRI="$1/capsule.md" ;;
    *)          PRI="" ;;
  esac
  { echo "# $3"
    for f in $PRI; do [ -f "$f" ] && emit_line "$f"; done
    find "$1" -name '*.md' ! -path '*/journal/*' ! -name 'INDEX.md' | sort | while read -r f; do
      case " $PRI " in *" $f "*) ;; *) emit_line "$f" ;; esac
    done
  } > "$2"
}
regen_all() {
  regen global INDEX.md "Global memory index"
  local d s
  for d in projects/*/; do
    s=$(basename "$d")
    regen "projects/$s" "projects/$s/INDEX.md" "Project: $s"
  done
}

# ---------- commands ----------
cmd_start() {       # stdin = hook JSON. STRICTLY read-only: no lock, no fetch, no ref movement.
  local IN CWD SLUG BESTLEN PFX S HOT PEND BR
  IN=$(cat 2>/dev/null || true)
  CWD=$(printf '%s' "$IN" | jq -r '.cwd // empty' 2>/dev/null)
  [ -n "$CWD" ] || CWD=$(printf '%s' "$IN" \
    | sed -n 's/.*"cwd"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
  [ -n "$CWD" ] || CWD=$PWD
  SLUG=""; BESTLEN=0
  while IFS=$'\t' read -r PFX S; do
    [ -n "$PFX" ] || continue
    case "$CWD" in
      "$PFX"|"$PFX"/*) [ "${#PFX}" -gt "$BESTLEN" ] && { SLUG=$S; BESTLEN=${#PFX}; } ;;
    esac
  done < projects/_map.tsv
  cap() { awk -v max="$1" -v src="$2" \
    '{ if (n + length($0) + 1 > max) { printf "[...%s truncated — run memory hygiene]\n", src; exit }
       n += length($0) + 1; print }'; }          # whole lines only: never splits UTF-8, never silent
  cap 5000 global/core.md < global/core.md
  echo; cap 1700 INDEX.md < INDEX.md; echo
  if [ -n "$SLUG" ] && [ -f "projects/$SLUG/INDEX.md" ]; then
    cap 1700 "projects/$SLUG/INDEX.md" < "projects/$SLUG/INDEX.md"
  else
    echo "(no project memory for $CWD — if this project recurs, create projects/<slug>/ + a _map.tsv row)"
  fi
  echo
  { echo "RECALL: index → Read the file; else grep -ril '<term>' $REPO/global $REPO/projects/${SLUG:-<slug>}. ≤3 memory files per lookup; ≤3 lookups per session, then Explore subagent."
    echo "WRITE: on 'remember'/wrap-up/nudge: agent-mem.sh wt → edit → agent-mem.sh save <wt> 'mem(${SLUG:-global}): …'. Facts: '- … [YYYY-MM-DD] #tag'; newest stamp wins, ties → later line, then last path."
    PEND=0
    for BR in $(git branch --list 'wt/*' --format='%(refname:short)' 2>/dev/null); do
      [ "$(git rev-list --count "master..$BR" 2>/dev/null || echo 0)" = 0 ] || PEND=$((PEND+1))
    done
    [ "$PEND" -gt 0 ] && echo "NOTE: $PEND unlanded writer branch(es) pending — run agent-mem.sh land to converge."
    HOT=$(find global projects -name '*.md' ! -path '*/journal/*' ! -name 'INDEX.md' \
          -exec cat {} + 2>/dev/null | wc -l | tr -d ' ')
    [ "${HOT:-0}" -gt 2500 ] && echo "WARNING: memory over budget ($HOT lines > 2500) — run memory hygiene"
  } | cap 600 footer
  exit 0
}

cmd_wt() {          # create writer worktree; prints its absolute path
  local P LP ID
  P=$$; LP=$PPID
  for _ in 1 2 3 4 5 6; do                      # nearest long-lived ancestor = liveness pid
    P=$(ps -o ppid= -p "$P" 2>/dev/null | tr -d ' ')
    { [ -z "$P" ] || [ "$P" -le 1 ]; } && break
    case "$(ps -o comm= -p "$P" 2>/dev/null)" in *claude*|*node*) LP=$P; break ;; esac
  done
  ID="$HOST-$(date +%Y%m%d-%H%M%S)-$LP"
  git worktree add ".wt/$ID" -b "wt/$ID" master >/dev/null 2>&1 || exit 1  # name clash → rerun
  echo "pid=$LP lstart=$(ps -p "$LP" -o lstart= 2>/dev/null)" > ".wt/$ID.who"
  echo "$REPO/.wt/$ID"
}

cmd_save() {        # $1 = worktree path, $2 = commit message
  local W MSG BR
  W=${1:?usage: agent-mem.sh save <worktree-path> "<msg>"}; W=${W%/}
  MSG=${2:-update}
  case "$MSG" in mem*) ;; *) MSG="mem: $MSG" ;; esac
  if [ ! -e "$W/.git" ]; then
    echo "agent-mem: $W is gone (pruned). New worktree: $(cmd_wt) — re-apply edits there." >&2
    exit 1
  fi
  git -C "$W" add -A
  git -C "$W" diff --cached --quiet || git -C "$W" commit -qm "$MSG"
  [ -f "$W.who" ] && touch "$W.who"              # writer heartbeat (§7 step 4 grace)
  BR="wt/$(basename "$W")"
  timeout 5 git push -q origin "$BR:$BR" 2>/dev/null || true   # off-machine backup, best-effort
}

cmd_land() {        # SessionEnd + PreCompact hooks, and by hand. --sync = stronger push loop.
  salvage_all       # PRE-LOCK: notes survive even if we defer or get killed below
  acquire 20 || { echo "agent-mem: live lander present — deferred (commits are safe on branches)"; exit 0; }
  do_land
  if [ "${1:-}" = "--sync" ]; then
    for _ in 1 2; do                             # stronger remote convergence than the single push
      beat; timeout 10 git push -q origin master 2>/dev/null && break
      beat; timeout 10 git fetch -q origin 2>/dev/null && merge_branch origin/master
    done
  fi
  exit 0            # guarded trap releases the lock iff our token is still in owner
}

cmd_nudge() {       # Stop hook: once-per-session mechanical distillation nudge
  local IN SID MARK AGE
  IN=$(cat 2>/dev/null || true)
  printf '%s' "$IN" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true' && exit 0
  SID=$(printf '%s' "$IN" | jq -r '.session_id // empty' 2>/dev/null)
  [ -n "$SID" ] || SID=$(printf '%s' "$IN" \
    | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
  [ -n "$SID" ] || SID="pid-$PPID"
  mkdir -p .wt/.nudge
  MARK=".wt/.nudge/$SID"
  [ -f "$MARK" ] || { touch "$MARK"; exit 0; }   # first Stop of the session: arm timer, no nudge
  [ -f "$MARK.done" ] && exit 0                  # already nudged this session: never repeat
  AGE=$(( $(date +%s) - $(mtime "$MARK") ))
  [ "$AGE" -lt 1500 ] && exit 0                  # <25 min since first Stop: too early to nag
  touch "$MARK.done"
  printf '%s\n' '{"decision":"block","reason":"agent-memory (one-time nudge): if this session produced durable lessons, decisions, or gotchas that you have NOT yet distilled into memory, do it now: run agent-mem.sh wt, append dated fact lines in that worktree, then agent-mem.sh save <wt> <msg>. If you already saved this session, or nothing here is durable, simply finish your response."}'
  exit 0
}

cmd_hygiene_report() {   # read-only
  echo "== files over line budget =="
  find global projects -name '*.md' ! -path '*/journal/*' | while read -r f; do
    n=$(wc -l < "$f"); cap=200
    case "$f" in */core.md) cap=70 ;; */INDEX.md) cap=30 ;; */capsule.md) cap=250 ;; esac
    [ "$n" -gt "$cap" ] && echo "$f: $n > $cap"
  done
  echo "== journal entries older than 30d ==";  find global projects -path '*journal/*.md' -mtime +30
  echo "== unreviewed guard lines ==";          grep -rh '#guard' global/journal/ 2>/dev/null
  echo "== lingering worktrees ==";             git worktree list | grep '/\.wt/' || echo "(none)"
}

usage() { echo "usage: agent-mem.sh start | wt | save <wt> '<msg>' | land [--sync] | nudge | reindex | hygiene-report" >&2; exit 2; }
case "${1:-}" in
  start)          cmd_start ;;
  wt)             cmd_wt ;;
  save)           shift; cmd_save "$@" ;;
  land|land-all)  shift; cmd_land "$@" ;;   # land-all kept as a back-compat alias
  nudge)          cmd_nudge ;;
  reindex)        regen_all ;;
  hygiene-report) cmd_hygiene_report ;;
  *)              usage ;;
esac
