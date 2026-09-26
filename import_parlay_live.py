#!/usr/bin/env python3
"""Import a captured pregame MLB board against the official fixture snapshot.

This captures actual observed odds, but does not infer that a future T-3h
decision saw the same price or that a sportsbook accepted a wager.
"""
import argparse
import collections
import datetime as dt
import json
import pathlib
import sqlite3

from import_snapshot import TEAM, parse_utc

BASE=pathlib.Path(__file__).resolve().parent


def import_board(conn,board,meta,fixture):
    receipt=parse_utc(meta['received_utc'])
    official=json.loads(fixture.read_text())
    fixtures=[g for g in official['games'] if g['status']!='Final']
    conn.executescript('''CREATE TABLE IF NOT EXISTS observed_live_quotes (
      id INTEGER PRIMARY KEY, official_game_pk INTEGER NOT NULL,
      official_schedule_capture_utc TEXT NOT NULL,
      home_team TEXT NOT NULL, away_team TEXT NOT NULL, scheduled_start_utc TEXT NOT NULL,
      provider_event_id TEXT NOT NULL, bookmaker TEXT NOT NULL, side TEXT NOT NULL,
      decimal_odds REAL NOT NULL, market_last_update_utc TEXT NOT NULL,
      request_utc TEXT NOT NULL, received_utc TEXT NOT NULL, capture_file TEXT NOT NULL,
      regions_requested TEXT,
      UNIQUE(official_game_pk,bookmaker,side,capture_file));''')
    columns={row[1] for row in conn.execute('PRAGMA table_info(observed_live_quotes)')}
    if 'regions_requested' not in columns:
        conn.execute('ALTER TABLE observed_live_quotes ADD COLUMN regions_requested TEXT')
    excluded=collections.Counter()
    inserted=0
    linked=set()
    for event in board:
        home,away=event.get('home_team'),event.get('away_team')
        if home not in TEAM or away not in TEAM:
            excluded['unknown_team']+=1;continue
        try:start=parse_utc(event['commence_time'])
        except (KeyError,TypeError,ValueError):excluded['missing_start']+=1;continue
        # The current official feed uses ATH and AZ; older archives use OAK and ARI.
        official_code=lambda name:{'OAK':'ATH','ARI':'AZ'}.get(TEAM[name],TEAM[name])
        candidates=[g for g in fixtures if g['home_team']==official_code(home) and
                    g['away_team']==official_code(away) and
                    abs(parse_utc(g['scheduled_start_utc'])-start)<=dt.timedelta(minutes=2)]
        if len(candidates)!=1:
            excluded['unmatched_or_ambiguous_fixture']+=1;continue
        provider_pk=(event.get('probable_pitchers') or {}).get('mlb_game_pk')
        if provider_pk is not None and int(provider_pk)!=candidates[0]['game_pk']:
            excluded['mlb_game_pk_disagrees']+=1;continue
        if receipt>=start:
            excluded['captured_after_start']+=1;continue
        fixture_game=candidates[0]
        linked.add(fixture_game['game_pk'])
        for bookmaker in event.get('bookmakers',[]):
            for market in bookmaker.get('markets',[]):
                if market.get('key')!='h2h':continue
                try:updated=parse_utc(market['last_update'])
                except (KeyError,TypeError,ValueError):excluded['missing_market_update']+=1;continue
                if updated>receipt or receipt-updated>dt.timedelta(hours=1):
                    excluded['stale_or_future_market_update']+=1;continue
                outcomes={o.get('name'):o.get('price') for o in market.get('outcomes',[])}
                if home not in outcomes or away not in outcomes:
                    excluded['incomplete_moneyline']+=1;continue
                try:prices=[float(outcomes[name]) for name in (home,away)]
                except (ValueError,TypeError):excluded['invalid_price']+=1;continue
                if any(price<=1 for price in prices):excluded['invalid_price']+=1;continue
                for side,price in zip(('home','away'),prices):
                    conn.execute('''INSERT OR IGNORE INTO observed_live_quotes
                        (official_game_pk,official_schedule_capture_utc,home_team,away_team,
                         scheduled_start_utc,provider_event_id,bookmaker,side,decimal_odds,
                         market_last_update_utc,request_utc,received_utc,capture_file,regions_requested)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (fixture_game['game_pk'],official['captured_at_utc'],official_code(home),official_code(away),
                         fixture_game['scheduled_start_utc'],event['id'],bookmaker['key'],side,price,
                         updated.isoformat(),meta['request_utc'],meta['received_utc'],meta['file'],
                         meta.get('regions_requested')))
                    inserted+=conn.execute('SELECT changes()').fetchone()[0]
    conn.commit()
    return {'board_events':len(board),'linked_official_fixtures':len(linked),
            'two_sided_book_quotes_inserted':inserted//2,'quote_rows_inserted':inserted,
            'excluded':dict(excluded)}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('board',type=pathlib.Path)
    p.add_argument('metadata',type=pathlib.Path)
    p.add_argument('official_fixture_snapshot',type=pathlib.Path)
    p.add_argument('--database',type=pathlib.Path,default=BASE/'output/mlb_time_machine.sqlite')
    args=p.parse_args()
    conn=sqlite3.connect(args.database)
    try:
        report=import_board(conn,json.loads(args.board.read_text()),json.loads(args.metadata.read_text()),args.official_fixture_snapshot)
        print(json.dumps(report,indent=2))
    finally:conn.close()


if __name__=='__main__':main()
