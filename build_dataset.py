#!/usr/bin/env python3
"""Build a point-in-time MLB moneyline research database from downloaded archives.

Python standard library only. Historical 'opening' lines have no verified offer
timestamp and are deliberately marked ineligible for executable ROI claims.
"""
import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import pathlib
import sqlite3
import statistics
import zipfile

BASE = pathlib.Path(__file__).resolve().parent
RAW = BASE / "raw"
OUT = BASE / "output"

RETRO_TO_MLB = {
    "ANA": "LAA", "ARI": "ARI", "ATL": "ATL", "BAL": "BAL", "BOS": "BOS",
    "CHA": "CWS", "CHN": "CHC", "CIN": "CIN", "CLE": "CLE", "COL": "COL",
    "DET": "DET", "HOU": "HOU", "KCA": "KC", "LAN": "LAD", "MIA": "MIA",
    "MIL": "MIL", "MIN": "MIN", "NYA": "NYY", "NYN": "NYM", "OAK": "OAK",
    "PHI": "PHI", "PIT": "PIT", "SDN": "SD", "SEA": "SEA", "SFN": "SF",
    "SLN": "STL", "TBA": "TB", "TEX": "TEX", "TOR": "TOR", "WAS": "WSH",
}
ALIASES = {"KCR": "KC", "SDP": "SD", "SFG": "SF", "WSN": "WSH",
           "CHW": "CWS", "LAD": "LAD", "TBR": "TB", "AZ": "ARI", "ATH": "OAK"}


def norm(code):
    code = (code or "").upper().strip()
    return ALIASES.get(code, RETRO_TO_MLB.get(code, code))


def date_str(raw):
    return dt.datetime.strptime(raw, "%Y%m%d").date().isoformat()


def get_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def decimal_american(x):
    x = get_float(x)
    if x is None or x == 0:
        return None
    return 1 + x / 100 if x > 0 else 1 + 100 / abs(x)


def load_games():
    games = []
    for path in sorted(RAW.glob("gl20??.zip")):
        with zipfile.ZipFile(path) as z:
            txt = next(n for n in z.namelist() if n.lower().endswith(".txt"))
            reader = csv.reader(io.TextIOWrapper(z.open(txt), encoding="latin-1"))
            for row in reader:
                if len(row) < 104 or len(row[0]) != 8:
                    continue
                year = int(row[0][:4])
                if year < 2014 or year > 2025:
                    continue
                ar, hr = get_int(row[9]), get_int(row[10])
                if ar is None or hr is None or ar == hr or row[14].strip():
                    continue  # unscored, tied/suspended or forfeited: settle separately
                day, away, home = date_str(row[0]), norm(row[3]), norm(row[6])
                num = get_int(row[1]) or 0
                games.append(dict(game_id=f"{row[6]}{row[0]}{num}", date=day,
                                  season=year, away=away, home=home, game_number=num,
                                  away_runs=ar, home_runs=hr, home_win=int(hr > ar),
                                  park_id=row[16], actual_away_starter_id=row[101],
                                  actual_home_starter_id=row[103],
                                  source_file=path.name))
    snapshots=sorted(RAW.glob('mlb_schedule_2026_asof_*.json'))
    if snapshots:
        path=snapshots[-1]
        captured=json.loads(path.read_text())
        for item in captured['games']:
            if item['status']!='Final' or item['home_score'] is None or item['away_score'] is None:
                continue
            hr,ar=int(item['home_score']),int(item['away_score'])
            if hr==ar:continue
            # Retrospective probablePitcher fields do not prove pregame knowledge.
            games.append(dict(game_id='MLB'+str(item['game_pk']),
                              date=item['official_date'],season=2026,
                              away=norm(item['away_team']),home=norm(item['home_team']),
                              game_number=int(item['game_number']),
                              away_runs=ar,home_runs=hr,home_win=int(hr>ar),
                              park_id=str(item['venue_id']),
                              actual_away_starter_id=None,actual_home_starter_id=None,
                              source_file=path.name))
    games.sort(key=lambda g: (g["date"], g["game_number"], g["game_id"]))
    assert len({g["game_id"] for g in games}) == len(games)
    return games


def safe_avg(values):
    return round(statistics.mean(values), 5) if values else None


def build_features(games):
    hist = collections.defaultdict(list)
    pending = []
    current_date = None
    features = []
    for g in games:
        if g["date"] != current_date:
            for prev in pending:
                hist[prev["home"]].append((prev["date"], prev["home_win"],
                                            prev["home_runs"], prev["away_runs"]))
                hist[prev["away"]].append((prev["date"], 1 - prev["home_win"],
                                            prev["away_runs"], prev["home_runs"]))
            pending, current_date = [], g["date"]
        if g["season"] >= 2015:
            feat = {"game_id": g["game_id"], "feature_cutoff_date_exclusive": g["date"]}
            for side in ("home", "away"):
                team_history = hist[g[side]]
                prior_season = [x for x in team_history if x[0][:4] == str(g["season"])]
                feat[f"{side}_prior_season_games"] = len(prior_season)
                feat[f"{side}_prior_season_win_pct"] = safe_avg([x[1] for x in prior_season])
                feat[f"{side}_rest_days"] = min((dt.date.fromisoformat(g["date"]) -
                    dt.date.fromisoformat(team_history[-1][0])).days - 1, 30) if team_history else None
                for n in (5, 10, 20):
                    subset = team_history[-n:]
                    feat[f"{side}_prior_{n}_games"] = len(subset)
                    feat[f"{side}_win_pct_{n}"] = safe_avg([x[1] for x in subset])
                    feat[f"{side}_runs_for_{n}"] = safe_avg([x[2] for x in subset])
                    feat[f"{side}_runs_against_{n}"] = safe_avg([x[3] for x in subset])
            features.append(feat)
        pending.append(g)
    return features


def odds_games(payload):
    for day, entries in payload.items():
        if not isinstance(entries, list):
            continue
        for item in entries:
            v = item.get("gameView", {})
            if v.get("gameType") != "R":
                continue
            away, home = v.get("awayTeam") or {}, v.get("homeTeam") or {}
            yield (day, norm(away.get("shortName")), norm(home.get("shortName"))), item


def prepare_odds(games, payload):
    bykey = collections.defaultdict(list)
    for g in games:
        if g["season"] >= 2021:
            bykey[(g["date"], g["away"], g["home"])].append(g)
    incoming = collections.defaultdict(list)
    for key, item in odds_games(payload):
        incoming[key].append(item)
    lines, matches, issues = [], [], []
    counts = collections.Counter()
    for key, entries in sorted(incoming.items()):
        candidates = bykey.get(key, [])
        # For doubleheaders, actual scores disambiguate the identity only.
        # Scores and actual starters never enter the pregame feature table.
        used = set()
        for item in entries:
            v = item["gameView"]
            scores = (get_int(v.get("awayTeamScore")), get_int(v.get("homeTeamScore")))
            available = [g for g in candidates if g["game_id"] not in used]
            exact = [g for g in available if (g["away_runs"],g["home_runs"]) == scores]
            if len(exact) != 1:
                counts["unmatched_or_ambiguous"] += 1
                issues.append((str(key), str(scores), len(candidates), len(exact)))
                continue
            g = exact[0]
            used.add(g["game_id"])
            matches.append((g["game_id"], v.get("startDate"), v.get("gameStatusText")))
            counts["matched_games"] += 1
            for offer in (item.get("odds") or {}).get("moneyline", []):
                book = offer.get("sportsbook")
                for kind, field in (("opening", "openingLine"), ("last_observed", "currentLine")):
                    pair = offer.get(field) or {}
                    for side in ("home", "away"):
                        american = get_int(pair.get(side + "Odds"))
                        decimal = decimal_american(american)
                        if decimal and book:
                            lines.append((g["game_id"],book,kind,side,american,decimal,
                                          None, None, "timestamp_unknown", "sbr_archive_via_ArnavSaraogi"))
                            counts[kind+"_offers"] += 1
    return matches, lines, issues, counts


SCHEMA = """
CREATE TABLE games (game_id TEXT PRIMARY KEY, game_date TEXT, season INTEGER, away_team TEXT,
 home_team TEXT, doubleheader_number INTEGER, away_runs INTEGER, home_runs INTEGER,
 home_win INTEGER, park_id TEXT, actual_away_starter_id TEXT, actual_home_starter_id TEXT,
 result_source TEXT);
CREATE TABLE pregame_features (game_id TEXT PRIMARY KEY REFERENCES games(game_id),
 cutoff_date_exclusive TEXT, home_prior_season_games INTEGER, home_prior_season_win_pct REAL,
 home_rest_days INTEGER, away_prior_season_games INTEGER, away_prior_season_win_pct REAL,
 away_rest_days INTEGER,
 home_prior_5_games INTEGER, home_win_pct_5 REAL, home_runs_for_5 REAL, home_runs_against_5 REAL,
 home_prior_10_games INTEGER, home_win_pct_10 REAL, home_runs_for_10 REAL, home_runs_against_10 REAL,
 home_prior_20_games INTEGER, home_win_pct_20 REAL, home_runs_for_20 REAL, home_runs_against_20 REAL,
 away_prior_5_games INTEGER, away_win_pct_5 REAL, away_runs_for_5 REAL, away_runs_against_5 REAL,
 away_prior_10_games INTEGER, away_win_pct_10 REAL, away_runs_for_10 REAL, away_runs_against_10 REAL,
 away_prior_20_games INTEGER, away_win_pct_20 REAL, away_runs_for_20 REAL, away_runs_against_20 REAL);
CREATE TABLE archive_matches (game_id TEXT PRIMARY KEY REFERENCES games(game_id),
 archived_start_utc TEXT, archived_status TEXT);
CREATE TABLE odds_quotes (id INTEGER PRIMARY KEY, game_id TEXT REFERENCES games(game_id),
 bookmaker TEXT, quote_kind TEXT, side TEXT, american_odds INTEGER, decimal_odds REAL,
 observed_at_utc TEXT, decision_at_utc TEXT, availability TEXT, quote_source TEXT,
 CHECK(availability!='verified_predecision' OR
       (observed_at_utc IS NOT NULL AND decision_at_utc IS NOT NULL
        AND observed_at_utc<=decision_at_utc)));
CREATE INDEX odds_match_idx ON odds_quotes(game_id,bookmaker,quote_kind,side);
CREATE TABLE public_signals (id INTEGER PRIMARY KEY, game_id TEXT REFERENCES games(game_id),
 team TEXT, player_id TEXT, signal_type TEXT, source_url TEXT NOT NULL,
 published_at_utc TEXT NOT NULL, collected_at_utc TEXT NOT NULL,
 decision_at_utc TEXT NOT NULL, status TEXT NOT NULL,
 impact_note TEXT, impact_rating REAL,
 CHECK(published_at_utc < decision_at_utc),
 CHECK(collected_at_utc <= decision_at_utc));
CREATE TABLE source_files (name TEXT PRIMARY KEY, sha256 TEXT, bytes INTEGER, url TEXT);
CREATE VIEW model_inputs AS
 SELECT g.game_date, g.season, g.home_team, g.away_team,
        f.*
 FROM pregame_features f JOIN games g USING(game_id);
CREATE VIEW verified_bet_quotes AS
 SELECT q.* FROM odds_quotes q JOIN archive_matches m USING(game_id)
 WHERE q.availability='verified_predecision' AND q.observed_at_utc IS NOT NULL
   AND q.decision_at_utc IS NOT NULL
   AND q.observed_at_utc<=q.decision_at_utc
   AND q.decision_at_utc<m.archived_start_utc;
CREATE VIEW timestamped_quotes AS
 SELECT q.* FROM odds_quotes q JOIN archive_matches m USING(game_id)
 WHERE q.availability='timestamp_verified_pregame'
   AND q.observed_at_utc IS NOT NULL AND q.decision_at_utc IS NOT NULL
   AND q.observed_at_utc<=q.decision_at_utc
   AND q.decision_at_utc<m.archived_start_utc;
"""


def source_record(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            h.update(block)
    url = (f"https://www.retrosheet.org/gamelogs/{path.name}" if path.name.startswith("gl")
           else (json.loads(path.read_text())['source_url'] if path.name.startswith('mlb_schedule_')
                 else "https://github.com/ArnavSaraogi/mlb-odds-scraper/releases/download/dataset/mlb_odds_dataset.json"))
    return (path.name,h.hexdigest(),path.stat().st_size,url)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-odds", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    games = load_games()
    features = build_features(games)
    matches, quotes, issues, counts = [], [], [], collections.Counter()
    odds_path = RAW / "mlb_odds_dataset.json"
    if odds_path.exists() and not args.skip_odds:
        with odds_path.open(encoding="utf-8") as f:
            matches, quotes, issues, counts = prepare_odds(games, json.load(f))
    db = OUT / "mlb_time_machine.sqlite"
    if db.exists(): db.unlink()
    c = sqlite3.connect(db)
    c.executescript(SCHEMA)
    c.executemany("INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [tuple(g[k] for k in
        ("game_id","date","season","away","home","game_number","away_runs","home_runs",
         "home_win","park_id","actual_away_starter_id","actual_home_starter_id","source_file")) for g in games])
    feature_columns = ["game_id","feature_cutoff_date_exclusive", "home_prior_season_games",
      "home_prior_season_win_pct","home_rest_days","away_prior_season_games",
      "away_prior_season_win_pct","away_rest_days"]
    for side in ("home","away"):
        for n in (5,10,20):
            feature_columns += [f"{side}_prior_{n}_games",f"{side}_win_pct_{n}",
                                f"{side}_runs_for_{n}",f"{side}_runs_against_{n}"]
    c.executemany("INSERT INTO pregame_features VALUES ("+','.join('?' for _ in feature_columns)+")",
                  [[feat.get(k) for k in feature_columns] for feat in features])
    c.executemany("INSERT INTO archive_matches VALUES (?,?,?)",matches)
    c.executemany("INSERT INTO odds_quotes (game_id,bookmaker,quote_kind,side,american_odds,decimal_odds,observed_at_utc,decision_at_utc,availability,quote_source) VALUES (?,?,?,?,?,?,?,?,?,?)",quotes)
    schedule_snapshots=sorted(RAW.glob('mlb_schedule_2026_asof_*.json'))
    sources=sorted(RAW.glob('gl20??.zip'))
    if schedule_snapshots:sources.append(schedule_snapshots[-1])
    if odds_path.exists() and not args.skip_odds:sources.append(odds_path)
    c.executemany("INSERT INTO source_files VALUES (?,?,?,?)",[source_record(p) for p in sources])
    c.commit()
    summary = {"games_total":len(games),"feature_rows_total":len(features),
               "odds_matched_games":len(matches),"odds_quote_rows":len(quotes),
               "ambiguous_or_unmatched_archive_entries":len(issues),
               "archive_counts":dict(counts),"year_counts":dict(c.execute(
                 "SELECT season, COUNT(*) FROM games GROUP BY season").fetchall()),
               "match_by_year":dict(c.execute("SELECT substr(g.game_date,1,4), COUNT(*) FROM archive_matches m JOIN games g USING(game_id) GROUP BY 1").fetchall()),
               "odds_not_trade_verified":True,
               "signals_ingested":0}
    (OUT/'quality_report.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
    with (OUT/'join_issues.csv').open('w',newline='') as f:
        w=csv.writer(f); w.writerow(['date_away_home','archived_scores','candidate_games','score_matches']);w.writerows(issues)
    c.close()
    print(json.dumps(summary,indent=2))


if __name__ == '__main__': main()
