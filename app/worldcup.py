"""FIFA World Cup data fetcher & cache.
Primary: ESPN API (reliable, no API key, real-time scores)
Fallback: TheSportsDB (jika ESPN gagal)

Cache: /opt/app/worldcup_cache.json
"""
import json
import os
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

CACHE_PATH = "/opt/app/worldcup_cache.json"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world"
TSDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"
TIMEOUT = 20
USER_AGENT = "techtalkerid-worldcup/3.0"

LEAGUE_ID = "4429"
LEAGUE_NAME = "FIFA World Cup"
LEAGUE_SEASON = "2026"

# World Cup season: Jun 11 - Jul 19, 2026
SEASON_START = datetime(2026, 6, 11, tzinfo=timezone.utc)
SEASON_END = datetime(2026, 7, 19, tzinfo=timezone.utc)

# Indonesia timezone
WIB = timezone(timedelta(hours=7))
DAY_NAMES_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
MONTH_NAMES_ID = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]
DAY_NAMES_ID_SHORT = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
MONTH_NAMES_ID_SHORT = [
    "", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
    "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
]

FT_STATUSES = {"STATUS_FINAL", "STATUS_FULL_TIME", "STATUS_AET", "STATUS_PEN"}
LIVE_STATUSES = {"STATUS_IN_PROGRESS", "STATUS_HALFTIME", "STATUS_FIRST_HALF",
                 "STATUS_SECOND_HALF", "STATUS_END_PERIOD", "STATUS_OVERTIME"}
NS_STATUSES = {"STATUS_SCHEDULED", "STATUS_PRE", "STATUS_POSTPONED"}


def fetch(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  [WARN] fetch failed {url[:60]}: {e}")
        return None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_wib(date_str: str, time_utc_str: str) -> dict | None:
    if not date_str or not time_utc_str:
        return None
    try:
        dt_utc = datetime.fromisoformat(f"{date_str}T{time_utc_str}:00+00:00")
        dt_wib = dt_utc.astimezone(WIB)
        wd = dt_wib.weekday()
        return {
            "time_wib": dt_wib.strftime("%H:%M"),
            "date_wib": dt_wib.strftime("%Y-%m-%d"),
            "day_name": DAY_NAMES_ID[wd],
            "day_short": DAY_NAMES_ID_SHORT[wd],
            "month_name": MONTH_NAMES_ID[dt_wib.month],
            "month_short": MONTH_NAMES_ID_SHORT[dt_wib.month],
            "date_long": f"{DAY_NAMES_ID[wd]}, {dt_wib.day} {MONTH_NAMES_ID[dt_wib.month]} {dt_wib.year}",
            "date_short": f"{dt_wib.day} {MONTH_NAMES_ID_SHORT[dt_wib.month]} {dt_wib.year}",
            "iso_wib": dt_wib.isoformat(),
        }
    except Exception:
        return None


def parse_event_dt(ev: dict) -> datetime | None:
    if not ev.get("date") or not ev.get("time_utc"):
        return None
    try:
        return datetime.fromisoformat(f"{ev['date']}T{ev['time_utc']}:00+00:00")
    except Exception:
        return None


def enrich_with_countdown(ev: dict) -> dict:
    ev = dict(ev)
    dt = parse_event_dt(ev)
    if not dt:
        ev["countdown"] = None
        ev["is_live"] = ev.get("status") in LIVE_STATUSES
        return ev
    if ev.get("home_score") is not None or ev.get("status") in FT_STATUSES:
        ev["countdown"] = None
        ev["is_live"] = False
        ev["finished_at"] = dt.isoformat()
        return ev
    delta = dt - now_utc()
    secs = int(delta.total_seconds())
    if secs > 0:
        days = secs // 86400
        hours = (secs % 86400) // 3600
        minutes = (secs % 3600) // 60
        seconds = secs % 60
        ev["countdown"] = {
            "total_seconds": secs, "days": days, "hours": hours,
            "minutes": minutes, "seconds": seconds,
            "kick_off_utc": dt.isoformat(),
        }
        ev["is_live"] = False
    else:
        ev["countdown"] = {"total_seconds": secs, "kick_off_utc": dt.isoformat()}
        ev["is_live"] = ev.get("status") in LIVE_STATUSES or True
    return ev


def normalize_espn_event(e: dict) -> dict | None:
    """Parse ESPN event format ke format internal kita."""
    try:
        comp = e.get("competitions", [{}])[0]
        if not comp:
            return None
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            return None
        home_c = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away_c = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
        home_team = home_c.get("team", {}).get("displayName") or home_c.get("team", {}).get("name", "?")
        away_team = away_c.get("team", {}).get("displayName") or away_c.get("team", {}).get("name", "?")
        # Score
        home_score = home_c.get("score")
        away_score = away_c.get("score")
        try:
            home_score = int(home_score) if home_score is not None and home_score != "" else None
        except (ValueError, TypeError):
            home_score = None
        try:
            away_score = int(away_score) if away_score is not None and away_score != "" else None
        except (ValueError, TypeError):
            away_score = None

        # Status
        status_type = comp.get("status", {}).get("type", {})
        status_code = status_type.get("name", "STATUS_SCHEDULED")
        if status_code in FT_STATUSES:
            status = "FT"
        elif status_code in LIVE_STATUSES:
            status = status_code
        elif status_code in NS_STATUSES:
            status = "NS"
        else:
            # Fallback: kalau ada score, treat as finished
            if home_score is not None and away_score is not None:
                status = "FT"
            else:
                status = "NS"

        # Date/time
        date_str = e.get("date", "")[:10]  # YYYY-MM-DD
        time_utc = e.get("date", "")[11:16] if e.get("date") else ""

        # Group (extract from altGameNote: "FIFA World Cup, Group D")
        group = ""
        alt = comp.get("altGameNote", "")
        if "Group" in alt:
            # Parse "FIFA World Cup, Group D" → "D"
            m = re.search(r"Group\s+([A-Z])", alt)
            if m:
                group = m.group(1)
        if not group:
            # Try competition notes
            for note in comp.get("notes", []):
                if isinstance(note, dict) and "group" in note.get("type", "").lower():
                    g = note.get("headline", "").replace("Group ", "").strip()
                    if g:
                        group = g
                        break
        if not group:
            # Last fallback: from season slug or round
            season = comp.get("season", {}) or comp.get("season", {})
            slug = season.get("slug", "")
            if slug and slug != "group-stage":
                group = slug
            if not group:
                # Round
                round_num = comp.get("round", {}).get("displayValue", "1")
                group = f"R{round_num}" if round_num else "?"
        if not group:
            group = "?"

        # Venue
        venue = comp.get("venue", {}).get("fullName", "")
        city = comp.get("venue", {}).get("address", {}).get("city", "")
        country = comp.get("venue", {}).get("address", {}).get("country", "")

        # Team badges (ESPN country flag logos: lowercase abbr in /countries/ path)
        home_badge = (home_c.get("team", {}).get("logos") or [{}])[0].get("href", "")
        away_badge = (away_c.get("team", {}).get("logos") or [{}])[0].get("href", "")
        # Fallback: ESPN's country flag logo URL pattern (verified working)
        home_abbr = (home_c.get("team", {}).get("abbreviation") or "").lower()
        away_abbr = (away_c.get("team", {}).get("abbreviation") or "").lower()
        if not home_badge and home_abbr:
            home_badge = f"https://a.espncdn.com/i/teamlogos/countries/500/{home_abbr}.png"
        if not away_badge and away_abbr:
            away_badge = f"https://a.espncdn.com/i/teamlogos/countries/500/{away_abbr}.png"

        # Round
        round_num = comp.get("round", {}).get("displayValue", "1")
        try:
            round_int = int(round_num)
        except (ValueError, TypeError):
            round_int = 1

        result = {
            "id": e.get("id") or f"espn-{date_str}-{home_team}-{away_team}",
            "date": date_str,
            "time_utc": time_utc,
            "time_local": "",
            "home_team": home_team,
            "away_team": away_team,
            "home_score": home_score,
            "away_score": away_score,
            "home_badge": home_badge,
            "away_badge": away_badge,
            "round": round_int,
            "group": group,
            "venue": venue,
            "city": city,
            "country": country,
            "status": status,
            "raw_status": status_code,
            "source": "espn",
        }
        wib = to_wib(date_str, time_utc)
        if wib:
            result["wib"] = wib
        return result
    except Exception as e:
        print(f"  [WARN] parse espn event failed: {e}")
        return None


def fetch_espn_all() -> list[dict]:
    """Fetch semua World Cup events dari ESPN (loop per hari)."""
    all_events: dict[str, dict] = {}
    current = SEASON_START
    today = now_utc()
    end = min(SEASON_END, today + timedelta(days=2))  # include 2 days ahead

    day_count = (end - SEASON_START).days + 1
    print(f"  ESPN: fetching {day_count} days…", flush=True)

    while current <= end:
        date_str = current.strftime("%Y%m%d")
        url = f"{ESPN_BASE}/scoreboard?dates={date_str}"
        data = fetch(url)
        if data and "events" in data:
            for e in data["events"]:
                ev = normalize_espn_event(e)
                if ev and ev.get("home_team") and ev.get("away_team"):
                    all_events[ev["id"]] = ev
        current += timedelta(days=1)
        # Don't hammer ESPN
        if day_count > 7:
            time.sleep(0.1)
    return list(all_events.values())


def fetch_tsdb_season() -> list[dict]:
    """Fallback: TheSportsDB season events."""
    data = fetch(f"{TSDB_BASE}/eventsseason.php?id={LEAGUE_ID}&s={LEAGUE_SEASON}")
    if not data or "events" not in data:
        return []
    events = data["events"]
    print(f"  TSDB: {len(events)} events")
    out: list[dict] = []
    for e in events:
        # Quick normalize (without detail fetch)
        date = e.get("dateEvent", "")
        time_utc = (e.get("strTime") or "")[:5]
        status_raw = e.get("strStatus", "NS")
        home_score = e.get("intHomeScore")
        away_score = e.get("intAwayScore")
        if home_score in (None, "", "null"): home_score = None
        else:
            try: home_score = int(home_score)
            except: home_score = None
        if away_score in (None, "", "null"): away_score = None
        else:
            try: away_score = int(away_score)
            except: away_score = None
        # If score is present (both sides), force FT status even if TSDB says NS
        if home_score is not None and away_score is not None:
            status = "FT"
        elif status_raw in FT_STATUSES:
            status = "FT"
        elif status_raw in LIVE_STATUSES:
            status = status_raw
        else:
            status = "NS"
        # Normalize team names for dedup matching
        home_team = (e.get("strHomeTeam") or "?").replace("Czech Republic", "Czechia").replace("Türkiye", "Türkiye")
        away_team = (e.get("strAwayTeam") or "?").replace("Czech Republic", "Czechia").replace("Türkiye", "Türkiye")
        result = {
            "id": e.get("idEvent"),
            "date": date,
            "time_utc": time_utc,
            "time_local": "",
            "home_team": home_team,
            "away_team": away_team,
            "home_score": home_score,
            "away_score": away_score,
            "home_badge": None, "away_badge": None,
            "round": 1, "group": "?", "venue": "", "city": "", "country": "",
            "status": status, "raw_status": status_raw,
            "source": "tsdb",
        }
        wib = to_wib(date, time_utc)
        if wib: result["wib"] = wib
        out.append(result)
    return out


def refresh() -> dict:
    """Refresh World Cup cache. Primary: ESPN. Fallback: TSDB."""
    print("  Fetching from ESPN (primary)…", flush=True)
    espn_events = fetch_espn_all()
    print(f"  ESPN total: {len(espn_events)} events")

    # Optionally supplement with TSDB for any events ESPN missed
    print("  Fetching from TheSportsDB (supplement)…", flush=True)
    tsdb_events = fetch_tsdb_season()
    print(f"  TSDB total: {len(tsdb_events)} events")

    # Merge: ESPN wins (more reliable, has real-time scores)
    # Dedup key: (date, normalized home_team, normalized away_team)
    def norm_name(n: str) -> str:
        return (n or "").lower().replace("ı", "i").replace("ć", "c").strip()

    def dedup_key(e: dict) -> str:
        return f"{e.get('date','')}|{norm_name(e.get('home_team',''))}|{norm_name(e.get('away_team',''))}"

    merged: dict[str, dict] = {}
    for e in espn_events:
        merged[dedup_key(e)] = e
    for e in tsdb_events:
        if dedup_key(e) not in merged:
            merged[dedup_key(e)] = e

    all_events = list(merged.values())
    if not all_events:
        return {"error": "no events", "refreshed_at": now_utc().isoformat()}

    # Sort by date+time
    all_events.sort(key=lambda e: (e.get("date", ""), e.get("time_utc", "")))

    # Pisahkan past (FT) dan upcoming
    past = [e for e in all_events if e.get("status") == "FT"]
    past.sort(key=lambda e: (e.get("date", ""), e.get("time_utc", "")), reverse=True)
    not_finished = [e for e in all_events if e.get("status") != "FT"]
    not_finished.sort(key=lambda e: (e.get("date", ""), e.get("time_utc", "")))
    upcoming = [enrich_with_countdown(e) for e in not_finished]

    # Group stats
    groups: dict[str, int] = {}
    for e in all_events:
        g = e.get("group") or "?"
        groups[g] = groups.get(g, 0) + 1

    # Source breakdown
    sources = {}
    for e in all_events:
        s = e.get("source", "?")
        sources[s] = sources.get(s, 0) + 1

    cache = {
        "_meta": {
            "last_refresh": now_utc().isoformat(),
            "version": "4.0",
            "season": LEAGUE_SEASON,
            "total_events": len(all_events),
            "sources": sources,
        },
        "world_cup": {
            "name": LEAGUE_NAME,
            "season": LEAGUE_SEASON,
            "league_id": LEAGUE_ID,
            "last_updated": now_utc().isoformat(),
            "all_matches": all_events,
            "upcoming": upcoming,
            "recent": past,
            "stats": {
                "total": len(all_events),
                "finished": len(past),
                "scheduled_or_live": len(not_finished),
                "groups": groups,
                "sources": sources,
            },
        },
    }
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CACHE_PATH)
    return {
        "refreshed_at": cache["_meta"]["last_refresh"],
        "total": len(all_events),
        "finished": len(past),
        "upcoming": len(upcoming),
        "sources": sources,
    }


def status() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {"exists": False, "path": CACHE_PATH}
    try:
        with open(CACHE_PATH) as f:
            data = json.load(f)
        wc = data.get("world_cup", {})
        meta = data.get("_meta", {})
        return {
            "exists": True,
            "path": CACHE_PATH,
            "last_refresh": meta.get("last_refresh"),
            "total": wc.get("stats", {}).get("total"),
            "finished": wc.get("stats", {}).get("finished"),
            "scheduled_or_live": wc.get("stats", {}).get("scheduled_or_live"),
            "sources": meta.get("sources", {}),
        }
    except Exception as e:
        return {"exists": True, "error": str(e)}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--status", action="store_true")
    args = p.parse_args()
    if args.refresh:
        print("Refreshing World Cup cache (ESPN + TSDB)…")
        t0 = time.time()
        s = refresh()
        print(f"Done in {time.time()-t0:.1f}s — {s}")
    elif args.status:
        print(json.dumps(status(), indent=2))
    else:
        print(json.dumps(status(), indent=2))
