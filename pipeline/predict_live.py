#!/usr/bin/env python3
"""Pre-registered live predictions for one MLB day.

Inputs (all captured BEFORE first pitch, UTC times in file names):
  --features  CSV from the MLB Stats API feature capture (one row per game side)
  --odds      CSV of moneyline prices (home,away,start_utc,book,home_price,away_price)
  --schedule  official 2026 schedule capture with finished results (for Elo)

Model: the V2 fundamentals model refitted on 2015-2025, then the V2 market stack
(logit market consensus + logit fundamentals) fitted on 2021-2025 archived openers.
Nothing here is tuned on 2026.

Decision rule (fixed in advance): paper bet 1 unit on the side with the highest
p_stack * price - 1 above 2 %, using only books licensed in Spain (bet365, unibet).
Output: appends to data/live/predictions.csv; never rewrites earlier rows.
"""
import argparse
import datetime as dt
import json
import math
import pathlib
import sqlite3
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))
from build_dataset import norm  # noqa: E402
from evaluate_models import elo_preds  # noqa: E402
import evaluate_v2 as v2  # noqa: E402

CONSENSUS_BOOKS = ["bet365", "betmgm", "betrivers", "caesars", "draftkings", "fanduel"]
SPAIN_BOOKS = ["bet365", "unibet"]
MODEL_VERSION = "v2.0-frozen-2026-09-26"


def elo_today(schedule_path, today, matchups):
    c = sqlite3.connect(ROOT / "output" / "mlb_time_machine.sqlite")
    g = pd.read_sql("SELECT game_id, game_date, season, home_team, away_team, home_win FROM games "
                    "ORDER BY game_date, doubleheader_number, game_id", c)
    rows = [{"id": r.game_id, "date": r.game_date, "year": r.season, "home": r.home_team,
             "away": r.away_team, "y": r.home_win} for r in g.itertuples()]
    sched = json.loads(pathlib.Path(schedule_path).read_text())
    done = [x for x in sched["games"] if x["status"] == "Final" and x["official_date"] < today
            and x["home_score"] is not None and x["home_score"] != x["away_score"]]
    for x in sorted(done, key=lambda x: (x["official_date"], x["game_pk"])):
        rows.append({"id": f"mlb{x['game_pk']}", "date": x["official_date"], "year": 2026,
                     "home": norm(x["home_team"]), "away": norm(x["away_team"]),
                     "y": int(x["home_score"] > x["away_score"])})
    for pk, h, a in matchups:
        rows.append({"id": f"today{pk}", "date": today, "year": 2026, "home": h, "away": a, "y": 0})
    p = elo_preds(rows, 10, 25)
    return {pk: p[f"today{pk}"] for pk, _, _ in matchups}, len(done)


def fitted_models():
    c = sqlite3.connect(v2.DB)
    games = pd.read_sql("SELECT game_id, game_date, season, home_team, away_team, home_win AS y, "
                        "doubleheader_number FROM games ORDER BY game_date, doubleheader_number, game_id", c)
    gl = [{"id": r.game_id, "date": r.game_date, "year": r.season, "home": r.home_team,
           "away": r.away_team, "y": r.y} for r in games.itertuples()]
    games["elo_logit"] = v2.logit(games.game_id.map(elo_preds(gl, 10, 25)))
    df = games.merge(pd.read_sql("SELECT * FROM player_features", c), on="game_id", how="left")
    df = df[df.season >= 2015]
    df[v2.FUND] = df[v2.FUND].fillna(0.0)
    fund = v2.fit(df[v2.FUND], df.y)
    pr = pd.read_sql("SELECT game_id, season, y, p_fund, open_cons FROM v2_predictions", c)
    pr = pr[(pr.season >= 2021) & pr.p_fund.notna() & pr.open_cons.notna()]
    stack = LogisticRegression(C=1e6, max_iter=1000).fit(
        np.c_[v2.logit(pr.open_cons), v2.logit(pr.p_fund)], pr.y)
    return fund, stack


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--odds", required=True)
    ap.add_argument("--schedule", required=True)
    ap.add_argument("--label", default="t3h")
    a = ap.parse_args()
    f = pd.read_csv(a.features)
    today = (pd.Timestamp(f.start_utc.min()) - pd.Timedelta(hours=10)).date().isoformat()
    wide = f[f.side == "home"].set_index("pk").join(f[f.side == "away"].set_index("pk"), rsuffix="_a")
    matchups = [(pk, norm(r.home), norm(r.away)) for pk, r in wide.iterrows()]
    elo, n2026 = elo_today(a.schedule, today, matchups)
    fund, stack = fitted_models()

    odds = pd.read_csv(a.odds)
    from teams import abbr
    odds["home"], odds["away"] = odds.home.map(abbr), odds.away.map(abbr)
    odds = odds[odds.home_price.notna() & odds.away_price.notna() & (odds.book != "kalshi")]
    odds["p_home_nv"] = (1 / odds.home_price) / (1 / odds.home_price + 1 / odds.away_price)
    out = []
    for pk, r in wide.iterrows():
        x = {"elo_logit": v2.logit(elo[pk])}
        for k in ("sp_fip", "sp_k", "sp_bb", "sp_outs"):
            hv, av = r[k], r[k + "_a"]
            x[f"diff_{k}"] = 0.0 if (pd.isna(hv) or pd.isna(av)) else hv - av
        x["diff_bp_fip"] = r.bp_fip - r.bp_fip_a
        x["diff_bp_pitches_3d"] = r.bp_p3 - r.bp_p3_a
        x["diff_lineup_woba"] = r.lineup_woba - r.lineup_woba_a
        p_fund = float(fund.predict_proba(pd.DataFrame([x])[v2.FUND])[:, 1][0])
        o = odds[(odds.home == r.home) & (odds.away == r.away)]
        cons = o[o.book.isin(CONSENSUS_BOOKS)].p_home_nv.mean()
        pin = o[o.book == "pinnacle"].p_home_nv.mean()
        p_stack = float(stack.predict_proba(np.c_[[v2.logit(cons)], [v2.logit(p_fund)]])[:, 1][0])
        best = None
        for _, b in o[o.book.isin(SPAIN_BOOKS)].iterrows():
            for side, p, price in (("home", p_stack, b.home_price), ("away", 1 - p_stack, b.away_price)):
                ev = p * price - 1
                if best is None or ev > best[3]:
                    best = (side, b.book, price, ev)
        flags = []
        if pd.isna(r.sp_id) or pd.isna(r.sp_id_a):
            flags.append("probable_missing")
        if (r.sp_rest or 0) > 30 or (r.sp_rest_a or 0) > 30:
            flags.append("starter_long_layoff")
        if (r.sp_outs < 13 if not pd.isna(r.sp_outs) else False) or (r.sp_outs_a < 13 if not pd.isna(r.sp_outs_a) else False):
            flags.append("opener_or_bulk")
        bet = best is not None and best[3] > v2.EDGE_MIN and not flags
        out.append({"model_version": MODEL_VERSION, "label": a.label,
                    "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    "features_file": pathlib.Path(a.features).name, "odds_file": pathlib.Path(a.odds).name,
                    "game_pk": pk, "start_utc": r.start_utc, "home": r.home, "away": r.away,
                    "p_elo": round(elo[pk], 4), "p_fund": round(p_fund, 4), "p_consensus_nv": round(cons, 4),
                    "p_pinnacle_nv": None if pd.isna(pin) else round(pin, 4), "p_stack": round(p_stack, 4),
                    "best_side": best[0] if best else None, "best_book": best[1] if best else None,
                    "best_price": best[2] if best else None, "best_ev": round(best[3], 4) if best else None,
                    "flags": ";".join(flags), "paper_bet": bool(bet),
                    "lineup_src": f"{r.lineup_src}/{r.lineup_src_a}"})
    res = pd.DataFrame(out).sort_values("start_utc")
    path = ROOT / "data" / "live" / "predictions.csv"
    res.to_csv(path, mode="a", header=not path.exists(), index=False)
    print(f"2026 finished games used for Elo: {n2026}")
    print(res[["start_utc", "home", "away", "p_elo", "p_fund", "p_consensus_nv", "p_pinnacle_nv", "p_stack",
               "best_side", "best_book", "best_price", "best_ev", "flags", "paper_bet"]].to_string(index=False))


if __name__ == "__main__":
    main()
