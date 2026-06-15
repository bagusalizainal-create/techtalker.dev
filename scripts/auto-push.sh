#!/bin/bash
# /opt/techtalker-source/scripts/auto-push.sh
# Auto-push all techtalker.dev code to GitHub every midnight.
# Source paths are the LIVE production paths on the VPS.
# Staging area is /opt/techtalker-source (already a git repo).
#
# Cron:  0 17 * * *   (= 00:00 WIB)
# Log:   /var/log/techtalkerid/auto-push.log
# Notif: Telegram ke chat_id kepala orang (best-effort, gak break push kalo gagal)
#
# Auth:  SSH deploy key at /root/.ssh/github_techtalker (read by ~/.ssh/config)
#        No token stored anywhere on disk.

set -u
SRC=/opt/techtalker-source
LOG=/var/log/techtalkerid/auto-push.log
TS="$(date '+%Y-%m-%d %H:%M:%S %Z')"
ENV_FILE=/root/.hermes/.env
TG_CHAT_ID="1831974263"   # kepala orang — Mamenjaya
REPO_URL="https://github.com/bagusalizainal-create/techtalker.dev"

# Ensure log dir exists
mkdir -p "$(dirname "$LOG")"

log() { echo "[$TS] $*" | tee -a "$LOG" ; }

# Telegram bot token (read from .env). Notifications are best-effort:
# if the token file is missing/unreadable, push still works, just no notif.
TG_BOT_TOKEN=""
if [ -r "$ENV_FILE" ]; then
  TG_BOT_TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2-)
fi

send_tg() {
  local msg="$1"
  [ -z "$TG_BOT_TOKEN" ] && { log "  (skip tg notif: no token)"; return 0; }
  # Build JSON payload via python (safer than bash string interpolation for HTML)
  local payload
  payload=$(python3 -c "
import json, sys
print(json.dumps({
  'chat_id': '$TG_CHAT_ID',
  'text': sys.argv[1],
  'parse_mode': 'HTML',
  'disable_web_page_preview': True,
}))" "$msg" 2>/dev/null) || { log "  (tg payload build failed)"; return 0; }
  curl -sS -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    --max-time 10 >/dev/null 2>&1 || log "  (tg notif failed, continuing)"
}

# ---- 1. Refresh staging area from live production paths ----
copy_or_skip() {
  local src="$1" dst="$2"
  if [ -f "$src" ]; then
    cp "$src" "$dst"
  else
    log "  skip (missing): $src"
  fi
}

log "=== auto-push start ==="

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
  # Notify only if user opted in via file flag (default: silent on no-op)
  if [ -f /opt/techtalker-source/.notify-noop ]; then
    send_tg "☀️ <b>techtalker.dev auto-push</b>
Tiap pagi check: <i>gak ada perubahan</i> sejak push terakhir. Repo udah up-to-date.
🔗 <a href=\"$REPO_URL\">$REPO_URL</a>"
  fi
  exit 0
fi

# ---- 3. Stage + commit ----
git add -A
COMMIT_MSG="auto-push: ${TS}"
if git -c user.email="auto-push@techtalkerid.dev" \
       -c user.name="techtalker-auto-push" \
       commit -m "$COMMIT_MSG" -q; then
  log "  committed: $COMMIT_MSG"
  COMMIT_SHA=$(git rev-parse --short HEAD)
  DIFF_FILES=$(git diff-tree --no-commit-id --name-only -r HEAD~1..HEAD 2>/dev/null | wc -l)
else
  log "  FATAL: commit failed"
  send_tg "❌ <b>techtalker.dev auto-push GAGAL</b>
<code>commit</code> step error jam $TS.
Cek: <code>tail -50 /var/log/techtalkerid/auto-push.log</code>"
  log "=== auto-push done (error) ==="
  exit 1
fi

# ---- 4. Push via SSH (no token, no prompt) ----
if GIT_TERMINAL_PROMPT=0 git push origin main 2>>"$LOG"; then
  log "  pushed to origin/main"
  log "=== auto-push done (success) ==="
  send_tg "✅ <b>techtalker.dev auto-push</b>
Pagi! Push jam 00:00 WIB udah sukses.
• Commit: <code>$COMMIT_SHA</code>
• Files: $DIFF_FILES berubah
• Repo: <a href=\"$REPO_URL\">bagusalizainal-create/techtalker.dev</a>
Cek detail: <a href=\"$REPO_URL/commits/main\">commits</a>"
  exit 0
else
  log "  FATAL: push failed (see git output above)"
  send_tg "❌ <b>techtalker.dev auto-push GAGAL</b>
<code>git push</code> error jam $TS.
Cek: <code>tail -50 /var/log/techtalkerid/auto-push.log</code>
Fix SSH key kalo perlu: <code>ssh -T git@github.com</code>"
  log "=== auto-push done (error) ==="
  exit 1
fi
