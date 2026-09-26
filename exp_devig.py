#!/usr/bin/env python3
"""Experiment #13: which de-vig method gives the best fair probability on US closing lines."""
import sqlite3, json, sys, numpy as np, pandas as pd
from scipy.optimize import brentq
import evaluate_v2 as v2

def mult(h, a): q = np.array([1/h, 1/a]); return q[0] / q.sum()
def additive(h, a): q = np.array([1/h, 1/a]); return q[0] - (q.sum() - 1) / 2
def power(h, a):
    q = np.array([1/h, 1/a]); k = brentq(lambda k: (q**k).sum() - 1, 0.5, 3); return q[0]**k
def shin(h, a):
    q = np.array([1/h, 1/a]); S = q.sum()
    f = lambda z: (np.sqrt(z**2 + 4*(1-z)*q**2/S) - z).sum() / (2*(1-z)) - 1
    z = brentq(f, 0.0, 0.4) if f(0.0) * f(0.4) < 0 else 0.0
    return (np.sqrt(z**2 + 4*(1-z)*q[0]**2/S) - z) / (2*(1-z))
def oddsratio(h, a):
    q = np.array([1/h, 1/a]); lq = np.log(q/(1-q))
    c = brentq(lambda c: (1/(1+np.exp(-(lq - c)))).sum() - 1, -1, 1); return 1/(1+np.exp(-(lq[0]-c)))
M = {"proportional": mult, "additive": additive, "power": power, "shin": shin, "odds_ratio": oddsratio}

c = sqlite3.connect(v2.DB)
q = pd.read_sql("SELECT game_id, bookmaker, side, decimal_odds FROM odds_quotes WHERE quote_kind='last_observed' AND decimal_odds>1", c)
w = q.pivot_table(index=["game_id", "bookmaker"], columns="side", values="decimal_odds", aggfunc="first").dropna().reset_index()
op = pd.read_sql("SELECT game_id, bookmaker, side, decimal_odds FROM odds_quotes WHERE quote_kind='opening' AND decimal_odds>1", c)
wo = op.pivot_table(index=["game_id", "bookmaker"], columns="side", values="decimal_odds", aggfunc="first").dropna().reset_index()
w = w.merge(wo, on=["game_id", "bookmaker"], suffixes=("", "_open"))
w = w[w.home.between(1.15, 6) & w.away.between(1.15, 6) &
      ((1/w.home/(1/w.home+1/w.away)) - (1/w.home_open/(1/w.home_open+1/w.away_open))).abs().le(0.15)]
g = pd.read_sql("SELECT game_id, season, home_win y FROM games", c)
w = w.merge(g, on="game_id")
for name, fn in M.items():
    w[name] = [fn(h, a) for h, a in zip(w.home, w.away)]
res = {}
for split, yrs in (("DEV", [2021, 2022, 2023]), ("VALID", [2024])):
    s = w[w.season.isin(yrs)]
    per_book = {n: round(float(v2.ll(s[n], s.y).mean()), 6) for n in M}
    cons = s.groupby("game_id").agg({**{n: "mean" for n in M}, "y": "first"})
    cons_ll = {n: round(float(v2.ll(cons[n], cons.y).mean()), 6) for n in M}
    fav = s[np.minimum(s.home, s.away) < 1.6]
    fav_ll = {n: round(float(v2.ll(fav[n], fav.y).mean()), 6) for n in M}
    res[split] = {"quotes": int(len(s)), "games": int(len(cons)), "per_book_ll": per_book, "consensus_ll": cons_ll,
                  "big_favourite_quotes_ll": fav_ll}
print(json.dumps(res, indent=1))
