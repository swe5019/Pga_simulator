#!/usr/bin/env python3
"""
probe_contest.py — what can actually be read about a DraftKings contest.

WHY THIS EXISTS
Everything this project knows about real contest ownership was transcribed by
hand from screenshots, and the field model it feeds is fitted to a single week
because of that. The obvious fix is to read the contest directly, and the
question "can we?" has three different answers depending on which endpoint you
mean and whether the account entered. Guessing at it from a container that
cannot reach draftkings.com at all wasted an exchange, so this settles it on a
runner that can.

READ-ONLY BY CONSTRUCTION
It writes no files and commits nothing, same as probe_nfl.py. It only reports,
per endpoint: the status, the content type, the size, and enough of the body to
tell a real payload from a login redirect. A contest gamecenter is a JavaScript
app, so the HTML landing page is expected to be useless; the data lives behind
the JSON endpoints the page calls, and those are what matter here.

THE COOKIE
`exportfullstandingscsv` is the only endpoint that carries every entry's
lineup, which is what ownership, stacks and duplicates are all derived from. It
needs a logged-in session AND an entry in the contest. If DK_COOKIE is set the
probe tries it; the cookie's value is never printed, only whether it was
present and what the server did with it.

USAGE
  PROBE_CONTEST=197411852 python tools/probe_contest.py
"""
import json
import os
import sys
import urllib.error
import urllib.request

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0 Safari/537.36"),
    "Accept": "*/*",
}

TIMEOUT = 45
SNIPPET = 320


def log(*a):
    print(*a, flush=True)


def probe(label, url, cookie=None, want="any"):
    """Fetch one endpoint and describe what came back. Never raises."""
    hdrs = dict(UA)
    if cookie:
        hdrs["Cookie"] = cookie
    log(f"\n--- {label}")
    log(f"    GET {url}")
    log(f"    cookie: {'sent' if cookie else 'none'}")
    try:
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            ctype = r.headers.get("Content-Type", "?")
            code = r.status
            final = r.geturl()
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read()[:SNIPPET]
        except Exception:
            pass
        log(f"    HTTP {e.code} {e.reason}  ({len(body)} bytes of body)")
        if body:
            log(f"    body: {body.decode('utf-8', 'replace')[:200]!r}")
        return None
    except Exception as e:
        log(f"    FAILED {type(e).__name__}: {str(e)[:160]}")
        return None

    log(f"    HTTP {code}  {ctype}  {len(raw):,} bytes")
    if final != url:
        log(f"    redirected to: {final}")

    text = raw.decode("utf-8", "replace")
    low = text[:400].lower()

    # A login wall and a real payload both come back 200, so the status alone
    # says nothing. The shape of the first few hundred bytes is the tell.
    if "<html" in low or "<!doctype" in low:
        log("    -> HTML page, not data. "
            "Either a login wall or the JS shell of the gamecenter.")
        if "login" in low or "signin" in low:
            log("    -> looks like a LOGIN redirect: not readable this way.")
        return None

    if want == "csv" or ctype.startswith("text/csv"):
        lines = text.splitlines()
        log(f"    -> CSV, {len(lines):,} lines")
        for ln in lines[:3]:
            log(f"       {ln[:170]}")
        return text

    try:
        doc = json.loads(text)
    except ValueError:
        log(f"    -> not JSON. first bytes: {text[:200]!r}")
        return None

    log("    -> JSON parsed.")
    if isinstance(doc, dict):
        log(f"       top-level keys: {sorted(doc.keys())[:18]}")
        for k, v in doc.items():
            if isinstance(v, list) and v:
                log(f"       {k}: list of {len(v):,}")
                if isinstance(v[0], dict):
                    log(f"         first item keys: {sorted(v[0].keys())[:18]}")
                    log(f"         first item: {json.dumps(v[0])[:280]}")
                break
    elif isinstance(doc, list):
        log(f"       list of {len(doc):,}")
        if doc and isinstance(doc[0], dict):
            log(f"       first item keys: {sorted(doc[0].keys())[:18]}")
    return doc


def main():
    cid = (os.environ.get("PROBE_CONTEST") or "197411852").strip()
    cookie = os.environ.get("DK_COOKIE", "").strip()
    log(f"probing DraftKings contest {cid}")
    log(f"DK_COOKIE secret: {'present' if cookie else 'NOT SET'}"
        f"{' (' + str(len(cookie)) + ' chars)' if cookie else ''}")
    log("nothing is written; this is a read-only diagnostic.")

    # Public-ish, in rough order of how useful the payload would be.
    probe("contest detail (api)",
          f"https://api.draftkings.com/contests/v1/contests/{cid}?format=json")
    probe("leaderboard (api v2)",
          "https://api.draftkings.com/scores/v2/leaderboards/"
          f"?format=json&contestKey={cid}")
    probe("leaderboard (www)",
          f"https://www.draftkings.com/contest/getleaderboard?contestId={cid}&i=0")
    probe("gamecenter page (the URL a human opens)",
          f"https://www.draftkings.com/contest/gamecenter/{cid}")

    # The one that matters: every entry's lineup.
    probe("full standings CSV, unauthenticated",
          f"https://www.draftkings.com/contest/exportfullstandingscsv/{cid}",
          want="csv")
    if cookie:
        probe("full standings CSV, WITH cookie",
              f"https://www.draftkings.com/contest/exportfullstandingscsv/{cid}",
              cookie=cookie, want="csv")
    else:
        log("\n--- full standings CSV, WITH cookie")
        log("    skipped: DK_COOKIE is not set as a repository secret.")

    log("\ndone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
