#!/usr/bin/env python3
"""
probe_props.py — read-only inspection of the Underdog pick'em feed.

WRITES NOTHING. Its job is to expose the exact field names and join keys so the
real fetcher can be written against reality rather than guesswork.

Only one endpoint survived the first probe. PrizePicks answers 403 behind a
DataDome captcha, and Underdog's beta/v5 and v6 paths want a client version
header. v2/pickem_search answers plainly, so that is what gets used.
"""
import json
import sys
import urllib.error
import urllib.request

URL = "https://api.underdogfantasy.com/v2/pickem_search/search_results?sport_id=NFL"
UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def dump(label, arr, n=2, trim=1400):
    print("=" * 78)
    print(f"{label}: {len(arr)} records")
    if not arr:
        return
    print(f"  keys: {sorted(arr[0])}")
    for i, rec in enumerate(arr[:n]):
        print(f"  --- [{i}] ---")
        print("  " + json.dumps(rec, indent=2)[:trim].replace("\n", "\n  "))


def main():
    try:
        doc = get(URL)
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read()[:300]}")
        return 1
    print("top level keys:", sorted(doc))
    print()

    for key in ("over_under_lines", "appearances", "players", "games",
                "solo_games", "teams"):
        dump(key, doc.get(key) or [], n=2)
        print()

    # Which stats exist, and how many lines each. This decides what the first
    # version can cover without guessing at Underdog's naming.
    stats = {}
    for ln in doc.get("over_under_lines") or []:
        ou = ln.get("over_under") or {}
        ap = ou.get("appearance_stat") or {}
        s = ap.get("display_stat") or ap.get("stat") or ou.get("title") or "?"
        stats[s] = stats.get(s, 0) + 1
    print("=" * 78)
    print("STAT TYPES on this page:")
    for s, n in sorted(stats.items(), key=lambda kv: -kv[1]):
        print(f"   {n:>4}  {s}")

    # Does it paginate, and how far?
    print()
    print("=" * 78)
    print("PAGINATION probe")
    for extra in ("&page=2", "&per_page=500", "&limit=500"):
        try:
            d2 = get(URL + extra)
            n = len(d2.get("over_under_lines") or [])
            same = (d2.get("over_under_lines") or [{}])[0].get("id") == \
                   (doc.get("over_under_lines") or [{}])[0].get("id")
            print(f"   {extra:<14} -> {n} lines, first id identical: {same}")
        except Exception as e:  # noqa: BLE001
            print(f"   {extra:<14} -> {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
