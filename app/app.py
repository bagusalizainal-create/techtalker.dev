"""TechTalkerID - Portal v3.0 (SPA-style)
Single-page experience: klik menu = ganti section di tempat.
Semua CRUD Notes + Server Stats bisa dipakai langsung dari sini.
Subdomain tetap berfungsi untuk advanced use (Swagger UI, raw JSON, dll).
"""
from flask import Flask, jsonify, request, Response
import urllib.request
import urllib.error
import json
import os
import time
import platform
import datetime
import base64
import tempfile
import threading
from urllib.parse import urljoin

app = Flask(__name__)
START = time.time()

# Internal service URLs (server-to-server, no CORS issue)
API_URL  = "http://127.0.0.1:8002"  # FastAPI Notes
DASH_URL = "http://127.0.0.1:8003"  # Flask Dashboard

# Realtime network rate state (file-backed, shared across gunicorn workers)
NET_STATE_PATH = "/tmp/techtalker_net_state.json"
_net_state_lock = threading.Lock()


def fetch_json(url: str, timeout: float = 1.5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def post_json(url: str, payload: dict, timeout: float = 2.0):
    """POST JSON ke service internal."""
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        try:
            return None, json.loads(e.read())
        except Exception:
            return None, {"status": e.code, "detail": str(e)}
    except Exception as e:
        return None, {"detail": str(e)}


def put_json(url: str, payload: dict, timeout: float = 2.0):
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="PUT"
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        try:
            return None, json.loads(e.read())
        except Exception:
            return None, {"status": e.code, "detail": str(e)}
    except Exception as e:
        return None, {"detail": str(e)}


def delete_json(url: str, timeout: float = 2.0):
    try:
        req = urllib.request.Request(url, method="DELETE")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        try:
            return None, json.loads(e.read())
        except Exception:
            return None, {"status": e.code, "detail": str(e)}
    except Exception as e:
        return None, {"detail": str(e)}


# ======================== ENDPOINTS (JSON) ========================

@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "portal", "version": "3.0.0"})


@app.route("/api/live-stats")
def live_stats():
    return jsonify({
        "server": fetch_json(f"{DASH_URL}/api/stats"),
        "notes":  fetch_json(f"{API_URL}/stats"),
    })


def _read_net_state():
    try:
        with open(NET_STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _write_net_state(state):
    # atomic write: tempfile + rename, biar gak setengah jadi kalau crash
    tmp = NET_STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, NET_STATE_PATH)


@app.route("/api/server-realtime")
def server_realtime():
    """Realtime VPS metrics dengan network rate (delta antar request).
    Digunakan frontend tab Server untuk auto-refresh tiap 2 detik.
    """
    import psutil  # local import biar gak ke-load kalau endpoint gak kepanggil

    # Sample CPU over 0.3s supaya angka akurat (bukan 0 di first call)
    cpu_overall = psutil.cpu_percent(interval=0.3)
    cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    boot = psutil.boot_time()
    now = time.time()

    # Load average (Linux only); guard with hasattr
    try:
        load1, load5, load15 = psutil.getloadavg()
    except (AttributeError, OSError):
        load1 = load5 = load15 = None

    # Network rate (delta vs last sample)
    net_in_mbs = net_out_mbs = 0.0
    with _net_state_lock:
        prev = _read_net_state()
        if prev:
            dt = now - prev["ts"]
            if dt > 0:
                net_in_mbs  = max(0.0, (net.bytes_recv - prev["rx"]) / dt / (1024 * 1024))
                net_out_mbs = max(0.0, (net.bytes_sent - prev["tx"]) / dt / (1024 * 1024))
        _write_net_state({
            "ts": now, "rx": net.bytes_recv, "tx": net.bytes_sent,
        })

    # Per-core freq (kalau ada)
    try:
        freq = psutil.cpu_freq()
        cpu_freq_mhz = freq.current if freq else None
    except Exception:
        cpu_freq_mhz = None

    return jsonify({
        "ts": now,
        "hostname": platform.node(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "boot": boot,
        "uptime": int(now - boot),
        "cpu": {
            "percent": cpu_overall,
            "per_core": cpu_per_core,
            "cores_phys": psutil.cpu_count(logical=False) or len(cpu_per_core),
            "cores_logical": psutil.cpu_count(logical=True) or len(cpu_per_core),
            "freq_mhz": cpu_freq_mhz,
        },
        "memory": {
            "percent": mem.percent,
            "used_mb": mem.used // (1024**2),
            "total_mb": mem.total // (1024**2),
            "available_mb": mem.available // (1024**2),
        },
        "swap": {
            "percent": swap.percent,
            "used_mb": swap.used // (1024**2),
            "total_mb": swap.total // (1024**2),
        },
        "disk": {
            "percent": disk.percent,
            "used_gb": disk.used // (1024**3),
            "total_gb": disk.total // (1024**3),
            "free_gb": disk.free // (1024**3),
        },
        "network": {
            "bytes_sent_mb": net.bytes_sent // (1024**2),
            "bytes_recv_mb": net.bytes_recv // (1024**2),
            "in_mbs":  round(net_in_mbs,  3),
            "out_mbs": round(net_out_mbs, 3),
        },
        "load": {"1": load1, "5": load5, "15": load15},
    })


@app.route("/api/worldcup")
def worldcup():
    """Return World Cup data dari cache (refresh tiap 6 jam via cron)."""
    if not os.path.exists("/opt/app/worldcup_cache.json"):
        return jsonify({"error": "no cache yet, run worldcup.py --refresh"}), 503
    try:
        with open("/opt/app/worldcup_cache.json") as f:
            cache = json.load(f)
    except Exception as e:
        return jsonify({"error": f"cache read failed: {e}"}), 500

    wc = cache.get("world_cup")
    if not wc:
        return jsonify({"error": "world_cup key not in cache"}), 404

    return jsonify({
        "name": wc.get("name"),
        "season": wc.get("season"),
        "last_updated": wc.get("last_updated"),
        "upcoming": wc.get("upcoming", []),
        "recent": wc.get("recent", []),
        "all_matches": wc.get("all_matches", []),  # for WC26 standings/favorites
        "stats": wc.get("stats", {}),
        "meta": cache.get("_meta", {}),
    })


@app.route("/api/worldcup/standings")
def worldcup_standings():
    """Compute group standings from finished matches in cache.
    Returns: { groups: {A: [{team, played, won, drawn, lost, gf, ga, gd, pts, badge}, ...]}, ... }
    """
    if not os.path.exists("/opt/app/worldcup_cache.json"):
        return jsonify({"error": "no cache yet"}), 503
    try:
        with open("/opt/app/worldcup_cache.json") as f:
            cache = json.load(f)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    matches = cache.get("world_cup", {}).get("all_matches", [])
    # Only finished matches (have both scores AND status indicates finished).
    # ESPN sometimes returns score=0 for not-yet-started matches, so we must
    # require an explicit finished status code.
    FT_RAW = {"STATUS_FINAL", "STATUS_FULL_TIME", "STATUS_AET", "STATUS_PEN"}
    def is_finished(m):
        if m.get("home_score") is None or m.get("away_score") is None:
            return False
        raw = (m.get("raw_status") or "").upper()
        return raw in FT_RAW or (m.get("status") or "").upper() == "FT"
    finished = [m for m in matches if is_finished(m)]

    # Group by group letter
    groups: dict[str, dict] = {}
    for m in finished:
        g = m.get("group") or "?"
        if g == "?" or not g or len(g) > 2:  # skip knockout rounds
            continue
        gkey = g.upper()
        if gkey not in groups:
            groups[gkey] = {}
        # Initialize teams
        for side, team, score_key in [("home", m.get("home_team"), "home_score"),
                                       ("away", m.get("away_team"), "away_score")]:
            badge = m.get(f"{side}_badge")
            if team not in groups[gkey]:
                groups[gkey][team] = {
                    "team": team, "badge": badge,
                    "played": 0, "won": 0, "drawn": 0, "lost": 0,
                    "gf": 0, "ga": 0, "gd": 0, "pts": 0,
                }
        h, a = m["home_team"], m["away_team"]
        hs, as_ = m["home_score"], m["away_score"]
        groups[gkey][h]["played"] += 1
        groups[gkey][a]["played"] += 1
        groups[gkey][h]["gf"] += hs
        groups[gkey][h]["ga"] += as_
        groups[gkey][a]["gf"] += as_
        groups[gkey][a]["ga"] += hs
        if hs > as_:
            groups[gkey][h]["won"] += 1
            groups[gkey][h]["pts"] += 3
            groups[gkey][a]["lost"] += 1
        elif hs < as_:
            groups[gkey][a]["won"] += 1
            groups[gkey][a]["pts"] += 3
            groups[gkey][h]["lost"] += 1
        else:
            groups[gkey][h]["drawn"] += 1
            groups[gkey][a]["drawn"] += 1
            groups[gkey][h]["pts"] += 1
            groups[gkey][a]["pts"] += 1

    # Sort each group: pts desc, gd desc, gf desc, name asc
    out: dict[str, list] = {}
    for gkey, teams in groups.items():
        rows = []
        for t in teams.values():
            t["gd"] = t["gf"] - t["ga"]
            rows.append(t)
        rows.sort(key=lambda r: (-r["pts"], -r["gd"], -r["gf"], r["team"]))
        out[gkey] = rows

    # Sort groups A..L then any extras
    sorted_groups = {}
    for k in sorted(out.keys(), key=lambda x: (len(x), x)):
        sorted_groups[k] = out[k]

    return jsonify({
        "groups": sorted_groups,
        "last_updated": cache.get("world_cup", {}).get("last_updated"),
        "total_groups": len(sorted_groups),
    })


@app.route("/api/worldcup/refresh", methods=["POST"])
def worldcup_refresh():
    """Manual trigger refresh World Cup cache."""
    try:
        from worldcup import refresh
        s = refresh()
        return jsonify({"ok": True, "summary": s})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tv/channels")
def tv_channels():
    """Return TV channels dengan filter & grouping.
    Query params:
      country=Indonesia (default: Indonesia)
      category=News (optional, filter by category)
      search=keyword (optional, search in name)
      group_by=category|none (default: none — flat list)
      limit=N (max channels, default: 500)
    Setiap channel sudah punya `proxied_url` (pre-computed in cache).
    Supports If-None-Match (ETag) → returns 304 if data hasn't changed.
    """
    try:
        from tv import get_channels, filter_channels, group_by_category, COMMON_CATEGORIES
        d = get_channels(force=False)
        all_channels = d.get("channels", [])
        stats = d.get("stats", {})
        etag = d.get("_meta", {}).get("etag")

        country = request.args.get("country", "Indonesia").strip()
        category = request.args.get("category", "").strip()
        search = request.args.get("search", "").strip()
        group_by = request.args.get("group_by", "none").strip()
        try:
            limit = int(request.args.get("limit", "500"))
        except Exception:
            limit = 500

        # ETag-based 304 short-circuit (saves bandwidth + parse time on country re-switch)
        # ETag varies per (country, category, search) so a different filter still gets a fresh 200
        client_etag = request.headers.get("If-None-Match")
        if etag and client_etag and client_etag == etag:
            resp = Response(status=304)
            resp.headers["ETag"] = etag
            resp.headers["Cache-Control"] = "public, max-age=300, must-revalidate"
            return resp

        # Filter (now uses pre-built by_country index, O(matches) instead of O(11.5K))
        filtered = filter_channels(d, country=country, category=category, search=search)

        # Build response — proxied_url is already in cache, no per-request b64 needed
        if group_by == "category":
            grouped = group_by_category(filtered)
            if limit:
                for cat in grouped:
                    grouped[cat] = grouped[cat][:limit]
            resp = jsonify({
                "country": country,
                "category": category or None,
                "search": search or None,
                "total_filtered": len(filtered),
                "by_category": grouped,
                "stats": {
                    "by_country": stats.get("by_country", {}),
                    "by_category": stats.get("by_category", {}),
                    "top_countries": stats.get("top_countries", []),
                    "common_categories": COMMON_CATEGORIES,
                },
                "meta": d.get("_meta", {}),
            })
        else:
            # Flat list (default) — proxied_url comes from cache
            channels_out = filtered[:limit] if limit else filtered
            resp = jsonify({
                "country": country,
                "category": category or None,
                "search": search or None,
                "total_filtered": len(filtered),
                "channels": channels_out,
                "stats": {
                    "by_country": stats.get("by_country", {}),
                    "by_category": stats.get("by_category", {}),
                },
                "meta": d.get("_meta", {}),
            })

        # HTTP cache headers — safe to cache up to 5 min, then must revalidate
        if etag:
            resp.headers["ETag"] = etag
        resp.headers["Cache-Control"] = "public, max-age=300, must-revalidate"
        return resp
    except Exception as e:
        return jsonify({"error": str(e), "channels": [], "by_category": {}}), 500


def b64e(s: str) -> str:
    """Base64 encode URL untuk proxy param."""
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii").rstrip("=")


def b64d(s: str) -> str | None:
    """Base64 decode URL dari proxy param."""
    try:
        # Restore padding
        padding = 4 - len(s) % 4
        if padding != 4:
            s = s + "=" * padding
        return base64.urlsafe_b64decode(s.encode("ascii")).decode("utf-8")
    except Exception:
        return None


@app.route("/api/tv/proxy", methods=["GET", "OPTIONS"])
def tv_proxy():
    """Generic CORS proxy untuk TV stream.
    Forward request ke external URL, return content dengan CORS headers.
    Untuk .m3u8 playlist, rewrite segment URLs agar juga lewat proxy.
    Untuk content lain (.ts segments dll), STREAM langsung (no memory bloat).
    """
    enc = request.args.get("u", "")
    original_url = b64d(enc) if enc else None
    if not original_url:
        return jsonify({"error": "missing or invalid 'u' param"}), 400
    if not (original_url.startswith("http://") or original_url.startswith("https://")):
        return jsonify({"error": "only http/https URLs allowed"}), 400

    # Headers to forward
    fwd_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    }
    if request.headers.get("Range"):
        fwd_headers["Range"] = request.headers["Range"]
    if request.headers.get("If-Range"):
        fwd_headers["If-Range"] = request.headers["If-Range"]

    try:
        req = urllib.request.Request(original_url, headers=fwd_headers)
        r = urllib.request.urlopen(req, timeout=15)
        content_type = r.headers.get("Content-Type", "application/octet-stream")
        content_length = r.headers.get("Content-Length")
        status_code = r.status

        # Detect & rewrite .m3u8 playlist (must read fully to rewrite lines)
        is_m3u8 = (
            "mpegurl" in content_type.lower()
            or "vnd.apple.mpegurl" in content_type.lower()
            or original_url.lower().split("?")[0].endswith(".m3u8")
            or original_url.lower().split("?")[0].endswith(".m3u")
        )

        if is_m3u8:
            # M3U8 playlists are small (< 50KB usually) — read fully, rewrite
            content = r.read()
            r.close()
            try:
                text = content.decode("utf-8", errors="ignore")
                new_lines = []
                for line in text.splitlines():
                    s = line.strip()
                    if not s or s.startswith("#"):
                        new_lines.append(line)
                        continue
                    if s.startswith("http://") or s.startswith("https://"):
                        abs_url = s
                    else:
                        abs_url = urljoin(original_url, s)
                    new_lines.append(f"/api/tv/proxy?u={b64e(abs_url)}")
                content = "\n".join(new_lines).encode("utf-8")
                content_type = "application/vnd.apple.mpegurl"
                content_length = str(len(content))
            except Exception as e:
                print(f"  [proxy] m3u8 rewrite failed: {e}")

            resp = Response(content, status=status_code, mimetype=content_type)
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        else:
            # .ts / .mp4 / other binary — STREAM to avoid loading large segments into memory
            def generate():
                try:
                    while True:
                        chunk = r.read(64 * 1024)  # 64KB chunks
                        if not chunk:
                            break
                        yield chunk
                finally:
                    try:
                        r.close()
                    except Exception:
                        pass

            resp = Response(generate(), status=status_code, mimetype=content_type)
            resp.headers["Cache-Control"] = "public, max-age=10"

        # Common CORS + cache headers
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Range, If-Range"
        if content_length:
            resp.headers["Content-Length"] = content_length
        return resp
    except urllib.error.HTTPError as e:
        return jsonify({"error": f"upstream {e.code}: {e.reason}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/tv/refresh", methods=["POST"])
def tv_refresh():
    """Manual trigger refresh TV M3U."""
    try:
        from tv import get_channels
        d = get_channels(force=True)
        m = d.get("_meta", {})
        return jsonify({"ok": True, "count": m.get("count", 0), "last_refresh": m.get("last_refresh")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tv/liveness")
def tv_liveness():
    """Return liveness status untuk channel URL (cached 30 min)."""
    country = request.args.get("country", "").strip()
    try:
        if country:
            from tv_live import check_country
            r = check_country(country, force=False)
        else:
            from tv_live import load_liveness
            r = load_liveness()
        if isinstance(r, dict) and "results" in r:
            return jsonify({
                "country": country or None,
                "cached": r.get("cached", False),
                "results": r.get("results", []),
            })
        return jsonify(r)
    except Exception as e:
        return jsonify({"error": str(e), "results": []}), 500


@app.route("/api/tv/liveness/refresh", methods=["POST"])
def tv_liveness_refresh():
    """Manual trigger liveness test untuk country tertentu."""
    country = request.args.get("country", "").strip()
    if not country:
        return jsonify({"error": "country required"}), 400
    try:
        from tv_live import check_country
        r = check_country(country, force=True)
        if "error" in r:
            return jsonify(r), 404
        return jsonify({
            "country": country,
            "ok": True,
            "results": r.get("results", []),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/services")
def services():
    api_health = fetch_json(f"{API_URL}/health")
    dash_health = fetch_json(f"{DASH_URL}/health")
    notes_stats = fetch_json(f"{API_URL}/stats")
    dash_stats = fetch_json(f"{DASH_URL}/api/stats")
    return jsonify({
        "portal": {"url": "https://www.techtalkerid.dev", "status": "live",
                   "uptime_seconds": int(time.time() - START)},
        "services": {
            "notes_api": {"url": "https://api.techtalkerid.dev",
                          "docs": "https://api.techtalkerid.dev/docs",
                          "status": "live" if api_health else "down",
                          "notes_count": (notes_stats or {}).get("total_notes")},
            "dashboard": {"url": "https://dash.techtalkerid.dev",
                          "status": "live" if dash_health else "down",
                          "stats": dash_stats},
        },
        "server": {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "now": datetime.datetime.utcnow().isoformat() + "Z",
        },
    })


# Proxy endpoint untuk Notes CRUD (no CORS, same-origin dari browser)
@app.route("/api/notes", methods=["GET", "POST"])
def notes_collection():
    if request.method == "GET":
        tag = request.args.get("tag")
        url = f"{API_URL}/notes"
        if tag:
            url += f"?tag={tag}"
        return jsonify(fetch_json(url) or [])
    # POST
    payload = request.get_json(silent=True) or {}
    if not payload.get("title"):
        return jsonify({"detail": [{"msg": "title wajib diisi"}]}), 422
    data, err = post_json(f"{API_URL}/notes", payload)
    if err:
        return jsonify(err), err.get("status", 500)
    return jsonify(data), 201


@app.route("/api/notes/<int:note_id>", methods=["GET", "PUT", "DELETE"])
def note_item(note_id):
    if request.method == "GET":
        data = fetch_json(f"{API_URL}/notes/{note_id}")
        if not data:
            return jsonify({"detail": "not found"}), 404
        return jsonify(data)
    if request.method == "PUT":
        payload = request.get_json(silent=True) or {}
        data, err = put_json(f"{API_URL}/notes/{note_id}", payload)
        if err:
            return jsonify(err), err.get("status", 500)
        return jsonify(data)
    # DELETE
    data, err = delete_json(f"{API_URL}/notes/{note_id}")
    if err:
        return jsonify(err), err.get("status", 500)
    return jsonify(data)


@app.route("/api/notes/search")
def notes_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    return jsonify(fetch_json(f"{API_URL}/notes/search?q={q}") or [])


# ======================== PAGE (HTML) ========================

@app.route("/")
def index():
    return PAGE_HTML


PAGE_HTML = r"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>techtalkerid.dev — Portal</title>
<!-- Preconnect to logo CDNs — saves TLS handshake on first logo of each page load -->
<link rel="preconnect" href="https://i.imgur.com" crossorigin>
<link rel="preconnect" href="https://i.postimg.cc" crossorigin>
<link rel="preconnect" href="https://i.ibb.co" crossorigin>
<link rel="preconnect" href="https://upload.wikimedia.org" crossorigin>
<link rel="preconnect" href="https://thumbor.prod.vidiocdn.com" crossorigin>
<link rel="dns-prefetch" href="https://i.imgur.com">
<link rel="dns-prefetch" href="https://i.postimg.cc">
<link rel="dns-prefetch" href="https://i.ibb.co">
<script src="https://cdn.jsdelivr.net/npm/hls.js@1.5.13"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0a0e1a; --bg2: #131826; --bg3: #1e293b;
    --fg: #e2e8f0; --fg2: #94a3b8; --fg3: #64748b;
    --accent: #4ade80; --accent2: #22d3ee; --warn: #fbbf24; --crit: #f87171;
  }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: var(--bg); color: var(--fg); line-height: 1.6; min-height: 100vh; }
  a { color: var(--accent2); text-decoration: none; }
  a:hover { text-decoration: underline; }
  code, pre { font-family: "SF Mono", Monaco, Consolas, monospace; font-size: 0.9em; }
  pre { background: var(--bg); padding: 12px; border-radius: 8px; overflow-x: auto; }

  /* === Topbar dengan nav === */
  .topbar { display: flex; justify-content: space-between; align-items: center;
            padding: 14px 32px; border-bottom: 1px solid var(--bg3);
            position: sticky; top: 0; background: rgba(10, 14, 26, 0.92);
            backdrop-filter: blur(10px); z-index: 100; gap: 16px; flex-wrap: wrap; }
  .logo { font-weight: 800; font-size: 1.1rem; white-space: nowrap; }
  .logo span { color: var(--accent); }
  .nav { display: flex; gap: 4px; flex-wrap: wrap; }
  .nav button { background: transparent; border: 0; color: var(--fg2); padding: 8px 14px;
                border-radius: 8px; cursor: pointer; font-size: 0.92rem; font-weight: 500;
                transition: all 0.15s; font-family: inherit; }
  .nav button:hover { background: var(--bg3); color: var(--fg); }
  .nav button.active { background: var(--bg3); color: var(--accent); }
  .topbar-right { display: flex; align-items: center; gap: 12px; font-size: 0.85rem;
                  color: var(--fg2); white-space: nowrap; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
         background: var(--accent); box-shadow: 0 0 8px var(--accent);
         animation: pulse 2s infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

  .container { max-width: 1100px; margin: 0 auto; padding: 32px; }

  /* === Sections (SPA-style) === */
  .section { display: none; }
  .section.active { display: block; animation: fade 0.25s; }
  @keyframes fade { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }

  /* === Hero (Beranda) === */
  .hero { text-align: center; margin-bottom: 40px; }
  .hero h1 { font-size: clamp(2.2rem, 5vw, 3.5rem); font-weight: 800; margin-bottom: 12px;
             background: linear-gradient(90deg, var(--accent), var(--accent2));
             -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
  .hero p { color: var(--fg2); margin-bottom: 4px; }
  .hero .sub { color: var(--fg3); font-size: 0.9rem; }

  /* === Stats grid === */
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
           gap: 12px; margin-bottom: 32px; }
  .stat { background: var(--bg2); border: 1px solid var(--bg3); border-radius: 12px;
          padding: 16px; transition: border-color 0.2s; }
  .stat:hover { border-color: var(--accent); }
  .stat .label { font-size: 0.72rem; color: var(--fg3); text-transform: uppercase; letter-spacing: 1px; }
  .stat .value { font-size: 1.4rem; font-weight: 700; margin-top: 4px; }
  .stat .small { font-size: 0.78rem; color: var(--fg2); margin-top: 3px; }
  .stat .bar { background: var(--bg3); height: 5px; border-radius: 3px; margin-top: 8px; overflow: hidden; }
  .stat .bar-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent2));
                     transition: width 0.5s; }
  .v-warn { color: var(--warn) !important; } .v-crit { color: var(--crit) !important; }

  /* Realtime sparkline (mini chart di tiap card) */
  .rt-spark { width:100%; height:28px; margin-top:6px; display:block; background:var(--bg);
              border-radius:4px; }
  .rt-core { background:var(--bg2); border:1px solid var(--bg3); border-radius:6px;
             padding:6px 8px; min-width:80px; text-align:center; }
  .rt-core .lbl { font-size:0.65rem; color:var(--fg3); text-transform:uppercase; letter-spacing:1px; }
  .rt-core .v   { font-size:0.95rem; font-weight:700; color:var(--fg); margin-top:2px; }
  .rt-core .b   { background:var(--bg3); height:4px; border-radius:2px; margin-top:4px; overflow:hidden; }
  .rt-core .bf  { height:100%; background:linear-gradient(90deg, var(--accent), var(--accent2));
                  transition: width 0.4s; }
  .rt-trend-up   { color: var(--warn); }
  .rt-trend-down { color: var(--accent); }
  .rt-trend-flat { color: var(--fg3); }

  h2.section-title { font-size: 0.85rem; text-transform: uppercase; color: var(--fg3);
                     letter-spacing: 2px; margin-bottom: 14px; padding-left: 4px; }

  /* === Service cards === */
  .services { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
              gap: 14px; }
  .service { background: var(--bg2); border: 1px solid var(--bg3); border-radius: 12px;
             padding: 20px; cursor: pointer; transition: all 0.2s; position: relative; }
  .service::before { content: ""; position: absolute; top: 0; left: 0; right: 0; height: 2px;
                     background: linear-gradient(90deg, var(--accent), var(--accent2));
                     transform: scaleX(0); transform-origin: left; transition: transform 0.3s;
                     border-radius: 12px 12px 0 0; }
  .service:hover { transform: translateY(-2px); border-color: var(--accent); }
  .service:hover::before { transform: scaleX(1); }
  .service .icon { width: 36px; height: 36px; border-radius: 8px; display: flex;
                   align-items: center; justify-content: center; font-size: 1.2rem; margin-bottom: 12px; }
  .icon.green { background: rgba(74, 222, 128, 0.15); }
  .icon.cyan  { background: rgba(34, 211, 238, 0.15); }
  .icon.purple { background: rgba(168, 85, 247, 0.15); }
  .icon.amber { background: rgba(251, 191, 36, 0.15); }
  .service h3 { font-size: 1rem; margin-bottom: 4px; }
  .service p { font-size: 0.85rem; color: var(--fg2); margin-bottom: 10px; }
  .service .arrow { color: var(--accent); font-size: 0.82rem; font-weight: 500; }
  .meta { display: inline-block; padding: 2px 7px; border-radius: 4px;
          background: rgba(74, 222, 128, 0.1); color: var(--accent);
          font-size: 0.7rem; font-weight: 600; margin-left: 6px; }

  /* === Form (Notes) === */
  .form-row { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
  .form-row input, .form-row textarea, .form-row select {
    background: var(--bg); border: 1px solid var(--bg3); color: var(--fg);
    padding: 10px 12px; border-radius: 8px; font-family: inherit; font-size: 0.92rem;
    flex: 1; min-width: 120px; outline: none; transition: border-color 0.15s;
  }
  .form-row input:focus, .form-row textarea:focus, .form-row select:focus {
    border-color: var(--accent);
  }
  .form-row textarea { min-height: 60px; resize: vertical; width: 100%; }
  .btn { background: var(--accent); color: #0a0e1a; border: 0; padding: 10px 18px;
         border-radius: 8px; font-weight: 600; cursor: pointer; font-family: inherit;
         font-size: 0.92rem; transition: all 0.15s; }
  .btn:hover { filter: brightness(1.1); transform: translateY(-1px); }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn.secondary { background: var(--bg3); color: var(--fg); }
  .btn.danger { background: var(--crit); color: white; }
  .btn.small { padding: 4px 10px; font-size: 0.78rem; }

  .note-card { background: var(--bg2); border: 1px solid var(--bg3); border-radius: 10px;
               padding: 16px; margin-bottom: 10px; }
  .note-card h4 { font-size: 1rem; margin-bottom: 4px; }
  .note-card .tag { display: inline-block; padding: 2px 8px; border-radius: 4px;
                    background: rgba(34, 211, 238, 0.15); color: var(--accent2);
                    font-size: 0.72rem; font-weight: 600; margin-right: 8px; }
  .note-card .meta { font-size: 0.78rem; color: var(--fg3); margin-bottom: 8px; }
  .note-card .body { color: var(--fg2); font-size: 0.92rem; white-space: pre-wrap;
                     margin-bottom: 8px; }
  .note-card .actions { display: flex; gap: 6px; }

  .empty { text-align: center; padding: 40px 20px; color: var(--fg3); }

  /* === Code/console panel === */
  .panel { background: var(--bg2); border: 1px solid var(--bg3); border-radius: 10px;
           padding: 20px; margin-bottom: 16px; }
  .panel pre { color: var(--accent2); }

  /* === API tab === */
  .api-grid { display: grid; gap: 8px; }
  .api-row { background: var(--bg2); border: 1px solid var(--bg3); border-radius: 8px;
             padding: 12px 16px; display: flex; align-items: center; gap: 12px; }
  .method { padding: 3px 8px; border-radius: 4px; font-size: 0.72rem; font-weight: 700;
            min-width: 56px; text-align: center; }
  .method.get { background: rgba(34, 211, 238, 0.15); color: var(--accent2); }
  .method.post { background: rgba(74, 222, 128, 0.15); color: var(--accent); }
  .method.put { background: rgba(251, 191, 36, 0.15); color: var(--warn); }
  .method.delete { background: rgba(248, 113, 113, 0.15); color: var(--crit); }
  .api-row code { color: var(--fg); }
  .api-row .desc { color: var(--fg2); font-size: 0.85rem; margin-left: auto; }

  /* === Footer === */
  .footer { text-align: center; padding: 32px; color: var(--fg3); font-size: 0.85rem;
            border-top: 1px solid var(--bg3); margin-top: 48px; }
  .footer code { background: var(--bg2); padding: 2px 8px; border-radius: 4px; color: var(--accent2); }

  /* === Match card (Football) === */
  .match { background: var(--bg2); border: 1px solid var(--bg3); border-radius: 10px;
           padding: 14px 16px; margin-bottom: 8px; display: grid;
           grid-template-columns: 1fr auto 1fr; gap: 16px; align-items: center; }
  .match:hover { border-color: var(--accent); }
  .match .team { font-weight: 600; font-size: 0.95rem; }
  .match .team.away { text-align: right; }
  .match .score { background: var(--bg); border: 1px solid var(--bg3); border-radius: 8px;
                  padding: 8px 16px; font-weight: 700; font-size: 1.1rem; min-width: 80px;
                  text-align: center; }
  .match.live .score { background: rgba(248, 113, 113, 0.15); border-color: var(--crit);
                        color: var(--crit); }
  .match.upcoming .score { color: var(--fg3); font-size: 0.85rem; font-weight: 500; }
  .match .meta { font-size: 0.78rem; color: var(--fg3); margin-top: 4px; }
  .match .badge { display: inline-block; padding: 2px 7px; border-radius: 4px;
                  font-size: 0.7rem; font-weight: 600; margin-left: 6px; }
  .match .badge.live { background: rgba(248, 113, 113, 0.15); color: var(--crit); }
  .match .badge.ft  { background: rgba(74, 222, 128, 0.15); color: var(--accent); }

  /* === WIB date/time block === */
  .wib-date { font-size: 0.82rem; color: var(--fg); margin-bottom: 4px; line-height: 1.4; }
  .wib-day { color: var(--accent); font-weight: 600; }
  .wib-time { color: var(--accent2); font-weight: 600; }
  .wib-meta .venue { color: var(--fg3); font-size: 0.78rem; margin-top: 2px; }

  /* === TV player + grid === */
  .tv-player-wrap { background: var(--bg2); border: 1px solid var(--bg3); border-radius: 12px; overflow: hidden; margin-bottom: 16px; }
  .tv-player { background: #000; aspect-ratio: 16/9; position: relative; display: flex; align-items: center; justify-content: center; }
  .tv-player video { width: 100%; height: 100%; object-fit: contain; background: #000; }
  .tv-channel-info { padding: 12px 16px; border-top: 1px solid var(--bg3); }
  .tv-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(90px, 1fr)); gap: 6px;
             max-height: 65vh; overflow-y: auto; padding: 4px;
             scrollbar-width: thin; scrollbar-color: var(--bg3) transparent; }
  .tv-grid::-webkit-scrollbar { width: 8px; }
  .tv-grid::-webkit-scrollbar-thumb { background: var(--bg3); border-radius: 4px; }
  .tv-grid::-webkit-scrollbar-track { background: transparent; }
  .tv-card { background: var(--bg2); border: 1px solid var(--bg3); border-radius: 6px; padding: 8px 4px; cursor: pointer; transition: all 0.15s; text-align: center; }
  .tv-card:hover { border-color: var(--accent); transform: translateY(-1px); }
  .tv-card.active { border-color: var(--accent); background: rgba(74, 222, 128, 0.1); }
  .tv-card .logo { width: 40px; height: 40px; margin: 0 auto 5px; background: rgba(255,255,255,0.06); border-radius: 5px; display: flex; align-items: center; justify-content: center; overflow: hidden; }
  .tv-card .logo img { width: 100%; height: 100%; object-fit: contain; padding: 2px; }
  .tv-card .logo-fallback { font-size: 1rem; color: var(--fg3); }
  .tv-card .name { font-size: 0.7rem; font-weight: 500; line-height: 1.2; color: var(--fg); overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
  .tv-card .cat { display: none; }
  .tv-filter-btn { padding: 5px 12px !important; }
  .tv-filter-btn.active { background: var(--accent) !important; color: #0a0e1a !important; }

  /* === Toast === */
  .toast { position: fixed; bottom: 24px; right: 24px; background: var(--bg2);
           border: 1px solid var(--accent); border-radius: 10px; padding: 12px 18px;
           box-shadow: 0 8px 24px rgba(0,0,0,0.4); transform: translateY(20px);
           opacity: 0; transition: all 0.3s; z-index: 200; max-width: 340px; }
  .toast.show { transform: none; opacity: 1; }
  .toast.err { border-color: var(--crit); }
  .toast small { color: var(--fg3); display: block; margin-top: 4px; font-size: 0.78rem; }

  @media (max-width: 600px) {
    .topbar { padding: 12px 16px; }
    .container { padding: 20px 16px; }
    .nav button { padding: 6px 10px; font-size: 0.85rem; }
  }

  /* ====================================================== */
  /* === WC26 (Menu Bar App Style) ======================== */
  /* ====================================================== */
  .wc26-wrap {
    max-width: 900px;
    margin: 0 auto;
  }
  .wc26-popover {
    background: var(--bg2);
    border: 1px solid var(--bg3);
    border-radius: 14px;
    overflow: hidden;
    box-shadow: 0 12px 40px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.04);
    --wc26-card-alpha: 0.92;
  }
  .wc26-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    background: linear-gradient(180deg, rgba(74,222,128,0.08), rgba(74,222,128,0.02));
    border-bottom: 1px solid var(--bg3);
    font-size: 0.85rem;
  }
  .wc26-brand {
    display: flex;
    align-items: center;
    gap: 6px;
    font-weight: 700;
    white-space: nowrap;
  }
  .wc26-logo { font-size: 1.05rem; }
  .wc26-title { color: var(--accent); letter-spacing: 0.5px; }
  .wc26-sep { color: var(--fg3); }
  .wc26-subtitle { color: var(--fg2); font-weight: 500; font-size: 0.78rem; }
  .wc26-rotator {
    flex: 1;
    text-align: center;
    font-size: 0.82rem;
    color: var(--fg);
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    padding: 0 8px;
  }
  .wc26-rotator.live { color: var(--crit); animation: wc26-fade 0.3s; }
  .wc26-rot-empty { color: var(--fg3); font-weight: 500; font-style: italic; }
  @keyframes wc26-fade { from { opacity: 0; transform: translateY(2px); } to { opacity: 1; transform: none; } }
  .wc26-actions { display: flex; gap: 4px; }
  .wc26-icon-btn {
    background: transparent; border: 0; color: var(--fg2);
    width: 28px; height: 28px; border-radius: 6px; cursor: pointer;
    font-size: 0.95rem; display: flex; align-items: center; justify-content: center;
    transition: all 0.15s; padding: 0;
  }
  .wc26-icon-btn:hover { background: var(--bg3); color: var(--fg); }
  .wc26-icon-btn:disabled { opacity: 0.4; cursor: not-allowed; }

  .wc26-subnav {
    display: flex;
    background: var(--bg);
    border-bottom: 1px solid var(--bg3);
    padding: 4px;
    gap: 2px;
  }
  .wc26-tab {
    flex: 1;
    background: transparent; border: 0; color: var(--fg2);
    padding: 7px 10px; border-radius: 6px; cursor: pointer;
    font-size: 0.78rem; font-weight: 600; font-family: inherit;
    transition: all 0.15s;
  }
  .wc26-tab:hover { background: var(--bg3); color: var(--fg); }
  .wc26-tab.active { background: var(--bg3); color: var(--accent); }

  .wc26-view { display: none; max-height: 70vh; overflow-y: auto;
    scrollbar-width: thin; scrollbar-color: var(--bg3) transparent; }
  .wc26-view.active { display: block; animation: wc26-fade 0.25s; }
  .wc26-view::-webkit-scrollbar { width: 6px; }
  .wc26-view::-webkit-scrollbar-thumb { background: var(--bg3); border-radius: 3px; }
  .wc26-view::-webkit-scrollbar-track { background: transparent; }

  .wc26-section { padding: 10px 12px 6px; }
  .wc26-section + .wc26-section { border-top: 1px solid rgba(255,255,255,0.04); }

  /* 2-column layout: Jadwal (kiri) | Hasil (kanan) */
  .wc26-2col {
    display: flex;
    align-items: stretch;
    gap: 0;
  }
  .wc26-2col > .wc26-section {
    flex: 1 1 0;
    min-width: 0;
  }
  .wc26-2col > .wc26-section + .wc26-section { border-top: none; border-left: 1px solid rgba(255,255,255,0.06); }
  .wc26-2col .wc26-list {
    max-height: 62vh;
    overflow-y: auto;
    padding-right: 2px;
  }
  .wc26-2col .wc26-list::-webkit-scrollbar { width: 5px; }
  .wc26-2col .wc26-list::-webkit-scrollbar-thumb { background: var(--bg3); border-radius: 3px; }
  .wc26-2col .wc26-list::-webkit-scrollbar-track { background: transparent; }
  .wc26-2col .wc26-section-title { padding-left: 4px; padding-right: 4px; }
  .wc26-2col .wc26-match { font-size: 0.78rem; padding: 6px 8px; }
  .wc26-2col .wc26-match .wc26-badge, .wc26-2col .wc26-match .wc26-badge-fb { width: 18px; height: 18px; }
  .wc26-2col .wc26-match .wc26-center { min-width: 52px; }
  .wc26-2col .wc26-match .wc26-score { font-size: 0.88rem; }
  @media (max-width: 640px) {
    .wc26-2col { flex-direction: column; }
    .wc26-2col > .wc26-section + .wc26-section { border-top: 1px solid rgba(255,255,255,0.04); border-left: none; }
  }
  .wc26-section-title {
    display: flex; align-items: center; gap: 6px;
    font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1.5px;
    color: var(--fg3); font-weight: 700; margin-bottom: 8px;
  }
  .wc26-count {
    margin-left: auto; background: var(--bg3); color: var(--fg2);
    padding: 1px 7px; border-radius: 8px; font-size: 0.7rem; font-weight: 600;
  }
  .wc26-pulse {
    display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    background: var(--crit); box-shadow: 0 0 8px var(--crit);
    animation: wc26-pulse 1.4s infinite;
  }
  @keyframes wc26-pulse { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(0.85); } }

  .wc26-list { display: flex; flex-direction: column; gap: 4px; }
  .wc26-list .wc26-empty { padding: 24px 12px; color: var(--fg3); text-align: center; font-size: 0.85rem; }

  .wc26-match {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    gap: 8px;
    align-items: center;
    background: rgba(255,255,255, var(--wc26-card-alpha, 0.02));
    background: color-mix(in srgb, var(--bg2) calc(var(--wc26-card-alpha, 0.92) * 100%), transparent);
    background: var(--bg);
    border: 1px solid var(--bg3);
    border-radius: 8px;
    padding: 8px 10px;
    cursor: pointer;
    transition: all 0.15s;
    font-size: 0.82rem;
    position: relative;
  }
  .wc26-match:hover { border-color: var(--accent); transform: translateX(2px); }
  .wc26-match.live { border-color: var(--crit); background: rgba(248,113,113,0.06); }
  .wc26-match.live:hover { background: rgba(248,113,113,0.1); }
  .wc26-match.fav-flag { border-left: 2px solid var(--warn); }
  .wc26-match .wc26-team {
    display: flex; align-items: center; gap: 6px; min-width: 0;
  }
  .wc26-match .wc26-team.away { justify-content: flex-end; flex-direction: row-reverse; }
  .wc26-match .wc26-team-name {
    font-weight: 600; white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; min-width: 0;
  }
  .wc26-match .wc26-team.away .wc26-team-name { text-align: right; }
  .wc26-match .wc26-badge {
    width: 22px; height: 22px; object-fit: contain;
    background: rgba(255,255,255,0.04); border-radius: 4px; padding: 2px; flex-shrink: 0;
  }
  .wc26-match .wc26-badge-fb {
    width: 22px; height: 22px; border-radius: 4px; display: flex; align-items: center; justify-content: center;
    background: rgba(255,255,255,0.06); color: var(--fg3); font-size: 0.7rem; font-weight: 700; flex-shrink: 0;
  }
  .wc26-match .wc26-center {
    display: flex; flex-direction: column; align-items: center; min-width: 64px; gap: 1px;
  }
  .wc26-match .wc26-score {
    font-weight: 700; font-size: 0.95rem; color: var(--fg);
    display: flex; align-items: center; gap: 4px;
  }
  .wc26-match .wc26-score .dash { color: var(--fg3); }
  .wc26-match.live .wc26-score { color: var(--crit); }
  .wc26-match .wc26-time {
    font-size: 0.7rem; color: var(--fg3); font-weight: 500;
  }
  .wc26-match .wc26-time.live-min { color: var(--crit); font-weight: 700; }
  .wc26-match .wc26-time.countdown { color: var(--accent2); font-weight: 600; }
  .wc26-match .wc26-fav-btn {
    position: absolute; top: 2px; right: 4px;
    background: transparent; border: 0; color: var(--fg3); cursor: pointer;
    font-size: 0.85rem; padding: 2px 4px; border-radius: 4px;
    opacity: 0; transition: all 0.15s;
  }
  .wc26-match:hover .wc26-fav-btn { opacity: 1; }
  .wc26-match .wc26-fav-btn.active { opacity: 1; color: var(--warn); }
  .wc26-match .wc26-fav-btn:hover { background: var(--bg3); color: var(--warn); }

  .wc26-day-header {
    font-size: 0.72rem; color: var(--fg2); font-weight: 700; padding: 8px 0 4px;
    text-transform: uppercase; letter-spacing: 1px;
    border-bottom: 1px dashed var(--bg3); margin-bottom: 6px;
    display: flex; align-items: center; gap: 6px;
  }
  .wc26-day-header .count {
    color: var(--fg3); font-weight: 500; text-transform: none; letter-spacing: 0;
  }

  /* Standings pills + table */
  .wc26-group-pills {
    display: flex; gap: 6px; padding: 12px; overflow-x: auto;
    scrollbar-width: none; border-bottom: 1px solid var(--bg3);
  }
  .wc26-group-pills::-webkit-scrollbar { display: none; }
  .wc26-pill {
    flex-shrink: 0; padding: 6px 12px; background: var(--bg);
    border: 1px solid var(--bg3); border-radius: 16px;
    color: var(--fg2); font-size: 0.78rem; font-weight: 600; cursor: pointer;
    transition: all 0.15s; font-family: inherit;
  }
  .wc26-pill:hover { border-color: var(--accent); color: var(--fg); }
  .wc26-pill.active { background: var(--accent); color: #0a0e1a; border-color: var(--accent); }

  .wc26-standings-wrap { padding: 12px; }
  .wc26-standings {
    width: 100%; border-collapse: collapse; font-size: 0.78rem;
  }
  .wc26-standings thead th {
    text-align: left; padding: 6px 8px; color: var(--fg3);
    font-size: 0.68rem; text-transform: uppercase; letter-spacing: 1px;
    border-bottom: 1px solid var(--bg3); font-weight: 700;
  }
  .wc26-standings thead th.num { text-align: center; }
  .wc26-standings tbody tr {
    border-bottom: 1px solid rgba(255,255,255,0.04);
    transition: background 0.1s;
  }
  .wc26-standings tbody tr:hover { background: var(--bg); }
  .wc26-standings tbody tr.qualify td { color: var(--accent); }
  .wc26-standings tbody tr.qualify td:first-child::before { content: "✓ "; color: var(--accent); }
  .wc26-standings td {
    padding: 7px 8px; vertical-align: middle;
  }
  .wc26-standings td.pos { font-weight: 700; color: var(--fg2); width: 28px; }
  .wc26-standings td.team { display: flex; align-items: center; gap: 6px; }
  .wc26-standings td.team img { width: 18px; height: 18px; object-fit: contain; }
  .wc26-standings td.team .fb { width: 18px; height: 18px; border-radius: 3px; display: flex; align-items: center; justify-content: center; background: rgba(255,255,255,0.06); color: var(--fg3); font-size: 0.65rem; font-weight: 700; }
  .wc26-standings td.num { text-align: center; font-variant-numeric: tabular-nums; }
  .wc26-standings td.pts { font-weight: 700; color: var(--accent); }
  .wc26-standings .gd-pos { color: var(--accent); }
  .wc26-standings .gd-neg { color: var(--crit); }
  .wc26-standings caption {
    text-align: left; padding: 4px 0 8px; color: var(--fg2); font-weight: 700;
    font-size: 0.85rem;
  }

  /* Settings */
  .wc26-settings-panel { padding: 16px; }
  .wc26-setting {
    display: flex; align-items: center; gap: 12px; padding: 12px 0;
    border-bottom: 1px solid rgba(255,255,255,0.04);
  }
  .wc26-setting > label { flex: 0 0 140px; color: var(--fg2); font-size: 0.85rem; font-weight: 500; }
  .wc26-setting select, .wc26-setting input[type=range] {
    flex: 1; background: var(--bg); border: 1px solid var(--bg3);
    color: var(--fg); padding: 7px 10px; border-radius: 6px; font-family: inherit;
    font-size: 0.85rem; outline: none; cursor: pointer;
  }
  .wc26-setting input[type=range] { padding: 0; height: 6px; -webkit-appearance: none; }
  .wc26-setting input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none; width: 16px; height: 16px; border-radius: 50%;
    background: var(--accent); cursor: pointer;
  }
  .wc26-setting input[type=range]::-moz-range-thumb {
    width: 16px; height: 16px; border-radius: 50%; background: var(--accent);
    cursor: pointer; border: 0;
  }
  .wc26-setting .wc26-val {
    flex: 0 0 50px; text-align: right; color: var(--fg3); font-size: 0.78rem;
    font-variant-numeric: tabular-nums;
  }
  .wc26-toggle { position: relative; display: inline-block; width: 40px; height: 22px; }
  .wc26-toggle input { opacity: 0; width: 0; height: 0; }
  .wc26-toggle-slider {
    position: absolute; cursor: pointer; inset: 0;
    background: var(--bg3); border-radius: 11px; transition: 0.2s;
  }
  .wc26-toggle-slider::before {
    content: ""; position: absolute; height: 16px; width: 16px; left: 3px; top: 3px;
    background: var(--fg2); border-radius: 50%; transition: 0.2s;
  }
  .wc26-toggle input:checked + .wc26-toggle-slider { background: var(--accent); }
  .wc26-toggle input:checked + .wc26-toggle-slider::before { transform: translateX(18px); background: #0a0e1a; }
  .wc26-about { flex: 1; color: var(--fg3); font-size: 0.8rem; line-height: 1.5; }

  .wc26-footer {
    display: flex; justify-content: space-between;
    padding: 8px 14px; border-top: 1px solid var(--bg3);
    font-size: 0.7rem; color: var(--fg3);
    background: var(--bg);
  }
  .wc26-empty { padding: 32px 16px; text-align: center; color: var(--fg3); font-size: 0.85rem; }

  /* Compact mode */
  .wc26-popover.compact .wc26-match { padding: 5px 8px; gap: 6px; }
  .wc26-popover.compact .wc26-badge,
  .wc26-popover.compact .wc26-badge-fb { width: 18px; height: 18px; }
  .wc26-popover.compact .wc26-section { padding: 8px 10px 4px; }
  .wc26-popover.compact .wc26-section-title { margin-bottom: 5px; }

  /* Team detail modal */
  .wc26-modal {
    position: fixed; inset: 0; z-index: 300;
    display: flex; align-items: center; justify-content: center;
    animation: wc26-fade 0.2s;
  }
  .wc26-modal-backdrop {
    position: absolute; inset: 0; background: rgba(0,0,0,0.6);
    backdrop-filter: blur(4px);
  }
  .wc26-modal-sheet {
    position: relative; background: var(--bg2);
    border: 1px solid var(--bg3); border-radius: 14px;
    width: min(560px, 92vw); max-height: 85vh;
    display: flex; flex-direction: column;
    box-shadow: 0 20px 60px rgba(0,0,0,0.6);
    animation: wc26-sheet 0.25s;
  }
  @keyframes wc26-sheet { from { opacity: 0; transform: translateY(20px) scale(0.96); } to { opacity: 1; transform: none; } }
  .wc26-modal-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 18px; border-bottom: 1px solid var(--bg3);
    background: linear-gradient(180deg, rgba(74,222,128,0.06), transparent);
  }
  .wc26-modal-team { display: flex; align-items: center; gap: 12px; }
  .wc26-modal-team img { width: 40px; height: 40px; object-fit: contain; background: rgba(255,255,255,0.05); border-radius: 6px; padding: 4px; }
  .wc26-modal-team h3 { font-size: 1.1rem; font-weight: 700; }
  .wc26-modal-sub { font-size: 0.78rem; color: var(--fg3); margin-top: 2px; }
  .wc26-modal-body { padding: 14px 18px; overflow-y: auto; }
  .wc26-modal-section { margin-bottom: 18px; }
  .wc26-modal-section:last-child { margin-bottom: 0; }
  .wc26-modal .wc26-match { cursor: default; }
  .wc26-modal .wc26-match:hover { transform: none; border-color: var(--bg3); }
  .wc26-modal .wc26-fav-btn { display: none; }

  .wc26-standings td.team button {
    background: transparent; border: 0; color: var(--fg);
    cursor: pointer; font: inherit; text-align: left; padding: 0;
    display: flex; align-items: center; gap: 6px;
  }
  .wc26-standings td.team button:hover { color: var(--accent); }
</style>
</head>
<body>

<div class="topbar">
  <div class="logo">techtalkerid<span>.dev</span></div>
  <div class="nav">
    <button class="active" data-tab="home">🏠 Beranda</button>
    <button data-tab="notes">📝 Notes</button>
    <button data-tab="server">📊 Server</button>
    <button data-tab="worldcup">🏆 Piala Dunia</button>
    <button data-tab="wc26">⚽ WC26</button>
    <button data-tab="tv">📺 TV</button>
    <button data-tab="api">🔌 API</button>
  </div>
  <div class="topbar-right">
    <span class="dot"></span>
    <span>Online</span>
  </div>
</div>

<div class="container">

  <!-- ========== HOME ========== -->
  <div id="sec-home" class="section active">
    <div class="hero">
      <h1>techtalkerid.dev</h1>
      <p>Self-hosted services di VPS Ubuntu 24.04</p>
      <p class="sub">Caddy reverse proxy • Python Flask + FastAPI • SQLite</p>
    </div>

    <div class="stats" id="stats">
      <div class="stat"><div class="label">CPU</div><div class="value" id="s-cpu">–</div><div class="small" id="s-cpu-sub">…</div><div class="bar"><div class="bar-fill" id="s-cpu-bar"></div></div></div>
      <div class="stat"><div class="label">Memory</div><div class="value" id="s-mem">–</div><div class="small" id="s-mem-sub">…</div><div class="bar"><div class="bar-fill" id="s-mem-bar"></div></div></div>
      <div class="stat"><div class="label">Disk (/)</div><div class="value" id="s-disk">–</div><div class="small" id="s-disk-sub">…</div><div class="bar"><div class="bar-fill" id="s-disk-bar"></div></div></div>
      <div class="stat"><div class="label">Uptime</div><div class="value" id="s-up">–</div><div class="small">server</div></div>
      <div class="stat"><div class="label">Notes</div><div class="value" id="s-notes">–</div><div class="small" id="s-notes-sub">…</div></div>
      <div class="stat"><div class="label">Refresh</div><div class="value" id="s-refresh" style="font-size:0.9rem">–</div><div class="small">auto 10s</div></div>
    </div>

    <h2 class="section-title">Layanan — klik untuk buka di tempat</h2>
    <div class="services">
      <div class="service" data-goto="notes">
        <div class="icon green">📝</div>
        <h3>Notes <span class="meta">live</span></h3>
        <p>Bikin, cari, edit, hapus catatan. Ada di tab <b>Notes</b>.</p>
        <span class="arrow">Buka →</span>
      </div>
      <div class="service" data-goto="server">
        <div class="icon cyan">📊</div>
        <h3>Server Monitor <span class="meta">live</span></h3>
        <p>Lihat CPU, RAM, disk, uptime real-time. Ada di tab <b>Server</b>.</p>
        <span class="arrow">Buka →</span>
      </div>
      <div class="service" data-goto="api">
        <div class="icon purple">🔌</div>
        <h3>API Reference <span class="meta">JSON</span></h3>
        <p>Daftar endpoint & cara pake. Ada di tab <b>API</b>.</p>
        <span class="arrow">Buka →</span>
      </div>
      <div class="service" data-goto="worldcup">
        <div class="icon green">⚽</div>
        <h3>Piala Dunia <span class="meta" id="m-fb">live</span></h3>
        <p>Jadwal, hasil, & countdown World Cup 2026. Auto-refresh 6 jam.</p>
        <span class="arrow">Buka →</span>
      </div>
      <div class="service" data-goto="wc26">
        <div class="icon green">🏆</div>
        <h3>WC26 <span class="meta">menu bar</span></h3>
        <p>Menu bar app style — live scores, standings, team details, favorites.</p>
        <span class="arrow">Buka →</span>
      </div>
      <div class="service" data-goto="tv">
        <div class="icon amber">📺</div>
        <h3>Live TV <span class="meta">202 ch</span></h3>
        <p>Stream TV Indonesia (TVRI, RCTI, SCTV, dll). Klik channel untuk nonton.</p>
        <span class="arrow">Buka →</span>
      </div>
    </div>
  </div>

  <!-- ========== NOTES ========== -->
  <div id="sec-notes" class="section">
    <h2 class="section-title">📝 Notes — bikin & manage catatan</h2>

    <div class="panel">
      <h3 style="font-size:0.95rem;margin-bottom:10px;color:var(--fg)">Buat catatan baru</h3>
      <div class="form-row">
        <input id="n-title" placeholder="Judul catatan…" maxlength="200" style="flex:2">
        <input id="n-tag" placeholder="tag (opsional)" maxlength="50" style="flex:1">
      </div>
      <div class="form-row">
        <textarea id="n-content" placeholder="Isi catatan…"></textarea>
      </div>
      <div class="form-row">
        <button class="btn" id="n-add">+ Tambah Catatan</button>
        <button class="btn secondary" id="n-clear">Bersihkan</button>
      </div>
    </div>

    <div class="panel">
      <h3 style="font-size:0.95rem;margin-bottom:10px;color:var(--fg)">Cari catatan</h3>
      <div class="form-row">
        <input id="n-search" placeholder="Ketik kata kunci, tekan Enter…" style="flex:3">
        <button class="btn secondary" id="n-clear-search">Reset</button>
      </div>
    </div>

    <div id="notes-list"></div>
  </div>

  <!-- ========== SERVER ========== -->
  <div id="sec-server" class="section">
    <h2 class="section-title">📊 Server — live monitoring
      <span style="font-size:0.72rem;font-weight:400;color:var(--fg3);margin-left:10px">
        <span id="rt-status" style="color:var(--accent)">● live</span>
        <span style="margin-left:8px">↻ <span id="rt-updated">…</span></span>
      </span>
    </h2>

    <div class="stats" id="stats2">
      <div class="stat">
        <div class="label">CPU <span id="rt-cpu-trend" style="color:var(--fg3);font-weight:400"></span></div>
        <div class="value" id="s2-cpu">–</div>
        <div class="small" id="s2-cpu-sub">…</div>
        <div class="bar"><div class="bar-fill" id="s2-cpu-bar"></div></div>
        <canvas class="rt-spark" id="rt-spark-cpu" width="200" height="28"></canvas>
      </div>
      <div class="stat">
        <div class="label">Memory <span id="rt-mem-trend" style="color:var(--fg3);font-weight:400"></span></div>
        <div class="value" id="s2-mem">–</div>
        <div class="small" id="s2-mem-sub">…</div>
        <div class="bar"><div class="bar-fill" id="s2-mem-bar"></div></div>
        <canvas class="rt-spark" id="rt-spark-mem" width="200" height="28"></canvas>
      </div>
      <div class="stat">
        <div class="label">Disk (/)</div>
        <div class="value" id="s2-disk">–</div>
        <div class="small" id="s2-disk-sub">…</div>
        <div class="bar"><div class="bar-fill" id="s2-disk-bar"></div></div>
      </div>
      <div class="stat">
        <div class="label">Network ↑</div>
        <div class="value" id="s2-netup">–</div>
        <div class="small" id="s2-netup-sub">sent</div>
      </div>
      <div class="stat">
        <div class="label">Network ↓</div>
        <div class="value" id="s2-netdn">–</div>
        <div class="small" id="s2-netdn-sub">received</div>
      </div>
      <div class="stat">
        <div class="label">Uptime</div>
        <div class="value" id="s2-up">–</div>
        <div class="small" id="s2-up-sub">…</div>
      </div>
    </div>

    <div class="stats" id="stats2b" style="margin-top:10px">
      <div class="stat">
        <div class="label">Load avg (1/5/15m)</div>
        <div class="value" id="rt-load" style="font-size:1.1rem">–</div>
        <div class="small" id="rt-load-sub">cores × 1.0 = normal</div>
      </div>
      <div class="stat">
        <div class="label">Swap</div>
        <div class="value" id="rt-swap">–</div>
        <div class="small" id="rt-swap-sub">…</div>
        <div class="bar"><div class="bar-fill" id="rt-swap-bar"></div></div>
      </div>
      <div class="stat">
        <div class="label">Net rate ↓</div>
        <div class="value" id="rt-netin" style="font-size:1.2rem">–</div>
        <div class="small">MB/s received</div>
      </div>
      <div class="stat">
        <div class="label">Net rate ↑</div>
        <div class="value" id="rt-netout" style="font-size:1.2rem">–</div>
        <div class="small">MB/s sent</div>
      </div>
    </div>

    <div class="panel">
      <h3 style="font-size:0.95rem;margin-bottom:10px;color:var(--fg)">CPU per-core (live)</h3>
      <div id="rt-cores" style="display:flex;gap:6px;flex-wrap:wrap;padding:4px 0">Loading…</div>
    </div>

    <div class="panel">
      <h3 style="font-size:0.95rem;margin-bottom:10px;color:var(--fg)">Detail sistem</h3>
      <div id="sys-detail" class="empty" style="padding:12px">Loading…</div>
    </div>

    <div class="panel">
      <h3 style="font-size:0.95rem;margin-bottom:10px;color:var(--fg)">Riwayat CPU &amp; Memory (60 sample terakhir, polling 2 dtk)</h3>
      <canvas id="chart" width="800" height="160" style="width:100%;height:160px;background:var(--bg);border-radius:8px"></canvas>
    </div>
  </div>

  <!-- ========== WC26 (Menu Bar App Style) ========== -->
  <div id="sec-wc26" class="section">
    <div class="wc26-wrap">
      <!-- Popover-style card ala macOS menu bar app -->
      <div class="wc26-popover" id="wc26-popover">
        <!-- Header: brand + rotating live score -->
        <div class="wc26-header">
          <div class="wc26-brand">
            <span class="wc26-logo">⚽</span>
            <span class="wc26-title">WC26</span>
            <span class="wc26-sep">·</span>
            <span class="wc26-subtitle" id="wc26-subtitle">FIFA World Cup 2026</span>
          </div>
          <div class="wc26-rotator" id="wc26-rotator">
            <span class="wc26-rot-empty">no live matches</span>
          </div>
          <div class="wc26-actions">
            <button class="wc26-icon-btn" id="wc26-refresh" title="Refresh">🔄</button>
            <button class="wc26-icon-btn" id="wc26-settings" title="Settings">⚙️</button>
          </div>
        </div>

        <!-- Sub-nav: Fixtures | Standings | Settings -->
        <div class="wc26-subnav">
          <button class="wc26-tab active" data-wc26tab="fixtures">📅 Fixtures</button>
          <button class="wc26-tab" data-wc26tab="standings">🏆 Standings</button>
          <button class="wc26-tab" data-wc26tab="settings">⚙️ Settings</button>
        </div>

        <!-- Fixtures view -->
        <div id="wc26-view-fixtures" class="wc26-view active">
          <!-- Live matches (pinned at top) -->
          <div class="wc26-section" id="wc26-live-section" style="display:none">
            <div class="wc26-section-title">
              <span class="wc26-pulse"></span>
              <span>🔴 LIVE</span>
              <span class="wc26-count" id="wc26-live-count">0</span>
            </div>
            <div id="wc26-live-list" class="wc26-list"></div>
          </div>

          <!-- Favorites -->
          <div class="wc26-section" id="wc26-fav-section" style="display:none">
            <div class="wc26-section-title">
              <span>⭐ Favorites</span>
              <span class="wc26-count" id="wc26-fav-count">0</span>
            </div>
            <div id="wc26-fav-list" class="wc26-list"></div>
          </div>

          <!-- 2-column: Jadwal (kiri) | Hasil (kanan) -->
          <div class="wc26-2col">
            <div class="wc26-section wc26-col-left">
              <div class="wc26-section-title">
                <span>📅 Jadwal</span>
              </div>
              <div id="wc26-upcoming-list" class="wc26-list"></div>
            </div>

            <div class="wc26-section wc26-col-right">
              <div class="wc26-section-title">
                <span>✅ Hasil</span>
              </div>
              <div id="wc26-recent-list" class="wc26-list"></div>
            </div>
          </div>
        </div>

        <!-- Standings view -->
        <div id="wc26-view-standings" class="wc26-view">
          <div class="wc26-group-pills" id="wc26-group-pills"></div>
          <div id="wc26-standings-table" class="wc26-standings-wrap">
            <div class="wc26-empty">Pilih group di atas untuk lihat klasemen.</div>
          </div>
        </div>

        <!-- Settings view -->
        <div id="wc26-view-settings" class="wc26-view">
          <div class="wc26-settings-panel">
            <div class="wc26-setting">
              <label>Auto-refresh</label>
              <select id="wc26-refresh-int">
                <option value="60">1 menit</option>
                <option value="300" selected>5 menit</option>
                <option value="600">10 menit</option>
                <option value="1800">30 menit</option>
                <option value="3600">1 jam</option>
                <option value="0">Off (manual)</option>
              </select>
            </div>
            <div class="wc26-setting">
              <label>Panel transparency</label>
              <input type="range" id="wc26-panel-alpha" min="50" max="100" value="100">
              <span class="wc26-val" id="wc26-panel-alpha-val">100%</span>
            </div>
            <div class="wc26-setting">
              <label>Card transparency</label>
              <input type="range" id="wc26-card-alpha" min="40" max="100" value="92">
              <span class="wc26-val" id="wc26-card-alpha-val">92%</span>
            </div>
            <div class="wc26-setting">
              <label>Tampilkan favorites</label>
              <label class="wc26-toggle">
                <input type="checkbox" id="wc26-show-fav" checked>
                <span class="wc26-toggle-slider"></span>
              </label>
            </div>
            <div class="wc26-setting">
              <label>Mode compact</label>
              <label class="wc26-toggle">
                <input type="checkbox" id="wc26-compact">
                <span class="wc26-toggle-slider"></span>
              </label>
            </div>
            <div class="wc26-setting">
              <label>About</label>
              <div class="wc26-about">
                Rebuild dari <a href="https://github.com/sk-izsk/WC26" target="_blank">sk-izsk/WC26</a> (macOS menu bar app).
                Data: ESPN + TheSportsDB. Cache refresh tiap 6 jam.
              </div>
            </div>
          </div>
        </div>

        <!-- Footer -->
        <div class="wc26-footer">
          <span id="wc26-lastupdate">Last update: …</span>
          <span id="wc26-countdown-info"></span>
        </div>
      </div>
    </div>

    <!-- Team detail modal (macOS sheet style) -->
    <div class="wc26-modal" id="wc26-team-modal" style="display:none">
      <div class="wc26-modal-backdrop" data-close></div>
      <div class="wc26-modal-sheet">
        <div class="wc26-modal-header">
          <div class="wc26-modal-team" id="wc26-modal-team">
            <img id="wc26-modal-badge" src="" alt="">
            <div>
              <h3 id="wc26-modal-name">—</h3>
              <div class="wc26-modal-sub" id="wc26-modal-sub">—</div>
            </div>
          </div>
          <button class="wc26-icon-btn" data-close>✕</button>
        </div>
        <div class="wc26-modal-body">
          <div class="wc26-modal-section">
            <div class="wc26-section-title">📊 Standing di group</div>
            <div id="wc26-modal-standing">—</div>
          </div>
          <div class="wc26-modal-section">
            <div class="wc26-section-title">📅 Jadwal & hasil</div>
            <div id="wc26-modal-matches" class="wc26-list"></div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- ========== WORLDCUP ========== -->
  <div id="sec-worldcup" class="section">
    <div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:8px">
      <h2 class="section-title" style="margin-bottom:0">🏆 Piala Dunia 2026</h2>
      <span style="color:var(--fg3);font-size:0.85rem" id="wc-meta">Loading…</span>
      <button class="btn secondary small" id="wc-refresh" style="margin-left:auto">🔄 Refresh</button>
    </div>
    <p style="color:var(--fg2);font-size:0.9rem;margin-bottom:24px">Jadwal & hasil pertandingan FIFA World Cup. Auto-refresh tiap 6 jam. Countdown real-time ke match berikutnya.</p>

    <h2 class="section-title">⏭️ Next match — jangan sampai kelewat</h2>
    <div id="wc-next"><div class="empty">Loading…</div></div>

    <h2 class="section-title" style="margin-top:32px">📅 Jadwal berikutnya</h2>
    <div id="wc-upcoming"><div class="empty">Loading…</div></div>

    <h2 class="section-title" style="margin-top:32px">✅ Hasil pertandingan</h2>
    <div id="wc-recent"><div class="empty">Loading…</div></div>
  </div>

  <!-- ========== TV ========== -->
  <div id="sec-tv" class="section">
    <div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:8px">
      <h2 class="section-title" style="margin-bottom:0">📺 Live TV</h2>
      <span style="color:var(--fg3);font-size:0.85rem" id="tv-meta">Loading…</span>
      <button class="btn secondary small" id="tv-refresh" style="margin-left:auto">🔄 Refresh list</button>
    </div>
    <p style="color:var(--fg2);font-size:0.9rem;margin-bottom:16px">Stream publik TV dari seluruh dunia. Klik channel untuk nonton. Pake HLS.js via VPS proxy (gak ada CORS issue).</p>

    <div class="tv-player-wrap">
      <div class="tv-player" id="tv-player">
        <div class="empty" style="padding:60px 20px">Pilih channel di bawah untuk mulai nonton</div>
      </div>
      <div class="tv-channel-info" id="tv-info" style="display:none">
        <strong id="tv-name">—</strong>
        <span id="tv-meta2" style="color:var(--fg3);font-size:0.85rem;margin-left:8px"></span>
      </div>
    </div>

    <div class="tv-controls" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px">
      <label style="color:var(--fg2);font-size:0.85rem">Negara:</label>
      <select id="tv-country" style="background:var(--bg);color:var(--fg);border:1px solid var(--bg3);padding:7px 10px;border-radius:6px;font-family:inherit;cursor:pointer;font-size:0.85rem">
        <option value="Indonesia">🇮🇩 Indonesia</option>
        <option value="Malaysia">🇲🇾 Malaysia</option>
        <option value="Singapore">🇸🇬 Singapore</option>
        <option value="Thailand">🇹🇭 Thailand</option>
        <option value="Philippines">🇵🇭 Philippines</option>
        <option value="Vietnam">🇻🇳 Vietnam</option>
        <option value="Hong Kong">🇭🇰 Hong Kong</option>
        <option value="Taiwan">🇹🇼 Taiwan</option>
        <option value="Japan">🇯🇵 Japan</option>
        <option value="Korea, Republic of">🇰🇷 Korea</option>
        <option value="China">🇨🇳 China</option>
        <option value="India">🇮🇳 India</option>
        <option value="United States">🇺🇸 United States</option>
        <option value="United Kingdom">🇬🇧 United Kingdom</option>
        <option value="Brazil">🇧🇷 Brazil</option>
        <option value="Germany">🇩🇪 Germany</option>
        <option value="France">🇫🇷 France</option>
        <option value="Spain">🇪🇸 Spain</option>
        <option value="Italy">🇮🇹 Italy</option>
        <option value="Mexico">🇲🇽 Mexico</option>
        <option value="Canada">🇨🇦 Canada</option>
        <option value="Australia">🇦🇺 Australia</option>
        <option value="Saudi Arabia">🇸🇦 Saudi Arabia</option>
        <option value="Egypt">🇪🇬 Egypt</option>
        <option value="Russia">🇷🇺 Russia</option>
        <option value="all">🌍 Semua negara</option>
      </select>
      <input id="tv-search" type="text" placeholder="🔍 Cari channel…" style="flex:1;min-width:160px;background:var(--bg);color:var(--fg);border:1px solid var(--bg3);padding:7px 10px;border-radius:6px;font-family:inherit;font-size:0.85rem;outline:none">
    </div>

    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px">
      <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:0.85rem;color:var(--fg2)">
        <input type="checkbox" id="tv-working-only" style="cursor:pointer">
        <span>Tampilkan hanya yang jalan</span>
      </label>
      <button class="btn secondary small" id="tv-test-live" style="font-size:0.78rem">🔍 Test koneksi</button>
      <span id="tv-live-status" style="color:var(--fg3);font-size:0.78rem;margin-left:auto">Belum di-test</span>
    </div>

    <h2 class="section-title" style="margin-top:8px">📡 Channel <span id="tv-count" style="color:var(--fg3);font-weight:400"></span></h2>
    <div id="tv-grid" class="tv-grid">
      <div class="empty">Loading channel list…</div>
    </div>
  </div>

  <!-- ========== API ========== -->
  <div id="sec-api" class="section">
    <h2 class="section-title">🔌 API Reference — programmatic access</h2>

    <div class="panel">
      <p style="color:var(--fg2);font-size:0.9rem">Semua endpoint di bawah ini bisa dipanggil dari <code>curl</code>, browser, atau kode lo. Sama domain (gak ada CORS).</p>
    </div>

    <div class="api-grid">
      <div class="api-row">
        <span class="method get">GET</span>
        <code>/api/live-stats</code>
        <span class="desc">Server stats + notes count (gabungan)</span>
      </div>
      <div class="api-row">
        <span class="method get">GET</span>
        <code>/api/notes</code>
        <span class="desc">List semua notes</span>
      </div>
      <div class="api-row">
        <span class="method post">POST</span>
        <code>/api/notes</code>
        <span class="desc">Buat note baru (title wajib)</span>
      </div>
      <div class="api-row">
        <span class="method get">GET</span>
        <code>/api/notes/{id}</code>
        <span class="desc">Ambil note by ID</span>
      </div>
      <div class="api-row">
        <span class="method put">PUT</span>
        <code>/api/notes/{id}</code>
        <span class="desc">Update note (partial)</span>
      </div>
      <div class="api-row">
        <span class="method delete">DELETE</span>
        <code>/api/notes/{id}</code>
        <span class="desc">Hapus note</span>
      </div>
      <div class="api-row">
        <span class="method get">GET</span>
        <code>/api/notes/search?q=keyword</code>
        <span class="desc">Cari note</span>
      </div>
      <div class="api-row">
        <span class="method get">GET</span>
        <code>/health</code>
        <span class="desc">Liveness probe</span>
      </div>
      <div class="api-row">
        <span class="method get">GET</span>
        <code>/api/worldcup</code>
        <span class="desc">World Cup data: upcoming + recent + all_matches (untuk WC26)</span>
      </div>
      <div class="api-row">
        <span class="method get">GET</span>
        <code>/api/worldcup/standings</code>
        <span class="desc">Klasemen group (computed dari match selesai) — buat WC26 standings tab</span>
      </div>
      <div class="api-row">
        <span class="method post">POST</span>
        <code>/api/worldcup/refresh</code>
        <span class="desc">Manual refresh World Cup cache (ESPN + TSDB)</span>
      </div>
    </div>

    <div class="panel" style="margin-top:24px">
      <h3 style="font-size:0.95rem;margin-bottom:10px;color:var(--fg)">Contoh panggilan</h3>
      <pre>curl https://www.techtalkerid.dev/api/notes</pre>
      <pre>curl -X POST https://www.techtalkerid.dev/api/notes \
  -H "Content-Type: application/json" \
  -d '{"title":"Catatan","content":"Halo","tag":"test"}'</pre>
      <pre>curl "https://www.techtalkerid.dev/api/notes/search?q=halo"</pre>
      <p style="color:var(--fg3);font-size:0.85rem;margin-top:8px">Atau pake subdomain langsung: <code>api.techtalkerid.dev</code> (Swagger UI di <code>/docs</code>)</p>
    </div>
  </div>

</div>

<div class="footer">
  Single-page portal • Flask + Caddy • IP <code>104.207.73.54</code>
</div>

<div class="toast" id="toast"></div>

<script>
// ============== TAB NAV (SPA) ==============
document.querySelectorAll('.nav button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const tab = btn.dataset.tab;
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.getElementById('sec-' + tab).classList.add('active');
    location.hash = tab;
    // Lazy-load section content
    if (tab === 'notes' && !window.__notesLoaded) { loadNotes(); window.__notesLoaded = true; }
    if (tab === 'server' && !window.__serverLoaded) { loadServer(); window.__serverLoaded = true; }
    if (tab === 'worldcup') { loadWorldCup(); }
    if (tab === 'wc26') { loadWC26(); }
    if (tab === 'tv') { loadTV(); }
  });
});

// Cards di Beranda: klik = switch tab
document.querySelectorAll('[data-goto]').forEach(card => {
  card.addEventListener('click', () => {
    document.querySelector(`.nav button[data-tab="${card.dataset.goto}"]`).click();
  });
});

// Restore dari URL hash (dipindah ke akhir script agar variable TV sudah di-init)

// ============== TOAST ==============
const toastEl = document.getElementById('toast');
function toast(msg, isErr=false) {
  toastEl.innerHTML = msg;
  toastEl.className = 'toast show' + (isErr ? ' err' : '');
  clearTimeout(window.__toastT);
  window.__toastT = setTimeout(() => toastEl.className = 'toast', 2500);
}

// ============== STATS (Beranda + Server) ==============
const history = []; // for chart
async function loadStats(prefix='') {
  try {
    const agg = await fetch('/api/live-stats').then(r => r.json()).catch(() => null);
    if (!agg) return;
    const $ = id => prefix + id;
    if (agg.server) {
      const stats = agg.server;
      const set = (id, v, cls) => {
        const el = document.getElementById($(id));
        if (!el) return;
        el.textContent = v;
        if (cls) el.className = 'value ' + cls;
      };
      const cpu = stats.cpu.percent;
      set('s-cpu', cpu.toFixed(1) + '%', cpu > 80 ? 'v-crit' : cpu > 50 ? 'v-warn' : '');
      document.getElementById($('s-cpu-sub')).textContent = stats.cpu.cores + ' cores';
      document.getElementById($('s-cpu-bar')).style.width = cpu + '%';
      const mem = stats.memory.percent;
      set('s-mem', mem.toFixed(1) + '%', mem > 80 ? 'v-crit' : mem > 50 ? 'v-warn' : '');
      document.getElementById($('s-mem-sub')).textContent = stats.memory.used_mb + ' / ' + stats.memory.total_mb + ' MB';
      document.getElementById($('s-mem-bar')).style.width = mem + '%';
      const disk = stats.disk.percent;
      set('s-disk', disk.toFixed(1) + '%', disk > 80 ? 'v-crit' : disk > 50 ? 'v-warn' : '');
      document.getElementById($('s-disk-sub')).textContent = stats.disk.used_gb + ' / ' + stats.disk.total_gb + ' GB';
      document.getElementById($('s-disk-bar')).style.width = disk + '%';
      const upH = Math.floor(stats.uptime_seconds / 3600);
      const upM = Math.floor((stats.uptime_seconds % 3600) / 60);
      set('s-up', upH + 'h ' + upM + 'm');
      // Server tab (prefix s2-)
      set('s2-cpu', cpu.toFixed(1) + '%', cpu > 80 ? 'v-crit' : cpu > 50 ? 'v-warn' : '');
      document.getElementById($('s2-cpu-sub')).textContent = stats.cpu.cores + ' cores';
      const s2CpuBar = document.getElementById($('s2-cpu-bar'));
      if (s2CpuBar) s2CpuBar.style.width = cpu + '%';
      set('s2-mem', mem.toFixed(1) + '%', mem > 80 ? 'v-crit' : mem > 50 ? 'v-warn' : '');
      document.getElementById($('s2-mem-sub')).textContent = stats.memory.used_mb + ' / ' + stats.memory.total_mb + ' MB';
      const s2MemBar = document.getElementById($('s2-mem-bar'));
      if (s2MemBar) s2MemBar.style.width = mem + '%';
      set('s2-disk', disk.toFixed(1) + '%', disk > 80 ? 'v-crit' : disk > 50 ? 'v-warn' : '');
      document.getElementById($('s2-disk-sub')).textContent = stats.disk.used_gb + ' / ' + stats.disk.total_gb + ' GB';
      const s2DiskBar = document.getElementById($('s2-disk-bar'));
      if (s2DiskBar) s2DiskBar.style.width = disk + '%';
      const upH2 = Math.floor(stats.uptime_seconds / 3600);
      const upM2 = Math.floor((stats.uptime_seconds % 3600) / 60);
      const upS2 = stats.uptime_seconds % 60;
      set('s2-up', upH2 + 'h ' + upM2 + 'm ' + upS2 + 's');
      set('s2-netup', Math.round(stats.network.bytes_sent_mb) + ' MB');
      set('s2-netdn', Math.round(stats.network.bytes_recv_mb) + ' MB');
      // History chart
      history.push({t: Date.now(), cpu, mem});
      if (history.length > 20) history.shift();
      drawChart();
    }
    if (agg.notes) {
      const noteEl = document.getElementById($('s-notes'));
      if (noteEl) {
        noteEl.textContent = agg.notes.total_notes;
        const tagCount = Object.keys(agg.notes.tags || {}).length;
        document.getElementById($('s-notes-sub')).textContent = tagCount + ' tag' + (tagCount !== 1 ? 's' : '');
      }
    }
    const refEl = document.getElementById($('s-refresh'));
    if (refEl) refEl.textContent = new Date().toLocaleTimeString('id-ID');
  } catch (e) {
    console.warn('Stats error:', e);
  }
}
loadStats();
setInterval(() => loadStats(), 10000);

// ============== NOTES (CRUD) ==============
async function loadNotes(query='') {
  const list = document.getElementById('notes-list');
  list.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const url = query
      ? `/api/notes/search?q=${encodeURIComponent(query)}`
      : '/api/notes';
    const data = await fetch(url).then(r => r.json()).catch(() => null);
    if (!data || !Array.isArray(data) || data.length === 0) {
      list.innerHTML = '<div class="empty">📝 Belum ada catatan. Bikin satu di atas!</div>';
      return;
    }
    list.innerHTML = data.map(n => `
      <div class="note-card" data-id="${n.id}">
        <h4>${escapeHtml(n.title)} ${n.tag ? `<span class="tag">${escapeHtml(n.tag)}</span>` : ''}</h4>
        <div class="meta">#${n.id} • ${new Date(n.created_at).toLocaleString('id-ID')}</div>
        <div class="body">${escapeHtml(n.content || '(kosong)')}</div>
        <div class="actions">
          <button class="btn secondary small" data-edit="${n.id}">Edit</button>
          <button class="btn danger small" data-del="${n.id}">Hapus</button>
        </div>
      </div>
    `).join('');
    // Hook actions
    list.querySelectorAll('[data-del]').forEach(b => {
      b.addEventListener('click', async () => {
        if (!confirm('Hapus catatan #' + b.dataset.del + '?')) return;
        const r = await fetch('/api/notes/' + b.dataset.del, {method:'DELETE'});
        if (r.ok) { toast('Catatan dihapus ✓'); loadNotes(document.getElementById('n-search').value); loadStats(); }
        else toast('Gagal hapus', true);
      });
    });
    list.querySelectorAll('[data-edit]').forEach(b => {
      b.addEventListener('click', async () => {
        const id = b.dataset.edit;
        const note = data.find(n => n.id == id);
        if (!note) return;
        const newTitle = prompt('Judul baru:', note.title);
        if (newTitle === null) return;
        const newContent = prompt('Isi baru:', note.content || '');
        if (newContent === null) return;
        const r = await fetch('/api/notes/' + id, {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({title: newTitle, content: newContent, tag: note.tag})
        });
        if (r.ok) { toast('Catatan diupdate ✓'); loadNotes(document.getElementById('n-search').value); }
        else toast('Gagal update', true);
      });
    });
  } catch (e) {
    list.innerHTML = '<div class="empty">⚠ Gagal load catatan</div>';
  }
}

document.getElementById('n-add').addEventListener('click', async () => {
  const title = document.getElementById('n-title').value.trim();
  const content = document.getElementById('n-content').value.trim();
  const tag = document.getElementById('n-tag').value.trim() || null;
  if (!title) { toast('Judul wajib diisi!', true); return; }
  const btn = document.getElementById('n-add');
  btn.disabled = true;
  try {
    const r = await fetch('/api/notes', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({title, content, tag})
    });
    if (r.ok) {
      toast('Catatan ditambah ✓');
      document.getElementById('n-title').value = '';
      document.getElementById('n-content').value = '';
      document.getElementById('n-tag').value = '';
      loadNotes();
      loadStats();
    } else {
      const err = await r.json().catch(() => ({}));
      toast('Gagal: ' + JSON.stringify(err.detail || err), true);
    }
  } finally {
    btn.disabled = false;
  }
});

document.getElementById('n-clear').addEventListener('click', () => {
  document.getElementById('n-title').value = '';
  document.getElementById('n-content').value = '';
  document.getElementById('n-tag').value = '';
});

document.getElementById('n-search').addEventListener('keydown', e => {
  if (e.key === 'Enter') loadNotes(e.target.value.trim());
});
document.getElementById('n-clear-search').addEventListener('click', () => {
  document.getElementById('n-search').value = '';
  loadNotes();
});

// ============== SERVER (chart) ==============
// ============== SERVER (realtime) ==============
let rtTimer = null;
let rtHistory = [];   // [{t, cpu, mem, netIn, netOut}, ...] max 60 sample
let lastCpu = lastMem = null;
let rtCoresRendered = false;

function setText(id, txt, cls) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = txt;
  if (cls) el.className = 'value ' + cls;
}

function fmtBytes(mb) {
  if (mb < 1024) return Math.round(mb) + ' MB';
  return (mb / 1024).toFixed(2) + ' GB';
}

function fmtUptime(sec) {
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  return `${m}m ${s}s`;
}

function trendArrow(curr, prev) {
  if (prev == null) return '';
  const d = curr - prev;
  if (Math.abs(d) < 0.2) return '<span class="rt-trend-flat"> → flat</span>';
  if (d > 0)  return `<span class="rt-trend-up"> ▲ +${d.toFixed(1)}</span>`;
  return `<span class="rt-trend-down"> ▼ ${d.toFixed(1)}</span>`;
}

function drawSparkline(canvasId, data, color) {
  const c = document.getElementById(canvasId);
  if (!c) return;
  // Resize canvas ke lebar card biar sharp (HiDPI)
  const w = c.clientWidth || 200;
  const h = 28;
  if (c.width !== w * 2) { c.width = w * 2; c.height = h * 2; }
  const ctx = c.getContext('2d');
  // Reset transform (penting — ctx.scale() kumulatif antar call, jadi reset dulu)
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.scale(2, 2);
  ctx.clearRect(0, 0, w, h);
  if (data.length < 2) {
    ctx.fillStyle = '#475569';
    ctx.font = '10px sans-serif';
    ctx.fillText('… collecting', 4, h / 2 + 3);
    return;
  }
  const max = 100;
  // background grid line 50%
  ctx.strokeStyle = '#1e293b';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2);
  ctx.stroke();
  // line
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  const step = w / (data.length - 1);
  data.forEach((v, i) => {
    const x = i * step;
    const y = h - (v / max) * (h - 4) - 2;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
  // last point dot
  const lastY = h - (data[data.length - 1] / max) * (h - 4) - 2;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(w - 1, lastY, 2.2, 0, Math.PI * 2);
  ctx.fill();
}

function renderCores(perCore) {
  const wrap = document.getElementById('rt-cores');
  if (!wrap) return;
  wrap.innerHTML = perCore.map((v, i) => {
    const cls = v > 80 ? 'v-crit' : v > 50 ? 'v-warn' : '';
    return `<div class="rt-core">
      <div class="lbl">core ${i}</div>
      <div class="v ${cls}">${v.toFixed(0)}%</div>
      <div class="b"><div class="bf" style="width:${Math.min(100, v)}%"></div></div>
    </div>`;
  }).join('');
  rtCoresRendered = true;
}

function updateCoresDelta(perCore) {
  if (!rtCoresRendered) { renderCores(perCore); return; }
  perCore.forEach((v, i) => {
    const card = document.querySelectorAll('#rt-cores .rt-core')[i];
    if (!card) return;
    const vEl = card.querySelector('.v');
    const bEl = card.querySelector('.bf');
    if (vEl) {
      vEl.textContent = v.toFixed(0) + '%';
      vEl.className = 'v ' + (v > 80 ? 'v-crit' : v > 50 ? 'v-warn' : '');
    }
    if (bEl) bEl.style.width = Math.min(100, v) + '%';
  });
}

async function loadServer() {
  // First paint: langsung fetch, lalu set interval 2 detik
  await pollRealtime();
  if (rtTimer) clearInterval(rtTimer);
  rtTimer = setInterval(pollRealtime, 2000);
}

async function pollRealtime() {
  try {
    const r = await fetch('/api/server-realtime', {cache: 'no-store'});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();

    // Status indicator
    const status = document.getElementById('rt-status');
    const upd = document.getElementById('rt-updated');
    if (status) { status.textContent = '● live'; status.style.color = 'var(--accent)'; }
    if (upd) upd.textContent = new Date(d.ts * 1000).toLocaleTimeString('id-ID');

    // CPU
    const cpu = d.cpu.percent;
    setText('s2-cpu', cpu.toFixed(1) + '%', cpu > 80 ? 'v-crit' : cpu > 50 ? 'v-warn' : '');
    document.getElementById('s2-cpu-sub').textContent =
      d.cpu.cores_phys + ' phys / ' + d.cpu.cores_logical + ' log' +
      (d.cpu.freq_mhz ? ' • ' + d.cpu.freq_mhz.toFixed(0) + ' MHz' : '');
    document.getElementById('s2-cpu-bar').style.width = cpu + '%';
    document.getElementById('rt-cpu-trend').innerHTML = trendArrow(cpu, lastCpu);

    // Memory
    const mem = d.memory.percent;
    setText('s2-mem', mem.toFixed(1) + '%', mem > 80 ? 'v-crit' : mem > 50 ? 'v-warn' : '');
    document.getElementById('s2-mem-sub').textContent =
      d.memory.used_mb + ' / ' + d.memory.total_mb + ' MB • avail ' + d.memory.available_mb + ' MB';
    document.getElementById('s2-mem-bar').style.width = mem + '%';
    document.getElementById('rt-mem-trend').innerHTML = trendArrow(mem, lastMem);

    // Disk
    const disk = d.disk.percent;
    setText('s2-disk', disk.toFixed(1) + '%', disk > 80 ? 'v-crit' : disk > 50 ? 'v-warn' : '');
    document.getElementById('s2-disk-sub').textContent =
      d.disk.used_gb + ' / ' + d.disk.total_gb + ' GB • free ' + d.disk.free_gb + ' GB';
    document.getElementById('s2-disk-bar').style.width = disk + '%';

    // Network total (kumulatif)
    setText('s2-netup', fmtBytes(d.network.bytes_sent_mb), d.network.out_mbs > 1 ? 'v-warn' : '');
    document.getElementById('s2-netup-sub').textContent =
      'total sent (' + d.network.out_mbs.toFixed(2) + ' MB/s)';
    setText('s2-netdn', fmtBytes(d.network.bytes_recv_mb), d.network.in_mbs > 1 ? 'v-warn' : '');
    document.getElementById('s2-netdn-sub').textContent =
      'total recv (' + d.network.in_mbs.toFixed(2) + ' MB/s)';

    // Net rate (realtime)
    setText('rt-netin', d.network.in_mbs.toFixed(3));
    setText('rt-netout', d.network.out_mbs.toFixed(3));

    // Uptime
    document.getElementById('s2-up').textContent = fmtUptime(d.uptime);
    document.getElementById('s2-up-sub').textContent =
      'booted ' + new Date(d.boot * 1000).toLocaleString('id-ID');

    // Load avg
    if (d.load && d.load[1] != null) {
      const cores = d.cpu.cores_logical;
      const norm = (v) => v < cores * 0.7 ? 'v-warn' : ''; // load > cores = overload
      document.getElementById('rt-load').textContent =
        d.load[1].toFixed(2) + ' / ' + d.load[5].toFixed(2) + ' / ' + d.load[15].toFixed(2);
      document.getElementById('rt-load-sub').textContent =
        cores + ' cores • ' + (d.load[1] < cores ? 'normal' : 'overload');
    } else {
      document.getElementById('rt-load').textContent = 'n/a';
    }

    // Swap
    setText('rt-swap', d.swap.percent.toFixed(1) + '%', d.swap.percent > 50 ? 'v-warn' : '');
    document.getElementById('rt-swap-sub').textContent =
      d.swap.used_mb + ' / ' + d.swap.total_mb + ' MB';
    document.getElementById('rt-swap-bar').style.width = d.swap.percent + '%';

    // CPU per-core
    updateCoresDelta(d.cpu.per_core);

    // System detail panel
    document.getElementById('sys-detail').innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;text-align:left">
        <div><small style="color:var(--fg3);text-transform:uppercase;font-size:0.72rem">Hostname</small>
             <div style="color:var(--fg);font-weight:600">${escapeHtml(d.hostname)}</div></div>
        <div><small style="color:var(--fg3);text-transform:uppercase;font-size:0.72rem">Platform</small>
             <div style="color:var(--fg);font-weight:600">${escapeHtml(d.platform.split('-')[0])}</div></div>
        <div><small style="color:var(--fg3);text-transform:uppercase;font-size:0.72rem">Python</small>
             <div style="color:var(--fg);font-weight:600">${escapeHtml(d.python)}</div></div>
        <div><small style="color:var(--fg3);text-transform:uppercase;font-size:0.72rem">Sample interval</small>
             <div style="color:var(--accent);font-weight:600">2 detik</div></div>
      </div>
    `;

    // History chart (pakai data realtime juga, max 60 sample = 2 menit)
    rtHistory.push({t: d.ts, cpu, mem, netIn: d.network.in_mbs, netOut: d.network.out_mbs});
    if (rtHistory.length > 60) rtHistory.shift();
    // Sinkronkan ke global `history` (const, jadi mutate isinya) untuk drawChart()
    history.length = 0;
    rtHistory.forEach(h => history.push({t: h.t, cpu: h.cpu, mem: h.mem}));
    drawChart();
    drawSparkline('rt-spark-cpu', rtHistory.map(h => h.cpu), '#4ade80');
    drawSparkline('rt-spark-mem', rtHistory.map(h => h.mem), '#22d3ee');

    lastCpu = cpu;
    lastMem = mem;
  } catch (e) {
    const status = document.getElementById('rt-status');
    if (status) { status.textContent = '● offline'; status.style.color = 'var(--crit)'; }
    console.warn('Realtime poll error:', e);
  }
}

function drawChart() {
  const canvas = document.getElementById('chart');
  if (!canvas || history.length === 0) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  // Grid
  ctx.strokeStyle = '#1e293b'; ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) {
    const y = (h / 4) * i;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }
  const drawLine = (key, color) => {
    ctx.strokeStyle = color; ctx.lineWidth = 2;
    ctx.beginPath();
    history.forEach((p, i) => {
      const x = (i / (history.length - 1 || 1)) * w;
      const y = h - (p[key] / 100) * h;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
  };
  drawLine('cpu', '#4ade80');
  drawLine('mem', '#22d3ee');
  // Legend
  ctx.font = '12px sans-serif';
  ctx.fillStyle = '#4ade80'; ctx.fillText('● CPU', 10, 18);
  ctx.fillStyle = '#22d3ee'; ctx.fillText('● Memory', 80, 18);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ============== WORLDCUP ==============
let wcCountdownInterval = null;
const TEAM_BADGE_PROXY = '/api/badge?url=';  // proxy untuk hindari CORS image issue

function badgeImg(url) {
  if (!url) return '';
  // Pakai <img> langsung karena TheSportsDB sudah set CORS-friendly headers
  return `<img src="${escapeHtml(url)}" alt="" style="width:32px;height:32px;object-fit:contain;vertical-align:middle;background:rgba(255,255,255,0.04);border-radius:4px;padding:2px">`;
}

function countdownText(cd) {
  if (!cd) return '';
  if (cd.days > 0) return `${cd.days}d ${cd.hours}j`;
  if (cd.hours > 0) return `${cd.hours}j ${cd.minutes}m`;
  if (cd.minutes > 0) {
    const s = Math.max(0, cd.total_seconds % 60);
    return `${cd.minutes}m ${s}s`;
  }
  return `${Math.max(0, cd.total_seconds)}s`;
}

function renderMatchCard(m, opts = {}) {
  const isFinished = m.home_score !== null && m.away_score !== null;
  const isUpcoming = !isFinished;
  const cd = m.countdown || {};
  const wib = m.wib || {};  // {time_wib, day_name, date_long, date_short, ...}
  const kickoffWIB = wib.time_wib ? `${wib.time_wib} WIB` : '';
  const kickoffDayDate = wib.date_long || m.date || '';
  const localTime = m.time_local ? `${m.time_local} EDT` : '';
  const venue = m.venue ? `${m.venue}${m.city ? ', ' + m.city : ''}` : '';
  const stage = [m.group ? 'Group ' + m.group : '', m.round ? 'Round ' + m.round : ''].filter(Boolean).join(' • ');

  let centerHtml;
  if (isFinished) {
    centerHtml = `<div class="score">${m.home_score} – ${m.away_score} <span class="badge ft">FT</span></div>`;
  } else if (cd.label === 'LIVE / dimulai' || m.is_live) {
    centerHtml = `<div class="score" style="color:var(--crit)">🔴 LIVE</div>`;
  } else {
    const big = opts.highlight && cd.total_seconds !== undefined;
    const lbl = big ? countdownText(cd) : (m.time_utc || 'TBD');
    centerHtml = `<div class="score" style="${big ? 'font-size:1.3rem;color:var(--accent)' : ''}">${lbl}</div>`;
  }

  // Untuk upcoming, tampilkan hari + tanggal lengkap + jam WIB (prominent)
  // Untuk finished, tampilkan tanggal lengkap + jam WIB saja
  const dateInfoHtml = wib.date_long ? `
    <div class="wib-date">
      <span class="wib-text">${escapeHtml(isUpcoming ? wib.date_long : wib.date_short)}</span>
      ${kickoffWIB ? '<span class="wib-time"> • ' + kickoffWIB + '</span>' : ''}
    </div>
  ` : '';

  return `
    <div class="match ${isFinished ? '' : 'upcoming'}" style="${opts.highlight ? 'border:2px solid var(--accent);background:rgba(74,222,128,0.05)' : ''}">
      <div>
        <div class="team home">${badgeImg(m.home_badge)} ${escapeHtml(m.home_team)}</div>
        <div class="meta">${stage || '—'}</div>
      </div>
      ${centerHtml}
      <div>
        <div class="team away">${escapeHtml(m.away_team)} ${badgeImg(m.away_badge)}</div>
        <div class="meta wib-meta" style="text-align:right">
          ${dateInfoHtml}
          ${venue ? '<div class="venue">🏟️ ' + escapeHtml(venue) + '</div>' : ''}
        </div>
      </div>
    </div>
  `;
}

async function loadWorldCup() {
  const nextEl = document.getElementById('wc-next');
  const upEl = document.getElementById('wc-upcoming');
  const recEl = document.getElementById('wc-recent');
  const meta = document.getElementById('wc-meta');
  meta.textContent = 'Loading…';
  try {
    const data = await fetch('/api/worldcup').then(r => r.json());
    if (data.error) {
      nextEl.innerHTML = `<div class="empty">⚠ ${data.error}</div>`;
      upEl.innerHTML = ''; recEl.innerHTML = '';
      meta.textContent = '';
      return;
    }
    const lu = data.last_updated ? new Date(data.last_updated).toLocaleString('id-ID') : '?';
    meta.textContent = `Last update: ${lu} • ${data.upcoming.length} upcoming • ${data.recent.length} recent`;

    // Next match = pertama di upcoming, atau null
    if (data.upcoming && data.upcoming.length > 0) {
      const next = data.upcoming[0];
      nextEl.innerHTML = renderMatchCard(next, {highlight: true});
      // Tambah countdown real-time (re-render tiap detik)
      if (wcCountdownInterval) clearInterval(wcCountdownInterval);
      wcCountdownInterval = setInterval(() => {
        if (!next.countdown || next.home_score !== null) return;
        next.countdown.total_seconds -= 1;
        if (next.countdown.total_seconds < 0) {
          next.countdown.label = 'LIVE / dimulai';
          next.is_live = true;
        } else {
          const s = next.countdown.total_seconds;
          next.countdown.days = Math.floor(s / 86400);
          next.countdown.hours = Math.floor((s % 86400) / 3600);
          next.countdown.minutes = Math.floor((s % 3600) / 60);
        }
        nextEl.innerHTML = renderMatchCard(next, {highlight: true});
      }, 1000);
    } else {
      nextEl.innerHTML = '<div class="empty">Tidak ada jadwal terdekat.</div>';
    }

    // Upcoming (skip first, karena sudah di next)
    const upRest = (data.upcoming || []).slice(1);
    if (upRest.length === 0) {
      upEl.innerHTML = '<div class="empty">Tidak ada jadwal lain.</div>';
    } else {
      upEl.innerHTML = upRest.map(m => renderMatchCard(m)).join('');
    }

    // Recent
    if (!data.recent || data.recent.length === 0) {
      recEl.innerHTML = '<div class="empty">Belum ada pertandingan selesai.</div>';
    } else {
      recEl.innerHTML = data.recent.map(m => renderMatchCard(m)).join('');
    }
  } catch (e) {
    nextEl.innerHTML = `<div class="empty">⚠ Gagal load: ${e.message}</div>`;
    meta.textContent = 'Error';
  }
}

document.getElementById('wc-refresh').addEventListener('click', async () => {
  const btn = document.getElementById('wc-refresh');
  btn.disabled = true;
  btn.textContent = '⏳ Refreshing…';
  try {
    await fetch('/api/worldcup/refresh', {method: 'POST'});
    toast('World Cup cache di-refresh ✓');
    loadWorldCup();
  } catch (e) {
    toast('Refresh gagal: ' + e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '🔄 Refresh';
  }
});

// ============== WC26 (Menu Bar App Style) ==============
// State
const wc26 = {
  data: null,           // /api/worldcup response
  standings: null,      // /api/worldcup/standings response
  favorites: [],        // team names (localStorage)
  activeTab: 'fixtures',// fixtures | standings | settings
  activeGroup: null,    // 'A', 'B', ...
  refreshTimer: null,
  refreshInterval: 300, // seconds (5 min default)
  showFav: true,
  compact: false,
  panelAlpha: 100,
  cardAlpha: 92,
  rotIdx: 0,            // rotator index for live matches
  rotTimer: null,
  // Settings persistence
  loadSettings() {
    try {
      const s = JSON.parse(localStorage.getItem('wc26_settings') || '{}');
      this.refreshInterval = s.refreshInterval ?? 300;
      this.showFav = s.showFav ?? true;
      this.compact = s.compact ?? false;
      this.panelAlpha = s.panelAlpha ?? 100;
      this.cardAlpha = s.cardAlpha ?? 92;
    } catch (e) {}
  },
  saveSettings() {
    localStorage.setItem('wc26_settings', JSON.stringify({
      refreshInterval: this.refreshInterval,
      showFav: this.showFav,
      compact: this.compact,
      panelAlpha: this.panelAlpha,
      cardAlpha: this.cardAlpha,
    }));
  },
  loadFavorites() {
    try { this.favorites = JSON.parse(localStorage.getItem('wc26_favorites') || '[]'); }
    catch (e) { this.favorites = []; }
  },
  saveFavorites() {
    localStorage.setItem('wc26_favorites', JSON.stringify(this.favorites));
  },
  isFav(team) { return this.favorites.includes(team); },
  toggleFav(team) {
    const i = this.favorites.indexOf(team);
    if (i >= 0) this.favorites.splice(i, 1);
    else this.favorites.push(team);
    this.saveFavorites();
  },
};

function wc26BadgeImg(url, name) {
  // Fix old broken ESPN URLs (soccer/500/UPPER -> countries/500/lower)
  if (url) {
    url = url.replace('soccer/500/', 'countries/500/');
    const base = url.substring(0, url.lastIndexOf('/') + 1);
    const fn = url.substring(url.lastIndexOf('/') + 1).toLowerCase();
    url = base + fn;
  }
  if (url) return `<img class="wc26-badge" src="${escapeHtml(url)}" alt="" onerror="this.outerHTML='<span class=\\'wc26-badge-fb\\'>${escapeHtml((name||'?').charAt(0).toUpperCase())}</span>'">`;
  return `<span class="wc26-badge-fb">${escapeHtml((name||'?').charAt(0).toUpperCase())}</span>`;
}

function wc26FmtCountdown(cd) {
  if (!cd) return '';
  if (cd.days != null && cd.days > 0) return `${cd.days}h ${cd.hours}j`;
  if (cd.hours != null && cd.hours > 0) return `${cd.hours}j ${cd.minutes}m`;
  if (cd.minutes != null && cd.minutes > 0) return `${cd.minutes}m ${cd.seconds ?? 0}s`;
  return `${Math.max(0, cd.seconds ?? cd.total_seconds ?? 0)}s`;
}

// Compute current match minute (e.g. "67'", "45'+2") from kickoff + status
function wc26LiveMinute(m) {
  if (!m.is_live || !m.wib || !m.wib.iso_wib) return null;
  try {
    const kickoff = new Date(m.wib.iso_wib);
    const now = new Date();
    const elapsedMs = now - kickoff;
    if (elapsedMs < 0) return null;
    const elapsedMin = Math.floor(elapsedMs / 60000);
    // 90 + stoppage (max ~105)
    if (elapsedMin > 105) return "FT";
    if (elapsedMin > 45 && elapsedMin <= 60) return "HT";
    const min = Math.min(90, Math.max(1, elapsedMin));
    return min + "'";
  } catch (e) { return null; }
}

function wc26RenderMatch(m, opts = {}) {
  // Determine state. ESPN sometimes returns score=0 for not-yet-started matches,
  // so we must check status code, not just score presence.
  const status = (m.status || '').toUpperCase();
  const rawStatus = (m.raw_status || '').toUpperCase();
  const isFinished = !m.is_live && (status === 'FT' || rawStatus.includes('FINAL') ||
                                    rawStatus.includes('FULL_TIME') || rawStatus.includes('STATUS_AET') ||
                                    rawStatus.includes('STATUS_PEN') ||
                                    (m.home_score != null && m.away_score != null &&
                                     (rawStatus === 'STATUS_FINAL' || rawStatus === 'STATUS_FULL_TIME' ||
                                      rawStatus === 'STATUS_AET' || rawStatus === 'STATUS_PEN')));
  const isLive = m.is_live && !isFinished;
  const liveMin = isLive ? wc26LiveMinute(m) : null;
  const fav = wc26.isFav(m.home_team) || wc26.isFav(m.away_team);

  let center;
  if (isLive) {
    const score = (m.home_score != null ? m.home_score : 0) + ' <span class="dash">–</span> ' + (m.away_score != null ? m.away_score : 0);
    center = `
      <div class="wc26-score">${score}</div>
      <div class="wc26-time live-min">${liveMin || 'LIVE'}</div>
    `;
  } else if (isFinished) {
    center = `
      <div class="wc26-score">${m.home_score} <span class="dash">–</span> ${m.away_score}</div>
      <div class="wc26-time">FT</div>
    `;
  } else {
    // Upcoming
    const wib = m.wib || {};
    const kickoffWIB = wib.time_wib || m.time_utc || 'TBD';
    // Countdown from now
    let cdTxt = '';
    if (m.countdown && m.countdown.total_seconds > 0) {
      cdTxt = wc26FmtCountdown(m.countdown);
    }
    center = `
      <div class="wc26-time">${escapeHtml(kickoffWIB)}${wib.time_wib ? ' <span style="color:var(--fg3);font-size:0.62rem">WIB</span>' : ''}</div>
      ${cdTxt ? `<div class="wc26-time countdown">${cdTxt}</div>` : ''}
    `;
  }

  const home = wc26BadgeImg(m.home_badge, m.home_team);
  const away = wc26BadgeImg(m.away_badge, m.away_team);
  const favBtnCls = fav ? 'active' : '';
  const favIcon = wc26.isFav(m.home_team) ? '⭐' : (wc26.isFav(m.away_team) ? '⭐' : '☆');

  // Click handler stored as data attr; will be wired in render
  return `
    <div class="wc26-match ${isLive ? 'live' : ''} ${fav ? 'fav-flag' : ''}" data-mid="${escapeHtml(m.id)}" data-home="${escapeHtml(m.home_team)}" data-away="${escapeHtml(m.away_team)}" data-fav="${fav}">
      <div class="wc26-team home">${home}<span class="wc26-team-name">${escapeHtml(m.home_team)}</span></div>
      <div class="wc26-center">${center}</div>
      <div class="wc26-team away">${away}<span class="wc26-team-name">${escapeHtml(m.away_team)}</span></div>
      <button class="wc26-fav-btn ${favBtnCls}" data-fav-team="${escapeHtml(m.home_team)}" data-fav-other="${escapeHtml(m.away_team)}" title="Favorite">${favIcon}</button>
    </div>
  `;
}

function wc26GroupByDay(matches) {
  // Group upcoming matches by WIB date
  const groups = {};
  for (const m of matches) {
    const key = m.wib?.date_wib || m.date;
    if (!groups[key]) groups[key] = [];
    groups[key].push(m);
  }
  return Object.entries(groups).map(([k, ms]) => ({ key: k, matches: ms }));
}

function wc26RenderDayHeader(dateKey, count) {
  // Try to make a friendly label from date
  const m = dateKey.match(/^(\d{4})-(\d{2})-(\d{2})/);
  let label = dateKey;
  if (m) {
    const dt = new Date(parseInt(m[1]), parseInt(m[2]) - 1, parseInt(m[3]));
    const dayName = ['Minggu','Senin','Selasa','Rabu','Kamis','Jumat','Sabtu'][dt.getDay()];
    // 0-indexed for JS Date.getMonth() (0=Jan, 5=June)
    const monthName = ['Januari','Februari','Maret','April','Mei','Juni','Juli','Agustus','September','Oktober','November','Desember'][dt.getMonth()];
    label = `${dayName}, ${parseInt(m[3])} ${monthName} ${m[1]}`;
  }
  return `<div class="wc26-day-header">${escapeHtml(label)} <span class="count">(${count} match)</span></div>`;
}

function wc26RenderUpcoming() {
  const el = document.getElementById('wc26-upcoming-list');
  if (!wc26.data || !wc26.data.upcoming || wc26.data.upcoming.length === 0) {
    el.innerHTML = '<div class="wc26-empty">Tidak ada jadwal lagi.</div>';
    return;
  }
  const days = wc26GroupByDay(wc26.data.upcoming);
  let html = '';
  for (const d of days) {
    html += wc26RenderDayHeader(d.key, d.matches.length);
    html += d.matches.map(m => wc26RenderMatch(m)).join('');
  }
  el.innerHTML = html;
}

function wc26RenderRecent() {
  const el = document.getElementById('wc26-recent-list');
  if (!wc26.data || !wc26.data.recent || wc26.data.recent.length === 0) {
    el.innerHTML = '<div class="wc26-empty">Belum ada hasil.</div>';
    return;
  }
  // Show last 15
  const matches = wc26.data.recent.slice(0, 15);
  el.innerHTML = matches.map(m => wc26RenderMatch(m)).join('');
}

function wc26RenderLive() {
  const section = document.getElementById('wc26-live-section');
  const list = document.getElementById('wc26-live-list');
  const count = document.getElementById('wc26-live-count');
  if (!wc26.data) { section.style.display = 'none'; return; }
  const liveMatches = (wc26.data.all_matches || wc26.data.upcoming || []).filter(m => m.is_live);
  if (liveMatches.length === 0) {
    section.style.display = 'none';
    return;
  }
  section.style.display = '';
  count.textContent = liveMatches.length;
  list.innerHTML = liveMatches.map(m => wc26RenderMatch(m)).join('');
}

function wc26RenderFavorites() {
  const section = document.getElementById('wc26-fav-section');
  const list = document.getElementById('wc26-fav-list');
  const count = document.getElementById('wc26-fav-count');
  if (!wc26.data || !wc26.showFav || wc26.favorites.length === 0) {
    section.style.display = 'none';
    return;
  }
  // Combine upcoming + recent, filter by fav teams
  const all = (wc26.data.upcoming || []).concat(wc26.data.recent || []);
  const favMatches = all.filter(m =>
    wc26.isFav(m.home_team) || wc26.isFav(m.away_team)
  ).sort((a, b) => {
    // Upcoming first, then by date
    const af = a.home_score === null ? 0 : 1;
    const bf = b.home_score === null ? 0 : 1;
    if (af !== bf) return af - bf;
    return (a.wib?.iso_wib || a.date || '').localeCompare(b.wib?.iso_wib || b.date || '');
  }).slice(0, 12);

  if (favMatches.length === 0) {
    section.style.display = 'none';
    return;
  }
  section.style.display = '';
  count.textContent = wc26.favorites.length;
  list.innerHTML = favMatches.map(m => wc26RenderMatch(m)).join('');
}

function wc26UpdateRotator() {
  const rot = document.getElementById('wc26-rotator');
  if (!wc26.data) return;
  const liveMatches = (wc26.data.all_matches || []).filter(m => m.is_live);
  if (liveMatches.length === 0) {
    rot.className = 'wc26-rotator';
    rot.innerHTML = '<span class="wc26-rot-empty">no live matches</span>';
    return;
  }
  const m = liveMatches[wc26.rotIdx % liveMatches.length];
  const h = m.home_score != null ? m.home_score : 0;
  const a = m.away_score != null ? m.away_score : 0;
  const min = wc26LiveMinute(m) || 'LIVE';
  const shortHome = m.home_team.length > 8 ? m.home_team.slice(0, 3).toUpperCase() : m.home_team;
  const shortAway = m.away_team.length > 8 ? m.away_team.slice(0, 3).toUpperCase() : m.away_team;
  rot.className = 'wc26-rotator live';
  rot.innerHTML = `🔴 ${escapeHtml(shortHome)} ${h}–${a} ${escapeHtml(shortAway)} <span style="opacity:0.7;font-size:0.7rem;margin-left:6px">${min}</span>`;
}

function wc26RenderStandings(groupKey) {
  const wrap = document.getElementById('wc26-standings-table');
  if (!wc26.standings || !wc26.standings.groups) {
    wrap.innerHTML = '<div class="wc26-empty">Belum ada data klasemen (tunggu match group stage selesai pertama).</div>';
    return;
  }
  if (!groupKey) {
    wrap.innerHTML = '<div class="wc26-empty">Pilih group di atas.</div>';
    return;
  }
  const rows = wc26.standings.groups[groupKey];
  if (!rows || rows.length === 0) {
    wrap.innerHTML = `<div class="wc26-empty">Group ${escapeHtml(groupKey)} belum ada match selesai.</div>`;
    return;
  }
  const html = `
    <table class="wc26-standings">
      <caption>Group ${escapeHtml(groupKey)} • Top 2 lolos ke knockout</caption>
      <thead><tr>
        <th class="pos">#</th>
        <th>Team</th>
        <th class="num">P</th><th class="num">W</th><th class="num">D</th><th class="num">L</th>
        <th class="num">GF</th><th class="num">GA</th><th class="num">GD</th><th class="num">Pts</th>
      </tr></thead>
      <tbody>
        ${rows.map((r, i) => {
          let badge = r.badge || '';
          if (badge && badge.includes('soccer/500/')) {
            badge = badge.replace('soccer/500/', 'countries/500/');
            const b = badge.substring(0, badge.lastIndexOf('/') + 1);
            const f = badge.substring(badge.lastIndexOf('/') + 1).toLowerCase();
            badge = b + f;
          }
          const badgeHtml = badge
            ? `<img src="${escapeHtml(badge)}" alt="" onerror="this.outerHTML='<span class=\\'fb\\'>${escapeHtml(r.team.charAt(0).toUpperCase())}</span>'">`
            : `<span class="fb">${escapeHtml(r.team.charAt(0).toUpperCase())}</span>`;
          return `
          <tr class="${i < 2 ? 'qualify' : ''}">
            <td class="pos">${i + 1}</td>
            <td class="team">
              <button data-team="${escapeHtml(r.team)}" data-badge="${escapeHtml(badge)}">
                ${badgeHtml}
                ${escapeHtml(r.team)}
              </button>
            </td>
            <td class="num">${r.played}</td>
            <td class="num">${r.won}</td>
            <td class="num">${r.drawn}</td>
            <td class="num">${r.lost}</td>
            <td class="num">${r.gf}</td>
            <td class="num">${r.ga}</td>
            <td class="num ${r.gd > 0 ? 'gd-pos' : r.gd < 0 ? 'gd-neg' : ''}">${r.gd > 0 ? '+' : ''}${r.gd}</td>
            <td class="num pts">${r.pts}</td>
          </tr>
        `;}).join('')}
      </tbody>
    </table>
  `;
  wrap.innerHTML = html;
  // Wire team buttons
  wrap.querySelectorAll('button[data-team]').forEach(btn => {
    btn.addEventListener('click', () => {
      wc26OpenTeamModal(btn.dataset.team, btn.dataset.badge);
    });
  });
}

function wc26RenderGroupPills() {
  const pills = document.getElementById('wc26-group-pills');
  if (!wc26.standings || !wc26.standings.groups) {
    pills.innerHTML = '';
    return;
  }
  const keys = Object.keys(wc26.standings.groups).sort((a, b) => (a.length - b.length) || a.localeCompare(b));
  if (!wc26.activeGroup && keys.length > 0) wc26.activeGroup = keys[0];
  pills.innerHTML = keys.map(k =>
    `<button class="wc26-pill ${k === wc26.activeGroup ? 'active' : ''}" data-grp="${escapeHtml(k)}">Group ${escapeHtml(k)}</button>`
  ).join('');
  pills.querySelectorAll('[data-grp]').forEach(btn => {
    btn.addEventListener('click', () => {
      wc26.activeGroup = btn.dataset.grp;
      wc26RenderGroupPills();
      wc26RenderStandings(wc26.activeGroup);
    });
  });
}

function wc26OpenTeamModal(teamName, badge) {
  if (!wc26.data) return;
  const all = (wc26.data.upcoming || []).concat(wc26.data.recent || []);
  const teamMatches = all.filter(m => m.home_team === teamName || m.away_team === teamName)
    .sort((a, b) => (a.wib?.iso_wib || a.date || '').localeCompare(b.wib?.iso_wib || b.date || ''));
  const wins = teamMatches.filter(m => {
    if (m.home_score == null) return false;
    return m.home_team === teamName ? m.home_score > m.away_score : m.away_score > m.home_score;
  }).length;
  const draws = teamMatches.filter(m => m.home_score != null && m.home_score === m.away_score).length;
  const losses = teamMatches.filter(m => {
    if (m.home_score == null) return false;
    return m.home_team === teamName ? m.home_score < m.away_score : m.away_score < m.home_score;
  }).length;

  // Find which group (use any match)
  const sampleMatch = teamMatches[0] || {};
  const group = sampleMatch.group || '?';
  const isFav = wc26.isFav(teamName);

  // Set modal content
  document.getElementById('wc26-modal-name').textContent = teamName;
  document.getElementById('wc26-modal-sub').textContent =
    `Group ${group} • ${teamMatches.length} match • ${wins}W ${draws}D ${losses}L` +
    (isFav ? ' • ⭐ Favorit' : '');
  const badgeEl = document.getElementById('wc26-modal-badge');
  if (badge) { badgeEl.src = badge; badgeEl.style.display = ''; }
  else { badgeEl.style.display = 'none'; }

  // Find team's standing row
  let standingHtml = '<div class="wc26-empty">Belum ada match selesai di group ini.</div>';
  if (wc26.standings && wc26.standings.groups && wc26.standings.groups[group]) {
    const row = wc26.standings.groups[group].find(r => r.team === teamName);
    if (row) {
      const allInGroup = wc26.standings.groups[group];
      const pos = allInGroup.findIndex(r => r.team === teamName) + 1;
      standingHtml = `
        <div style="display:flex;align-items:center;gap:14px;padding:8px 0">
          <div style="font-size:1.6rem;font-weight:800;color:${pos <= 2 ? 'var(--accent)' : 'var(--fg2)'};width:32px">${pos}</div>
          <div style="flex:1">
            <div style="font-weight:700;font-size:0.95rem">${escapeHtml(teamName)}</div>
            <div style="color:var(--fg3);font-size:0.75rem">Group ${escapeHtml(group)}</div>
          </div>
          <div style="display:flex;gap:14px;text-align:center;font-size:0.8rem">
            <div><div style="color:var(--fg3);font-size:0.65rem;text-transform:uppercase">P</div><div style="font-weight:700">${row.played}</div></div>
            <div><div style="color:var(--fg3);font-size:0.65rem;text-transform:uppercase">W-D-L</div><div style="font-weight:700">${row.won}-${row.drawn}-${row.lost}</div></div>
            <div><div style="color:var(--fg3);font-size:0.65rem;text-transform:uppercase">GD</div><div style="font-weight:700;color:${row.gd > 0 ? 'var(--accent)' : row.gd < 0 ? 'var(--crit)' : 'var(--fg2)'}">${row.gd > 0 ? '+' : ''}${row.gd}</div></div>
            <div><div style="color:var(--fg3);font-size:0.65rem;text-transform:uppercase">Pts</div><div style="font-weight:800;color:var(--accent);font-size:1.1rem">${row.pts}</div></div>
          </div>
        </div>
      `;
    }
  }
  document.getElementById('wc26-modal-standing').innerHTML = standingHtml;

  // Match list
  const matchListEl = document.getElementById('wc26-modal-matches');
  if (teamMatches.length === 0) {
    matchListEl.innerHTML = '<div class="wc26-empty">Belum ada match.</div>';
  } else {
    matchListEl.innerHTML = teamMatches.map(m => wc26RenderMatch(m)).join('');
  }

  // Show modal
  const modal = document.getElementById('wc26-team-modal');
  modal.style.display = 'flex';
  // Add favorite toggle to header
  const subEl = document.getElementById('wc26-modal-sub');
  subEl.innerHTML = subEl.textContent + ` <button id="wc26-modal-fav" style="margin-left:8px;background:transparent;border:0;color:${isFav ? 'var(--warn)' : 'var(--fg3)'};cursor:pointer;font-size:0.85rem">${isFav ? '★' : '☆'}</button>`;
  document.getElementById('wc26-modal-fav').addEventListener('click', () => {
    wc26.toggleFav(teamName);
    wc26OpenTeamModal(teamName, badge); // re-render
    wc26RenderFavorites();
  });
}

function wc26CloseTeamModal() {
  document.getElementById('wc26-team-modal').style.display = 'none';
}

async function wc26Load() {
  try {
    const [data, standings] = await Promise.all([
      fetch('/api/worldcup').then(r => r.json()),
      fetch('/api/worldcup/standings').then(r => r.json()),
    ]);
    if (data.error) {
      document.getElementById('wc26-upcoming-list').innerHTML =
        `<div class="wc26-empty">⚠ ${escapeHtml(data.error)}</div>`;
      return;
    }
    wc26.data = data;
    wc26.standings = standings;
    wc26.renderAll();
  } catch (e) {
    document.getElementById('wc26-upcoming-list').innerHTML =
      `<div class="wc26-empty">⚠ Gagal load: ${escapeHtml(e.message)}</div>`;
  }
}

wc26.renderAll = function() {
  // Re-attach & re-render everything
  wc26RenderLive();
  wc26RenderFavorites();
  wc26RenderUpcoming();
  wc26RenderRecent();
  wc26UpdateRotator();
  wc26RenderGroupPills();
  wc26RenderStandings(wc26.activeGroup);
  // Footer
  const lu = wc26.data?.last_updated;
  document.getElementById('wc26-lastupdate').textContent =
    `Last update: ${lu ? new Date(lu).toLocaleString('id-ID') : '?'}`;
  // Apply settings to popover
  const pop = document.getElementById('wc26-popover');
  pop.style.opacity = (wc26.panelAlpha / 100).toString();
  pop.style.background = `rgba(19, 24, 38, ${(wc26.panelAlpha / 100).toFixed(2)})`;
  pop.classList.toggle('compact', wc26.compact);
  // Wire favorite buttons (event delegation re-attached on each render)
  document.querySelectorAll('.wc26-fav-btn').forEach(btn => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const team = btn.dataset.favTeam;
      const other = btn.dataset.favOther;
      // Toggle fav on whichever team is currently favorited, or the first one
      if (wc26.isFav(team)) wc26.toggleFav(team);
      else if (wc26.isFav(other)) wc26.toggleFav(other);
      else wc26.toggleFav(team);
      wc26.renderAll();
      toast(wc26.isFav(team) || wc26.isFav(other) ? '⭐ Ditambah ke favorites' : '☆ Dihapus dari favorites');
    };
  });
  // Wire team-name click in standings (no-op extra — already wired) and in match list (open team modal)
  document.querySelectorAll('#wc26-view-standings .wc26-standings button[data-team]').forEach(b => b.onclick = (e) => {
    e.preventDefault();
    wc26OpenTeamModal(b.dataset.team, b.dataset.badge);
  });
  document.querySelectorAll('.wc26-match .wc26-team-name').forEach(el => {
    el.onclick = (e) => {
      e.stopPropagation();
      const match = el.closest('.wc26-match');
      const team = el.closest('.wc26-team').classList.contains('home') ? match.dataset.home : match.dataset.away;
      const badgeSrc = el.parentElement.querySelector('img.wc26-badge')?.src || '';
      wc26OpenTeamModal(team, badgeSrc);
    };
  });
};

function wc26ApplySettings() {
  wc26.saveSettings();
  // Update form values
  document.getElementById('wc26-refresh-int').value = String(wc26.refreshInterval);
  document.getElementById('wc26-panel-alpha').value = String(wc26.panelAlpha);
  document.getElementById('wc26-panel-alpha-val').textContent = wc26.panelAlpha + '%';
  document.getElementById('wc26-card-alpha').value = String(wc26.cardAlpha);
  document.getElementById('wc26-card-alpha-val').textContent = wc26.cardAlpha + '%';
  document.getElementById('wc26-show-fav').checked = wc26.showFav;
  document.getElementById('wc26-compact').checked = wc26.compact;
}

function wc26StartAutoRefresh() {
  if (wc26.refreshTimer) clearInterval(wc26.refreshTimer);
  if (wc26.refreshInterval > 0) {
    wc26.refreshTimer = setInterval(() => wc26Load(), wc26.refreshInterval * 1000);
  }
}

function wc26StartRotator() {
  if (wc26.rotTimer) clearInterval(wc26.rotTimer);
  wc26.rotTimer = setInterval(() => {
    wc26.rotIdx++;
    wc26UpdateRotator();
  }, 5000);
}

async function loadWC26() {
  wc26.loadSettings();
  wc26.loadFavorites();
  wc26ApplySettings();
  await wc26Load();
  wc26StartAutoRefresh();
  wc26StartRotator();
  // Start minute tick for live matches
  if (window.__wc26MinTick) clearInterval(window.__wc26MinTick);
  window.__wc26MinTick = setInterval(() => {
    if (wc26.data && wc26.data.all_matches && wc26.data.all_matches.some(m => m.is_live)) {
      wc26RenderLive();
      wc26UpdateRotator();
    }
  }, 30000); // every 30s re-compute minute
}

// Wire sub-tab switching
document.querySelectorAll('.wc26-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.wc26tab;
    wc26.activeTab = tab;
    document.querySelectorAll('.wc26-tab').forEach(b => b.classList.toggle('active', b === btn));
    document.querySelectorAll('.wc26-view').forEach(v => v.classList.remove('active'));
    document.getElementById('wc26-view-' + tab).classList.add('active');
  });
});

// Wire header refresh button
document.getElementById('wc26-refresh').addEventListener('click', async () => {
  const btn = document.getElementById('wc26-refresh');
  btn.disabled = true;
  try {
    await fetch('/api/worldcup/refresh', {method:'POST'});
    toast('WC26 cache di-refresh ✓');
    await wc26Load();
  } catch (e) {
    toast('Refresh gagal: ' + e.message, true);
  } finally {
    btn.disabled = false;
  }
});

// Wire header settings button (jump to settings tab)
document.getElementById('wc26-settings').addEventListener('click', () => {
  document.querySelector('.wc26-tab[data-wc26tab="settings"]').click();
});

// Wire settings form
document.getElementById('wc26-refresh-int').addEventListener('change', e => {
  wc26.refreshInterval = parseInt(e.target.value);
  wc26.saveSettings();
  wc26StartAutoRefresh();
  toast('Auto-refresh: ' + (wc26.refreshInterval > 0 ? `setiap ${wc26.refreshInterval/60} menit` : 'off'));
});
document.getElementById('wc26-panel-alpha').addEventListener('input', e => {
  wc26.panelAlpha = parseInt(e.target.value);
  document.getElementById('wc26-panel-alpha-val').textContent = wc26.panelAlpha + '%';
  wc26.saveSettings();
  wc26.renderAll();
});
document.getElementById('wc26-card-alpha').addEventListener('input', e => {
  wc26.cardAlpha = parseInt(e.target.value);
  document.getElementById('wc26-card-alpha-val').textContent = wc26.cardAlpha + '%';
  wc26.saveSettings();
  wc26.renderAll();
});
document.getElementById('wc26-show-fav').addEventListener('change', e => {
  wc26.showFav = e.target.checked;
  wc26.saveSettings();
  wc26.renderAll();
});
document.getElementById('wc26-compact').addEventListener('change', e => {
  wc26.compact = e.target.checked;
  wc26.saveSettings();
  wc26.renderAll();
});

// Wire modal close
document.querySelectorAll('#wc26-team-modal [data-close]').forEach(el => {
  el.addEventListener('click', wc26CloseTeamModal);
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && document.getElementById('wc26-team-modal').style.display === 'flex') {
    wc26CloseTeamModal();
  }
});

// ============== TV (Live TV — flat list with liveness check) ==============
let tvChannels = [];   // flat list (all matching filter for current country)
let tvCurrent = null;
let tvHls = null;
let tvCountry = 'Indonesia';
let tvSearch = '';
let tvLiveness = {};   // map url -> {status, code}
let tvWorkingOnly = false;
// Per-country in-memory cache: { countryKey: { channels, liveness, ts } }
// Avoids re-fetching when user switches back to a previously viewed country.
const tvCache = new Map();
const TV_CACHE_TTL_MS = 5 * 60 * 1000;  // 5 minutes client-side cache
let tvCurrentETag = null;  // for If-None-Match on subsequent fetches
// Pagination
const TV_PAGE_SIZE = 36;   // cards visible per page
let tvVisibleCount = TV_PAGE_SIZE;

async function loadTV() {
  const meta = document.getElementById('tv-meta');
  const grid = document.getElementById('tv-grid');
  meta.textContent = 'Loading…';
  tvVisibleCount = TV_PAGE_SIZE;  // reset pagination on (re)load

  // Build cache key (country + search)
  const cacheKey = `${tvCountry}::${tvSearch}`;

  // 1) Check client-side cache first — instant render if hit
  const cached = tvCache.get(cacheKey);
  if (cached && (Date.now() - cached.ts) < TV_CACHE_TTL_MS) {
    tvChannels = cached.channels;
    tvLiveness = cached.liveness || {};
    tvCurrentETag = cached.etag || null;
    updateTVMeta(cached.meta, tvChannels.length);
    renderTVFlat();
    return;
  }

  // 2) Fetch from server (with ETag for 304 short-circuit on re-fetch)
  let lastErr = null;
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const params = new URLSearchParams();
      params.set('country', tvCountry);
      if (tvSearch) params.set('search', tvSearch);
      const url = '/api/tv/channels?' + params.toString();

      // Build headers with conditional ETag (saves bandwidth if server still has same data).
      // Only attach If-None-Match when we already have a cached response to fall back to.
      // Otherwise a 304 leaves us with no payload and we'd have to retry.
      const fetchHeaders = {};
      if (cached && cached.etag) {
        fetchHeaders['If-None-Match'] = cached.etag;
      }

      const resp = await fetch(url, {signal: AbortSignal.timeout(30000), headers: fetchHeaders});
      if (resp.status === 304 && cached) {
        // Server confirms data hasn't changed — refresh cache timestamp
        cached.ts = Date.now();
        tvChannels = cached.channels;
        tvLiveness = cached.liveness || {};
        updateTVMeta(cached.meta, tvChannels.length);
        renderTVFlat();
        return;
      }
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();
      if (data.error) throw new Error(data.error);

      tvChannels = data.channels || [];
      const m = data.meta || {};
      const etag = resp.headers.get('ETag');
      tvCurrentETag = etag || null;
      const total = data.total_filtered || 0;
      updateTVMeta(m, total);

      // Try to load cached liveness (silent fail)
      try {
        const livenessData = await fetch(`/api/tv/liveness?country=${encodeURIComponent(tvCountry)}`, {signal: AbortSignal.timeout(5000)}).then(r => r.json());
        if (livenessData.results) {
          tvLiveness = {};
          for (const r of livenessData.results) tvLiveness[r.url] = r;
        }
      } catch (e) { /* ignore liveness load failure */ }

      // Save to client cache for instant switch back
      tvCache.set(cacheKey, {
        channels: tvChannels,
        liveness: {...tvLiveness},
        meta: m,
        etag: etag,
        ts: Date.now(),
      });

      renderTVFlat();
      return; // success
    } catch (e) {
      lastErr = e;
      console.warn(`loadTV attempt ${attempt} failed:`, e.message);
      if (attempt < 2) await new Promise(r => setTimeout(r, 1000));
    }
  }
  // Both attempts failed
  grid.innerHTML = `<div class="empty">
    ⚠ Gagal load: ${escapeHtml(lastErr?.message || 'unknown')}<br>
    <button class="btn secondary small" onclick="loadTV()" style="margin-top:8px">🔄 Coba lagi</button>
  </div>`;
  meta.textContent = 'Error';
}

function updateTVMeta(m, total) {
  const meta = document.getElementById('tv-meta');
  const lu = m.last_refresh ? new Date(m.last_refresh).toLocaleString('id-ID') : '?';
  meta.textContent = `Last update: ${lu} • ${total} channels`;
  document.getElementById('tv-count').textContent = `(${tvChannels.length})`;
}

function updateLiveStatus() {
  const statusEl = document.getElementById('tv-live-status');
  const total = tvChannels.length;
  const working = tvChannels.filter(c => tvLiveness[c.url]?.status === 'working').length;
  const tested = Object.keys(tvLiveness).filter(u => tvChannels.find(c => c.url === u)).length;
  if (tested === 0) {
    statusEl.textContent = 'Belum di-test';
    statusEl.style.color = 'var(--fg3)';
  } else {
    statusEl.textContent = `✓ ${working}/${total} working (tested: ${tested})`;
    statusEl.style.color = working > 0 ? 'var(--accent)' : 'var(--fg3)';
  }
}

function renderTVFlat() {
  const grid = document.getElementById('tv-grid');
  let chans = tvChannels;
  if (tvWorkingOnly) {
    chans = chans.filter(c => tvLiveness[c.url]?.status === 'working');
  }
  if (chans.length === 0) {
    if (tvWorkingOnly && tvChannels.length > 0) {
      grid.innerHTML = '<div class="empty">Tidak ada channel yang work untuk negara ini. Klik "🔍 Test koneksi" untuk re-test. Coba matikan filter "hanya yang jalan".</div>';
    } else {
      grid.innerHTML = '<div class="empty">Tidak ada channel. Coba ganti negara atau kurangi filter search.</div>';
    }
    return;
  }

  // Pagination: show only first N cards, "Load more" reveals the rest
  // Keeps DOM small for fast first paint; user can progressively load more.
  const visible = chans.slice(0, tvVisibleCount);
  const hasMore = chans.length > visible.length;

  // Use DocumentFragment for fast batch insertion
  const frag = document.createDocumentFragment();
  const tmp = document.createElement('div');
  tmp.innerHTML = visible.map(c => renderTVCard(c)).join('');
  while (tmp.firstChild) frag.appendChild(tmp.firstChild);
  grid.innerHTML = '';
  grid.appendChild(frag);

  // Attach click handlers (single delegation, no per-card listener leak)
  grid.querySelectorAll('.tv-card').forEach(card => {
    card.addEventListener('click', () => {
      const ch = {
        name: card.dataset.name,
        url: card.dataset.url,
        proxied_url: card.dataset.proxied,
        group: card.dataset.group,
        country: card.dataset.country,
      };
      playChannel(ch);
    });
  });

  // Update meta with visible/total ratio if paginated
  const meta = document.getElementById('tv-count');
  if (hasMore || chans.length !== tvChannels.length) {
    meta.textContent = `(showing ${visible.length} of ${chans.length}${tvWorkingOnly ? ' working' : ''})`;
  } else {
    meta.textContent = `(${tvChannels.length})`;
  }

  // Append "Load more" button if there's more
  if (hasMore) {
    const moreWrap = document.createElement('div');
    moreWrap.className = 'tv-load-more-wrap';
    moreWrap.style.gridColumn = '1 / -1';
    moreWrap.style.textAlign = 'center';
    moreWrap.style.padding = '12px';
    const moreBtn = document.createElement('button');
    moreBtn.className = 'btn secondary small';
    moreBtn.textContent = `⬇ Load more (${chans.length - visible.length} remaining)`;
    moreBtn.onclick = () => {
      tvVisibleCount += TV_PAGE_SIZE;
      renderTVFlat();
    };
    moreWrap.appendChild(moreBtn);
    grid.appendChild(moreWrap);
  }

  updateLiveStatus();
}

function renderTVCard(c) {
  const initial = (c.name || '?').charAt(0).toUpperCase();
  const isActive = tvCurrent && tvCurrent.name === c.name;
  const lv = tvLiveness[c.url];
  const statusIcon = !lv ? '' :
    lv.status === 'working' ? '<span title="Working" style="color:var(--accent);font-size:0.7rem;position:absolute;top:2px;right:4px">✓</span>' :
    lv.status === 'geoblocked' ? '<span title="Geo-blocked (cuma bisa dari negara asal)" style="color:var(--warn);font-size:0.7rem;position:absolute;top:2px;right:4px">🌍</span>' :
    lv.status === 'dead' ? '<span title="Stream mati / expired" style="color:var(--crit);font-size:0.7rem;position:absolute;top:2px;right:4px">✗</span>' :
    lv.status === 'timeout' ? '<span title="Timeout / lambat" style="color:var(--warn);font-size:0.7rem;position:absolute;top:2px;right:4px">⏱</span>' :
    '';
  const cardStyle = !lv ? '' :
    lv.status === 'dead' ? 'opacity:0.4;filter:grayscale(0.5)' :
    lv.status === 'geoblocked' ? 'opacity:0.55' : '';
  // loading="lazy" defers below-the-fold image loading — big win when 100+ logos
  // decoding="async" prevents image decode from blocking render
  // fetchpriority="low" hints the browser logos aren't critical
  const logoHtml = c.logo
    ? `<img src="${escapeHtml(c.logo)}" alt="" loading="lazy" decoding="async" fetchpriority="low" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'"><span class="logo-fallback" style="display:none">${initial}</span>`
    : `<span class="logo-fallback">${initial}</span>`;
  return `
    <div class="tv-card ${isActive ? 'active' : ''}"
         style="position:relative;${cardStyle}"
         data-name="${escapeHtml(c.name)}"
         data-url="${escapeHtml(c.url)}"
         data-proxied="${escapeHtml(c.proxied_url || '')}"
         data-group="${escapeHtml(c.group || '')}"
         data-country="${escapeHtml(c.country || '')}"
         title="${escapeHtml(c.name)}${c.group ? ' • ' + escapeHtml(c.group) : ''}${lv ? ' • ' + lv.status : ''}">
      ${statusIcon}
      <div class="logo">${logoHtml}</div>
      <div class="name">${escapeHtml(c.name)}</div>
    </div>
  `;
}

function playChannel(ch) {
  if (!ch) return;
  const url = ch.proxied_url || ch.url;
  tvCurrent = {...ch, url};
  const playerEl = document.getElementById('tv-player');
  const infoEl = document.getElementById('tv-info');
  if (tvHls) { try { tvHls.destroy(); } catch (e) {} tvHls = null; }
  playerEl.innerHTML = '<video id="tv-video" controls autoplay playsinline></video>';
  const video = playerEl.querySelector('video');

  const isDash = url.toLowerCase().includes('.mpd');

  if (isDash) {
    playerEl.innerHTML = `<div class="empty" style="padding:40px 20px">
      <strong>${escapeHtml(ch.name)}</strong><br><br>
      Stream ini format DASH (.mpd), belum disupport di player ini.<br>
      <small style="color:var(--fg3)">Coba channel lain (yang .m3u8 biasanya jalan)</small>
    </div>`;
  } else if (window.Hls && window.Hls.isSupported()) {
    tvHls = new Hls({
      enableWorker: true,
      lowLatencyMode: false,
      maxBufferLength: 30,
      maxMaxBufferLength: 60,
    });
    tvHls.loadSource(url);
    tvHls.attachMedia(video);
    let errorCount = 0;
    tvHls.on(Hls.Events.ERROR, (e, data) => {
      console.warn('HLS error:', data.type, data.details, data);
      if (data.fatal) {
        errorCount++;
        if (errorCount > 3) {
          try { tvHls.destroy(); } catch (e) {}
          tvHls = null;
          playerEl.innerHTML = `<div class="empty" style="padding:40px 20px">
            <strong>${escapeHtml(ch.name)}</strong><br><br>
            ⚠ Stream error: ${escapeHtml(data.details || 'gagal load')}<br>
            <small style="color:var(--fg3)">Channel mungkin lagi off-air atau diblokir. Coba channel lain.</small>
          </div>`;
          toast(`Stream error: ${data.details || 'unknown'}`, true);
        }
      }
    });
    tvHls.on(Hls.Events.MANIFEST_PARSED, () => {
      video.play().catch(err => {
        console.warn('Autoplay blocked:', err);
        toast('Klik ▶ untuk play (autoplay diblok browser)', false);
      });
    });
  } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
    video.src = url;
    video.play().catch(err => console.warn('Autoplay blocked:', err));
  } else {
    video.src = url;
  }

  infoEl.style.display = 'block';
  document.getElementById('tv-name').textContent = ch.name;
  const meta2 = [ch.group, ch.country].filter(Boolean).join(' • ');
  document.getElementById('tv-meta2').textContent = meta2;

  document.querySelectorAll('.tv-card').forEach(c => c.classList.remove('active'));
  document.querySelectorAll(`.tv-card[data-name="${cssEscape(ch.name)}"]`).forEach(c => c.classList.add('active'));
  toast(`▶ ${ch.name}`);
}

function cssEscape(s) {
  if (window.CSS && CSS.escape) return CSS.escape(s);
  return String(s).replace(/[^\w-]/g, c => '\\' + c);
}

// Country + search handlers
// Restore last country from localStorage on first TV tab open
try {
  const savedCountry = localStorage.getItem('tvLastCountry');
  if (savedCountry) {
    const sel = document.getElementById('tv-country');
    // Only restore if the saved value is one of the available options
    if (sel && [...sel.options].some(o => o.value === savedCountry)) {
      tvCountry = savedCountry;
      sel.value = savedCountry;
    }
  }
} catch (e) { /* localStorage may be disabled */ }

document.getElementById('tv-country').addEventListener('change', (e) => {
  tvCountry = e.target.value;
  try { localStorage.setItem('tvLastCountry', tvCountry); } catch (e2) {}
  // Reset pagination so user sees the first page of new country
  tvVisibleCount = TV_PAGE_SIZE;
  loadTV();
});
let tvSearchTimer = null;
document.getElementById('tv-search').addEventListener('input', (e) => {
  tvSearch = e.target.value.trim();
  clearTimeout(tvSearchTimer);
  tvSearchTimer = setTimeout(() => loadTV(), 400);
});

document.getElementById('tv-refresh').addEventListener('click', async () => {
  const btn = document.getElementById('tv-refresh');
  btn.disabled = true;
  btn.textContent = '⏳ Refreshing…';
  try {
    await fetch('/api/tv/refresh', {method: 'POST'});
    toast('TV channel list di-refresh ✓');
    loadTV();
  } catch (e) {
    toast('Refresh gagal: ' + e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '🔄 Refresh list';
  }
});

// Test liveness (koneksi) untuk negara saat ini
document.getElementById('tv-test-live').addEventListener('click', async () => {
  const btn = document.getElementById('tv-test-live');
  const statusEl = document.getElementById('tv-live-status');
  btn.disabled = true;
  const origText = btn.textContent;
  btn.textContent = '⏳ Testing…';
  statusEl.textContent = 'Testing koneksi channel…';
  statusEl.style.color = 'var(--fg3)';
  try {
    const r = await fetch(`/api/tv/liveness/refresh?country=${encodeURIComponent(tvCountry)}`, {method: 'POST'}).then(r => r.json());
    if (r.ok && r.results) {
      tvLiveness = {};
      for (const x of r.results) tvLiveness[x.url] = x;
      updateLiveStatus();
      renderTVFlat();
      const working = r.results.filter(x => x.status === 'working').length;
      toast(`✓ ${working}/${r.results.length} channel working`);
    } else {
      toast('Test gagal: ' + (r.error || 'unknown'), true);
    }
  } catch (e) {
    toast('Test gagal: ' + e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = origText;
  }
});

// Toggle "Tampilkan hanya yang jalan"
document.getElementById('tv-working-only').addEventListener('change', (e) => {
  tvWorkingOnly = e.target.checked;
  tvVisibleCount = TV_PAGE_SIZE;  // reset pagination on filter change
  renderTVFlat();
});

// Restore dari URL hash (di akhir script, setelah semua variable di-init)
if (location.hash) {
  const t = location.hash.slice(1);
  const btn = document.querySelector(`.nav button[data-tab="${t}"]`);
  if (btn) btn.click();
}
</script>

</body>
</html>
"""

