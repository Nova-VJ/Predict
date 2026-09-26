#!/usr/bin/env python3
"""One unattended capture run (designed for GitHub Actions cron every ~20 min).

Each run:
  1. Captures the official MLB schedule for today and tomorrow (US date) with
     probable pitchers and posted lineups. Free, no key.
  2. Captures moneyline odds ONLY if some game is inside a decision window:
       * "t3h"   : start - 3h30m .. start - 2h30m  (first capture per game)
       * "close" : start - 40m   .. start          (every run: last one = our close)
     This keeps the free credit budget: ~8 start slots/day x ~3 calls = ~24 credits/day.
  3. Writes gzipped raw JSON + a manifest line with request/receipt UTC times.

Keys come from environment variables only (GitHub Secrets / .env), never from code:
  PARLAY_API_KEY   (ParlayAPI, 1,000 free credits/month)
  ODDS_API_KEY     (The Odds API, 500 free credits/month) - optional second source
  ODDS_REGIONS     default "us,eu": US books are the PRIMARY reference; eu adds Pinnacle, Unibet, PMU.
                   (uk/au add no MLB books on ParlayAPI; each region costs 1 credit)

Standard library only.
"""
import datetime as dt
import gzip
import json
import os
import pathlib
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "captures"
STATE = ROOT / "data" / "state" / "windows_done.json"
UA = {"User-Agent": "MLB-Time-Machine-research/2.0"}
GAME_TYPES = "R,F,D,L,W"  # regular season + postseason rounds


def now():
    return dt.datetime.now(dt.timezone.utc)


def get(url, headers=None, timeout=40):
    t0 = now()
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            meta = {"status": r.status, "headers": {k: r.headers.get(k) for k in (
                "X-Credits-Cost", "X-Credits-Remaining", "x-requests-remaining", "x-requests-used",
                "Content-Type")}}
    except urllib.error.HTTPError as ex:
        body, meta = ex.read(), {"status": ex.code, "headers": {}}
    except Exception as ex:  # network error: record and continue
        body, meta = b"", {"status": None, "error": type(ex).__name__}
    meta.update({"request_utc": t0.isoformat(), "received_utc": now().isoformat()})
    return body, meta


def save(kind, body, meta, source_url):
    t = now()
    folder = DATA / t.strftime("%Y/%m/%d")
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{kind}_{t.strftime('%Y%m%dT%H%M%SZ')}.json.gz"
    (folder / name).write_bytes(gzip.compress(body))
    line = {"file": str((folder / name).relative_to(ROOT)), "kind": kind,
            "source_url": source_url, **meta}
    with open(DATA / "manifest.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
    return line


def schedule():
    today = (now() - dt.timedelta(hours=10)).date()  # US baseball day
    q = urllib.parse.urlencode({"sportId": 1, "startDate": today.isoformat(),
                                "endDate": (today + dt.timedelta(days=1)).isoformat(),
                                "gameType": GAME_TYPES,
                                "hydrate": "probablePitcher,lineups,team,weather,venue"})
    url = "https://statsapi.mlb.com/api/v1/schedule?" + q
    body, meta = get(url)
    save("mlb_schedule", body, meta, url)
    games = []
    if meta.get("status") == 200:
        for d in json.loads(body).get("dates", []):
            for g in d.get("games", []):
                if g.get("status", {}).get("abstractGameState") == "Preview":
                    games.append({"pk": g["gamePk"], "start": dt.datetime.fromisoformat(
                        g["gameDate"].replace("Z", "+00:00"))})
    return games


def windows_due(games):
    done = json.loads(STATE.read_text()) if STATE.exists() else {}
    t, due = now(), set()
    for g in games:
        mins = (g["start"] - t).total_seconds() / 60
        if 150 <= mins <= 210 and f"{g['pk']}:t3h" not in done:
            due.add("t3h")
            done[f"{g['pk']}:t3h"] = t.isoformat()
        if 0 <= mins <= 40:
            due.add("close")
    # forget state older than 3 days
    cutoff = (t - dt.timedelta(days=3)).isoformat()
    done = {k: v for k, v in done.items() if v >= cutoff}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(done, indent=0))
    return sorted(due)


def to_capture_csv(events, meta, source, tag):
    """Odds-API-style JSON -> the common capture CSV read by market_compare.py."""
    t = now()
    folder = DATA / t.strftime("%Y/%m/%d")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"capture_{source}_{tag}_{t.strftime('%Y%m%dT%H%M%SZ')}.csv"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"# observed_request_utc={meta['request_utc']} received_utc={meta['received_utc']} source={source} window={tag}\n")
        fh.write("event_id,commence_utc,home,away,book,last_update,home_price,away_price\n")
        for e in events:
            for b in e.get("bookmakers", []):
                m = next((m for m in b.get("markets", []) if m.get("key") == "h2h"), None)
                if not m:
                    continue
                o = {x["name"]: x["price"] for x in m.get("outcomes", [])}
                fh.write(",".join(str(v) for v in (e["id"], e["commence_time"], e["home_team"], e["away_team"],
                                                     b["key"], b.get("last_update", ""), o.get(e["home_team"], ""),
                                                     o.get(e["away_team"], ""))) + "\n")
    return path


def odds(tag):
    regions = os.environ.get("ODDS_REGIONS", "us,eu")
    out = []
    key = os.environ.get("PARLAY_API_KEY")
    if key:
        url = "https://parlay-api.com/v1/sports/baseball_mlb/odds?" + urllib.parse.urlencode(
            {"regions": regions, "markets": "h2h", "oddsFormat": "decimal"})
        body, meta = get(url, {"X-API-Key": key})
        out.append(save(f"odds_parlay_{tag}", body, meta, url))
        if meta.get("status") == 200:
            csv_path = to_capture_csv(json.loads(body), meta, "parlayapi", tag)
            import subprocess, sys
            subprocess.run([sys.executable, str(ROOT / "pipeline" / "market_compare.py"), str(csv_path)], check=False)
    key = os.environ.get("ODDS_API_KEY")
    if key:
        base = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds?"
        q = {"regions": regions, "markets": "h2h", "oddsFormat": "decimal"}
        body, meta = get(base + urllib.parse.urlencode({**q, "apiKey": key}))
        out.append(save(f"odds_theoddsapi_{tag}", body, meta, base + urllib.parse.urlencode(q)))
    return out


def main():
    games = schedule()
    due = windows_due(games)
    if due:  # one board call serves every window due now (saves credits)
        for line in odds("_".join(due)):
            print(json.dumps({k: line[k] for k in ("file", "status", "headers") if k in line}))
    print(json.dumps({"utc": now().isoformat(), "upcoming_games": len(games), "odds_windows": due}))


if __name__ == "__main__":
    main()
