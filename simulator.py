#!/usr/bin/env python3
"""Plate-appearance Monte Carlo game simulator v0 (experiment #14).

Matchup: generalized log5 / odds-ratio: p_k proportional to batter_k * pitcher_k / league_k.
Base running (simple, fixed): 1B all runners +1 (runner from 2nd scores 60 %), 2B runners from
2nd/3rd score and from 1st to 3rd (scores 40 %), 3B/HR clear the bases, BB/HBP forced advances,
out in play: with < 2 outs a runner on 3rd scores 30 %. Starter pitches until his expected outs,
then the bullpen. Extra innings with a runner on 2nd (2020+), capped at 13 innings (tie -> 0.5).
Outputs per game: p_home_win, p_home_f5_win, p_f5_tie, mean total runs, mean home/away runs.
"""
import pathlib
import sys
import zlib

import numpy as np
import pandas as pd

BASE = pathlib.Path(__file__).resolve().parent
N = 800
K, BB, S1, S2, S3, HR, OUT = range(7)


def matchup(bat, pit, lg):
    x = bat * pit / lg
    return x / x.sum(-1, keepdims=True)


def half_inning(rng, cum_sp, cum_bp, bidx, pouts, sp_limit, active, ghost):
    """Simulate one half inning for all active sims. Returns runs, updated batter idx and pitcher outs."""
    n = len(bidx)
    outs = np.where(active, 0, 3)
    b1 = np.zeros(n, bool); b2 = np.full(n, ghost) & active; b3 = np.zeros(n, bool)
    runs = np.zeros(n, np.int16)
    while True:
        live = outs < 3
        if not live.any():
            break
        use_bp = pouts >= sp_limit
        cum = np.where(use_bp[:, None], cum_bp[bidx], cum_sp[bidx])
        u = rng.random(n)[:, None]
        ev = (u > cum).sum(1)
        ev = np.where(live, ev, -1)
        r = np.zeros(n, np.int16)
        # outs
        k = ev == K
        oip = ev == OUT
        sf = oip & b3 & (outs < 2) & (rng.random(n) < 0.3)
        r += sf
        b3 = np.where(sf, False, b3)
        outs = outs + (k | oip)
        pouts = pouts + (k | oip)
        # walks
        w = ev == BB
        fb3 = w & b1 & b2 & b3
        r += fb3
        nb3 = np.where(w, b3 | (b1 & b2), b3)
        nb2 = np.where(w, b2 | b1, b2)
        b1 = np.where(w, True, b1); b2 = nb2; b3 = nb3
        # singles
        s = ev == S1
        sc2 = s & b2 & (rng.random(n) < 0.6)
        r += s * b3 + sc2
        nb3 = np.where(s, (b2 & ~sc2), b3)
        nb2 = np.where(s, b1, b2)
        b1 = np.where(s, True, b1); b2 = nb2; b3 = nb3
        # doubles
        d = ev == S2
        sc1 = d & b1 & (rng.random(n) < 0.4)
        r += d * (b2.astype(np.int16) + b3) + sc1
        b3 = np.where(d, b1 & ~sc1, b3)
        b2 = np.where(d, True, b2)
        b1 = np.where(d, False, b1)
        # triples / HR
        t = ev == S3
        h = ev == HR
        clear = t | h
        r += clear * (b1.astype(np.int16) + b2 + b3) + h
        b1 = np.where(clear, False, b1); b2 = np.where(clear, False, b2); b3 = np.where(clear, t | (b3 & ~clear), b3)
        runs += r
        bidx = np.where(live, (bidx + 1) % 9, bidx)
    return runs, bidx, pouts


def sim_game(rng, lu_h, lu_a, sp_h, sp_a, bp_h, bp_a, o_h, o_a, lg, ghost_era=True):
    # home batters face away pitchers and vice versa; cumulative probs per batter slot
    cum = lambda lu, sp, bp: (np.cumsum(matchup(lu, sp[None, :], lg), 1)[:, :-1],
                              np.cumsum(matchup(lu, bp[None, :], lg), 1)[:, :-1])
    h_sp, h_bp = cum(lu_h, sp_a, bp_a)
    a_sp, a_bp = cum(lu_a, sp_h, bp_h)
    bh = np.zeros(N, int); ba = np.zeros(N, int)
    po_h = np.zeros(N); po_a = np.zeros(N)  # outs recorded by home / away pitchers
    rh = np.zeros(N, int); ra = np.zeros(N, int)
    f5h = f5a = None
    lim_h = np.round(o_h + rng.normal(0, 2.5, N)); lim_a = np.round(o_a + rng.normal(0, 2.5, N))
    for inn in range(1, 14):
        alive = (inn <= 9) | (rh == ra)
        if not alive.any():
            break
        ghost = ghost_era and inn >= 10
        r, ba, po_h = half_inning(rng, a_sp, a_bp, ba, po_h, lim_h, alive, ghost)
        ra += r
        alive_b = alive & ~((inn >= 9) & (rh > ra))
        r, bh, po_a = half_inning(rng, h_sp, h_bp, bh, po_a, lim_a, alive_b, ghost)
        rh += r
        if inn == 5:
            f5h, f5a = rh.copy(), ra.copy()
    win = np.where(rh > ra, 1.0, np.where(rh < ra, 0.0, 0.5))
    return {"p_home_win": win.mean(), "p_home_f5_win": (f5h > f5a).mean(), "p_f5_tie": (f5h == f5a).mean(),
            "total_runs": (rh + ra).mean(), "home_runs": rh.mean(), "away_runs": ra.mean()}


_Z = None


def _one(i):
    global _Z
    if _Z is None:
        _Z = {k: v for k, v in np.load(BASE / "output" / "sim_inputs.npz").items()}
    z = _Z
    gid = str(z["game_id"][i])
    rng = np.random.default_rng(zlib.crc32(gid.encode()))
    lu, sp, bp, o, lg = z["lineups"][i], z["sp"][i], z["bp"][i], z["sp_outs"][i], z["league"][i]
    res = sim_game(rng, lu[0], lu[1], sp[0], sp[1], bp[0], bp[1], o[0], o[1], lg, ghost_era=gid[3:7] >= "2020")
    res["game_id"] = gid
    return res


def main():
    z = np.load(BASE / "output" / "sim_inputs.npz")
    ids = z["game_id"]
    start = sys.argv[1] if len(sys.argv) > 1 else "2016"
    todo = [i for i, gid in enumerate(ids) if str(gid)[3:7] >= start]
    import multiprocessing as mp
    with mp.Pool() as pool:
        rows = pool.map(_one, todo, chunksize=50)
    out = pd.DataFrame(rows)
    out.to_csv(BASE / "output" / "sim_v0.csv", index=False)
    print(len(out), out.describe().round(3).to_string())


if __name__ == "__main__":
    main()
