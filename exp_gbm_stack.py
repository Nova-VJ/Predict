#!/usr/bin/env python3
"""Experiment: non-linear stack (gradient boosting) on market opener + V2 features, weekly refit, DEV only."""
import sqlite3, json, numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
import evaluate_v2 as v2
c = sqlite3.connect(v2.DB)
bt = pd.read_sql("SELECT * FROM bt_baseline", c)
pf = pd.read_sql("SELECT * FROM player_features", c)
df = bt.merge(pf, on="game_id", how="left")
df = df[df.open_cons.notna() & df.p_fund.notna() & (df.season <= 2023)].sort_values("game_date").reset_index(drop=True)
F = ["diff_sp_fip", "diff_sp_k", "diff_sp_bb", "diff_sp_outs", "diff_bp_fip", "diff_bp_pitches_3d", "diff_lineup_woba"]
X = np.c_[v2.logit(df.open_cons), v2.logit(df.p_fund), df[F].fillna(0).values]
df["p_gbm"] = np.nan
days = sorted(df.game_date.unique()); last = None; m = None
for d in days:
    tr = (df.game_date < d).values
    if tr.sum() < 1500: continue
    if last is None or (pd.Timestamp(d) - pd.Timestamp(last)).days >= 7:
        m = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=100,
                                           l2_regularization=1.0, random_state=0).fit(X[tr], df.y[tr]); last = d
    te = (df.game_date == d).values
    df.loc[te, "p_gbm"] = m.predict_proba(X[te])[:, 1]
s = df[df.p_gbm.notna() & df.p_stack_open_cons.notna()]
out = {str(y): {"n": int(len(g)), "gbm_minus_open": round(float((v2.ll(g.p_gbm, g.y) - v2.ll(g.open_cons, g.y)).mean()), 6),
                "stack_minus_open": round(float((v2.ll(g.p_stack_open_cons, g.y) - v2.ll(g.open_cons, g.y)).mean()), 6)}
       for y, g in s.groupby("season")}
print(json.dumps(out, indent=1))
