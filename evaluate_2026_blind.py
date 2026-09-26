#!/usr/bin/env python3
"""Experiment #3 (EXPERIMENTS.md): blind 2026 test of the frozen V2 model vs Pinnacle.

Inputs (captured 2026-09-26, see data/blind2026/):
  features_2026_sample.csv  per game side, point-in-time features from the MLB Stats API
  oddspapi_2026_sample.csv  per fixture/book/side: open, T-3h and last pre-start price
  capturas/mlb_schedule_2026_asof_*.json  official 2026 results (for Elo)
Rules are those registered in EXPERIMENTS.md #3; nothing is tuned here.
"""
import json
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))
import evaluate_v2 as v2  # noqa: E402
from build_dataset import norm  # noqa: E402
from predict_live import fitted_models  # noqa: E402
from evaluate_models import elo_preds  # noqa: E402
import sqlite3  # noqa: E402

D = ROOT / "data" / "blind2026"
SPAIN = ["leovegas.es", "bwin.es"]


def elo_2026(schedule):
    c = sqlite3.connect(v2.DB)
    g = pd.read_sql("SELECT game_id, game_date, season, home_team, away_team, home_win FROM games "
                    "WHERE season <= 2025 ORDER BY game_date, doubleheader_number, game_id", c)
    rows = [{"id": r.game_id, "date": r.game_date, "year": r.season, "home": r.home_team,
             "away": r.away_team, "y": r.home_win} for r in g.itertuples()]
    s = json.loads(pathlib.Path(schedule).read_text())["games"]
    done = sorted([x for x in s if x["status"] == "Final" and x["home_score"] is not None
                   and x["home_score"] != x["away_score"]], key=lambda x: (x["official_date"], x["game_pk"]))
    for x in done:
        rows.append({"id": x["game_pk"], "date": x["official_date"], "year": 2026, "home": norm(x["home_team"]),
                     "away": norm(x["away_team"]), "y": int(x["home_score"] > x["away_score"])})
    return elo_preds(rows, 10, 25)


def nv(h, a):
    return (1 / h) / (1 / h + 1 / a)


def boot_mean(x, seed=3):
    x = np.asarray(x, float)
    if len(x) < 2:
        return [None, None]
    r = np.random.default_rng(seed).choice(x, (5000, len(x))).mean(1)
    return [round(float(np.percentile(r, 2.5)), 4), round(float(np.percentile(r, 97.5)), 4)]


def main():
    f = pd.read_csv(D / "features_2026_sample.csv")
    o = pd.read_csv(D / "oddspapi_2026_sample.csv")
    sched = sorted((ROOT / "capturas").glob("mlb_schedule_2026_asof_*.json"))[-1]
    elo = elo_2026(sched)
    fund, stack = fitted_models()

    h = f[f.side == "home"].set_index("pk")
    a = f[f.side == "away"].set_index("pk")
    g = h.join(a, rsuffix="_a")
    g = g[g.home_score != g.away_score]
    g["y"] = (g.home_score > g.away_score).astype(int)
    g["p_elo"] = g.index.map(elo)
    rows = []
    for lu in ("prev", "actual"):
        X = pd.DataFrame({"elo_logit": v2.logit(g.p_elo)}, index=g.index)
        for k in ("sp_fip", "sp_k", "sp_bb", "sp_outs"):
            X[f"diff_{k}"] = (g[k] - g[k + "_a"]).fillna(0)
        X["diff_bp_fip"] = g.bp_fip - g.bp_fip_a
        X["diff_bp_pitches_3d"] = g.bp_p3 - g.bp_p3_a
        X["diff_lineup_woba"] = (g[f"lineup_woba_{lu}"] - g[f"lineup_woba_{lu}_a"]).fillna(0)
        g[f"p_fund_{lu}"] = fund.predict_proba(X[v2.FUND])[:, 1]

    # odds: wide per fixture
    o["home"], o["away"] = o.home.map(norm), o.away.map(norm)
    o["start"] = pd.to_datetime(o.start, utc=True)
    g["start"] = pd.to_datetime(g.start_utc, utc=True)
    g["hn"], g["an"] = g.home.map(norm), g.away.map(norm)
    out = []
    for pk, r in g.iterrows():
        m = o[(o.home == r.hn) & (o.away == r.an) & ((o.start - r.start).abs() < pd.Timedelta(hours=3))]
        if m.empty:
            continue
        pin = m[m.book == "pinnacle"].set_index("side")
        if not {"home", "away"} <= set(pin.index) or pin[["t3h", "close"]].isna().any().any():
            continue
        p_t3 = nv(pin.at["home", "t3h"], pin.at["away", "t3h"])
        p_cl = nv(pin.at["home", "close"], pin.at["away", "close"])
        p_stack = float(stack.predict_proba(np.c_[[v2.logit(p_t3)], [v2.logit(r.p_fund_prev)]])[:, 1][0])
        rec = {"pk": pk, "date": r.date, "y": r.y, "p_elo": r.p_elo, "p_fund": r.p_fund_prev,
               "p_fund_actual_lineup": r.p_fund_actual, "p_pin_t3h": p_t3, "p_pin_close": p_cl, "p_stack": p_stack}
        for name, p in (("model", p_stack), ("control", p_t3)):
            best = None
            for book in SPAIN:
                s = m[m.book == book].set_index("side")
                if not {"home", "away"} <= set(s.index) or s.t3h.isna().any():
                    continue
                for side, ps, price in (("home", p, s.at["home", "t3h"]), ("away", 1 - p, s.at["away", "t3h"])):
                    ev = ps * price - 1
                    if best is None or ev > best[2]:
                        best = (side, price, ev, book)
            if best and best[2] > v2.EDGE_MIN:
                side, price, ev, book = best
                won = r.y == 1 if side == "home" else r.y == 0
                fair = 1 / (p_cl if side == "home" else 1 - p_cl)
                rec[f"{name}_bet"] = f"{side}@{price}({book})"
                rec[f"{name}_profit"] = price - 1 if won else -1.0
                rec[f"{name}_clv"] = price / fair - 1
        out.append(rec)
    res = pd.DataFrame(out)
    res.to_csv(D / "blind2026_results.csv", index=False)
    ll = lambda c: round(float(v2.ll(res[c], res.y).mean()), 5)
    rep = {"games_evaluated": int(len(res)),
           "log_loss": {c: ll(c) for c in ("p_elo", "p_fund", "p_fund_actual_lineup", "p_stack", "p_pin_t3h", "p_pin_close")},
           "stack_minus_pin_t3h_ci": boot_mean(v2.ll(res.p_stack, res.y) - v2.ll(res.p_pin_t3h, res.y))}
    for name in ("model", "control"):
        b = res[res.get(f"{name}_profit").notna()] if f"{name}_profit" in res else res.iloc[0:0]
        rep[name] = {"bets": int(len(b))}
        if len(b):
            rep[name].update({"roi": round(float(b[f"{name}_profit"].mean()), 4),
                              "mean_clv": round(float(b[f"{name}_clv"].mean()), 4),
                              "clv_ci95": boot_mean(b[f"{name}_clv"]),
                              "share_clv_pos": round(float((b[f"{name}_clv"] > 0).mean()), 3)})
    (D / "blind2026_report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
