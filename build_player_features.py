#!/usr/bin/env python3
"""Pre-game player features (starter, bullpen, lineup) from Retrosheet day-by-day files.

Source: chadwickbureau/retrosplits `daybyday/playing-YYYY.csv` (free, derived from
Retrosheet event files). One row per player per game.

Point-in-time rule: every feature for a game played on date D is computed from
appearances on dates strictly before D. Same-day games (doubleheaders) never see
each other. Stats decay exponentially with a pre-declared half-life (no tuning).

What is (and is not) known before first pitch:
  * Starting pitcher: announced as probable 1-5 days ahead; late scratches are rare
    and US books settle "listed pitcher" bets as void. We use the actual starter as
    a proxy for the announced probable. Openers/bullpen games are flagged via the
    starter's expected outs.
  * Starting lineup: published roughly 1-4 h before first pitch. Valid for a
    decision taken at/near the close; NOT guaranteed at T-3h.
  * Bullpen fatigue: relief pitches thrown on the three previous dates (fully known).

Output table: player_features (one row per game_id) in output/mlb_time_machine.sqlite.
"""
import collections
import datetime as dt
import pathlib
import sqlite3

import pandas as pd

BASE = pathlib.Path(__file__).resolve().parent
RAW = BASE / "raw" / "retrosplits"
DB = BASE / "output" / "mlb_time_machine.sqlite"

HL_PITCHER = 365.0   # days, starters' skill
HL_BULLPEN = 90.0    # days, bullpen composition changes faster
HL_BATTER = 365.0
HL_LEAGUE = 365.0
M_SP_BF = 200.0      # shrinkage: batters faced of league-average prior for a starter
M_BP_BF = 300.0
M_BAT_PA = 250.0
M_SP_STARTS = 5.0
SLOT_PA = {1: 4.65, 2: 4.55, 3: 4.45, 4: 4.35, 5: 4.25, 6: 4.15, 7: 4.05, 8: 3.95, 9: 3.85}

COLS = ["game.key", "game.date", "season.phase", "team.alignment", "team.key", "person.key",
        "slot", "seq", "B_PA", "B_H", "B_2B", "B_3B", "B_HR", "B_BB", "B_IBB", "B_HP",
        "P_GS", "P_OUT", "P_TBF", "P_H", "P_HR", "P_BB", "P_IBB", "P_SO", "P_HP", "P_ER", "P_PITCH"]


class Decayed:
    """Exponentially decayed sums keyed by entity, decayed lazily by calendar day."""

    def __init__(self, half_life, width):
        self.f = 0.5 ** (1.0 / half_life)
        self.width = width
        self.s = {}

    def get(self, key, day):
        v = self.s.get(key)
        if v is None:
            return [0.0] * self.width
        sums, last = v
        k = self.f ** (day - last)
        return [x * k for x in sums]

    def add(self, key, day, values):
        cur = self.get(key, day)
        self.s[key] = ([a + b for a, b in zip(cur, values)], day)


def fip_bf(hr, bbhp, so, bf):
    return (13 * hr + 3 * bbhp - 2 * so) / bf if bf > 0 else None


def woba_num(r):
    singles = r["B_H"] - r["B_2B"] - r["B_3B"] - r["B_HR"]
    return (0.69 * (r["B_BB"] - r["B_IBB"]) + 0.72 * r["B_HP"] + 0.88 * singles +
            1.25 * r["B_2B"] + 1.58 * r["B_3B"] + 2.0 * r["B_HR"])


def load():
    frames = []
    for path in sorted(RAW.glob("playing-20??.csv")):
        d = pd.read_csv(path, usecols=COLS, low_memory=False)
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    num = [c for c in COLS if c[:2] in ("B_", "P_")] + ["slot", "seq"]
    d[num] = d[num].apply(pd.to_numeric, errors="coerce").fillna(0)
    d["day"] = pd.to_datetime(d["game.date"]).map(lambda x: x.toordinal())
    return d.sort_values(["day", "game.key"])


def main():
    d = load()
    # pitcher sums: BF, SO, BB+HP, HR, OUT, ER, starts, start_outs
    sp = Decayed(HL_PITCHER, 8)
    # bullpen sums per team: BF, SO, BB+HP, HR
    bp = Decayed(HL_BULLPEN, 4)
    # batter sums: PA, woba_num
    bat = Decayed(HL_BATTER, 2)
    lg = Decayed(HL_LEAGUE, 6)  # league: BF, SO, BBHP, HR, PA, woba_num
    relief_pitches = collections.defaultdict(float)  # (team, day) -> pitches
    last_app = {}  # pitcher -> last appearance day

    out = []
    for day, block in d.groupby("day", sort=True):
        L = lg.get("L", day)
        if L[0] < 1000:  # warm-up: need league baseline
            lg_fip, lg_woba = 0.10, 0.315
        else:
            lg_fip = fip_bf(L[3], L[2], L[1], L[0])
            lg_woba = L[5] / L[4]

        # ---------- features (state before this day) ----------
        for gkey, g in block.groupby("game.key"):
            row = {"game_id": gkey, "feature_day": dt.date.fromordinal(day).isoformat()}
            for align, side in ((1, "home"), (0, "away")):
                t = g[g["team.alignment"] == align]
                if t.empty:
                    continue
                team = t["team.key"].iloc[0]
                starter = t[t["P_GS"] == 1]
                if len(starter):
                    pid = starter["person.key"].iloc[0]
                    s = sp.get(pid, day)
                    bf = s[0]
                    row[f"{side}_sp_id"] = pid
                    row[f"{side}_sp_bf"] = bf
                    row[f"{side}_sp_fip"] = ((13 * s[3] + 3 * s[2] - 2 * s[1]) + lg_fip * M_SP_BF) / (bf + M_SP_BF)
                    row[f"{side}_sp_k"] = (s[1] + (L[1] / L[0] if L[0] else 0.22) * M_SP_BF) / (bf + M_SP_BF)
                    row[f"{side}_sp_bb"] = (s[2] + (L[2] / L[0] if L[0] else 0.09) * M_SP_BF) / (bf + M_SP_BF)
                    row[f"{side}_sp_outs"] = (s[7] + 15.5 * M_SP_STARTS) / (s[6] + M_SP_STARTS)
                    row[f"{side}_sp_rest"] = (day - last_app[pid]) if pid in last_app else None
                b = bp.get(team, day)
                row[f"{side}_bp_fip"] = ((13 * b[3] + 3 * b[2] - 2 * b[1]) + lg_fip * M_BP_BF) / (b[0] + M_BP_BF)
                row[f"{side}_bp_pitches_3d"] = sum(relief_pitches.get((team, day - k), 0.0) for k in (1, 2, 3))
                lineup = t[(t["seq"] == 1) & (t["slot"].between(1, 9))]
                if len(lineup) == 9:
                    tot = 0.0
                    for _, r in lineup.iterrows():
                        pa, num = bat.get(r["person.key"], day)
                        tot += SLOT_PA[int(r["slot"])] * (num + lg_woba * M_BAT_PA) / (pa + M_BAT_PA)
                    row[f"{side}_lineup_woba"] = tot / sum(SLOT_PA.values())
                    row[f"{side}_lineup_n_new"] = int(sum(bat.get(p, day)[0] < 50 for p in lineup["person.key"]))
            out.append(row)

        # ---------- update states with this day's results ----------
        pit = block[block["P_TBF"] > 0]
        for _, r in pit.iterrows():
            bbhp = r["P_BB"] + r["P_HP"]
            pid = r["person.key"]
            last_app[pid] = day
            gs = r["P_GS"] == 1
            sp.add(pid, day, [r["P_TBF"], r["P_SO"], bbhp, r["P_HR"], r["P_OUT"], r["P_ER"],
                              1.0 if gs else 0.0, r["P_OUT"] if gs else 0.0])
            if not gs:
                bp.add(r["team.key"], day, [r["P_TBF"], r["P_SO"], bbhp, r["P_HR"]])
                relief_pitches[(r["team.key"], day)] += r["P_PITCH"]
            lg.add("L", day, [r["P_TBF"], r["P_SO"], bbhp, r["P_HR"], 0, 0])
        bats = block[block["B_PA"] > 0]
        for _, r in bats.iterrows():
            w = woba_num(r)
            bat.add(r["person.key"], day, [r["B_PA"], w])
            lg.add("L", day, [0, 0, 0, 0, r["B_PA"], w])

    f = pd.DataFrame(out)
    for base in ("sp_fip", "sp_k", "sp_bb", "sp_outs", "bp_fip", "bp_pitches_3d", "lineup_woba"):
        if f"home_{base}" in f and f"away_{base}" in f:
            f[f"diff_{base}"] = f[f"home_{base}"] - f[f"away_{base}"]
    c = sqlite3.connect(DB)
    f.to_sql("player_features", c, if_exists="replace", index=False)
    c.execute("CREATE INDEX IF NOT EXISTS ix_pf ON player_features(game_id)")
    c.commit()
    n = c.execute("SELECT COUNT(*) FROM player_features p JOIN games g USING(game_id)").fetchone()[0]
    print(f"player_features: {len(f)} rows, {n} joined to games")
    print(f.describe().T[["count", "mean", "std"]].round(4).to_string())


if __name__ == "__main__":
    main()
