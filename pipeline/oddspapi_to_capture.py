#!/usr/bin/env python3
"""OddsPapi historical/live JSON -> common capture CSV (for world books: Spain, Asia, exchanges).

OddsPapi MLB moneyline = market 131 "Winner (incl. extra innings)", outcome 131 = participant1
(home), 132 = participant2 (away). Each outcome holds a time series of {createdAt, price, active}.
For a chosen instant (--at, ISO UTC) the price in force is the last active entry at or before it.

Usage:
  python pipeline/oddspapi_to_capture.py hist_*.json.gz --fixtures fixtures.json --at-offset-min -180
  (-180 = T-3h; 0 = last price before first pitch)
"""
import argparse
import datetime as dt
import gzip
import json
import pathlib


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def price_at(series, when):
    best = None
    for e in series:
        t = ts(e["createdAt"])
        if t <= when and e.get("price", 0) > 1 and e.get("active", True):
            if best is None or t > ts(best["createdAt"]):
                best = e
    return best


def rows_for(hist, fixture, offset_min):
    start = ts(fixture["startTime"])
    when = start + dt.timedelta(minutes=offset_min) if offset_min < 0 else start - dt.timedelta(seconds=1)
    for book, b in (hist.get("bookmakers") or {}).items():
        m = (b.get("markets") or {}).get("131")
        if not m:
            continue
        side = {}
        for oid, key in (("131", "home"), ("132", "away")):
            series = [x for p in (m.get("outcomes", {}).get(oid, {}).get("players") or {}).values() for x in p]
            side[key] = price_at(series, when)
        if side["home"] and side["away"]:
            last = max(ts(side["home"]["createdAt"]), ts(side["away"]["createdAt"]))
            yield [fixture["fixtureId"], fixture["startTime"], fixture["participant1Name"], fixture["participant2Name"],
                   book, last.isoformat().replace("+00:00", "Z"), side["home"]["price"], side["away"]["price"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hist", nargs="+")
    ap.add_argument("--fixtures", required=True, help="JSON list of fixtures (as returned by /v4/fixtures)")
    ap.add_argument("--at-offset-min", type=int, default=-180)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    fx = {f["fixtureId"]: f for f in json.loads(pathlib.Path(a.fixtures).read_text())}
    with open(a.out, "w", encoding="utf-8") as out:
        out.write(f"# source=oddspapi at_offset_min={a.at_offset_min} observed_request_utc=historical\n")
        out.write("event_id,commence_utc,home,away,book,last_update,home_price,away_price\n")
        for p in a.hist:
            raw = gzip.decompress(pathlib.Path(p).read_bytes()) if p.endswith(".gz") else pathlib.Path(p).read_bytes()
            h = json.loads(raw)
            f = fx.get(h.get("fixtureId"))
            if f:
                for r in rows_for(h, f, a.at_offset_min):
                    out.write(",".join(str(x) for x in r) + "\n")


if __name__ == "__main__":
    main()
