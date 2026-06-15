#!/bin/bash
# /opt/techtalker-source/scripts/auto-push.sh
# Auto-push all techtalker.dev code to GitHub every midnight.
# Source paths are the LIVE production paths on the VPS.
# Staging area is /opt/techtalker-source (already a git repo).
#
# Cron:  0 0 * * *   /opt/techtalker-source/scripts/auto-push.sh
# Log:   /var/log/techtalkerid/auto-push.log
#
# Auth:  SSH deploy key at /root/.ssh/github_techtalker (read by ~/.ssh/config)
#        No token stored anywhere on disk.

set -u
SRC=/opt/techtalker-source
LOG=/var/log/techtalkerid/auto-push.log
TS="$(date '+%Y-%m-%d %H:%M:%S %Z')"

# Ensure log dir exists
mkdir -p "$(dirname "$LOG")"

log() { echo "[$TS] $*" | tee -a "$LOG" ; }

log "=== auto-push start ==="

# ---- 1. Refresh staging area from live production paths ----
copy_or_skip() {
  local src="$1" dst="$2"
  if [ -f "$src" ]; then
    cp "$src" "$dst"
  else
    log "  skip (missing): $src"
  fi
}

copy_or_skip /opt/app/app.py              "$SRC/app/app.py"
copy_or_skip /opt/app/worldcup.py         "$SRC/app/worldcup.py"
copy_or_skip /opt/app/football.py         "$SRC/app/football.py"
copy_or_skip /opt/app/tv.py               "$SRC/app/tv.py"
copy_or_skip /opt/app/tv_live.py          "$SRC/app/tv_live.py"
copy_or_skip /opt/app/requirements.txt    "$SRC/app/requirements.txt"
copy_or_skip /opt/api/app.py              "$SRC/api/app.py"
copy_or_skip /opt/api/requirements.txt    "$SRC/api/requirements.txt"
copy_or_skip /opt/dash/app.py             "$SRC/dash/app.py"
copy_or_skip /opt/dash/requirements.txt   "$SRC/dash/requirements.txt"
copy_or_skip /etc/caddy/Caddyfile         "$SRC/docs/Caddyfile"
crontab -l > "$SRC/docs/crontab.txt" 2>/dev/null

cd "$SRC" || { log "FATAL: cannot cd $SRC"; exit 1; }

# ---- 2. Skip if nothing changed ----
if git diff --quiet HEAD 2>/dev/null && [ -z "$(git status --porcelain)" ]; then
  log "  no changes, skipping push"
  log "=== auto-push done (no-op) ==="
  exit 0
fi

# ---- 3. Stage + commit ----
git add -A
COMMIT_MSG="auto-push: ${TS}"
if git -c user.email="auto-push@techtalkerid.dev" \
       -c user.name="techtalker-auto-push" \
       commit -m "$COMMIT_MSG" -q; then
  log "  committed: $COMMIT_MSG"
else
  log "  FATAL: commit failed"
  log "=== auto-push done (error) ==="
  exit 1
fi

# ---- 4. Push via SSH (no token, no prompt) ----
if GIT_TERMINAL_PROMPT=0 git push origin main 2>>"$LOG"; then
  log "  pushed to origin/main"
  log "=== auto-push done (success) ==="
  exit 0
else
  log "  FATAL: push failed (see git output above)"
  log "=== auto-push done (error) ==="
  exit 1
fi
