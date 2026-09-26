#!/usr/bin/env python3
"""Platoon features: share of each starting lineup with the platoon advantage vs the opposing starter.

Handedness from Retrosheet biofile (BATS L/R/B, THROWS L/R); lineups and starters from retrosplits.
Switch hitters (B) always have the advantage. Only pre-game-knowable facts are used (announced
starter and posted lineup). Output table platoon_features(game_id, ...).
Source: https://github.com/chadwickbureau/retrosheet reference/biofile.csv
"""
import pathlib
import sqlite3

import pandas as pd

BASE = pathlib.Path(__file__).resolve().parent
bio = pd.read_csv(BASE / "raw/retrosheet_ref/biofile.csv", usecols=["PLAYERID", "BATS", "THROWS"])
bats = dict(zip(bio.PLAYERID, bio.BATS))
throws = dict(zip(bio.PLAYERID, bio.THROWS))
rows = []
for p in sorted((BASE / "raw/retrosplits").glob("playing-20??.csv")):
    d = pd.read_csv(p, usecols=["game.key", "team.alignment", "person.key", "slot", "seq", "P_GS"], low_memory=False)
    d["P_GS"] = pd.to_numeric(d.P_GS, errors="coerce").fillna(0)
    for gk, g in d.groupby("game.key"):
        sp = {al: g[(g["team.alignment"] == al) & (g.P_GS == 1)]["person.key"] for al in (0, 1)}
        r = {"game_id": gk}
        for al, side in ((1, "home"), (0, "away")):
            opp = sp[1 - al]
            hand = throws.get(opp.iloc[0]) if len(opp) else None
            lu = g[(g["team.alignment"] == al) & (g.seq == 1) & (g.slot.between(1, 9))]["person.key"]
            if hand in ("L", "R") and len(lu) == 9:
                adv = [(bats.get(b) == "B") or (bats.get(b) in ("L", "R") and bats.get(b) != hand) for b in lu]
                r[f"{side}_platoon_share"] = sum(adv) / 9
            r[f"{side}_faces_lhp"] = 1.0 if hand == "L" else 0.0
        rows.append(r)
f = pd.DataFrame(rows)
f["diff_platoon"] = f.home_platoon_share - f.away_platoon_share
f["diff_faces_lhp"] = f.home_faces_lhp - f.away_faces_lhp
c = sqlite3.connect(BASE / "output/mlb_time_machine.sqlite")
f.to_sql("platoon_features", c, if_exists="replace", index=False)
print(len(f), f[["home_platoon_share", "away_platoon_share", "diff_platoon"]].describe().round(3).to_string())
