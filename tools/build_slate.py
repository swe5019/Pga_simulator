#!/usr/bin/env python3
"""
build_slate.py — turn the master spreadsheet's "Sheet1" into data/slate.json.

Source of the workbook (in priority order):
  1. $SLATE_SOURCE_URL  — a "anyone with the link can view" OneDrive/SharePoint
     share link. Downloaded server-side (no auth needed for anonymous links).
  2. data/master.xlsx or data/master.ods committed in the repo.

The website (assets/js/app.js) fetches data/slate.json on load, so refreshing
that file is all it takes to update the live slate.
"""
import base64
import json
import math
import os
import sys
import datetime
import io

import pandas as pd
import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO, "data")
OUT = os.path.join(DATA_DIR, "slate.json")
SHEET = os.environ.get("SLATE_SHEET", "Sheet1")

# Map model field -> accepted column names (lower-cased, stripped).
COLS = {
    "name": ["name"],
    "salary": ["salary"],
    "sgTot": ["sg_tot", "sg_total", "sgtot"],
    "sgT2g": ["sg_t2g", "sg_t2_g", "sgt2g"],
    "sgPutt": ["sg_putt", "sgputt"],
    "sgArg": ["sg_arg", "sgarg"],
    "sgApp": ["sg_app", "sgapp"],
    "sgOtt": ["sg_ott", "sgott"],
    "ownership": ["predicted_ownership_pct", "ownership", "own%", "proj_own"],
    "winOdds": ["win_odds"],
    "impliedProb": ["implied_prob_pct", "implied_prob"],
    "leverage": ["leverage_score", "leverage"],
    "leverageTier": ["leverage_tier"],
}


def onedrive_share_to_download(url: str) -> str:
    """Convert an anonymous OneDrive/SharePoint share link to a direct-content URL."""
    b64 = base64.urlsafe_b64encode(url.encode("utf-8")).decode("utf-8").rstrip("=")
    return "https://api.onedrive.com/v1.0/shares/u!" + b64 + "/root/content"


def fetch_workbook() -> tuple[bytes, str]:
    """Return (raw_bytes, suffix) for the workbook, or raise."""
    url = os.environ.get("SLATE_SOURCE_URL", "").strip()
    if url:
        for candidate in (onedrive_share_to_download(url),
                          url + ("&" if "?" in url else "?") + "download=1",
                          url):
            try:
                r = requests.get(candidate, allow_redirects=True, timeout=60)
                if r.ok and r.content[:2] == b"PK":  # xlsx/ods are zip files
                    print(f"Downloaded workbook from {candidate[:60]}… "
                          f"({len(r.content)} bytes)")
                    return r.content, ".xlsx"
            except Exception as e:  # noqa: BLE001
                print(f"  fetch attempt failed: {e}")
        raise SystemExit("ERROR: SLATE_SOURCE_URL set but no valid workbook downloaded. "
                         "Make sure the link is 'anyone with the link can view'.")

    for name in ("master.xlsx", "master.ods"):
        p = os.path.join(DATA_DIR, name)
        if os.path.exists(p):
            with open(p, "rb") as fh:
                print(f"Using committed {name}")
                return fh.read(), os.path.splitext(name)[1]
    return None, None  # nothing to do (no source yet) — handled as a clean no-op


def num(v):
    try:
        f = float(str(v).replace(",", "").strip())
        return f if math.isfinite(f) else None  # drop NaN / Infinity (invalid JSON)
    except (TypeError, ValueError):
        return None


def main() -> int:
    raw, suffix = fetch_workbook()
    if raw is None:
        print("No SLATE_SOURCE_URL secret and no data/master.xlsx|.ods — "
              "leaving existing data/slate.json untouched.")
        return 0

    # Preferred path: train the ownership model on the Data tab and predict the
    # current slate (automates the Colab). Falls back to the simple sheet read.
    try:
        import ownership_model
        golfers, meta = ownership_model.build_from_workbook(raw, suffix)
        if golfers:
            doc = {
                "updatedUtc": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                "source": f"Data tab + ownership model ({meta['slate']})",
                "slate": meta["slate"],
                "trainRows": meta["trainRows"],
                "trainEvents": meta["trainEvents"],
                "count": len(golfers),
                "golfers": golfers,
            }
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(OUT, "w") as fh:
                json.dump(doc, fh, indent=1)
            withown = sum("ownership" in g for g in golfers)
            print(f"Wrote {OUT}: {len(golfers)} golfers for {meta['slate']} "
                  f"(model trained on {meta['trainRows']} rows / {meta['trainEvents']} events, "
                  f"{withown} with predicted ownership)")
            return 0
    except Exception as e:  # noqa: BLE001
        print(f"Ownership model path unavailable ({type(e).__name__}: {e}); "
              f"falling back to sheet read.")

    engine = "odf" if suffix == ".ods" else "openpyxl"
    df = pd.read_excel(io.BytesIO(raw), sheet_name=SHEET, engine=engine)

    lower = {str(c).strip().lower(): c for c in df.columns}
    idx = {}
    for field, names in COLS.items():
        for n in names:
            if n in lower:
                idx[field] = lower[n]
                break
    if "name" not in idx or "salary" not in idx:
        raise SystemExit(f"Sheet '{SHEET}' needs Name and Salary columns; found {list(df.columns)}")

    golfers = []
    for _, row in df.iterrows():
        name = str(row[idx["name"]]).strip()
        salary = num(row[idx["salary"]])
        if not name or name.lower() == "nan" or not salary:
            continue
        rec = {"name": name, "salary": int(salary)}
        for field in ("sgTot", "sgT2g", "sgPutt", "sgArg", "sgApp", "sgOtt",
                      "ownership", "winOdds", "impliedProb", "leverage"):
            if field in idx:
                v = num(row[idx[field]])
                if v is not None:
                    rec[field] = round(v, 3)
        if "leverageTier" in idx:
            t = str(row[idx["leverageTier"]]).strip()
            if t and t.lower() != "nan":
                rec["leverageTier"] = t
        golfers.append(rec)

    if not golfers:
        raise SystemExit("Parsed 0 golfers — aborting so we don't blank the live slate.")

    doc = {
        "updatedUtc": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "source": f"master {SHEET}",
        "count": len(golfers),
        "golfers": golfers,
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(doc, fh, indent=1)
    with_sg = sum("sgTot" in g for g in golfers)
    with_own = sum("ownership" in g for g in golfers)
    print(f"Wrote {OUT}: {len(golfers)} golfers ({with_sg} with SG_TOT, {with_own} with ownership)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
