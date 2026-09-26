#!/usr/bin/env python3
"""V2 evaluation: fundamentals (Elo + starter + bullpen + lineup) and market-anchored stack.

Everything is walk-forward by season: a season is predicted only with models fitted on
earlier seasons. Hyperparameters are declared here and NOT tuned on test seasons:
  * LogisticRegression C=1.0 on standardized features.
  * Elo K=10, home=25 (chosen on 2023 by evaluate_models.py; inherited, not re-tuned).
  * Betting rule: back a side when model_p * price - 1 > EDGE_MIN (2 %), flat 1 unit.

Market benchmarks built from the SBR archive (no verified timestamps):
  * open_cons  : mean de-vigged opening probability across books.
  * close_cons : mean de-vigged last-observed probability across books, after dropping
                 book quotes that look in-play (|p_last - p_open| > 0.15 or price outside
                 [1.15, 6.0]). 2021 DraftKings/FanDuel contain ~8 % in-play quotes.
Bet prices: bet365 (licensed in Spain), opening and last-observed.

Output: output/v2_report.json and table v2_predictions.
"""
import collections
import json
import math
import pathlib
import random
import sqlite3

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from evaluate_models import elo_preds

BASE = pathlib.Path(__file__).resolve().parent
DB = BASE / "output" / "mlb_time_machine.sqlite"
C = 1.0
EDGE_MIN = 0.02
BET_BOOK = "bet365"
FUND = ["elo_logit", "diff_sp_fip", "diff_sp_k", "diff_sp_bb", "diff_sp_outs",
        "diff_bp_fip", "diff_bp_pitches_3d", "diff_lineup_woba"]


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def ll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def fit(X, y):
    m = make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=1000))
    m.fit(X, y)
    return m


def market_frame(c):
    q = pd.read_sql("SELECT game_id, bookmaker, quote_kind, side, decimal_odds FROM odds_quotes "
                    "WHERE decimal_odds > 1", c)
    w = q.pivot_table(index=["game_id", "bookmaker"], columns=["quote_kind", "side"],
                      values="decimal_odds", aggfunc="first")
    w.columns = [f"{k}_{s}" for k, s in w.columns]
    w = w.reset_index()
    for k in ("opening", "last_observed"):
        ih, ia = 1 / w[f"{k}_home"], 1 / w[f"{k}_away"]
        w[f"p_{k}"] = ih / (ih + ia)
    ok_close = ((w["p_last_observed"] - w["p_opening"]).abs() <= 0.15)
    for s in ("home", "away"):
        ok_close &= w[f"last_observed_{s}"].between(1.15, 6.0)
    w["p_close_clean"] = w["p_last_observed"].where(ok_close)
    g = w.groupby("game_id").agg(open_cons=("p_opening", "mean"),
                                 close_cons=("p_close_clean", "mean"),
                                 n_books=("p_opening", "count"))
    b = w[w.bookmaker == BET_BOOK].set_index("game_id")
    b = b.assign(close_ok=ok_close[w.bookmaker == BET_BOOK].values)
    b = b[["opening_home", "opening_away", "last_observed_home", "last_observed_away", "close_ok"]]
    b.columns = ["b_open_home", "b_open_away", "b_close_home", "b_close_away", "b_close_ok"]
    return g.join(b, how="left")


def block_ci(df, col_a, col_b, seed):
    """95 % CI of mean log-loss difference (a - b), resampling whole days."""
    d = (ll(df[col_a], df.y) - ll(df[col_b], df.y)).groupby(df.game_date).agg(["sum", "count"])
    s, n = d["sum"].values, d["count"].values
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(2000, len(d)))
    draws = s[idx].sum(1) / n[idx].sum(1)
    return [float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))]


def summarize(df, cols):
    out = {}
    for col in cols:
        v = df[col].notna()
        out[col] = {"n": int(v.sum()),
                    "log_loss": round(float(ll(df.loc[v, col], df.loc[v, "y"]).mean()), 6),
                    "brier": round(float(((df.loc[v, col] - df.loc[v, "y"]) ** 2).mean()), 6)}
    return out


def bets(df, pcol, when):
    """Flat 1-unit bets at bet365 `when` price (open/close); returns rows."""
    rows = []
    for r in df.itertuples():
        p = getattr(r, pcol)
        ph, pa = getattr(r, f"b_{when}_home"), getattr(r, f"b_{when}_away")
        if pd.isna(p) or pd.isna(ph) or pd.isna(pa):
            continue
        if when == "close" and not r.b_close_ok:
            continue
        ev_h, ev_a = p * ph - 1, (1 - p) * pa - 1
        side, price, ev = ("home", ph, ev_h) if ev_h >= ev_a else ("away", pa, ev_a)
        if ev <= EDGE_MIN:
            continue
        won = r.y == 1 if side == "home" else r.y == 0
        clv = None
        if when == "open" and not pd.isna(r.close_cons):
            fair_close = 1 / (r.close_cons if side == "home" else 1 - r.close_cons)
            clv = price / fair_close - 1
        rows.append({"season": r.season, "date": r.game_date, "ev": ev,
                     "profit": price - 1 if won else -1.0, "clv": clv})
    return pd.DataFrame(rows)


def bet_summary(b, seed):
    if b.empty:
        return {"bets": 0}
    days = b.groupby("date")["profit"].agg(["sum", "count"])
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(days), size=(2000, len(days)))
    roi = days["sum"].values[idx].sum(1) / days["count"].values[idx].sum(1)
    out = {"bets": int(len(b)), "mean_ev_claimed": round(float(b.ev.mean()), 4),
           "roi": round(float(b.profit.mean()), 4),
           "roi_ci95": [round(float(np.percentile(roi, 2.5)), 4), round(float(np.percentile(roi, 97.5)), 4)]}
    if b.clv.notna().any():
        out["mean_clv_vs_clean_close"] = round(float(b.clv.mean()), 4)
        out["share_clv_positive"] = round(float((b.clv > 0).mean()), 4)
    return out


def main():
    c = sqlite3.connect(DB)
    games = pd.read_sql("SELECT game_id, game_date, season, home_team, away_team, home_win AS y, "
                        "doubleheader_number FROM games ORDER BY game_date, doubleheader_number, game_id", c)
    glist = [{"id": r.game_id, "date": r.game_date, "year": r.season, "home": r.home_team,
              "away": r.away_team, "y": r.y} for r in games.itertuples()]
    games["p_elo"] = games.game_id.map(elo_preds(glist, 10, 25))
    games["elo_logit"] = logit(games.p_elo)
    pf = pd.read_sql("SELECT * FROM player_features", c)
    df = games.merge(pf, on="game_id", how="left").merge(market_frame(c), left_on="game_id",
                                                        right_index=True, how="left")
    df = df[df.season >= 2015].reset_index(drop=True)
    for col in FUND:
        df[col] = df[col].fillna(0.0)  # missing diff -> neutral; coverage reported below
    coverage = {"games": int(len(df)),
                "with_both_starters": int(df.home_sp_id.notna().__and__(df.away_sp_id.notna()).sum()),
                "with_both_lineups": int(df.home_lineup_woba.notna().__and__(df.away_lineup_woba.notna()).sum()),
                "with_open_cons": int(df.open_cons.notna().sum()),
                "with_clean_close_cons": int(df.close_cons.notna().sum())}

    # ---- 1. fundamentals, walk-forward from 2018 ----
    df["p_fund"] = np.nan
    coefs = {}
    for year in range(2018, 2026):
        tr, te = df.season < year, df.season == year
        m = fit(df.loc[tr, FUND], df.loc[tr, "y"])
        df.loc[te, "p_fund"] = m.predict_proba(df.loc[te, FUND])[:, 1]
        coefs[year] = dict(zip(FUND, np.round(m[-1].coef_[0], 4).tolist()))

    # ---- 2. market-anchored stacks (3 params): logit(mkt) + logit(fund) ----
    for anchor in ("open_cons", "close_cons"):
        col = f"p_stack_{anchor}"
        df[col] = np.nan
        for year in range(2022, 2026):
            tr = (df.season < year) & (df.season >= 2021) & df[anchor].notna() & df.p_fund.notna()
            te = (df.season == year) & df[anchor].notna() & df.p_fund.notna()
            X = lambda s: np.c_[logit(df.loc[s, anchor]), logit(df.loc[s, "p_fund"])]
            m = LogisticRegression(C=1e6, max_iter=1000).fit(X(tr), df.loc[tr, "y"])
            df.loc[te, col] = m.predict_proba(X(te))[:, 1]
            coefs[f"stack_{anchor}_{year}"] = {"w_market": round(float(m.coef_[0][0]), 4),
                                               "w_fund": round(float(m.coef_[0][1]), 4),
                                               "intercept": round(float(m.intercept_[0]), 4)}

    report = {"coverage": coverage, "hyperparameters": {"C": C, "edge_min": EDGE_MIN, "bet_book": BET_BOOK,
                                                         "elo": "K=10 home=25"},
              "coefficients": coefs, "seasons": {}}

    # ---- sports-only comparison 2018-2025 ----
    for year in range(2018, 2026):
        s = df[df.season == year]
        report["seasons"][year] = {"all_games": summarize(s, ["p_elo", "p_fund"])}
        report["seasons"][year]["fund_minus_elo_ci"] = block_ci(s, "p_fund", "p_elo", year)

    # ---- same-sample comparison with market 2022-2025 ----
    for year in range(2022, 2026):
        s = df[(df.season == year) & df.open_cons.notna() & df.close_cons.notna()]
        r = report["seasons"][year]
        r["market_sample"] = summarize(s, ["p_elo", "p_fund", "open_cons", "close_cons",
                                           "p_stack_open_cons", "p_stack_close_cons"])
        r["fund_minus_open_ci"] = block_ci(s, "p_fund", "open_cons", year)
        r["fund_minus_close_ci"] = block_ci(s, "p_fund", "close_cons", year)
        r["stack_open_minus_open_ci"] = block_ci(s, "p_stack_open_cons", "open_cons", year)
        r["stack_close_minus_close_ci"] = block_ci(s, "p_stack_close_cons", "close_cons", year)

    # ---- betting diagnostics (hypothetical, unverified timestamps) ----
    test = df[df.season.between(2022, 2025)]
    report["betting"] = {}
    for name, pcol, when in (("fund_at_open", "p_fund", "open"),
                             ("stack_open_at_open", "p_stack_open_cons", "open"),
                             ("fund_at_close", "p_fund", "close"),
                             ("stack_close_at_close", "p_stack_close_cons", "close")):
        b = bets(test, pcol, when)
        report["betting"][name] = {"all": bet_summary(b, 1)}
        for year in range(2022, 2026):
            report["betting"][name][year] = bet_summary(b[b.season == year] if len(b) else b, year)

    # calibration of fundamentals 2022-2025
    t = df[df.season.between(2022, 2025)]
    bins = pd.cut(t.p_fund, [0, .35, .4, .45, .5, .55, .6, .65, 1])
    report["calibration_p_fund_2022_2025"] = [
        {"bin": str(k), "n": int(len(v)), "pred": round(float(v.p_fund.mean()), 4), "actual": round(float(v.y.mean()), 4)}
        for k, v in t.groupby(bins, observed=True)]

    (BASE / "output" / "v2_report.json").write_text(json.dumps(report, indent=1, default=str))
    keep = ["game_id", "game_date", "season", "y", "p_elo", "p_fund", "open_cons", "close_cons",
            "p_stack_open_cons", "p_stack_close_cons"]
    df[keep].to_sql("v2_predictions", c, if_exists="replace", index=False)
    c.commit()
    print(json.dumps({k: report[k] for k in ("coverage",)}, indent=1))
    for y, r in report["seasons"].items():
        line = f"{y}: elo {r['all_games']['p_elo']['log_loss']} fund {r['all_games']['p_fund']['log_loss']}"
        if "market_sample" in r:
            m = r["market_sample"]
            line += (f" | mkt n={m['open_cons']['n']} open {m['open_cons']['log_loss']} close {m['close_cons']['log_loss']}"
                     f" fund {m['p_fund']['log_loss']} stackO {m['p_stack_open_cons']['log_loss']}"
                     f" stackC {m['p_stack_close_cons']['log_loss']}")
        print(line)
    print(json.dumps(report["betting"], indent=1))
    print(json.dumps({k: v for k, v in coefs.items() if str(k).startswith("stack")}, indent=1))


if __name__ == "__main__":
    main()
