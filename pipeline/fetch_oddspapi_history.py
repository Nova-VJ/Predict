#!/usr/bin/env python3
"""Backfill timestamped 2026 MLB moneyline history from OddsPapi (free tier).

Why: OddsPapi documents a free /v4/historical-odds endpoint with every price change
(`createdAt`) per bookmaker, including Pinnacle, for fixtures since January 2026.
That gives us T-3h and closing prices for the 2026 season - a season our model has
NEVER been tuned on, i.e. a clean out-of-sample test.

Budget: free plan ~250 requests/month (check your dashboard). 1 request = 1 fixture,
up to 3 bookmakers. The script is resumable and stops at --max-requests.
Rate limit: the endpoint documents a 5 s cooldown; we wait 6 s.

Usage:
  export ODDSPAPI_KEY=...            # never commit it
  python pipeline/fetch_oddspapi_history.py --discover            # find sport/tournament ids
  python pipeline/fetch_oddspapi_history.py --tournament-id N --from 2026-04-01 --to 2026-04-30 \
         --bookmakers pinnacle,bet365,codere --max-requests 200

Fixture listing calls also count as requests; ranges are fetched in 48 h chunks as documented.
Endpoint details were read from the public docs on 2026-09-26 and are untested from our side:
the first run should use --max-requests 3 and inspect the saved files.
"""
import argparse
import datetime as dt
import gzip
import json
import os
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "oddspapi"
HOST = "https://api.oddspapi.io/v4/"


def call(path, **params):
    key = os.environ.get("ODDSPAPI_KEY")
    if not key:
        raise SystemExit("Set ODDSPAPI_KEY in the environment.")
    url = HOST + path + "?" + urllib.parse.urlencode({**params, "apiKey": key})
    t0 = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "MLB-TM/2.0"}),
                                    timeout=60) as r:
            body, status = r.read(), r.status
    except urllib.error.HTTPError as ex:
        body, status = ex.read(), ex.code
    time.sleep(6)
    return status, body, t0


def save(name, body, meta):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json.gz").write_bytes(gzip.compress(body))
    with open(OUT / "manifest.jsonl", "a") as f:
        f.write(json.dumps({"name": name, **meta}) + "\n")


def done_fixtures():
    m = OUT / "manifest.jsonl"
    if not m.exists():
        return set()
    return {json.loads(l)["fixture_id"] for l in m.open() if '"fixture_id"' in l and '"status": 200' in l}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--tournament-id")
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="end")
    ap.add_argument("--bookmakers", default="pinnacle,bet365")
    ap.add_argument("--max-requests", type=int, default=20)
    a = ap.parse_args()
    used = 0
    if a.discover:
        s, b, t = call("sports"); used += 1
        save("sports", b, {"status": s, "request_utc": t})
        sports = json.loads(b)
        base = [x for x in sports if "baseball" in json.dumps(x).lower()]
        print("baseball sports:", json.dumps(base)[:800])
        for sp in base[:1]:
            sid = sp.get("sportId") or sp.get("id")
            s, b, t = call("tournaments", sportId=sid); used += 1
            save(f"tournaments_{sid}", b, {"status": s, "request_utc": t})
            print([x for x in json.loads(b) if "mlb" in json.dumps(x).lower()][:5])
        return
    start = dt.date.fromisoformat(a.start)
    end = dt.date.fromisoformat(a.end)
    skip = done_fixtures()
    day = start
    while day <= end and used < a.max_requests:
        frm = dt.datetime.combine(day, dt.time(), dt.timezone.utc)
        to = frm + dt.timedelta(hours=47, minutes=59)
        s, b, t = call("fixtures", tournamentId=a.tournament_id, **{"from": frm.isoformat().replace("+00:00", "Z"),
                                                                     "to": to.isoformat().replace("+00:00", "Z")})
        used += 1
        save(f"fixtures_{day}", b, {"status": s, "request_utc": t})
        fixtures = json.loads(b) if s == 200 else []
        for fx in fixtures:
            fid = fx.get("fixtureId")
            if not fid or fid in skip or used >= a.max_requests:
                continue
            s2, b2, t2 = call("historical-odds", fixtureId=fid, bookmakers=a.bookmakers)
            used += 1
            save(f"hist_{fid}", b2, {"status": s2, "request_utc": t2, "fixture_id": fid,
                                     "start": fx.get("startTime"), "home": fx.get("participant1Name"),
                                     "away": fx.get("participant2Name"), "bookmakers": a.bookmakers})
            skip.add(fid)
        day += dt.timedelta(days=2)
    print(json.dumps({"requests_used": used, "fixtures_saved_total": len(skip)}))


if __name__ == "__main__":
    main()
