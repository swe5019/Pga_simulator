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


HIST_DIR = os.path.join(DATA_DIR, "history")


def _safe(name):
    return "".join(c if c.isalnum() else "_" for c in str(name)).strip("_") or "event"


def _nrm(s):
    """Normalize a player name for cross-source matching (DK vs sheet)."""
    import re
    s = str(s).lower()
    for a, b in [("é", "e"), ("ö", "o"), ("ø", "o"), ("í", "i"), ("á", "a")]:
        s = s.replace(a, b)
    s = re.sub(r"[^a-z ]", " ", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _mae_vs(actual, predmap):
    """Mean absolute error between a prediction map and actuals, matching names
    by normalized form. Returns (mae, n_compared) or (None, 0)."""
    pm = {_nrm(k): v for k, v in (predmap or {}).items() if v is not None}
    pairs = [(predmap_v, actual[n]) for n in actual
             for predmap_v in [pm.get(_nrm(n))] if predmap_v is not None]
    if not pairs:
        return None, 0
    return round(sum(abs(p - a) for p, a in pairs) / len(pairs), 3), len(pairs)


def _load_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _save_json(path, doc):
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=1)


def archive_history(golfers, meta, raw, suffix):
    """Preserve every tournament's predictions + (when present) actual ownership/
    FPTS to data/history/, so the full history lives in the repo independent of
    the OneDrive sheet. Builds a predicted-vs-actual record (and per-event MAE)
    that grows automatically as you fill in results. Never raises — archiving
    must not jeopardize the live slate write."""
    try:
        os.makedirs(HIST_DIR, exist_ok=True)
        now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        slate = meta["slate"]

        # Read the Data tab once; build an event -> date map so the archive (and
        # the accuracy page) can order events chronologically.
        sheet = os.environ.get("SLATE_SHEET_DATA", "Data")
        engine = "odf" if suffix == ".ods" else "openpyxl"
        date_by_event = {}
        df = None
        try:
            df = pd.read_excel(io.BytesIO(raw), sheet_name=sheet, engine=engine)
            cols0 = {str(c).strip().lower(): c for c in df.columns}
            ct, cd = cols0.get("tournament_name"), cols0.get("date")
            if ct and cd:
                for ev, grp in df.groupby(ct):
                    ds = grp[cd].dropna()
                    if not ds.empty:
                        date_by_event[str(ev).strip()] = str(ds.iloc[0]).strip()
        except Exception:  # noqa: BLE001
            df = None

        # 1) Snapshot the current slate's predicted ownership (merge, keep actuals).
        cur = os.path.join(HIST_DIR, _safe(slate) + ".json")
        doc = _load_json(cur) or {"tournament": slate}
        doc["tournament"] = slate
        doc["updatedUtc"] = now
        doc["cvMaePct"] = meta.get("cvMaePct")
        if date_by_event.get(slate):
            doc["date"] = date_by_event[slate]
        doc["predicted"] = {
            g["name"]: g["ownership"] for g in golfers if g.get("ownership") is not None
        }
        _save_json(cur, doc)

        # 2) Actual ownership / FPTS for every event in the Data tab. Update each
        #    event's file and compute MAE wherever we have both predicted + actual.
        cols = {str(c).strip().lower(): c for c in df.columns} if df is not None else {}
        c_tour = cols.get("tournament_name")
        c_name = cols.get("name")
        c_own = cols.get("actual_ownership")
        c_fpts = cols.get("fpts") or cols.get("actual_fpts")
        # Optional: your Colab/own ownership projection, for a head-to-head MAE vs
        # the website model. Add any of these columns to the Data tab to enable it.
        c_colab = (cols.get("colab_ownership") or cols.get("colab_predicted")
                   or cols.get("predicted_ownership") or cols.get("predicted_ownership_pct")
                   or cols.get("colab_own"))
        if c_tour and c_name and c_own:
            for ev, grp in df.groupby(c_tour):
                ev = str(ev).strip()
                if not ev or ev.lower() == "nan":
                    continue
                own_raw = grp[c_own].dropna()
                if own_raw.empty:
                    continue
                # Sheet stores ownership as a fraction (0.286); scale to % if so.
                scale = 100.0 if float(own_raw.max()) <= 1.5 else 1.0
                colab_scale = 1.0
                if c_colab is not None:
                    cr = grp[c_colab].dropna()
                    if not cr.empty:
                        colab_scale = 100.0 if float(cr.max()) <= 1.5 else 1.0
                actual, actual_fpts, colab = {}, {}, {}
                for _, row in grp.iterrows():
                    nm = str(row[c_name]).strip()
                    if not nm or nm.lower() == "nan":
                        continue
                    ov = num(row[c_own])
                    if ov is not None:
                        actual[nm] = round(ov * scale, 2)
                    if c_fpts:
                        fv = num(row[c_fpts])
                        if fv is not None:
                            actual_fpts[nm] = round(fv, 1)
                    if c_colab is not None:
                        cv = num(row[c_colab])
                        if cv is not None:
                            colab[nm] = round(cv * colab_scale, 2)
                if not actual:
                    continue
                p = os.path.join(HIST_DIR, _safe(ev) + ".json")
                d = _load_json(p) or {"tournament": ev}
                d["tournament"] = ev
                if date_by_event.get(ev):
                    d["date"] = date_by_event[ev]
                d["actual"] = actual
                if actual_fpts:
                    d["actualFpts"] = actual_fpts
                if colab:
                    d["colab"] = colab

                mae, ncommon = _mae_vs(actual, d.get("predicted") or {})
                if mae is not None:
                    d["maePct"] = mae
                    d["comparedPlayers"] = ncommon
                cmae, _ = _mae_vs(actual, colab)
                if cmae is not None:
                    d["colabMaePct"] = cmae  # head-to-head: your Colab vs website
                d.setdefault("updatedUtc", now)
                _save_json(p, d)

        # 2b) Merge real post-contest ownership pulled from DraftKings
        #     (data/actual_ownership.json, written by fetch_dk.py). This is the
        #     true contest number, so it becomes the 'actual' and we (re)score
        #     both the website and Colab predictions against it.
        dk_doc = _load_json(os.path.join(DATA_DIR, "actual_ownership.json")) or {}
        for ev, info in (dk_doc.get("tournaments") or {}).items():
            own = info.get("ownership") or {}
            if not own:
                continue
            p = os.path.join(HIST_DIR, _safe(ev) + ".json")
            d = _load_json(p) or {"tournament": ev}
            d["tournament"] = ev
            if date_by_event.get(ev):
                d["date"] = date_by_event[ev]
            merged = dict(d.get("actual") or {})
            merged.update({k: round(float(v), 2) for k, v in own.items()})
            d["actual"] = merged
            d["actualSource"] = "DK contest " + str(info.get("contestId"))
            if info.get("fpts"):
                d["actualFpts"] = {**(d.get("actualFpts") or {}), **info["fpts"]}

            mae, ncommon = _mae_vs(merged, d.get("predicted") or {})
            if mae is not None:
                d["maePct"], d["comparedPlayers"] = mae, ncommon
            cmae, _ = _mae_vs(merged, d.get("colab") or {})
            if cmae is not None:
                d["colabMaePct"] = cmae
            d["updatedUtc"] = now
            _save_json(p, d)

        # 3) Rebuild the index of all archived events.
        events = []
        for fn in sorted(os.listdir(HIST_DIR)):
            if not fn.endswith(".json") or fn == "index.json":
                continue
            d = _load_json(os.path.join(HIST_DIR, fn)) or {}
            events.append({
                "tournament": d.get("tournament", fn[:-5]),
                "file": "history/" + fn,
                "date": d.get("date"),
                "hasPredicted": bool(d.get("predicted")),
                "hasActual": bool(d.get("actual")),
                "maePct": d.get("maePct"),
                "colabMaePct": d.get("colabMaePct"),
                "comparedPlayers": d.get("comparedPlayers"),
                "updatedUtc": d.get("updatedUtc"),
            })
        _save_json(os.path.join(HIST_DIR, "index.json"),
                   {"updatedUtc": now, "count": len(events), "events": events})
        withmae = sum(1 for e in events if e.get("maePct") is not None)
        print(f"Archived history: {len(events)} events "
              f"({withmae} with predicted-vs-actual MAE) -> data/history/")
    except Exception as e:  # noqa: BLE001
        print(f"History archive skipped ({type(e).__name__}: {e})")


def main() -> int:
    raw, suffix = fetch_workbook()
    if raw is None:
        print("No SLATE_SOURCE_URL secret and no data/master.xlsx|.ods — "
              "leaving existing data/slate.json untouched.")
        return 0

    # One-off broad hyperparameter search (manual): prints best params, no write.
    if os.environ.get("OWNERSHIP_TUNE", "").strip():
        import ownership_model
        ownership_model.optuna_search(raw, suffix,
                                      n_trials=int(os.environ.get("TUNE_TRIALS", "60")))
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
                "cvMaePct": meta.get("cvMaePct"),
                "ensemble": meta.get("ensemble"),
                "count": len(golfers),
                "golfers": golfers,
            }
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(OUT, "w") as fh:
                json.dump(doc, fh, indent=1)
            archive_history(golfers, meta, raw, suffix)  # accumulate per-event history
            withown = sum("ownership" in g for g in golfers)
            print(f"Wrote {OUT}: {len(golfers)} golfers for {meta['slate']} "
                  f"(trained on {meta['trainRows']} rows / {meta['trainEvents']} events; "
                  f"{meta['ensemble']}-model ensemble, n_estimators={meta.get('nEstimators')}, "
                  f"lr={meta.get('learningRate')}; leave-one-tournament-out MAE "
                  f"{meta.get('cvMaePct')}% (Colab baseline ~2.42%); {withown} with ownership)")
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
