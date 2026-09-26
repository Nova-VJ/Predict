"""Leakage tests for player_features (run after build_player_features.py)."""
import pathlib
import random
import sqlite3
import unittest

import pandas as pd

import build_player_features as bpf

BASE = pathlib.Path(__file__).resolve().parent


class PlayerFeatureLeakage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c = sqlite3.connect(BASE / "output" / "mlb_time_machine.sqlite")
        cls.pf = pd.read_sql("SELECT game_id, feature_day, home_sp_id, home_sp_bf FROM player_features", c)
        cols = ["game.key", "game.date", "person.key", "P_TBF", "P_GS"]
        frames = [pd.read_csv(p, usecols=cols) for p in sorted(bpf.RAW.glob("playing-20??.csv"))]
        cls.raw = pd.concat(frames)
        cls.raw = cls.raw[pd.to_numeric(cls.raw.P_TBF, errors="coerce").fillna(0) > 0]

    def test_starter_history_uses_only_earlier_dates(self):
        rng = random.Random(7)
        sample = self.pf[self.pf.feature_day >= "2016-01-01"].sample(40, random_state=7)
        f = 0.5 ** (1 / bpf.HL_PITCHER)
        for r in sample.itertuples():
            d = pd.Timestamp(r.feature_day)
            prior = self.raw[(self.raw["person.key"] == r.home_sp_id) & (pd.to_datetime(self.raw["game.date"]) < d)]
            age = (d - pd.to_datetime(prior["game.date"])).dt.days
            expected = float((prior.P_TBF.astype(float) * f ** age).sum())
            self.assertAlmostEqual(r.home_sp_bf, expected, places=3, msg=r.game_id)

    def test_debut_start_has_no_history(self):
        first = self.raw.sort_values("game.date").groupby("person.key").first()
        debut = first[(first.P_GS == 1) & (first["game.date"] >= "2016-01-01")]
        ids = set(zip(debut["game.key"], debut.index))
        rows = self.pf[[ (g, p) in ids for g, p in zip(self.pf.game_id, self.pf.home_sp_id)]]
        self.assertGreater(len(rows), 20)
        self.assertTrue((rows.home_sp_bf == 0).all())


if __name__ == "__main__":
    unittest.main()
