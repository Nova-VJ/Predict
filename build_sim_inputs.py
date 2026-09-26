#!/usr/bin/env python3
"""Point-in-time plate-appearance rates for the game simulator (experiment #14).

Per game and side: the 9 starting batters' PA outcome rates, the starter's and the bullpen's
rates allowed, and the starter's expected outs. Categories (per PA):
  K, BB (incl. HBP), 1B, 2B, 3B, HR, OUT (ball in play out; remainder).
Rates decay exponentially (batters/starters 365 d, bullpen 90 d) and are shrunk to the league
rate with pseudo-counts. Only appearances on dates before the game are used.
Output: output/sim_inputs.npz
"""
import pathlib

import numpy as np
import pandas as pd

import build_player_features as bpf

BASE = pathlib.Path(__file__).resolve().parent
CAT = ["K", "BB", "1B", "2B", "3B", "HR", "OUT"]
M_BAT, M_SP, M_BP = 250.0, 200.0, 300.0
COLS = ["game.key", "game.date", "team.alignment", "team.key", "person.key", "slot", "seq",
        "B_PA", "B_SO", "B_BB", "B_HP", "B_H", "B_2B", "B_3B", "B_HR",
        "P_GS", "P_TBF", "P_SO", "P_BB", "P_HP", "P_H", "P_2B", "P_3B", "P_HR", "P_OUT"]


def vec_bat(r):
    pa = r.B_PA
    k, bb = r.B_SO, r.B_BB + r.B_HP
    s = r.B_H - r.B_2B - r.B_3B - r.B_HR
    v = np.array([k, bb, s, r.B_2B, r.B_3B, r.B_HR, 0.0])
    v[6] = max(pa - v[:6].sum(), 0.0)
    return v


def vec_pit(r):
    pa = r.P_TBF
    s = r.P_H - r.P_2B - r.P_3B - r.P_HR
    v = np.array([r.P_SO, r.P_BB + r.P_HP, s, r.P_2B, r.P_3B, r.P_HR, 0.0])
    v[6] = max(pa - v[:6].sum(), 0.0)
    return v


class Dec:
    def __init__(self, hl):
        self.f = 0.5 ** (1 / hl)
        self.s = {}

    def get(self, k, day):
        v = self.s.get(k)
        return np.zeros(7) if v is None else v[0] * self.f ** (day - v[1])

    def add(self, k, day, x):
        self.s[k] = (self.get(k, day) + x, day)


def main():
    frames = [pd.read_csv(p, usecols=COLS, low_memory=False) for p in sorted(bpf.RAW.glob("playing-20??.csv"))]
    d = pd.concat(frames, ignore_index=True)
    num = [c for c in COLS if c[:2] in ("B_", "P_")] + ["slot", "seq"]
    d[num] = d[num].apply(pd.to_numeric, errors="coerce").fillna(0)
    d["day"] = pd.to_datetime(d["game.date"]).map(lambda x: x.toordinal())
    d = d.sort_values(["day", "game.key"])
    bat, sp, bp, lg = Dec(365), Dec(365), Dec(90), Dec(365)
    spo = {}  # starter outs decayed: (starts, outs)
    ids, lineups, sps, bps, outs, lgs = [], [], [], [], [], []
    for day, block in d.groupby("day", sort=True):
        L = lg.get("L", day)
        lr = L / L.sum() if L.sum() > 5000 else np.array([.22, .09, .145, .045, .004, .03, .466])
        for gk, g in block.groupby("game.key"):
            ok = True
            lu_g, sp_g, bp_g, o_g = [], [], [], []
            for al in (1, 0):
                t = g[g["team.alignment"] == al]
                lu = t[(t.seq == 1) & t.slot.between(1, 9)].sort_values("slot")
                st = t[t.P_GS == 1]
                if len(lu) != 9 or len(st) != 1 or t.empty:
                    ok = False
                    break
                lu_g.append([(bat.get(p, day) + lr * M_BAT) / (bat.get(p, day).sum() + M_BAT) for p in lu["person.key"]])
                pid = st["person.key"].iloc[0]
                sv = sp.get(pid, day)
                sp_g.append((sv + lr * M_SP) / (sv.sum() + M_SP))
                bv = bp.get(t["team.key"].iloc[0], day)
                bp_g.append((bv + lr * M_BP) / (bv.sum() + M_BP))
                s0, o0 = spo.get(pid, (0.0, 0.0, day))[:2]
                o_g.append((o0 + 15.5 * 5) / (s0 + 5))
            if ok:
                ids.append(gk)
                lineups.append(lu_g)
                sps.append(sp_g)
                bps.append(bp_g)
                outs.append(o_g)
                lgs.append(lr)
        # update after the day
        f = 0.5 ** (1 / 365)
        for r in block.itertuples(index=False):
            if r.B_PA > 0:
                v = vec_bat(r)
                bat.add(r[4], day, v)
                lg.add("L", day, v)
            if r.P_TBF > 0:
                v = vec_pit(r)
                if r.P_GS == 1:
                    sp.add(r[4], day, v)
                    s0, o0, d0 = spo.get(r[4], (0.0, 0.0, day))
                    k = f ** (day - d0)
                    spo[r[4]] = (s0 * k + 1, o0 * k + r.P_OUT, day)
                else:
                    sp.add(r[4], day, v)
                    bp.add(r[3], day, v)
    np.savez_compressed(BASE / "output" / "sim_inputs.npz", game_id=np.array(ids),
                        lineups=np.array(lineups, dtype=np.float32), sp=np.array(sps, dtype=np.float32),
                        bp=np.array(bps, dtype=np.float32), sp_outs=np.array(outs, dtype=np.float32),
                        league=np.array(lgs, dtype=np.float32))
    print(len(ids), "games; league rates", np.round(lr, 4))


if __name__ == "__main__":
    main()
