#!/usr/bin/env python3
"""Import a saved The Odds API historical MLB snapshot without claiming execution.

The paid request is made separately and its unmodified JSON is supplied here.
Rejection is strict: stale snapshots, unconfirmed identities and missing book
updates stay out of the research database.
"""
import argparse
import datetime as dt
import json
import pathlib
import sqlite3

from build_dataset import decimal_american

BASE=pathlib.Path(__file__).resolve().parent
TEAM={
 'Arizona Diamondbacks':'ARI','Atlanta Braves':'ATL','Baltimore Orioles':'BAL',
 'Boston Red Sox':'BOS','Chicago Cubs':'CHC','Chicago White Sox':'CWS',
 'Cincinnati Reds':'CIN','Cleveland Guardians':'CLE','Colorado Rockies':'COL',
 'Detroit Tigers':'DET','Houston Astros':'HOU','Kansas City Royals':'KC',
 'Los Angeles Angels':'LAA','Los Angeles Dodgers':'LAD','Miami Marlins':'MIA',
 'Milwaukee Brewers':'MIL','Minnesota Twins':'MIN','New York Mets':'NYM',
 'New York Yankees':'NYY','Oakland Athletics':'OAK','Athletics':'OAK',
 'Philadelphia Phillies':'PHI','Pittsburgh Pirates':'PIT','San Diego Padres':'SD',
 'San Francisco Giants':'SF','Seattle Mariners':'SEA','St. Louis Cardinals':'STL',
 'Tampa Bay Rays':'TB','Texas Rangers':'TEX','Toronto Blue Jays':'TOR',
 'Washington Nationals':'WSH',
}


def parse_utc(s):
    v=dt.datetime.fromisoformat(s.replace('Z','+00:00'))
    if v.tzinfo is None or v.utcoffset()!=dt.timedelta(0):
        raise ValueError('UTC timestamp required')
    return v


def import_snapshot(conn,payload):
    snap=parse_utc(payload['timestamp'])
    accepted=0
    rejected={}
    def skip(reason): rejected[reason]=rejected.get(reason,0)+1
    for event in payload['data']:
        if event.get('sport_key')!='baseball_mlb': skip('wrong_sport');continue
        home,away=event.get('home_team'),event.get('away_team')
        if home not in TEAM or away not in TEAM: skip('unknown_team');continue
        start=parse_utc(event['commence_time'])
        decision=start-dt.timedelta(hours=3)
        if snap>decision or decision-snap>dt.timedelta(minutes=30):
            skip('snapshot_not_within_30m_of_Tminus3h');continue
        # Match the existing game by teams and scheduled start, excluding
        # postponements and doubleheaders whose identity cannot be proven.
        games=conn.execute('''SELECT g.game_id,m.archived_start_utc FROM games g
          JOIN archive_matches m USING(game_id)
          WHERE g.home_team=? AND g.away_team=?
          AND g.game_date BETWEEN ? AND ?''',
          (TEAM[home],TEAM[away],(start-dt.timedelta(days=1)).date().isoformat(),
                                 (start+dt.timedelta(days=1)).date().isoformat())).fetchall()
        games=[(gid,parse_utc(t)) for gid,t in games if t and abs(parse_utc(t)-start)<=dt.timedelta(minutes=90)]
        if len(games)!=1:skip('ambiguous_or_missing_game');continue
        gid,archived_start=games[0]
        if decision>=archived_start:skip('decision_after_archived_start');continue
        for book in event.get('bookmakers',[]):
            for market in book.get('markets',[]):
                if market.get('key')!='h2h':continue
                updated=market.get('last_update') or book.get('last_update')
                if not updated:skip('book_update_missing');continue
                updated=parse_utc(updated)
                if updated>snap or snap-updated>dt.timedelta(hours=1):
                    skip('book_quote_stale_or_future');continue
                prices={x['name']:x['price'] for x in market.get('outcomes',[]) if 'price' in x}
                if home not in prices or away not in prices:
                    skip('incomplete_moneyline');continue
                offers=[]
                for side,name in (('home',home),('away',away)):
                    price=int(prices[name])
                    dec=decimal_american(price)
                    if not dec:break
                    offers.append((gid,book['key'],'Tminus3h_snapshot',side,price,dec,
                        snap.isoformat(),decision.isoformat(),'timestamp_verified_pregame',
                        'the_odds_api:'+event['id']))
                if len(offers)==2:
                    conn.executemany('''INSERT INTO odds_quotes
                      (game_id,bookmaker,quote_kind,side,american_odds,decimal_odds,
                       observed_at_utc,decision_at_utc,availability,quote_source)
                      VALUES (?,?,?,?,?,?,?,?,?,?)''',offers)
                    accepted+=1
    conn.commit()
    return {'two_sided_book_quotes':accepted,'excluded_events_or_books':rejected}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('snapshot_json',type=pathlib.Path)
    p.add_argument('--database',type=pathlib.Path,default=BASE/'output/mlb_time_machine.sqlite')
    args=p.parse_args()
    payload=json.loads(args.snapshot_json.read_text())
    conn=sqlite3.connect(args.database)
    try:
        print(json.dumps(import_snapshot(conn,payload),indent=2))
    except Exception:
        conn.rollback();raise
    finally: conn.close()


if __name__=='__main__':main()
