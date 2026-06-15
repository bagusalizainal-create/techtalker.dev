"""Football data fetcher & cache for TheSportsDB API.

Mendukung multi-kompetisi (World Cup, Liga 1 Indonesia, Premier League, dll).
Data di-cache ke JSON file, di-refresh via cron tiap 6 jam.

Usage:
  python football.py --refresh   # refresh cache dari API
  python football.py --status    # cek status cache

Cache structure:
  football_cache.json = {
    "world_cup": {
      "last_updated": "...",
      "upcoming": [...],
      "recent": [...],
    },
    ...
  }
"""
import json
import os
import time
import urllib.request
import urllib.error
import argparse
from datetime import datetime, timezone

CACHE_PATH = os.environ.get(
    "FOOTBALL_CACHE", "/opt/app/football_cache.json"
)
API_BASE = "https://www.thesportsdb.com/api/v1/json/3"
USER_AGENT = "techtalkerid-portal/1.0"
TIMEOUT = 15  # seconds

# Kompetisi yang di-track. ID dari TheSportsDB.
# Cek https://www.thesportsdb.com/api/v1/json/3/all_leagues.php untuk lengkap
COMPETITIONS = {
    "world_cup": {
        "id": "4429",
        "name": "FIFA World Cup",
        "country": "International",
        "emoji": "🏆",
    },
    "u17_world_cup": {
        "id": "4903",
        "name": "FIFA U-17 World Cup",
        "country": "International",
        "emoji": "🌱",
    },
    # Liga 1 Indonesia ID: 4666 (cek API), Premier League 4328
    "premier_league": {
        "id": "4328",
        "name": "Premier League",
        "country": "England",
        "emoji": "🏴",
    },
    "la_liga": {
        "id": "4335",
        "name": "La Liga",
        "country": "Spain",
        "emoji": "🇪🇸",
    },
    "serie_a": {
        "id": "4332",
        "name": "Serie A",
        "country": "Italy",
        "emoji": "🇮🇹",
    },
    "bundesliga": {
        "id": "4331",
        "name": "Bundesliga",
        "country": "Germany",
        "emoji": "🇩🇪",
    },
    "ligue_1": {
        "id": "4334",
        "name": "Ligue 1",
        "country": "France",
        "emoji": "🇫🇷",
    },
    "champions_league": {
        "id": "4480",
        "name": "UEFA Champions League",
        "country": "Europe",
        "emoji": "⭐",
    },
}


def fetch(url: str) -> dict | None:
    """GET request ke API, return parsed JSON atau None kalau gagal."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  [WARN] fetch failed {url}: {e}")
        return None


def fetch_competition(league_id: str, kind: str) -> list[dict]:
    """Fetch upcoming atau past events untuk satu liga.
    kind: 'upcoming' atau 'past'.
    """
    endpoint = "eventsnextleague" if kind == "upcoming" else "eventspastleague"
    url = f"{API_BASE}/{endpoint}.php?id={league_id}"
    data = fetch(url)
    if not data or "events" not in data or not data["events"]:
        return []
    return [normalize_event(e) for e in data["events"]]


def normalize_event(e: dict) -> dict:
    """Normalize event ke field-field penting aja."""
    home_score = e.get("intHomeScore")
    away_score = e.get("intAwayScore")
    timestamp = e.get("strTimestamp") or ""
    if timestamp and "T" in timestamp:
        date = timestamp.split("T")[0]
        time_ = timestamp.split("T")[1][:5]
    else:
        date = e.get("dateEvent", "")
        time_ = e.get("strTime", "")[:5]
    return {
        "id": e.get("idEvent"),
        "date": date,
        "time": time_,
        "home_team": e.get("strHomeTeam", "?"),
        "away_team": e.get("strAwayTeam", "?"),
        "home_score": int(home_score) if home_score not in (None, "", "null") else None,
        "away_score": int(away_score) if away_score not in (None, "", "null") else None,
        "round": e.get("intRound"),
        "venue": e.get("strVenue"),
        "league": e.get("strLeague"),
        "season": e.get("strSeason"),
        "status": (
            "finished" if (home_score not in (None, "", "null")
                            and away_score not in (None, "", "null"))
            else "scheduled"
        ),
        "thumb": e.get("strThumb"),
    }


def get_status() -> dict:
    """Return status cache: kapan terakhir update, per kompetisi."""
    if not os.path.exists(CACHE_PATH):
        return {"exists": False, "path": CACHE_PATH}
    try:
        with open(CACHE_PATH) as f:
            data = json.load(f)
        return {
            "exists": True,
            "path": CACHE_PATH,
            "last_refresh": data.get("_meta", {}).get("last_refresh"),
            "competitions": {
                k: {
                    "name": v.get("name"),
                    "last_updated": v.get("last_updated"),
                    "upcoming_count": len(v.get("upcoming", [])),
                    "recent_count": len(v.get("recent", [])),
                }
                for k, v in data.items() if k != "_meta"
            },
        }
    except Exception as e:
        return {"exists": True, "error": str(e)}


def refresh_all(competitions: list[str] | None = None) -> dict:
    """Refresh cache untuk kompetisi tertentu (default: semua).
    Returns ringkasan hasil.
    """
    if competitions is None:
        competitions = list(COMPETITIONS.keys())

    # Load existing cache (kalau ada) untuk merge
    cache = {}
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH) as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    now = datetime.now(timezone.utc).isoformat()
    cache["_meta"] = {"last_refresh": now, "version": "1.0"}

    summary = {"refreshed": [], "failed": [], "total_upcoming": 0, "total_recent": 0}

    for key in competitions:
        comp = COMPETITIONS.get(key)
        if not comp:
            summary["failed"].append({"key": key, "reason": "unknown competition"})
            continue
        print(f"  → {comp['name']} (id={comp['id']})…", end="", flush=True)
        upcoming = fetch_competition(comp["id"], "upcoming")
        recent = fetch_competition(comp["id"], "past")
        # Sort
        upcoming.sort(key=lambda x: (x.get("date") or "9999", x.get("time") or ""))
        recent.sort(key=lambda x: (x.get("date") or "0000", x.get("time") or ""), reverse=True)
        recent = recent[:5]  # simpan cuma 5 terakhir

        cache[key] = {
            "name": comp["name"],
            "country": comp["country"],
            "emoji": comp["emoji"],
            "id": comp["id"],
            "last_updated": now,
            "upcoming": upcoming[:8],  # batasi 8 jadwal berikutnya
            "recent": recent,
        }
        if upcoming or recent:
            print(f" ✓ {len(upcoming)} upcoming, {len(recent)} recent")
            summary["refreshed"].append(key)
            summary["total_upcoming"] += len(upcoming)
            summary["total_recent"] += len(recent)
        else:
            print(f" ⚠ no data (kompetisi mungkin lagi off-season)")

    # Tulis ke file atomically
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CACHE_PATH)
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true", help="Refresh cache dari API")
    p.add_argument("--status", action="store_true", help="Tampilkan status cache")
    p.add_argument("--competitions", nargs="*", help="Limit kompetisi (default: semua)")
    p.add_argument("--list", action="store_true", help="List kompetisi yang tersedia")
    args = p.parse_args()

    if args.list:
        print("Kompetisi yang tersedia:")
        for k, v in COMPETITIONS.items():
            print(f"  {k:20s} {v['emoji']} {v['name']} ({v['country']}, id={v['id']})")
        return

    if args.status:
        s = get_status()
        print(json.dumps(s, indent=2, ensure_ascii=False))
        return

    if args.refresh:
        print(f"Refreshing football cache → {CACHE_PATH}")
        print(f"Started at: {datetime.now(timezone.utc).isoformat()}\n")
        t0 = time.time()
        s = refresh_all(args.competitions)
        elapsed = time.time() - t0
        print(f"\nDone in {elapsed:.1f}s")
        print(f"  Refreshed: {len(s['refreshed'])} kompetisi")
        print(f"  Failed:    {len(s['failed'])}")
        print(f"  Total upcoming: {s['total_upcoming']}")
        print(f"  Total recent:   {s['total_recent']}")
        print(f"  Last refresh:  {s.get('refreshed_at', 'now')}")
        return

    # Default: status
    s = get_status()
    print(json.dumps(s, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
