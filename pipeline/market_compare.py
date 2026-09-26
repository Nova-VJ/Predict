#!/usr/bin/env python3
"""World market comparison with the US market as primary reference.

Input: one odds capture CSV (any source) with columns
  event_id,commence_utc,home,away,book,last_update,home_price,away_price
  and an optional first comment line '# observed_request_utc=... received_utc=... source=...'.
Optional: data/live/predictions.csv to attach the model probability.

Per game it computes:
  * us_consensus  : median de-vigged home probability of the us_reference books (PRIMARY)
  * pinnacle      : Pinnacle de-vigged probability (sharp global benchmark)
  * global        : median de-vigged probability of every valid book
  * per book      : margin, de-vigged prob, deviation vs US (percentage points),
                    value of each side at that book priced against the US fair line,
                    staleness of the quote, validity flags
  * best prices   : per side, overall / US-regulated / Spain-licensed
Outputs:
  * SQLite tables market_quotes and market_board (append, keyed by capture_id)
  * data/app/market_board_<capture>.json  (stable schema for the front end, see SCHEMA below)
Standard library only (+ sqlite3).
"""
import argparse
import csv
import datetime as dt
import json
import pathlib
import sqlite3
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[1]
REG = json.loads((ROOT / "config" / "bookmakers.json").read_text())["books"]
STALE_MIN = 30          # quote older than this vs capture time -> stale
OUTLIER_PP = 3.0        # |deviation vs US| above this (pp) -> outlier
MARGIN_OK = (-0.02, 0.25)

SCHEMA = {
    "capture": "id, observed_utc, source, reference='us_consensus'",
    "games[]": "game_key, start_utc, home, away, reference{us_consensus, pinnacle, global, model}, "
               "dispersion_pp, n_books{total,us,spain}, best{overall,us_regulated,spain_licensed}{home,away}{price,book,value_vs_us}, books[]",
    "books[]": "book, name, country, kind, spain_licensed, home_price, away_price, margin, p_home_nv, "
               "dev_vs_us_pp, value_home_vs_us, value_away_vs_us, last_update, stale, outlier, valid",
    "book_summary[]": "book, name, kind, games, avg_margin, avg_abs_dev_vs_us_pp, times_best_price",
}


def parse_ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def f(x):
    try:
        v = float(x)
        return v if v > 1.0 else None
    except (TypeError, ValueError):
        return None


def load(path):
    meta, rows = {}, []
    with open(path, encoding="utf-8") as fh:
        first = fh.readline()
        if first.startswith("#"):
            meta = dict(kv.split("=", 1) for kv in first[1:].split() if "=" in kv)
        else:
            fh.seek(0)
        rows = list(csv.DictReader(fh))
    return meta, rows


def model_probs():
    p = ROOT / "data" / "live" / "predictions.csv"
    if not p.exists():
        return {}
    out = {}
    for r in csv.DictReader(open(p)):
        out[(r["home"], r["away"], r["start_utc"][:13])] = float(r["p_stack"])  # latest row wins
    return out


def build(meta, rows):
    from teams import abbr
    observed = parse_ts(meta.get("observed_request_utc") or meta.get("received_utc") or
                        dt.datetime.now(dt.timezone.utc).isoformat())
    games = {}
    for r in rows:
        key = (abbr(r["home"]), abbr(r["away"]), r["commence_utc"])
        games.setdefault(key, []).append(r)
    models = model_probs()
    out_games, quotes = [], []
    for (h, a, start), rs in sorted(games.items(), key=lambda kv: kv[0][2]):
        books = []
        for r in rs:
            info = REG.get(r["book"], {"name": r["book"], "country": "?", "kind": "unknown",
                                       "us_reference": False, "spain_licensed": False})
            hp, ap = f(r["home_price"]), f(r["away_price"])
            b = {"book": r["book"], "name": info["name"], "country": info["country"], "kind": info["kind"],
                 "spain_licensed": info["spain_licensed"], "us_reference": info["us_reference"],
                 "home_price": hp, "away_price": ap, "last_update": r.get("last_update") or None}
            b["valid"] = hp is not None and ap is not None
            if b["valid"]:
                b["margin"] = round(1 / hp + 1 / ap - 1, 4)
                b["valid"] = MARGIN_OK[0] <= b["margin"] <= MARGIN_OK[1]
                b["p_home_nv"] = round((1 / hp) / (1 / hp + 1 / ap), 4)
            lu = parse_ts(b["last_update"])
            b["stale"] = bool(lu and (observed - lu).total_seconds() > STALE_MIN * 60)
            books.append(b)
        ok = [b for b in books if b["valid"]]
        us = [b["p_home_nv"] for b in ok if b["us_reference"]]
        pin = [b["p_home_nv"] for b in ok if b["book"] == "pinnacle"]
        ref_us = statistics.median(us) if us else None
        ref_glob = statistics.median([b["p_home_nv"] for b in ok]) if ok else None
        for b in books:
            if b["valid"] and ref_us is not None:
                b["dev_vs_us_pp"] = round(100 * (b["p_home_nv"] - ref_us), 2)
                b["value_home_vs_us"] = round(ref_us * b["home_price"] - 1, 4)
                b["value_away_vs_us"] = round((1 - ref_us) * b["away_price"] - 1, 4)
                b["outlier"] = abs(b["dev_vs_us_pp"]) > OUTLIER_PP
            else:
                b.update({"dev_vs_us_pp": None, "value_home_vs_us": None, "value_away_vs_us": None, "outlier": None})

        def best(filt):
            res = {}
            for side, pk, vk in (("home", "home_price", "value_home_vs_us"), ("away", "away_price", "value_away_vs_us")):
                c = [b for b in ok if filt(b) and not b["stale"]]
                if c:
                    m = max(c, key=lambda b: b[pk])
                    res[side] = {"price": m[pk], "book": m["book"], "value_vs_us": m[vk]}
            return res

        mkey = (h, a, start[:13])
        g = {"game_key": f"{start[:10]}_{a}@{h}", "start_utc": start, "home": h, "away": a,
             "reference": {"us_consensus": None if ref_us is None else round(ref_us, 4),
                           "pinnacle": pin[0] if pin else None,
                           "global": None if ref_glob is None else round(ref_glob, 4),
                           "model": models.get(mkey)},
             "dispersion_pp": round(100 * statistics.pstdev([b["p_home_nv"] for b in ok]), 2) if len(ok) > 1 else None,
             "n_books": {"total": len(ok), "us": len(us), "spain": sum(b["spain_licensed"] for b in ok)},
             "best": {"overall": best(lambda b: True),
                      "us_regulated": best(lambda b: b["kind"] == "us_regulated"),
                      "spain_licensed": best(lambda b: b["spain_licensed"])},
             "books": sorted(books, key=lambda b: (not b["us_reference"], b["kind"], b["book"]))}
        out_games.append(g)
        for b in books:
            quotes.append((g["game_key"], start, h, a, b["book"], b["kind"], b["home_price"], b["away_price"],
                           b.get("margin"), b.get("p_home_nv"), b.get("dev_vs_us_pp"), b["last_update"],
                           int(b["stale"]), int(b["valid"])))
    # book scorecard for this capture
    agg = {}
    for g in out_games:
        winners = {g["best"]["overall"].get(s, {}).get("book") for s in ("home", "away")}
        for b in g["books"]:
            if not b["valid"]:
                continue
            s = agg.setdefault(b["book"], {"book": b["book"], "name": b["name"], "kind": b["kind"],
                                           "games": 0, "m": [], "d": [], "times_best_price": 0})
            s["games"] += 1
            s["m"].append(b["margin"])
            if b["dev_vs_us_pp"] is not None:
                s["d"].append(abs(b["dev_vs_us_pp"]))
            s["times_best_price"] += b["book"] in winners
    summary = [{"book": s["book"], "name": s["name"], "kind": s["kind"], "games": s["games"],
                "avg_margin": round(statistics.mean(s["m"]), 4),
                "avg_abs_dev_vs_us_pp": round(statistics.mean(s["d"]), 2) if s["d"] else None,
                "times_best_price": s["times_best_price"]} for s in agg.values()]
    summary.sort(key=lambda s: s["avg_margin"])
    return observed, out_games, quotes, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capture_csv")
    ap.add_argument("--db", default=str(ROOT / "output" / "mlb_time_machine.sqlite"))
    a = ap.parse_args()
    meta, rows = load(a.capture_csv)
    observed, games, quotes, summary = build(meta, rows)
    cid = observed.strftime("%Y%m%dT%H%M%SZ")
    board = {"schema_version": 1, "capture": {"id": cid, "observed_utc": observed.isoformat(),
                                             "source": meta.get("source", "unknown"), "reference": "us_consensus"},
             "games": games, "book_summary": summary}
    out = ROOT / "data" / "app" / f"market_board_{cid}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(board, indent=1))
    c = sqlite3.connect(a.db)
    c.execute("""CREATE TABLE IF NOT EXISTS market_quotes (capture_id TEXT, game_key TEXT, start_utc TEXT,
                 home TEXT, away TEXT, book TEXT, kind TEXT, home_price REAL, away_price REAL, margin REAL,
                 p_home_nv REAL, dev_vs_us_pp REAL, last_update TEXT, stale INTEGER, valid INTEGER,
                 PRIMARY KEY (capture_id, game_key, book))""")
    c.execute("""CREATE TABLE IF NOT EXISTS market_board (capture_id TEXT, game_key TEXT, start_utc TEXT,
                 p_us REAL, p_pinnacle REAL, p_global REAL, p_model REAL, dispersion_pp REAL, n_books INTEGER,
                 best_home_price REAL, best_home_book TEXT, best_away_price REAL, best_away_book TEXT,
                 PRIMARY KEY (capture_id, game_key))""")
    c.executemany("INSERT OR REPLACE INTO market_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  [(cid,) + q for q in quotes])
    c.executemany("INSERT OR REPLACE INTO market_board VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  [(cid, g["game_key"], g["start_utc"], g["reference"]["us_consensus"], g["reference"]["pinnacle"],
                    g["reference"]["global"], g["reference"]["model"], g["dispersion_pp"], g["n_books"]["total"],
                    g["best"]["overall"].get("home", {}).get("price"), g["best"]["overall"].get("home", {}).get("book"),
                    g["best"]["overall"].get("away", {}).get("price"), g["best"]["overall"].get("away", {}).get("book"))
                   for g in games])
    c.commit()
    print(f"capture {cid}: {len(games)} games, {len(quotes)} quotes -> {out.relative_to(ROOT)}")
    for g in games:
        r = g["reference"]
        bo = g["best"]["overall"]
        print(f"{g['game_key']:<26} US {r['us_consensus']}  PIN {r['pinnacle']}  GLOB {r['global']}  "
              f"model {r['model']}  disp {g['dispersion_pp']}pp  best H {bo.get('home',{}).get('price')}"
              f"({bo.get('home',{}).get('book')})  best A {bo.get('away',{}).get('price')}({bo.get('away',{}).get('book')})")
    print("\nbook scorecard (this capture):")
    for s in summary:
        print(f"  {s['book']:<11} {s['kind']:<17} margin {s['avg_margin']:.3f}  |dev vs US| {s['avg_abs_dev_vs_us_pp']}pp  best-price {s['times_best_price']}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT / "pipeline"))
    main()
