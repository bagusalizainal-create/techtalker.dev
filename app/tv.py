"""Global TV channel list (M3U parser + cache).
Source: iptv-org index.m3u (semua negara)
Refresh: cron harian atau manual via endpoint.
"""
import base64
import json
import os
import re
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

CACHE_PATH = "/opt/app/tv_cache.json"
SOURCE_URL = "https://iptv-org.github.io/iptv/index.m3u"
CACHE_MAX_AGE = 86400  # 1 day
TIMEOUT = 60
USER_AGENT = "techtalkerid-tv/1.0"
# Path prefix for proxied URLs embedded in cache. Server uses same path.
PROXY_PATH = "/api/tv/proxy"


def _b64e(s: str) -> str:
    """Base64 url-safe encode (no padding) for proxy URL params."""
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii").rstrip("=")

# Common categories to expose prominently
COMMON_CATEGORIES = [
    "General", "News", "Sports", "Entertainment", "Movies",
    "Music", "Kids", "Religious", "Education", "Documentary",
    "Business", "Lifestyle", "Culture", "Series", "Comedy",
    "Animation", "Legislative",
]

# Country code → country name mapping (ISO 3166-1 alpha-2 to English name)
COUNTRY_CODE_TO_NAME = {
    "ID": "Indonesia", "US": "United States", "GB": "United Kingdom",
    "IN": "India", "CN": "China", "JP": "Japan", "KR": "Korea, Republic of",
    "BR": "Brazil", "DE": "Germany", "FR": "France", "ES": "Spain",
    "IT": "Italy", "MX": "Mexico", "CA": "Canada", "AU": "Australia",
    "TR": "Turkey", "SA": "Saudi Arabia", "EG": "Egypt", "RU": "Russia",
    "NL": "Netherlands", "MY": "Malaysia", "SG": "Singapore", "TH": "Thailand",
    "VN": "Vietnam", "PH": "Philippines", "PK": "Pakistan", "BD": "Bangladesh",
    "HK": "Hong Kong", "TW": "Taiwan", "AR": "Argentina", "CL": "Chile",
    "CO": "Colombia", "PE": "Peru", "VE": "Venezuela", "AT": "Austria",
    "BE": "Belgium", "CH": "Switzerland", "CZ": "Czech Republic", "DK": "Denmark",
    "FI": "Finland", "GR": "Greece", "HU": "Hungary", "IE": "Ireland",
    "IL": "Israel", "NG": "Nigeria", "NO": "Norway", "NZ": "New Zealand",
    "PL": "Poland", "PT": "Portugal", "RO": "Romania", "SE": "Sweden",
    "SK": "Slovakia", "TR": "Turkey", "UA": "Ukraine", "AE": "United Arab Emirates",
    "ZA": "South Africa", "SE": "Sweden", "NO": "Norway", "DK": "Denmark",
    "FI": "Finland", "GR": "Greece", "HR": "Croatia", "BG": "Bulgaria",
    "RS": "Serbia", "SI": "Slovenia", "SK": "Slovakia", "LT": "Lithuania",
    "LV": "Latvia", "EE": "Estonia", "IS": "Iceland", "LU": "Luxembourg",
    "MT": "Malta", "CY": "Cyprus", "BH": "Bahrain", "KW": "Kuwait",
    "OM": "Oman", "QA": "Qatar", "JO": "Jordan", "LB": "Lebanon",
    "IQ": "Iraq", "IR": "Iran", "SY": "Syria", "YE": "Yemen",
    "MA": "Morocco", "DZ": "Algeria", "TN": "Tunisia", "LY": "Libya",
    "SD": "Sudan", "ET": "Ethiopia", "KE": "Kenya", "TZ": "Tanzania",
    "UG": "Uganda", "GH": "Ghana", "NG": "Nigeria", "SN": "Senegal",
    "ZW": "Zimbabwe", "AO": "Angola", "MZ": "Mozambique", "ET": "Ethiopia",
    "PE": "Peru", "BO": "Bolivia", "EC": "Ecuador", "PY": "Paraguay",
    "UY": "Uruguay", "GY": "Guyana", "SR": "Suriname", "GF": "French Guiana",
    "FK": "Falkland Islands",
}

# Top countries untuk default quick switch
TOP_COUNTRIES = [
    "Indonesia", "Malaysia", "Singapore", "Thailand", "Philippines",
    "Vietnam", "Hong Kong", "Taiwan", "Japan", "Korea, Republic of",
    "China", "India", "United States", "United Kingdom", "Brazil",
    "Germany", "France", "Spain", "Italy", "Mexico",
    "Canada", "Australia", "Saudi Arabia", "Egypt", "Russia",
]


def fetch_m3u() -> str:
    """Fetch M3U playlist dari iptv-org."""
    req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", errors="ignore")


def parse_m3u(content: str) -> list[dict]:
    """Parse M3U jadi list of channel dicts."""
    channels: list[dict] = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith("#EXTINF"):
            i += 1
            continue
        extinf = line[len("#EXTINF:"):]
        comma = extinf.find(",")
        if comma == -1:
            i += 1
            continue
        attrs_str, name = extinf[:comma], extinf[comma+1:].strip()
        # Clean name
        name = re.sub(r"\s*\(\d+p\).*$", "", name)
        name = re.sub(r"\s*\[.*?\]\s*$", "", name).strip()
        # Skip corrupt
        if re.search(r'(like Gecko|Mozilla/|http-user-agent|group-title|,\s*\"$)', name):
            i += 1
            continue
        # Parse attrs
        tvg_id = ""
        logo = ""
        group = "General"
        country = ""
        lang = ""
        for m in re.finditer(r'(\w[\w-]*)="([^"]*)"', attrs_str):
            key, val = m.group(1), m.group(2)
            if key == "tvg-id":
                tvg_id = val
            elif key == "tvg-logo":
                logo = val
            elif key == "group-title":
                group = val
            elif key == "tvg-country":
                country = val
            elif key == "tvg-language":
                lang = val
        # Next non-EXTVLCOPT line is URL
        i += 1
        while i < len(lines) and lines[i].startswith("#EXTVLCOPT"):
            i += 1
        if i < len(lines):
            url = lines[i].strip()
            if url and not url.startswith("#"):
                # Resolve country code → full name
                country_resolved = ""
                if country:
                    country_resolved = country
                elif "." in tvg_id:
                    parts = tvg_id.split(".")
                    if len(parts) >= 2:
                        last = parts[-1]
                        if "@" in last:
                            cc = last.split("@")[0].upper()
                            country_resolved = COUNTRY_CODE_TO_NAME.get(cc, cc)
                channels.append({
                    "name": name,
                    "logo": logo,
                    "group": group,
                    "country": country_resolved,
                    "lang": lang,
                    "url": url,
                    "tvg_id": tvg_id,
                })
        i += 1
    return channels


def load_cache() -> dict | None:
    if not os.path.exists(CACHE_PATH):
        return None
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def save_cache(channels: list[dict]) -> None:
    """Build cache with pre-computed proxied_url and per-country index.

    Cache schema:
      {
        "_meta": { last_refresh, source, count, etag },
        "channels": [ {name, logo, group, country, lang, url, tvg_id, proxied_url}, ... ],
        "by_country": { country_name: [channel_indices], ... },  # O(1) country filter
        "stats": { by_country, by_category, top_countries, common_categories },
      }
    """
    by_country_count: dict[str, int] = defaultdict(int)
    by_category_count: dict[str, int] = defaultdict(int)
    by_country_idx: dict[str, list[int]] = defaultdict(list)

    for i, c in enumerate(channels):
        country = c.get("country", "") or "Unknown"
        category = c.get("group", "") or "Other"
        # Pre-compute proxied_url ONCE per refresh (was done on every API call before)
        c["proxied_url"] = f"{PROXY_PATH}?u={_b64e(c['url'])}"
        by_country_count[country] += 1
        by_category_count[category] += 1
        by_country_idx[country].append(i)

    last_refresh = datetime.now(timezone.utc).isoformat()
    etag = 'W/"tv-' + str(int(time.time())) + '"'

    data = {
        "_meta": {
            "last_refresh": last_refresh,
            "source": SOURCE_URL,
            "count": len(channels),
            "etag": etag,
        },
        "channels": channels,
        "by_country": dict(sorted(by_country_idx.items(), key=lambda x: -len(x[1]))),
        "stats": {
            "by_country": dict(sorted(by_country_count.items(), key=lambda x: -x[1])[:50]),
            "by_category": dict(sorted(by_category_count.items(), key=lambda x: -x[1])),
            "top_countries": TOP_COUNTRIES,
            "common_categories": COMMON_CATEGORIES,
        },
    }
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, CACHE_PATH)


def get_channels(force: bool = False) -> dict:
    """Get full channel list. Refresh if stale or force=True.

    On every load, ensure cache has the new schema fields (proxied_url,
    by_country, etag). If the cache is from an older version, backfill
    in-place so API responses are immediately optimized.
    """
    cache = load_cache()
    if cache and not force:
        meta = cache.get("_meta", {})
        last = meta.get("last_refresh")
        # Backfill new schema fields if missing (one-time migration)
        if last and "proxied_url" not in (cache.get("channels") or [{}])[0]:
            print("[tv] migrating cache to new schema (proxied_url + by_country)…")
            save_cache(cache.get("channels", []))
            cache = load_cache()
        if last and "by_country" not in cache:
            # Shouldn't happen after save_cache backfill, but be safe
            save_cache(cache.get("channels", []))
            cache = load_cache()
        if last:
            try:
                dt = datetime.fromisoformat(last)
                age = (datetime.now(timezone.utc) - dt).total_seconds()
                if age < CACHE_MAX_AGE:
                    return cache
            except Exception:
                pass
    try:
        content = fetch_m3u()
        channels = parse_m3u(content)
        save_cache(channels)
        return load_cache()
    except Exception as e:
        if cache:
            cache.setdefault("_meta", {})["error"] = f"refresh failed: {e}"
            return cache
        return {"_meta": {"error": str(e)}, "channels": [], "stats": {}, "by_country": {}}


def filter_channels(cached: dict, country: str = "", category: str = "", search: str = "") -> list[dict]:
    """Filter channels using pre-built by_country index for O(matches) lookup.

    Falls back to full scan for the (rare) case where the index is missing.
    """
    all_channels = cached.get("channels") or []
    by_country = cached.get("by_country") or {}

    # Country filter — use pre-built index when possible
    if country and by_country:
        cl = country.lower()
        if cl == "all":
            result = all_channels
        else:
            # Match either full name or 2-letter prefix (legacy compatibility)
            indices = by_country.get(country)
            if indices is None:
                # Case-insensitive scan of country keys
                indices = []
                for k, v in by_country.items():
                    if k.lower() == cl or k.lower().startswith(cl[:2]):
                        indices.extend(v)
            if not indices:
                return []
            result = [all_channels[i] for i in indices]
    else:
        result = all_channels

    if category:
        cat = category.lower()
        result = [c for c in result if cat in (c.get("group") or "").lower()]
    if search:
        sl = search.lower()
        result = [c for c in result if sl in (c.get("name") or "").lower() or sl in (c.get("group") or "").lower()]
    return result


def group_by_category(channels: list[dict]) -> dict[str, list[dict]]:
    """Group channels by category, sorted alphabetically inside each group."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in channels:
        cat = c.get("group") or "Other"
        groups[cat].append(c)
    # Sort each group by name
    for cat in groups:
        groups[cat].sort(key=lambda x: (x.get("name") or "").lower())
    # Return ordered by count desc
    return dict(sorted(groups.items(), key=lambda x: -len(x[1])))


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--status", action="store_true")
    args = p.parse_args()
    if args.refresh:
        print("Refreshing global TV channels…")
        t0 = time.time()
        d = get_channels(force=True)
        m = d.get("_meta", {})
        s = d.get("stats", {})
        print(f"Done in {time.time()-t0:.1f}s — {m.get('count', 0)} channels")
        print(f"  Countries: {len(s.get('by_country', {}))}")
        print(f"  Categories: {len(s.get('by_category', {}))}")
    elif args.status:
        d = load_cache() or {}
        m = d.get("_meta", {})
        s = d.get("stats", {})
        print(f"Channels: {m.get('count', 0)} • Last: {m.get('last_refresh', 'never')}")
        print(f"  Top countries: {list(s.get('by_country', {}).items())[:5]}")
        print(f"  Top categories: {list(s.get('by_category', {}).items())[:5]}")
    else:
        d = get_channels()
        print(f"Loaded {len(d.get('channels', []))} channels")
