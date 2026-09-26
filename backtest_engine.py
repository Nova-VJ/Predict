#!/usr/bin/env python3
"""Daily walk-forward backtest engine (protocol in EXPERIMENTS.md).

For every game day D from 2016 on, the fundamentals model is refitted on all games
played before D (2015 onward) and predicts the games of D. From 2021 on, a market stack
logit(p) = a*logit(market) + b*logit(p_fund) [+ extra market terms] + c is refitted
the same way on earlier days with odds. Nothing ever sees day D before predicting it.

Usage:
  python backtest_engine.py --name baseline
  python backtest_engine.py --name platoon --extra diff_platoon
  python backtest_engine.py --name movement --stack-extra move
Results: output/backtests/<name>.json and table bt_<name> in SQLite.
Split metrics are reported for DEV (2019-2023), VALID (2024) and TEST (2025) - but TEST is
printed only with --show-test (to be used once, see protocol).
"""
import argparse
import json
import pathlib
import sqlite3
import time

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import evaluate_v2 as v2
from evaluate_models import elo_preds

BASE = pathlib.Path(__file__).resolve().parent
OUT = BASE / "output" / "backtests"
SPLITS = {"DEV": range(2019, 2024), "VALID": [2024], "TEST": [2025]}
REFIT_EVERY_DAYS = 1


def load_frame(extra):
    c = sqlite3.connect(v2.DB)
    g = pd.read_sql("SELECT game_id, game_date, season, home_team, away_team, home_win AS y, park_id, "
                    "doubleheader_number FROM games WHERE season BETWEEN 2014 AND 2025 "
                    "ORDER BY game_date, doubleheader_number, game_id", c)
    gl = [{"id": r.game_id, "date": r.game_date, "year": r.season, "home": r.home_team,
           "away": r.away_team, "y": r.y} for r in g.itertuples()]
    g["p_elo"] = g.game_id.map(elo_preds(gl, 10, 25))
    g["elo_logit"] = v2.logit(g.p_elo)
    g = g.merge(pd.read_sql("SELECT * FROM player_features", c), on="game_id", how="left")
    for tbl in extra.get("tables", []):
        g = g.merge(pd.read_sql(f"SELECT * FROM {tbl}", c), on="game_id", how="left")
    g = g.merge(v2.market_frame(c), left_on="game_id", right_index=True, how="left")
    return g[g.season >= 2015].reset_index(drop=True)


def walk_forward(df, feats, stack_extra):
    df = df.copy()
    df[feats] = df[feats].fillna(0.0)
    days = sorted(df.game_date.unique())
    p_fund = np.full(len(df), np.nan)
    model, last_fit = None, None
    t0 = time.time()
    for d in days:
        if d < "2016-03-01":
            continue
        idx = np.where(df.game_date.values == d)[0]
        if model is None or last_fit is None or (pd.Timestamp(d) - pd.Timestamp(last_fit)).days >= REFIT_EVERY_DAYS:
            tr = df.game_date.values < d
            model = make_pipeline(StandardScaler(), LogisticRegression(C=v2.C, max_iter=1000))
            model.fit(df.loc[tr, feats], df.loc[tr, "y"])
            last_fit = d
        p_fund[idx] = model.predict_proba(df.loc[idx, feats])[:, 1]
    df["p_fund"] = p_fund
    # market stacks, refit daily on earlier days with odds (from 2021)
    for anchor in ("open_cons", "close_cons"):
        col = f"p_stack_{anchor}"
        df[col] = np.nan
        ok = df[anchor].notna() & df.p_fund.notna()
        X = [v2.logit(df[anchor]), v2.logit(df.p_fund)]
        if "move" in stack_extra and anchor == "close_cons":
            X.append(v2.logit(df.close_cons) - v2.logit(df.open_cons))
        X = np.c_[tuple(X)]
        odays = sorted(df.loc[ok, "game_date"].unique())
        for d in odays:
            tr = ok & (df.game_date < d)
            if tr.sum() < 800:
                continue
            te = ok & (df.game_date == d)
            m = LogisticRegression(C=1e6, max_iter=1000).fit(X[tr.values], df.loc[tr, "y"])
            df.loc[te, col] = m.predict_proba(X[te.values])[:, 1]
    return df, round(time.time() - t0, 1)


def season_metrics(df):
    out = {}
    for s, g in df.groupby("season"):
        r = {"n": int(len(g)), "ll_elo": float(v2.ll(g.p_elo, g.y).mean()),
             "ll_fund": float(v2.ll(g.p_fund, g.y).mean()) if g.p_fund.notna().all() else None}
        m = g[g.open_cons.notna() & g.close_cons.notna() & g.p_stack_open_cons.notna()]
        if len(m) > 200:
            r.update({"n_mkt": int(len(m)),
                      "ll_open": float(v2.ll(m.open_cons, m.y).mean()),
                      "ll_close": float(v2.ll(m.close_cons, m.y).mean()),
                      "ll_fund_mkt": float(v2.ll(m.p_fund, m.y).mean()),
                      "ll_stack_open": float(v2.ll(m.p_stack_open_cons, m.y).mean()),
                      "ll_stack_close": float(v2.ll(m.p_stack_close_cons, m.y).mean())})
        out[int(s)] = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items()}
    return out


def split_summary(df, years):
    s = df[df.season.isin(list(years))]
    res = {"games": int(len(s)), "ll_fund": round(float(v2.ll(s.p_fund, s.y).mean()), 6)}
    m = s[s.open_cons.notna() & s.p_stack_open_cons.notna()]
    if len(m):
        res.update({"games_mkt": int(len(m)),
                    "ll_stack_open_minus_open": round(float((v2.ll(m.p_stack_open_cons, m.y) - v2.ll(m.open_cons, m.y)).mean()), 6),
                    "ll_stack_close_minus_close": round(float((v2.ll(m.p_stack_close_cons, m.y) - v2.ll(m.close_cons, m.y)).mean()), 6),
                    "ci_stack_open_minus_open": v2.block_ci(m, "p_stack_open_cons", "open_cons", 1),
                    "ci_stack_close_minus_close": v2.block_ci(m, "p_stack_close_cons", "close_cons", 2)})
        for name, col, when in (("open", "p_stack_open_cons", "open"), ("close", "p_stack_close_cons", "close")):
            b = v2.bets(m, col, when)
            res[f"bets_{name}"] = v2.bet_summary(b, 3)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--extra", nargs="*", default=[], help="extra feature columns")
    ap.add_argument("--tables", nargs="*", default=[], help="extra SQLite tables keyed by game_id")
    ap.add_argument("--stack-extra", nargs="*", default=[])
    ap.add_argument("--show-test", action="store_true")
    a = ap.parse_args()
    feats = v2.FUND + a.extra
    df = load_frame({"tables": a.tables})
    df, secs = walk_forward(df, feats, a.stack_extra)
    rep = {"name": a.name, "features": feats, "stack_extra": a.stack_extra, "refit_every_days": REFIT_EVERY_DAYS,
           "seconds": secs, "seasons": season_metrics(df),
           "DEV": split_summary(df, SPLITS["DEV"]), "VALID": split_summary(df, SPLITS["VALID"])}
    if a.show_test:
        rep["TEST"] = split_summary(df, SPLITS["TEST"])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{a.name}.json").write_text(json.dumps(rep, indent=1, default=str))
    keep = ["game_id", "game_date", "season", "y", "p_elo", "p_fund", "open_cons", "close_cons",
            "p_stack_open_cons", "p_stack_close_cons"]
    df[keep].to_sql(f"bt_{a.name}", sqlite3.connect(v2.DB), if_exists="replace", index=False)
    show = {k: rep[k] for k in ("name", "seconds", "DEV")}
    if not a.show_test:
        show["VALID"] = "(hidden: see JSON when deciding)"
    print(json.dumps(show, indent=1, default=str))
    print("per season (DEV only):")
    for s in range(2016, 2024):
        r = rep["seasons"].get(s, {})
        print(s, {k: r.get(k) for k in ("ll_elo", "ll_fund", "ll_open", "ll_close", "ll_stack_open", "ll_stack_close")})


if __name__ == "__main__":
    main()
