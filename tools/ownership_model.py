#!/usr/bin/env python3
"""
ownership_model.py — automated DFS golf ownership predictor.

A faithful port of the user's Colab LightGBM model, adapted to run in the
sync pipeline. Reads the workbook's "Data" tab (history + current slate),
trains on historical Actual_Ownership, predicts the current slate's
ownership, derives win/top5/top10 equity from odds, and returns golfer
records for slate.json.

Falls back gracefully: callers should catch exceptions and use the simpler
sheet-based builder if anything here can't run (missing deps/columns/data).
"""
import io
import os

import numpy as np
import pandas as pd

SG_COLS = ["SG_PUTT", "SG_ARG", "SG_APP", "SG_OTT", "SG_T2G", "SG_TOT"]


def american_prob(o):
    """American odds -> implied probability (handles +/-)."""
    try:
        o = float(o)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(o) or o == 0:
        return None
    return 100.0 / (o + 100.0) if o > 0 else (-o) / ((-o) + 100.0)


def engineer_features(df):
    d = df.copy()
    d["Injury_Risk"] = d.get("Injury_Risk", 0)
    d["Injury_Risk"] = pd.to_numeric(d["Injury_Risk"], errors="coerce").fillna(0).astype(int)

    for col in ["Win_Odds_Monday", "Odds_Change", "Actual_Ownership", "FPTS",
                "NO_CUT", "Is_Major", "Entries"]:
        if col not in d.columns:
            d[col] = np.nan

    num = lambda c: pd.to_numeric(d[c], errors="coerce")
    for c in ["Win_Odds", "Win_Odds_Monday", "Salary", "Actual_Ownership",
              "1W", "2W", "3W", "CH_Finish_1", "CH_Finish_2", "CH_Finish_3",
              "CH_Events", "CH_Made_Cuts", "NO_CUT", "Is_Major", "Entries"] + SG_COLS:
        if c in d.columns:
            d[c] = num(c)

    d["Implied_Prob"] = np.where(d["Win_Odds"].notna() & (d["Win_Odds"] > 0),
                                 100.0 / (d["Win_Odds"] + 100.0), np.nan)
    d["log_IP"] = np.log(d["Implied_Prob"].clip(lower=0.0005))

    d["Salary_Rank"] = d.groupby("Tournament_Name")["Salary"].rank(ascending=False, method="min")
    d["Salary_Pct"] = d.groupby("Tournament_Name")["Salary"].transform(
        lambda x: (x - x.min()) / (x.max() - x.min()) if x.max() > x.min() else 0.0)

    for w in ["1W", "2W", "3W"]:
        if w in d.columns:
            d[f"Top5_{w}"] = (d[w] <= 5).astype(float)
            d[f"Top10_{w}"] = (d[w] <= 10).astype(float)
            d[f"Top20_{w}"] = (d[w] <= 20).astype(float)
            d[f"MC_{w}"] = (d[w] == 80).astype(float)
    d["Trend_Avg"] = d[["1W", "2W", "3W"]].mean(axis=1)
    d["Form_Slope"] = d["1W"] - d["3W"]

    ch = ["CH_Finish_1", "CH_Finish_2", "CH_Finish_3"]
    d["CH_Best"] = d[ch].min(axis=1)
    d["CH_Win"] = (d["CH_Best"] == 1).astype(float)
    d["CH_Top5"] = (d["CH_Best"] <= 5).astype(float)
    d["CH_Top10"] = (d["CH_Best"] <= 10).astype(float)
    d["CH_Avg_Finish"] = d[ch].mean(axis=1)
    d["Has_CH"] = (d["CH_Events"].fillna(0) > 0).astype(int)
    d["CH_Made_Cuts"] = d["CH_Made_Cuts"].fillna(0)

    d["Odds_Salary_Ratio"] = d["Implied_Prob"] / (d["Salary"] / 50000.0)
    d["IP_per_1k_salary"] = (d["Implied_Prob"] * 100) / (d["Salary"] / 1000.0)

    d["Odds_Change_Pct"] = np.where(
        d["Win_Odds_Monday"].notna() & d["Win_Odds"].notna() & (d["Win_Odds_Monday"] > 0),
        (d["Win_Odds"] - d["Win_Odds_Monday"]) / d["Win_Odds_Monday"] * 100, np.nan)
    d["IP_Monday"] = np.where(d["Win_Odds_Monday"].notna() & (d["Win_Odds_Monday"] > 0),
                              100.0 / (d["Win_Odds_Monday"] + 100.0), np.nan)
    d["IP_Change"] = d["Implied_Prob"] - d["IP_Monday"]

    for sg in SG_COLS:
        if sg in d.columns:
            d[f"{sg}_filled"] = d[sg].fillna(0)
    return d


FEATURES = [
    "log_IP", "Implied_Prob", "Salary_Pct", "Salary_Rank",
    "Top5_1W", "Top10_1W", "Top20_1W", "MC_1W",
    "Top5_2W", "Top10_2W", "MC_2W", "Top5_3W", "Top10_3W", "MC_3W",
    "Trend_Avg", "Form_Slope",
    "CH_Win", "CH_Top5", "CH_Top10", "CH_Avg_Finish", "Has_CH", "CH_Made_Cuts", "CH_Events",
    "SG_PUTT_filled", "SG_ARG_filled", "SG_APP_filled", "SG_OTT_filled", "SG_T2G_filled", "SG_TOT_filled",
    "NO_CUT", "Is_Major", "Entries",
    "Odds_Salary_Ratio", "IP_per_1k_salary", "Odds_Change_Pct", "IP_Monday", "IP_Change",
    "Injury_Risk",
]

PARAMS = dict(objective="regression", metric="mae", n_estimators=400, learning_rate=0.04,
              max_depth=4, num_leaves=15, subsample=0.75, colsample_bytree=0.8,
              min_child_samples=6, random_state=42, verbose=-1,
              # Reproducible fit: single-thread + deterministic so the same data
              # always yields the same ownership (LightGBM is otherwise non-
              # deterministic across thread counts / machines).
              num_threads=1, deterministic=True, force_row_wise=True)


def pick_slate(df):
    name = os.environ.get("SLATE_NAME", "").strip()
    if name:
        return name
    # Otherwise the most recent tournament by Date.
    d = df.copy()
    d["_dt"] = pd.to_datetime(d["Date"], errors="coerce")
    return d.sort_values("_dt").iloc[-1]["Tournament_Name"]


def odds_equity(raw, suffix):
    """Read the Odds tab -> {normname: {win,top5,top10}} implied probabilities."""
    try:
        engine = "odf" if suffix == ".ods" else "openpyxl"
        od = pd.read_excel(io.BytesIO(raw), sheet_name="Odds", engine=engine)
    except Exception:
        return {}
    cols = {str(c).strip().lower(): c for c in od.columns}

    def g(row, *names):
        for n in names:
            if n in cols:
                return row[cols[n]]
        return None

    out = {}
    for _, r in od.iterrows():
        nm = str(g(r, "player", "name") or "").strip()
        if not nm:
            continue
        wp, t5, t10 = (american_prob(g(r, "win_odds")), american_prob(g(r, "top5_odds")),
                       american_prob(g(r, "top10_odds")))
        out[_norm(nm)] = {  # store as percentages to match impliedProb
            "winProb": _r(wp * 100, 2) if wp is not None else None,
            "top5Prob": _r(t5 * 100, 1) if t5 is not None else None,
            "top10Prob": _r(t10 * 100, 1) if t10 is not None else None,
        }
    return out


def _norm(s):
    import re
    s = str(s).lower()
    for a, b in [("é", "e"), ("ö", "o"), ("ø", "o"), ("í", "i"), ("á", "a")]:
        s = s.replace(a, b)
    s = re.sub(r"[^a-z ]", " ", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _r(v, n=3):
    return round(v, n) if v is not None and np.isfinite(v) else None


def build_from_workbook(raw, suffix):
    """Train + predict ownership for the current slate; return (golfers, meta)."""
    import lightgbm as lgb

    engine = "odf" if suffix == ".ods" else "openpyxl"
    df = pd.read_excel(io.BytesIO(raw), sheet_name="Data", engine=engine)
    if "Tournament_Name" not in df.columns:
        raise ValueError("Data tab missing Tournament_Name")

    slate_name = pick_slate(df)
    df = engineer_features(df)
    feats = [f for f in FEATURES if f in df.columns]

    train = df[df["Actual_Ownership"].notna() & (df["Tournament_Name"] != slate_name)].copy()
    slate = df[df["Tournament_Name"] == slate_name].copy()
    if len(slate) == 0:
        raise ValueError(f"No rows for slate '{slate_name}' in Data tab")
    if len(train) < 50:
        raise ValueError(f"Only {len(train)} training rows — too few to model")

    medians = train[feats].median()
    Xtr = train[feats].fillna(medians)
    ytr = np.log1p(train["Actual_Ownership"] * 100)
    model = lgb.LGBMRegressor(**PARAMS)
    model.fit(Xtr, ytr)

    preds = np.expm1(model.predict(slate[feats].fillna(medians))).clip(min=0)
    total = preds.sum() or 1.0
    calibrated = preds * (600.0 / total)  # 6 roster spots * 100%
    slate = slate.assign(
        _own=np.round(calibrated, 2),
        _ip=np.round(slate["Implied_Prob"] * 100, 2),
    )
    slate["_lev"] = np.round(slate["_ip"] / slate["_own"].replace(0, np.nan), 3)

    def tier(s):
        if pd.isna(s):
            return "NEUTRAL"
        if s >= 2.0:
            return "HIGH"
        if s >= 1.25:
            return "MEDIUM"
        if s <= 0.60:
            return "CHALK"
        return "NEUTRAL"

    odds = odds_equity(raw, suffix)
    golfers = []
    for _, r in slate.iterrows():
        name = str(r["Name"]).strip()
        sal = r.get("Salary")
        if not name or name.lower() == "nan" or pd.isna(sal):
            continue
        rec = {"name": name, "salary": int(sal)}
        for key, col in [("sgTot", "SG_TOT"), ("sgT2g", "SG_T2G"), ("sgPutt", "SG_PUTT"),
                         ("sgArg", "SG_ARG"), ("sgApp", "SG_APP"), ("sgOtt", "SG_OTT")]:
            v = _r(r.get(col))
            if v is not None:
                rec[key] = v
        rec["ownership"] = float(r["_own"]) if np.isfinite(r["_own"]) else None
        if rec["ownership"] is None:
            del rec["ownership"]
        wo = _r(r.get("Win_Odds"), 0)
        if wo is not None:
            rec["winOdds"] = wo
        ip = _r(r.get("Implied_Prob") and r["Implied_Prob"] * 100, 2)
        if ip is not None:
            rec["impliedProb"] = ip
        if np.isfinite(r["_lev"]):
            rec["leverage"] = float(r["_lev"])
        rec["leverageTier"] = tier(r["_lev"])
        eq = odds.get(_norm(name))
        if eq:
            for k in ("winProb", "top5Prob", "top10Prob"):
                if eq.get(k) is not None:
                    rec[k] = eq[k]
        golfers.append(rec)

    meta = {"slate": slate_name, "trainRows": int(len(train)),
            "trainEvents": int(train["Tournament_Name"].nunique())}
    return golfers, meta
