#!/usr/bin/env python3
"""How many bets are needed to prove an edge, and what a bankroll looks like on the way.

1. Power analysis: bets needed to detect a true edge with ROI vs with CLV.
2. Monte Carlo bankroll: 10,000 simulated careers of N bets at a given true edge,
   flat 1 % stakes and 1/4 Kelly, to show the probability of being in loss after N
   bets even with a real edge, and the typical worst drawdown.
3. Our own backtest selections (stack at open, 2022-2025) replayed and bootstrapped.

Output: output/portfolio_sim.json
"""
import json
import pathlib
import sqlite3

import numpy as np
import pandas as pd

import evaluate_v2 as v2

BASE = pathlib.Path(__file__).resolve().parent
RNG = np.random.default_rng(260926)
Z_A, Z_B = 1.645, 0.842  # one-sided 5 % false positive, 80 % power


def n_needed(sd, edge):
    return int(np.ceil(((Z_A + Z_B) * sd / edge) ** 2))


def career(n_bets, edge, odds, stake_rule, sims=10_000):
    """Simulate bankrolls starting at 100. edge = true EV per unit staked at `odds`."""
    p_true = (1 + edge) / odds
    wins = RNG.random((sims, n_bets)) < p_true
    bank = np.full(sims, 100.0)
    peak = bank.copy()
    maxdd = np.zeros(sims)
    for i in range(n_bets):
        if stake_rule == "flat1":
            stake = np.full(sims, 1.0)  # 1 % of the INITIAL bank
        else:  # quarter Kelly on believed edge (= true edge here, optimistic)
            f = max(edge, 0) / (odds - 1) / 4
            stake = bank * f
        bank = bank + np.where(wins[:, i], stake * (odds - 1), -stake)
        peak = np.maximum(peak, bank)
        maxdd = np.maximum(maxdd, 1 - bank / peak)
    return {"p_in_loss": round(float((bank < 100).mean()), 3),
            "median_final": round(float(np.median(bank)), 1),
            "p5_final": round(float(np.percentile(bank, 5)), 1),
            "median_max_drawdown": round(float(np.median(maxdd)), 3),
            "p95_max_drawdown": round(float(np.percentile(maxdd, 95)), 3)}


def main():
    c = sqlite3.connect(v2.DB)
    df = pd.read_sql("SELECT game_id, game_date, season, y, p_fund, p_stack_open_cons FROM v2_predictions", c)
    df = df.merge(v2.market_frame(c), left_on="game_id", right_index=True, how="left")
    rep = {}

    b = v2.bets(df[df.season.between(2022, 2025)], "p_stack_open_cons", "open")
    bf = v2.bets(df[df.season.between(2022, 2025)], "p_fund", "open")
    odds_sd = float(b.profit.std())
    clv_sd = float(b.clv.std())
    rep["observed"] = {"profit_sd_per_bet": round(odds_sd, 3), "clv_sd_per_bet": round(clv_sd, 4),
                       "stack_bets_per_season": b.groupby("season").size().to_dict(),
                       "fund_bets_per_season": bf.groupby("season").size().to_dict()}

    rep["bets_needed"] = {f"edge_{int(e*100)}pct": {"by_roi": n_needed(odds_sd, e), "by_clv": n_needed(clv_sd, e)}
                          for e in (0.01, 0.02, 0.03, 0.05)}

    rep["monte_carlo"] = {}
    for n in (100, 250, 500, 1000, 2500):
        for e in (0.0, 0.02, 0.04):
            for rule in ("flat1", "kelly_quarter"):
                if e == 0 and rule == "kelly_quarter":
                    continue
                rep["monte_carlo"][f"n{n}_edge{int(e*100)}_{rule}"] = career(n, e, 2.1, rule, sims=10_000 if n <= 1000 else 4000)

    # replay our backtest selections: flat 1 unit, bootstrap order and sample
    prof = b.profit.values
    boots = RNG.choice(prof, size=(10_000, len(prof)), replace=True)
    final = 100 + boots.sum(1)
    path = 100 + np.cumsum(prof)
    rep["backtest_stack_open"] = {"bets": int(len(prof)), "total_units": round(float(prof.sum()), 1),
                                  "worst_point_units": round(float(path.min() - 100), 1),
                                  "bootstrap_p_profit": round(float((final > 100).mean()), 3),
                                  "mean_clv": round(float(b.clv.mean()), 4)}
    (BASE / "output" / "portfolio_sim.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
