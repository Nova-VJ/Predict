#!/usr/bin/env python3
"""Experiment #14 evaluation: simulator p(win) alone (calibrated) and combined with V2, daily walk-forward."""
import json, sqlite3, numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
import evaluate_v2 as v2
c = sqlite3.connect(v2.DB)
bt = pd.read_sql("SELECT game_id, game_date, season, y, p_fund, open_cons, close_cons FROM bt_baseline", c)
sim = pd.read_csv("output/sim_v0.csv")
df = bt.merge(sim, on="game_id", how="inner").sort_values("game_date").reset_index(drop=True)
df = df[df.p_fund.notna()].reset_index(drop=True)
X1 = np.c_[v2.logit(df.p_home_win.clip(0.02, 0.98))]
X2 = np.c_[v2.logit(df.p_fund), v2.logit(df.p_home_win.clip(0.02, 0.98))]
df["p_sim_cal"] = np.nan; df["p_combo"] = np.nan
for d in sorted(df.game_date.unique()):
    tr = (df.game_date < d).values; te = (df.game_date == d).values
    if tr.sum() < 2000: continue
    df.loc[te, "p_sim_cal"] = LogisticRegression(C=1e6).fit(X1[tr], df.y[tr]).predict_proba(X1[te])[:, 1]
    df.loc[te, "p_combo"] = LogisticRegression(C=1e6).fit(X2[tr], df.y[tr]).predict_proba(X2[te])[:, 1]
out = {}
for s, g in df[df.season.between(2019, 2023)].groupby("season"):
    out[int(s)] = {k: round(float(v2.ll(g[k], g.y).mean()), 6) for k in ("p_fund", "p_sim_cal", "p_combo")}
    m = g[g.open_cons.notna()]
    if len(m): out[int(s)]["open_cons_same_games"] = round(float(v2.ll(m.open_cons, m.y).mean()), 6); out[int(s)]["combo_same_games"] = round(float(v2.ll(m.p_combo, m.y).mean()), 6)
dev = df[df.season.between(2019, 2023)]
out["DEV"] = {k: round(float(v2.ll(dev[k], dev.y).mean()), 6) for k in ("p_fund", "p_sim_cal", "p_combo")}
out["runs_check"] = {"sim_total_mean": round(float(df.total_runs.mean()), 3)}
print(json.dumps(out, indent=1))
df[["game_id", "season", "p_sim_cal", "p_combo", "total_runs", "p_home_f5_win", "p_f5_tie"]].to_sql("sim_v0_eval", c, if_exists="replace", index=False)
