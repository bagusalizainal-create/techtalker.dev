# techtalker.dev

Self-hosted tech portal running at [techtalkerid.dev](https://techtalkerid.dev) — a SPA (single-page app) aggregating multiple internal services behind a Caddy reverse proxy on a single Ubuntu 24.04 VPS.

## Architecture

```
Internet
  → DNS A records at Name.com
  → Caddy :80/:443 (auto-TLS via Let's Encrypt)
  → SPA (Flask :8001) — single-page entry point
  → Internal services:
      - FastAPI :8002 (Notes API + SQLite)
      - Flask  :8003 (Server dashboard)
  → All cross-service calls go through same-origin /api/* proxy
  → External data cached in JSON files, refreshed by crontab
```

See [docs/Caddyfile](docs/Caddyfile) for the full reverse proxy config.

## Repository layout

```
/opt/app/    Portal SPA + WC26 + data fetchers   (Flask :8001)
/opt/api/    Notes API                            (FastAPI :8002)
/opt/dash/   Server dashboard                     (Flask :8003)
/etc/caddy/  Reverse proxy + auto-TLS
crontab      @reboot for services + hourly cache refresh
```

### `app/` (main portal)

- **`app.py`** — Flask SPA. All HTML/CSS/JS embedded as a single string. Tabs: Beranda, Notes, Server, Piala Dunia, **WC26** (macOS menu bar app style popover), TV, API.
- **`worldcup.py`** — Fetches FIFA World Cup 2026 data from ESPN + TheSportsDB. Cache: `worldcup_cache.json`. Refresh: hourly via crontab.
- **`football.py`** — Older generic football fetcher (kept for the "Piala Dunia" tab fallback).
- **`tv.py`** / **`tv_live.py`** — Live TV channel list (iptv-org M3U sources) + liveness checker.

### `api/` (Notes API)

FastAPI + SQLAlchemy + SQLite. CRUD for notes. Swagger UI at `/docs`.

### `dash/` (Dashboard)

Flask + psutil. Live CPU/mem/disk/uptime. Auto-refreshes every 5s.

## Features

- 🏠 **Beranda** — system stats, services grid
- 📝 **Notes** — CRUD notes, search, tags
- 📊 **Server** — live monitoring with 20-sample chart
- 🏆 **Piala Dunia** — basic World Cup fixtures + countdown
- ⚽ **WC26** — popover-style FIFA World Cup 2026 viewer (group standings, favorites, team detail modal, live rotator, adjustable refresh/transparency)
- 📺 **TV** — 200+ live TV channels (HLS via server-side CORS proxy)
- 🔌 **API** — endpoint reference

## Running

Each service is a tmux session, auto-started by crontab `@reboot`:

```cron
@reboot /bin/bash -c 'sleep 10 && tmux new-session -d -s api  "cd /opt/api  && ./venv/bin/uvicorn app:app  --host 127.0.0.1 --port 8002 --workers 2"'
@reboot /bin/bash -c 'sleep 11 && tmux new-session -d -s app  "cd /opt/app  && ./venv/bin/gunicorn app:app --bind 127.0.0.1:8001 --workers 2"'
@reboot /bin/bash -c 'sleep 12 && tmux new-session -d -s dash "cd /opt/dash && ./venv/bin/gunicorn app:app --bind 127.0.0.1:8003 --workers 2"'
```

Data refreshes:
```cron
0 3 * * * cd /opt/app && ./venv/bin/python tv.py --refresh
0 * * * * cd /opt/app && ./venv/bin/python worldcup.py --refresh
```

## Endpoints

| Path | Service | Description |
|---|---|---|
| `/` | app | SPA HTML |
| `/api/notes` | app (proxy) | List / create notes |
| `/api/notes/{id}` | app (proxy) | Get / update / delete note |
| `/api/worldcup` | app | World Cup upcoming + recent + all matches |
| `/api/worldcup/standings` | app | Computed group standings (no upstream endpoint) |
| `/api/worldcup/refresh` | app (POST) | Manual cache refresh |
| `/api/tv/channels` | app | TV channel list (200+ from iptv-org M3U) |
| `/api/tv/proxy` | app | Generic CORS proxy for HLS streams |
| `/api/live-stats` | app | Aggregated stats (server + notes) |
| `/api/services` | app | Service health snapshot |
| `/api/stats` | dash | System stats (psutil) |
| `/health` | each | Liveness |
| `app.techtalkerid.dev` | app | Same SPA via subdomain |
| `api.techtalkerid.dev` | api | Notes API + Swagger UI |
| `dash.techtalkerid.dev` | dash | Standalone dashboard |

## Tech stack

- **Caddy 2.11** — reverse proxy + auto-TLS
- **Flask 3.0.3** + **FastAPI 0.115** — Python web
- **gunicorn 23.0** + **uvicorn 0.30** — WSGI/ASGI servers
- **SQLite + SQLAlchemy 2.0** — Notes persistence
- **psutil 5.9** — Server metrics
- **hls.js 1.5** — Browser HLS playback
- **ESPN** (primary) + **TheSportsDB** (fallback) — World Cup data
- **iptv-org** M3U sources — Live TV channels

## Security notes

- All internal services bind `127.0.0.1` only — never exposed to internet
- Caddy adds `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options` on all routes
- No API keys, secrets, or user data in this repo — all upstream APIs use public free tier
- `notes.db` (SQLite, contains user notes) is gitignored

## See also

For deployment sandboxes, ESPN data gotchas, and other operational notes, see the [Hermes `vps-multi-service-portal` skill](https://github.com/.../skills) → `references/espn-worldcup-gotchas.md`.

## License

MIT
