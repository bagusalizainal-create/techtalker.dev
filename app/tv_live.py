"""Channel liveness checker.
Test setiap channel URL via HEAD/short GET request, return status.
Status: working | dead | geoblocked | timeout | unknown
"""
import json
import os
import re
import time
import urllib.request
import urllib.error
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

CACHE_PATH = "/opt/app/tv_cache.json"
RESULTS_PATH = "/opt/app/tv_liveness.json"
TIMEOUT = 8
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def check_one(url: str) -> dict:
    """Test satu URL. Return {url, status, detail}."""
    # Try HEAD first (cheap)
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            code = r.getcode()
            if 200 <= code < 400:
                return {"url": url, "status": "working", "code": code}
            elif code in (401, 403):
                return {"url": url, "status": "geoblocked", "code": code}
            elif code in (404, 410):
                return {"url": url, "status": "dead", "code": code}
            else:
                return {"url": url, "status": "unknown", "code": code}
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {"url": url, "status": "geoblocked", "code": e.code}
        elif e.code in (404, 410):
            return {"url": url, "status": "dead", "code": e.code}
        else:
            return {"url": url, "status": "unknown", "code": e.code}
    except Exception as e:
        # Try GET (some servers don't support HEAD)
        try:
            req = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                code = r.getcode()
                if 200 <= code < 400:
                    return {"url": url, "status": "working", "code": code}
                elif code in (401, 403):
                    return {"url": url, "status": "geoblocked", "code": code}
                elif code in (404, 410):
                    return {"url": url, "status": "dead", "code": code}
                return {"url": url, "status": "unknown", "code": code}
        except urllib.error.HTTPError as e2:
            if e2.code in (401, 403):
                return {"url": url, "status": "geoblocked", "code": e2.code}
            elif e2.code in (404, 410):
                return {"url": url, "status": "dead", "code": e2.code}
            return {"url": url, "status": "unknown", "code": e2.code}
        except Exception as e2:
            return {"url": url, "status": "timeout", "error": str(e2)[:100]}


def check_batch(urls: list[str], max_workers: int = 6) -> list[dict]:
    """Test banyak URL paralel. Return list of {url, status, code}."""
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(check_one, u): u for u in urls}
        for fut in as_completed(futures):
            try:
                r = fut.result()
                results.append(r)
            except Exception as e:
                results.append({"url": futures[fut], "status": "error", "error": str(e)[:100]})
    return results


def save_liveness(results: list[dict]) -> None:
    """Save liveness results to disk."""
    data = {
        "_meta": {
            "last_check": datetime.now(timezone.utc).isoformat(),
            "count": len(results),
        },
        "results": {r["url"]: r for r in results},
    }
    tmp = RESULTS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, RESULTS_PATH)


def load_liveness() -> dict:
    if not os.path.exists(RESULTS_PATH):
        return {}
    try:
        with open(RESULTS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def check_country(country: str, force: bool = False) -> dict:
    """Test semua channel untuk country tertentu. Returns liveness results."""
    if not os.path.exists(CACHE_PATH):
        return {"error": "no cache"}
    with open(CACHE_PATH) as f:
        cache = json.load(f)
    channels = cache.get("channels", [])
    urls = list({c["url"] for c in channels if (c.get("country") or "").lower() == country.lower()})
    if not urls:
        return {"error": f"no channels for {country}"}

    # Check if we have recent results (kecuali force)
    existing = load_liveness()
    if existing and not force:
        meta = existing.get("_meta", {})
        last = meta.get("last_check")
        if last:
            try:
                dt = datetime.fromisoformat(last)
                age = (datetime.now(timezone.utc) - dt).total_seconds()
                if age < 1800:  # 30 min cache
                    # Filter existing results for this country's URLs
                    cached_results = existing.get("results", {})
                    out = [cached_results[u] for u in urls if u in cached_results]
                    if len(out) == len(urls):
                        return {"country": country, "results": out, "cached": True, "age_seconds": int(age)}
            except Exception:
                pass

    # Test fresh
    results = check_batch(urls)
    save_liveness(results)
    return {"country": country, "results": results, "cached": False}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--country", default="Malaysia")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    print(f"Testing channels for {args.country}…")
    t0 = time.time()
    r = check_country(args.country, force=args.force)
    if "error" in r:
        print(f"Error: {r['error']}")
    else:
        # Summary
        s = {}
        for x in r["results"]:
            s[x["status"]] = s.get(x["status"], 0) + 1
        print(f"Done in {time.time()-t0:.1f}s — {sum(s.values())} channels")
        for st, n in sorted(s.items()):
            print(f"  {st}: {n}")
        # Detail working
        working = [x for x in r["results"] if x["status"] == "working"]
        print(f"\nWorking channels:")
        for w in working:
            print(f"  ✓ {w['url'][:80]}")
