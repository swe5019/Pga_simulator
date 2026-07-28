#!/usr/bin/env python3
"""
fetch_news.py — build data/news.json for the Industry News tab.

Pulls PGA / DFS coverage from public RSS feeds and public Reddit JSON, keeps
only what's relevant to THIS week's tournament, and counts how often each golfer
in the current field is being talked about.

Why this runs server-side: browsers can't fetch third-party feeds directly (CORS),
so a scheduled job publishes a same-origin JSON file the app can read — the same
pattern already used for slate.json and dk.json.

Two mention counts are kept deliberately separate, because they mean different things:
  news    — articles from golf/DFS outlets. Spikes on injuries, withdrawals, form.
  chatter — DFS community posts. Spikes on hype, and leads projected ownership.

Output: data/news.json
"""

import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OUT = os.path.join(DATA_DIR, "news.json")

UA = "SlateSims/1.0 (PGA DFS news aggregator; +https://slatesims.com)"

# Direct outlet feeds. Several publishers block datacenter IPs or move these URLs
# without notice, so each is best-effort and failures are recorded, not fatal.
RSS_FEEDS = [
    # DFS/betting publishers first. These are the ones that matter: they carry real
    # article links and real summaries, so golfer names can actually be extracted.
    # Google News aggregates the same writers but hands back opaque redirect tokens
    # with no recoverable URL, which caps mention counts at whoever made the headline.
    ("RotoWire Golf", "https://www.rotowire.com/rss/news.php?sport=GOLF"),
    ("RotoBaller Golf", "https://www.rotoballer.com/category/fantasy-golf/feed"),
    ("RotoBaller", "https://www.rotoballer.com/feed"),
    ("Golf News Net", "https://thegolfnewsnet.com/feed/"),
    ("FantasyLabs", "https://www.fantasylabs.com/feed/"),
    ("Action Network", "https://www.actionnetwork.com/rss.xml"),
    ("VSiN", "https://www.vsin.com/feed/"),
    ("Pinnacle Golf", "https://www.pinnacle.com/en/betting-resources/rss"),
    ("SportsGrid", "https://www.sportsgrid.com/feed/"),
    # General golf outlets, kept for withdrawal/injury coverage the DFS sites miss.
    ("Yahoo Golf", "https://sports.yahoo.com/golf/rss/"),
    ("Golfweek", "https://golfweek.usatoday.com/rss/"),
    ("Sky Sports Golf", "https://www.skysports.com/rss/12040"),
    ("Golf Monthly", "https://www.golfmonthly.com/feeds/all"),
    ("Bunkered", "https://www.bunkered.co.uk/feed"),
    ("Golf.com", "https://golf.com/feed/"),
    ("GolfWRX", "https://www.golfwrx.com/feed/"),
]


def google_news_feeds(event, slate_id):
    """
    Google News RSS queries, built around THIS week's tournament.

    This is the backbone of the tab rather than a nice-to-have: querying by topic
    pulls the same story from many outlets through one dependable endpoint, instead
    of depending on a pile of individual publisher feeds that break or block us.
    It also means the feed actually tracks the current tournament, since the query
    is rebuilt from the live event name each run.

    Queries are deliberately DFS-shaped, not general golf. A broad "PGA Tour news"
    query drags in schedule announcements and celebrity filler, which is noise to
    someone building DraftKings lineups.
    """
    base = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="
    queries = []
    if event:
        queries.append((f"Google News: {event} DFS",
                        f'"{event}" DraftKings OR DFS OR "daily fantasy"'))
        queries.append((f"Google News: {event} picks",
                        f'"{event}" picks OR lineup OR ownership OR sleepers'))
        queries.append((f"Google News: {event} WD",
                        f'"{event}" withdraws OR withdrawal OR injury'))
    queries += [
        ("Google News: PGA DFS", "PGA DraftKings DFS daily fantasy golf picks"),
        ("Google News: PGA WD", "PGA Tour golfer withdraws OR injury OR replaces"),
    ]
    return [(label, base + urllib.parse.quote(q)) for label, q in queries]


# --- Relevance: is this actually useful to someone building DK PGA lineups? ---

# Explicit DFS / betting vocabulary. Any hit qualifies an item on its own.
DFS_TERMS = [
    "draftkings", "draft kings", " dk ", "dfs", "daily fantasy", "fantasy golf",
    "fantasy", "fanduel", "lineup", "lineups", "ownership", "gpp", "showdown",
    "milly maker", "sleeper", "sleepers", "chalk", "leverage", "value play",
    "one and done", "optimizer", "projections", "salary", "salaries", "punt",
    "betting", "odds", "outright", "prop", "parlay", "picks", "preview",
    "best bets", "expert picks", "core plays",
    # "fade"/"fades" deliberately omitted: in golf writing a fade is a shot shape,
    # so it fires on ordinary coverage. Real fade articles also say picks/ownership.
]

# Roster-impacting news. A withdrawal isn't "DFS content" in the literal sense, but
# it's the single most actionable thing for a lineup, so it qualifies on its own when
# the item is about this week (a field golfer or the event itself). "tee times" is
# deliberately absent — it mostly matches broadcast/TV-schedule filler.
ROSTER_TERMS = [
    "withdraw", "withdrew", "withdrawal", "withdrawals", " wd ", "injury",
    "injured", "pulls out", "pulled out", "replaces", "replacement",
    "disqualified", "suspended play", "illness", "player list",
    # Anchored rather than a bare "out of the", which fired on ordinary prose like
    # "picking his ball up out of the hole".
    "out of the tournament", "out of the field", "out of the event",
]


# Headline phrases that mean a golfer's status changed. Split by severity: a
# withdrawal is settled, an injury note is a risk flag that still needs watching.
WD_TERMS = ["withdraw", "withdrew", "withdrawal", " wd ", "pulls out", "pulled out",
            "out of the tournament", "out of the field", "out of the event",
            "disqualified", "replaces"]
INJURY_TERMS = ["injury", "injured", "illness", "back spasms", "wrist", "ailing",
                "injury scare", "doubtful", "questionable"]


def roster_alert(title, matchers):
    """
    Detect a status change from a HEADLINE and say which golfers it applies to.

    Deliberately title-only. Withdrawal stories name the affected player in the
    headline, whereas body text routinely name-drops a dozen others — flagging on
    the summary would mark a whole leaderboard round-up as withdrawn.
    """
    t = " " + (title or "").lower() + " "
    kind = None
    if any(k in t for k in WD_TERMS):
        kind = "wd"
    elif any(k in t for k in INJURY_TERMS):
        kind = "injury"
    if not kind:
        return None
    named = golfers_in_text(strip_publisher(title), matchers)
    if not named:
        return None
    return {"kind": kind, "golfers": named}


def strip_publisher(title):
    """
    Drop Google News' trailing " - Publisher" before keyword matching.

    Without this, anything published BY a DFS outlet matches on the outlet's own
    name: "Who won the playoff at the 2025 Rocket Classic - DraftKings Network" is
    trivia, not DFS content, but the byline made it look like a DraftKings article.
    Only used for relevance testing; the displayed title keeps its attribution.
    """
    return re.sub(r"\s+-\s+[^-]{2,40}$", "", title or "")


def is_dfs_relevant(text, about_this_week):
    """
    Keep only what a DraftKings PGA DFS player needs.

    Two ways in: explicit DFS/betting content, or roster-impacting news about this
    week's tournament. General golf coverage — schedule announcements, equipment
    reviews, prize money, tour politics — is dropped even when it names a golfer.

    `about_this_week` is true when the item mentions a golfer in the field OR the
    event itself. Requiring a matched golfer was too strict: withdrawal round-ups
    like "Field 2026: Full Player List, Withdrawals" name nobody in the headline
    yet are exactly what a lineup builder needs to see.
    """
    t = " " + (text or "").lower() + " "
    if any(k in t for k in DFS_TERMS):
        return True
    if about_this_week and any(k in t for k in ROSTER_TERMS):
        return True
    return False


# Community chatter — the ownership leading indicator. Reddit blocks the .json API
# from datacenter IPs (which is exactly what a CI runner is), but the plain .rss
# listings are served far more permissively, so those are tried first.
SUBREDDITS = ["dfsports", "DraftKings", "golf"]

MAX_ITEMS = 120  # cap what we publish so news.json stays small

# Tournament news is perishable. Google News topic queries happily return matches
# from months back — "Koepka withdraws from RBC Canadian Open" is 6 weeks stale and
# reads as current if you don't check the date, which is actively dangerous when the
# whole point is deciding who to roster this week.
MAX_AGE_DAYS = 10


# ---------------------------------------------------------------- name matching

_NICKNAMES = {
    "johnny": "john", "jonny": "john", "jon": "john",
    "billy": "bill", "willie": "will", "robby": "rob", "bobby": "bob",
    "tommy": "tom", "danny": "dan", "andy": "andrew", "paddy": "patrick",
    "ricky": "rick", "rickie": "rick", "nicky": "nick",
    "tony": "anthony", "mikey": "mike", "stevie": "steve",
    "benny": "ben", "sammy": "sam", "matty": "matt", "timmy": "tim",
    "jimmy": "jim", "kenny": "ken", "ronnie": "ron", "donnie": "don",
    "matti": "matthias",
}

# Letters NFD-style stripping won't split (ø is its own letter, not o + accent).
_ACCENTS = [("é", "e"), ("è", "e"), ("ë", "e"), ("ö", "o"), ("ø", "o"), ("ó", "o"),
            ("í", "i"), ("á", "a"), ("à", "a"), ("ä", "a"), ("å", "a"), ("ü", "u"),
            ("ú", "u"), ("ñ", "n"), ("ç", "c"), ("æ", "ae"), ("ð", "d"), ("þ", "th"),
            ("ł", "l"), ("š", "s"), ("ž", "z"), ("č", "c")]


def _nrm(s):
    """Normalize a name for matching. Mirrors build_slate._nrm / app.js normName."""
    s = str(s or "").lower()
    for a, b in _ACCENTS:
        s = s.replace(a, b)
    s = re.sub(r"[^a-z ]", " ", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    parts = s.split(" ")
    if len(parts) > 1 and parts[0] in _NICKNAMES:
        parts[0] = _NICKNAMES[parts[0]]
    return " ".join(parts)


def build_matchers(golfers):
    """
    Build the patterns used to spot each golfer in free text.

    Full names always count. A bare surname only counts when it's UNIQUE in this
    week's field — with two Hojgaards, two Kims and two Svenssons in a typical
    field, crediting "Kim" to a specific player would invent data. Ambiguous
    surnames are simply not counted rather than guessed at.
    """
    surname_counts = {}
    for g in golfers:
        parts = _nrm(g["name"]).split()
        if parts:
            surname_counts[parts[-1]] = surname_counts.get(parts[-1], 0) + 1

    matchers = []
    for g in golfers:
        norm = _nrm(g["name"])
        parts = norm.split()
        pats = [re.escape(norm)]
        if len(parts) > 1:
            # "s. scheffler" / "scottie scheffler" both reduce to the surname test
            surname = parts[-1]
            if surname_counts.get(surname, 0) == 1 and len(surname) >= 4:
                pats.append(re.escape(surname))
        rx = re.compile(r"\b(?:" + "|".join(pats) + r")\b")
        matchers.append((g["name"], rx, surname_counts.get(parts[-1], 0) > 1 if parts else False))
    return matchers


def golfers_in_text(text, matchers):
    """Names of golfers mentioned in a blob of text."""
    t = _nrm(text)
    return [name for name, rx, _amb in matchers if rx.search(t)]


# ---------------------------------------------------------------- fetching

def get(url, timeout=25, headers=None):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def err_label(e):
    """Readable error for diagnostics — HTTP status matters (403 blocked vs 404 moved)."""
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    if isinstance(e, urllib.error.URLError):
        return f"URLError ({e.reason})"
    return type(e).__name__


def reddit_token():
    """
    App-only OAuth token, if Reddit credentials are configured.

    Reddit blocks anonymous .json AND .rss requests from datacenter IPs, which is
    what a CI runner is — that's why chatter came back empty. An app-only token
    (free, no user account access) is served normally from those same IPs. Without
    credentials we simply report chatter as unavailable rather than faking it.
    """
    cid = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        return None
    import base64
    basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=b"grant_type=client_credentials",
        headers={"Authorization": "Basic " + basic, "User-Agent": UA,
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read()).get("access_token")


def parse_when(s):
    """Publish date -> epoch seconds. Feeds mix RFC-822 (RSS) and ISO-8601 (Atom)."""
    s = (s or "").strip()
    if not s:
        return 0.0
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s).timestamp()
    except Exception:  # noqa: BLE001
        pass
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = (s.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
          .replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " "))
    return re.sub(r"\s+", " ", s).strip()


def parse_rss(xml_bytes, source):
    """Parse an RSS or Atom feed into [{title, link, summary, published, source}]."""
    out = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    for item in root.iter():
        tag = item.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue

        def field(*names):
            for n in names:
                el = item.find(n)
                if el is None:
                    el = item.find("atom:" + n, ns)
                if el is not None:
                    if n == "link" and not (el.text or "").strip():
                        return (el.get("href") or "").strip()
                    return (el.text or "").strip()
            return ""

        title = strip_html(field("title"))
        if not title:
            continue
        out.append({
            "title": title,
            "link": field("link", "id"),
            "summary": strip_html(field("description", "summary", "content"))[:400],
            "published": field("pubDate", "published", "updated"),
            "source": source,
            "kind": "news",
        })
    return out


def fetch_rss(feeds):
    """Fetch a list of (label, url) feeds. Returns (items, diagnostics)."""
    items, diag = [], []
    for source, url in feeds:
        try:
            got = parse_rss(get(url), source)
            items.extend(got)
            diag.append({"source": source, "ok": bool(got), "items": len(got),
                         "error": None if got else "no items"})
        except Exception as e:  # noqa: BLE001
            diag.append({"source": source, "ok": False, "items": 0,
                         "error": err_label(e)})
    ok = sum(1 for d in diag if d["ok"])
    print(f"RSS: {ok}/{len(feeds)} feeds returned items, {len(items)} items")
    for d in diag:
        if not d["ok"]:
            print(f"  skipped {d['source']}: {d['error']}")
    return items, diag


def fetch_reddit():
    """
    Recent posts from the DFS/golf subreddits, counted locally so we never need
    per-golfer queries (which would blow through rate limits on a 141-man field).

    Tries the .rss listing first: Reddit blocks its .json API from datacenter IPs
    like CI runners, which is why chatter came back empty on the first live run.
    """
    items, diag = [], []
    token, tok_err = None, None
    try:
        token = reddit_token()
    except Exception as e:  # noqa: BLE001
        tok_err = err_label(e)
    if token:
        print("Reddit: using app-only OAuth")
    elif tok_err:
        print(f"Reddit: OAuth failed ({tok_err}); falling back to anonymous")

    for sub in SUBREDDITS:
        got, err = [], None
        urls = []
        if token:
            urls.append((f"https://oauth.reddit.com/r/{sub}/new?limit=100",
                         {"Authorization": "bearer " + token}))
        urls += [(f"https://www.reddit.com/r/{sub}/new/.rss?limit=100", None),
                 (f"https://old.reddit.com/r/{sub}/new/.rss?limit=100", None),
                 (f"https://www.reddit.com/r/{sub}/new.json?limit=100", None)]
        for url, hdrs in urls:
            try:
                raw = get(url, headers=hdrs)
                if ".rss" not in url:
                    data = json.loads(raw)
                    for child in data.get("data", {}).get("children", []):
                        d = child.get("data", {})
                        if not (d.get("title") or "").strip():
                            continue
                        got.append({
                            "title": d["title"].strip(),
                            "link": "https://www.reddit.com" + (d.get("permalink") or ""),
                            "summary": strip_html(d.get("selftext") or "")[:400],
                            "published": datetime.datetime.utcfromtimestamp(
                                d.get("created_utc") or 0).isoformat() + "Z",
                            "source": "r/" + sub, "kind": "chatter",
                        })
                else:
                    for it in parse_rss(raw, "r/" + sub):
                        it["kind"] = "chatter"
                        got.append(it)
                if got:
                    break
                err = "no items"
            except Exception as e:  # noqa: BLE001
                err = err_label(e)
        items.extend(got)
        diag.append({"source": "r/" + sub, "ok": bool(got), "items": len(got),
                     "error": None if got else (
                         f"{err} — set REDDIT_CLIENT_ID/SECRET to enable chatter"
                         if not token else err)})
        if not got:
            print(f"  reddit r/{sub} failed: {err}")
    print(f"Reddit: {len(items)} posts")
    return items, diag


# ---------------------------------------------------------------- main

def extract_names_from_body(url, matchers, timeout=6):
    """
    Fetch an article and pull golfer names out of its text.

    Needed because Google News RSS carries no real summary — its description is the
    headline repeated plus the publisher — and DFS articles ("Best Bets and Odds",
    "experts share their picks") name players in the body, never the headline. Without
    this, buzz counts only see the handful of golfers big enough to headline a story.

    Only names are extracted; no article text is stored or republished.
    """
    try:
        raw = get(url, timeout=timeout)
    except Exception:  # noqa: BLE001
        return []
    try:
        html = raw.decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return []
    # Drop script/style blocks before stripping tags, or JS identifiers leak in.
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = strip_html(html)[:60000]
    return golfers_in_text(text, matchers)


def enrich_mentions(items, matchers, limit=45, workers=8):
    """
    Second pass: for items whose headline named nobody, look inside the article.
    Bounded and parallel so a 3-hourly job stays quick, and entirely best-effort —
    sites that block or time out are simply skipped.
    """
    # Google News links are opaque redirect tokens (…/rss/articles/CBMi…), and the
    # newer AU_yqL format carries no recoverable URL — fetching one returns Google's
    # JS redirect shell, never the article. Skip them instead of burning the budget
    # on pages that can't yield names.
    targets = [it for it in items
               if not it.get("golfers") and "news.google.com" not in (it.get("link") or "")
               ][:limit]
    if not targets:
        return 0
    from concurrent.futures import ThreadPoolExecutor
    found = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = ex.map(lambda it: extract_names_from_body(it.get("link") or "", matchers),
                         targets)
        for it, names in zip(targets, results):
            if names:
                it["golfers"] = names
                found += 1
    print(f"Body scan: {found}/{len(targets)} articles yielded golfer names")
    return found


def load_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def main():
    slate = load_json(os.path.join(DATA_DIR, "slate.json")) or {}
    dk = load_json(os.path.join(DATA_DIR, "dk.json")) or {}
    golfers = slate.get("golfers") or []
    if not golfers:
        print("No golfers in slate.json — nothing to match against; aborting.")
        return 1

    event = dk.get("event") or ""
    slate_id = slate.get("slate") or dk.get("tournament") or ""
    # Event keywords for relevance, e.g. "Rocket Classic" -> {rocket, classic}
    event_words = {w for w in _nrm(event).split() if len(w) > 3 and w not in ("open", "classic", "championship", "tour", "invitational")}

    matchers = build_matchers(golfers)
    rss_items, rss_diag = fetch_rss(RSS_FEEDS + google_news_feeds(event, slate_id))
    red_items, red_diag = fetch_reddit()
    raw = rss_items + red_items

    # Keep an item if it mentions the event or anyone in this week's field.
    now_ts = datetime.datetime.utcnow().timestamp()
    seen_links, items = set(), []
    mentions = {}
    for it in raw:
        blob = f"{it['title']} {it.get('summary','')}"
        names = golfers_in_text(blob, matchers)
        norm_blob = _nrm(blob)
        hits_event = bool(event_words) and any(w in norm_blob for w in event_words)
        # Must be about this week (the event or someone in the field) AND be useful
        # to a DK lineup builder. The second test is what keeps general golf
        # coverage — schedule news, equipment, tour politics — out of the tab.
        if not names and not hits_event:
            continue
        relevance_blob = f"{strip_publisher(it['title'])} {it.get('summary','')}"
        if not is_dfs_relevant(relevance_blob, bool(names) or hits_event):
            continue
        # Drop stale coverage. Without this the feed mixes last month's withdrawals
        # in with this week's and they're indistinguishable at a glance.
        ts = parse_when(it.get("published"))
        if ts and (now_ts - ts) > MAX_AGE_DAYS * 86400:
            continue
        link = it.get("link") or it["title"]
        if link in seen_links:
            continue
        seen_links.add(link)
        it["golfers"] = names
        # Flag roster-status news (withdrawal / injury) so the buzz table can say WHY
        # a golfer is being talked about. High buzz from a WD is the opposite signal
        # to high buzz from hype, and the raw count can't tell them apart.
        # Only treat a status change as current if the story is about THIS event.
        # "Koepka withdraws from RBC Canadian Open" names a golfer in our field and
        # says "withdraws", but he is playing this week — flagging him would be worse
        # than showing nothing.
        alert = roster_alert(it["title"], matchers) if hits_event else None
        if alert:
            it["alert"] = alert["kind"]
            # Kept separate from it["golfers"]: alerts must stay headline-derived even
            # after the body scan below widens who counts as "mentioned".
            it["_alertGolfers"] = alert["golfers"]
        items.append(it)

    # Newest first, across both kinds. Sorting news ahead of chatter and then
    # truncating would starve chatter out of the list entirely once it's flowing,
    # and "Latest" has to actually mean latest.
    items.sort(key=lambda x: parse_when(x.get("published")), reverse=True)
    items = items[:MAX_ITEMS]

    # Widen mention coverage by reading the articles that named nobody in the
    # headline, then tally. Counting has to happen after this pass, not during the
    # loop above, or the newly-found names would be missed.
    enrich_mentions(items, matchers)

    for it in items:
        # One item counts once per golfer, so a single long article can't dominate.
        for n in it.get("golfers") or []:
            m = mentions.setdefault(n, {"name": n, "news": 0, "chatter": 0})
            m["news" if it["kind"] == "news" else "chatter"] += 1
        # Attribute the alert only to golfers named in the HEADLINE. A round-up that
        # mentions ten players while reporting one withdrawal must not mark all ten
        # as out; WD stories name the affected player in the title.
        for n in it.pop("_alertGolfers", []) or []:
            m = mentions.setdefault(n, {"name": n, "news": 0, "chatter": 0})
            # A withdrawal outranks an injury note — it's already decided.
            if m.get("alert") != "wd":
                m["alert"] = it["alert"]
                m["alertHeadline"] = it["title"][:160]
                m["alertLink"] = it.get("link") or ""

    table = sorted(mentions.values(), key=lambda m: -(m["news"] + m["chatter"]))
    for m in table:
        m["total"] = m["news"] + m["chatter"]

    doc = {
        "updatedUtc": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "slate": slate_id,
        "event": event,
        "counts": {
            "items": len(items),
            "golfersMentioned": len(table),
            "news": sum(1 for i in items if i["kind"] == "news"),
            "chatter": sum(1 for i in items if i["kind"] == "chatter"),
        },
        # Per-source status, so a silently dead feed is visible in the data itself
        # instead of only in a workflow log nobody reads.
        "sources": rss_diag + red_diag,
        "mentions": table,
        "items": items,
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(doc, fh, indent=1)
    print(f"Wrote {OUT}: {len(items)} items, {len(table)} golfers mentioned "
          f"(event {event!r})")
    if table[:5]:
        print("  most talked about: " + ", ".join(
            f"{m['name']} ({m['total']})" for m in table[:5]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
