"""Tests for the market comparison layer (US consensus is the primary reference)."""
import sys
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "pipeline"))
import market_compare as mc  # noqa: E402


def row(book, hp, ap, lu="2026-09-26T12:00:00Z"):
    return {"event_id": "e1", "commence_utc": "2026-09-26T23:10:00Z", "home": "Chicago White Sox",
            "away": "Colorado Rockies", "book": book, "last_update": lu, "home_price": hp, "away_price": ap}


class MarketCompare(unittest.TestCase):
    def setUp(self):
        self.meta = {"observed_request_utc": "2026-09-26T12:05:00Z"}
        mc.model_probs = lambda: {}

    def test_us_consensus_is_median_of_us_reference_books(self):
        rows = [row("draftkings", 2.0, 2.0), row("fanduel", 1.9, 2.1), row("betmgm", 2.1, 1.9),
                row("pinnacle", 1.5, 3.0)]
        _, games, _, _ = mc.build(self.meta, rows)
        g = games[0]
        self.assertAlmostEqual(g["reference"]["us_consensus"], 0.5, places=3)  # Pinnacle does not move it
        self.assertAlmostEqual(g["reference"]["pinnacle"], (1 / 1.5) / (1 / 1.5 + 1 / 3.0), places=3)

    def test_one_sided_or_absurd_quotes_are_invalid(self):
        rows = [row("draftkings", 2.0, 2.0), row("kalshi", 33.33, ""), row("parx", 1.2, 1.2)]
        _, games, _, _ = mc.build(self.meta, rows)
        valid = {b["book"]: b["valid"] for b in games[0]["books"]}
        self.assertTrue(valid["draftkings"])
        self.assertFalse(valid["kalshi"])
        self.assertFalse(valid["parx"])  # margin 67 % -> rejected

    def test_value_vs_us_and_staleness(self):
        rows = [row("draftkings", 2.0, 2.0), row("fanduel", 2.0, 2.0), row("novig", 2.1, 1.95),
                row("betrivers", 2.2, 1.8, lu="2026-09-26T10:00:00Z")]
        _, games, _, _ = mc.build(self.meta, rows)
        b = {x["book"]: x for x in games[0]["books"]}
        self.assertAlmostEqual(b["novig"]["value_home_vs_us"], 0.05, places=3)
        self.assertTrue(b["betrivers"]["stale"])
        self.assertEqual(games[0]["best"]["overall"]["home"]["book"], "novig")  # stale 2.2 excluded


if __name__ == "__main__":
    unittest.main()
