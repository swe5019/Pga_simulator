#!/usr/bin/env python3
"""
probe_props.py — read-only check of whether NFL prop lines are reachable.

WRITES NOTHING. It answers one question before any modelling work starts: can a
GitHub Actions runner actually pull prop lines, and in what shape?

This matters because api.draftkings.com already refuses this runner, which is
why contest payouts are modelled rather than exact. If the pick'em feeds refuse
it too, a scraped props tool cannot be built on this infrastructure at all and
the money is better spent on a paid odds feed. Better to find that out in five
minutes than after building a simulation to consume it.

For each endpoint it reports the HTTP status, the response size, the top level
shape, and one sample record so the field names can be read off directly.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Candidate public endpoints. Several spellings per site on purpose: these move,
# and the point is to find out which (if any) answer, not to be elegant.
TARGETS = [
    ("PrizePicks NFL projections",
     "https://api.prizepicks.com/projections?league_id=9&per_page=250&single_stat=true"),
    ("PrizePicks leagues",
     "https://api.prizepicks.com/leagues"),
    ("Underdog over/under lines v6",
     "https://api.underdogfantasy.com/beta/v6/over_under_lines"),
    ("Underdog over/under lines v5",
     "https://api.underdogfantasy.com/beta/v5/over_under_lines"),
    ("Underdog pickem search NFL",
     "https://api.underdogfantasy.com/v2/pickem_search/search_results?sport_id=NFL"),
    ("The Odds API (needs key, shows whether host is reachable)",
     "https://api.the-odds-api.com/v4/sports/"),
]


def shape(obj, depth=0):
    """One line describing what came back, without dumping the whole payload."""
    pad = "  " * depth
    if isinstance(obj, dict):
        ks = list(obj)[:12]
        return f"{pad}dict with {len(obj)} keys: {ks}"
    if isinstance(obj, list):
        return f"{pad}list of {len(obj)}"
    return f"{pad}{type(obj).__name__}"


def probe(name, url):
    print("=" * 78)
    print(name)
    print(url[:110])
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read()
            ms = int((time.time() - t0) * 1000)
            print(f"  HTTP {r.status}  {len(raw):,} bytes  {ms} ms")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read()[:200].decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        print(f"  HTTP {e.code} {e.reason}")
        if body:
            print(f"  body: {body.strip()[:180]}")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"  FAILED: {e}")
        return False

    try:
        doc = json.loads(raw.decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        print(f"  not json: {e}")
        print(f"  first 200 chars: {raw[:200]!r}")
        return False

    print("  " + shape(doc))
    # Walk the usual containers so the real records are visible whatever the
    # wrapper is called.
    for key in ("data", "projections", "over_under_lines", "players", "games",
                "appearances", "included", "results"):
        if isinstance(doc, dict) and key in doc and isinstance(doc[key], list) and doc[key]:
            arr = doc[key]
            print(f"  {key}: list of {len(arr)}")
            print(f"  sample {key}[0]:")
            print("    " + json.dumps(arr[0], indent=2)[:900].replace("\n", "\n    "))
            break
    else:
        if isinstance(doc, list) and doc:
            print("  sample [0]:")
            print("    " + json.dumps(doc[0], indent=2)[:600].replace("\n", "\n    "))
        elif isinstance(doc, dict):
            print("  top level sample:")
            print("    " + json.dumps(doc, indent=2)[:600].replace("\n", "\n    "))
    return True


def main():
    print("Probing NFL prop line sources. Read only, writes nothing.\n")
    ok = []
    for name, url in TARGETS:
        if probe(name, url):
            ok.append(name)
        print()
    print("=" * 78)
    print(f"REACHABLE: {len(ok)} of {len(TARGETS)}")
    for n in ok:
        print(f"   - {n}")
    if not ok:
        print("\nNothing answered. A scraped props tool is not viable from this")
        print("runner; budget for a paid odds feed or a manual weekly upload.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
