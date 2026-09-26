#!/usr/bin/env python3
"""Experiment: pure line shopping at the opener (no model).
Fair price = median de-vigged probability of the OTHER books (leave-one-out, US consensus logic).
Bet 1u when price * fair_p - 1 > threshold at any book; ROI and CLV vs clean closing consensus.
"""
import sqlite3, sys, json, numpy as np, pandas as pd
import evaluate_v2 as v2
TH = float(sys.argv[1]) if len(sys.argv) > 1 else 0.02
YEARS = [int(y) for y in sys.argv[2].split(",")] if len(sys.argv) > 2 else [2021, 2022, 2023]
c = sqlite3.connect(v2.DB)
q = pd.read_sql("SELECT game_id, bookmaker, quote_kind, side, decimal_odds FROM odds_quotes WHERE decimal_odds>1 AND quote_kind='opening'", c)
w = q.pivot_table(index=["game_id", "bookmaker"], columns="side", values="decimal_odds", aggfunc="first").dropna().reset_index()
w["p"] = (1 / w.home) / (1 / w.home + 1 / w.away)
g = pd.read_sql("SELECT game_id, game_date, season, home_win y FROM games", c).set_index("game_id")
close = v2.market_frame(c)["close_cons"]
rows = []
for gid, b in w.groupby("game_id"):
    if gid not in g.index or len(b) < 4 or pd.isna(close.get(gid)):
        continue
    s = g.loc[gid]
    if s.season not in YEARS:
        continue
    best = None
    for i, r in b.iterrows():
        fair = b.drop(i).p.median()
        for side, pr, pf in (("home", r.home, fair), ("away", r.away, 1 - fair)):
            ev = pr * pf - 1
            if best is None or ev > best[0]:
                best = (ev, side, pr, r.bookmaker)
    if best[0] > TH:
        ev, side, pr, bk = best
        won = s.y == 1 if side == "home" else s.y == 0
        pc = close[gid] if side == "home" else 1 - close[gid]
        rows.append({"season": s.season, "date": s.game_date, "ev": ev, "book": bk, "profit": pr - 1 if won else -1.0, "clv": pr * pc - 1})
b = pd.DataFrame(rows)
print(json.dumps({"threshold": TH, "years": YEARS, "all": v2.bet_summary(b, 1),
                  "by_season": {int(k): v2.bet_summary(v, 2) for k, v in b.groupby("season")},
                  "by_book": b.groupby("book").size().to_dict()}, indent=1))
