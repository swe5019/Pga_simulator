#!/usr/bin/env python3
"""
probe_props.py — find the full-slate Underdog endpoint, and dump its shape.

WRITES NOTHING.

Where this got to: v2/pickem_search/search_results answers 200 but returns a
featured subset, 100 lines over 4 teams, and ignores page/per_page/limit. The
real slate is thousands of lines. beta/v5 and v6 answer 426 "upgrade required",
which is a client version check rather than a block, so the first job here is to
see whether the right headers get past it.
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "https://api.underdogfantasy.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")


def get(url, extra=None, timeout=45):
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
         "Accept-Language": "en-US,en;q=0.9", "Origin": "https://underdogfantasy.com",
         "Referer": "https://underdogfantasy.com/"}
    if extra:
        h.update(extra)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8", "replace"))


def lines_of(doc):
    for k in ("over_under_lines", "lines", "data"):
        v = doc.get(k) if isinstance(doc, dict) else None
        if isinstance(v, list):
            return k, v
    return None, []


def try_url(label, url, extra=None):
    try:
        st, doc = get(url, extra)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read()[:120].decode("utf-8", "replace").replace("\n", " ")
        except Exception:  # noqa: BLE001
            pass
        print(f"  {label:<46} HTTP {e.code}  {body[:90]}")
        return None
    except Exception as e:  # noqa: BLE001
        print(f"  {label:<46} ERR {str(e)[:70]}")
        return None
    key, arr = lines_of(doc)
    teams = len(doc.get("teams") or []) if isinstance(doc, dict) else 0
    print(f"  {label:<46} HTTP {st}  {key}={len(arr)}  teams={teams}  "
          f"keys={sorted(doc)[:6] if isinstance(doc, dict) else '?'}")
    return doc


def main():
    print("1. CLIENT VERSION HEADERS against beta over_under_lines")
    print("   (426 is a version gate, not a ban, so this is worth a shot)")
    versions = ["20260101", "1.0.0", "9.9.9", "2026.10.1", "251013"]
    for v in versions:
        for ct in ("web", "ios", "android"):
            try_url(f"v6 client-version={v} client-type={ct}",
                    f"{BASE}/beta/v6/over_under_lines",
                    {"client-version": v, "client-type": ct})
    print()

    print("2. OTHER PATH SHAPES")
    for path in ("/beta/v3/over_under_lines", "/beta/v4/over_under_lines",
                 "/v1/over_under_lines", "/beta/v6/over_under_lines",
                 "/v2/pickem_search/search_results?sport_id=NFL",
                 "/v3/pickem_search/search_results?sport_id=NFL",
                 "/v2/pickem_search/search_results?sport_id=NFL&per_page=1000",
                 "/beta/v5/over_under_lines?sport_id=NFL"):
        try_url(path, BASE + path)
    print()

    print("3. SEARCH WITH A QUERY TERM (does it widen past the featured set?)")
    doc0 = None
    for q in ("", "a", "e", "yards", "receptions"):
        qs = f"&search_term={q}" if q else ""
        d = try_url(f"search_term={q!r}",
                    f"{BASE}/v2/pickem_search/search_results?sport_id=NFL{qs}")
        if q == "" and d:
            doc0 = d
    print()

    # The shapes still needed to write the fetcher. Printed LAST on purpose is
    # wrong when logs get tailed, so these go first in the section and short.
    if doc0:
        print("4. RECORD SHAPES (from the plain search call)")
        for key in ("over_under_lines", "appearances", "players"):
            arr = doc0.get(key) or []
            print("=" * 70)
            print(f"{key}: {len(arr)}  keys={sorted(arr[0]) if arr else '[]'}")
            if arr:
                print(json.dumps(arr[0], indent=1)[:1100])
    return 0


if __name__ == "__main__":
    sys.exit(main())
