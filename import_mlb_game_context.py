#!/usr/bin/env python3
"""Create point-in-time pitcher, bullpen and lineup observations."""
import argparse
import collections
import datetime as dt
import json
import pathlib
import sqlite3

from import_snapshot import parse_utc

BASE=pathlib.Path(__file__).resolve().parent


def earlier(record,start):
    return 'payload' in record and parse_utc(record['received_at_utc'])<parse_utc(start)


def pitcher_form(record,game):
    if not record:return None
    cutoff=min(dt.date.fromisoformat(game['official_date']),
               parse_utc(record['received_at_utc']).date())
    splits=[s for group in record['payload'].get('stats',[]) for s in group.get('splits',[])
            if s.get('date') and dt.date.fromisoformat(s['date'])<cutoff and
            s.get('stat',{}).get('gamesStarted',0)>0]
    splits.sort(key=lambda s:(s['date'],s.get('game',{}).get('gamePk',0)))
    recent=splits[-5:]
    total=lambda field:sum(int(s['stat'].get(field) or 0) for s in recent)
    return {'season_starts_before':len(splits),'last5_starts':len(recent),
            'last5_outs':total('outs'),'last5_strikeouts':total('strikeOuts'),
            'last5_walks':total('baseOnBalls'),'last5_home_runs':total('homeRuns'),
            'last5_earned_runs':total('earnedRuns'),
            'last_start_pitches':int(splits[-1]['stat'].get('numberOfPitches') or 0) if splits else None,
            'days_since_last_start':(dt.date.fromisoformat(game['official_date'])-
                                    dt.date.fromisoformat(splits[-1]['date'])).days if splits else None}


def bullpen_form(captures,final_games,game,team):
    target=dt.date.fromisoformat(game['official_date'])
    rows=[]
    expected=0
    for previous in final_games:
        prior=dt.date.fromisoformat(previous['official_date'])
        if not (0<(target-prior).days<=3) or team not in (previous['home_team'],previous['away_team']):continue
        expected+=1
        record=captures.get(('final_box',previous['game_pk']))
        if not record or not earlier(record,game['scheduled_start_utc']):continue
        if prior>=parse_utc(record['received_at_utc']).date():continue
        side='home' if previous['home_team']==team else 'away'
        box=record['payload'].get('teams',{}).get(side,{})
        if not box.get('pitchers'):continue
        for pid in box['pitchers']:
            stats=box.get('players',{}).get('ID'+str(pid),{}).get('stats',{}).get('pitching',{})
            if not stats or int(stats.get('gamesStarted') or 0):continue
            rows.append(((target-prior).days,pid,int(stats.get('numberOfPitches') or 0),
                         int(stats.get('outs') or 0)))
    if expected==0:return {'prior_team_games':0,'observed_team_games':0,'relief_pitches_1d':0,
                           'relief_pitches_3d':0,'relief_outs_3d':0,'relievers_used_3d':0}
    seen=sum(bool(captures.get(('final_box',g['game_pk'])) and
                  earlier(captures[('final_box',g['game_pk'])],game['scheduled_start_utc']))
             for g in final_games if team in (g['home_team'],g['away_team']) and
             0<(target-dt.date.fromisoformat(g['official_date'])).days<=3)
    return {'prior_team_games':expected,'observed_team_games':seen,
            'relief_pitches_1d':sum(p for days,_,p,_ in rows if days==1) if seen==expected else None,
            'relief_pitches_3d':sum(p for _,_,p,_ in rows) if seen==expected else None,
            'relief_outs_3d':sum(outs for _,_,_,outs in rows) if seen==expected else None,
            'relievers_used_3d':len(set(pid for _,pid,_,_ in rows)) if seen==expected else None}


def import_context(conn,snapshot,filename):
    conn.executescript('''CREATE TABLE IF NOT EXISTS observed_pitcher_form (
      official_game_pk INTEGER, side TEXT, team TEXT, probable_pitcher_id INTEGER,
      captured_at_utc TEXT, scheduled_start_utc TEXT, season_starts_before INTEGER,
      last5_starts INTEGER, last5_outs INTEGER, last5_strikeouts INTEGER,
      last5_walks INTEGER, last5_home_runs INTEGER, last5_earned_runs INTEGER,
      last_start_pitches INTEGER, days_since_last_start INTEGER,
      source_url TEXT, capture_file TEXT,
      PRIMARY KEY(official_game_pk,side,capture_file));
    CREATE TABLE IF NOT EXISTS observed_bullpen_workload (
      official_game_pk INTEGER, side TEXT, team TEXT, captured_at_utc TEXT,
      scheduled_start_utc TEXT, prior_team_games INTEGER, observed_team_games INTEGER,
      relief_pitches_1d INTEGER, relief_pitches_3d INTEGER, relief_outs_3d INTEGER,
      relievers_used_3d INTEGER, source_file TEXT,
      PRIMARY KEY(official_game_pk,side,source_file));
    CREATE TABLE IF NOT EXISTS observed_lineups (
      official_game_pk INTEGER, side TEXT, team TEXT, captured_at_utc TEXT,
      scheduled_start_utc TEXT, announced INTEGER, batter_ids_json TEXT,
      source_url TEXT, capture_file TEXT,
      PRIMARY KEY(official_game_pk,side,capture_file));
    DROP VIEW IF EXISTS latest_pregame_context;
    CREATE VIEW latest_pregame_context AS
      WITH pf AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY official_game_pk,side
        ORDER BY captured_at_utc DESC) rn FROM observed_pitcher_form),
      bp AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY official_game_pk,side
        ORDER BY captured_at_utc DESC) rn FROM observed_bullpen_workload),
      lu AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY official_game_pk,side
        ORDER BY captured_at_utc DESC) rn FROM observed_lineups)
      SELECT lu.official_game_pk,lu.side,lu.team,lu.scheduled_start_utc,
        lu.captured_at_utc AS lineup_observed_utc,lu.announced,lu.batter_ids_json,
        pf.probable_pitcher_id,pf.captured_at_utc AS pitcher_observed_utc,
        pf.season_starts_before,pf.last5_starts,pf.last5_outs,pf.last5_strikeouts,
        pf.last5_walks,pf.last5_home_runs,pf.last5_earned_runs,
        pf.last_start_pitches,pf.days_since_last_start,
        bp.captured_at_utc AS bullpen_observed_utc,bp.prior_team_games,
        bp.observed_team_games,bp.relief_pitches_1d,bp.relief_pitches_3d,
        bp.relief_outs_3d,bp.relievers_used_3d
      FROM lu LEFT JOIN pf ON pf.official_game_pk=lu.official_game_pk
        AND pf.side=lu.side AND pf.rn=1
      LEFT JOIN bp ON bp.official_game_pk=lu.official_game_pk
        AND bp.side=lu.side AND bp.rn=1
      WHERE lu.rn=1;
    DROP VIEW IF EXISTS decision_eligible_context;
    CREATE VIEW decision_eligible_context AS
      SELECT c.official_game_pk,c.side,c.team,c.scheduled_start_utc,
        c.lineup_observed_utc,c.announced,c.batter_ids_json,
        CASE WHEN p.player_id IS NOT NULL THEN c.probable_pitcher_id END
          AS eligible_probable_pitcher_id,
        CASE WHEN p.player_id IS NOT NULL THEN 1 ELSE 0 END AS pitcher_status_clear,
        CASE WHEN p.player_id IS NOT NULL THEN c.season_starts_before END AS season_starts_before,
        CASE WHEN p.player_id IS NOT NULL THEN c.last5_starts END AS last5_starts,
        CASE WHEN p.player_id IS NOT NULL THEN c.last5_outs END AS last5_outs,
        CASE WHEN p.player_id IS NOT NULL THEN c.last5_strikeouts END AS last5_strikeouts,
        CASE WHEN p.player_id IS NOT NULL THEN c.last5_walks END AS last5_walks,
        CASE WHEN p.player_id IS NOT NULL THEN c.last5_home_runs END AS last5_home_runs,
        CASE WHEN p.player_id IS NOT NULL THEN c.last5_earned_runs END AS last5_earned_runs,
        CASE WHEN p.player_id IS NOT NULL THEN c.days_since_last_start END AS days_since_last_start,
        CASE WHEN p.player_id IS NOT NULL AND c.days_since_last_start>14
          THEN 1 ELSE 0 END AS long_rest_review,
        c.prior_team_games,c.observed_team_games,c.relief_pitches_1d,
        c.relief_pitches_3d,c.relief_outs_3d,c.relievers_used_3d
      FROM latest_pregame_context c
      LEFT JOIN nonconflicting_probable_starters p
        ON p.official_game_pk=c.official_game_pk AND p.side=c.side
        AND p.player_id=c.probable_pitcher_id;''')
    captures={(c['kind'],c['id']):c for c in snapshot['captures']}
    counts=collections.Counter()
    for game in snapshot['future_games']:
        for side in ('home','away'):
            team=game[side+'_team']
            lineup=captures.get(('lineup',game['game_pk']))
            if lineup and earlier(lineup,game['scheduled_start_utc']):
                order=lineup['payload'].get('teams',{}).get(side,{}).get('battingOrder') or []
                conn.execute('INSERT OR IGNORE INTO observed_lineups VALUES(?,?,?,?,?,?,?,?,?)',
                             (game['game_pk'],side,team,lineup['received_at_utc'],
                              game['scheduled_start_utc'],int(len(order)>=9),
                              json.dumps(order),lineup['url'],filename))
                counts['lineups_announced' if len(order)>=9 else 'lineups_missing']+=1
            pid=game.get(side+'_probable_pitcher_id_at_capture')
            pitcher=captures.get(('pitcher',pid)) if pid else None
            if pitcher and earlier(pitcher,game['scheduled_start_utc']):
                form=pitcher_form(pitcher,game)
                conn.execute('INSERT OR IGNORE INTO observed_pitcher_form VALUES('+','.join('?'*17)+')',
                    (game['game_pk'],side,team,pid,pitcher['received_at_utc'],
                     game['scheduled_start_utc'],*(form[k] for k in (
                      'season_starts_before','last5_starts','last5_outs','last5_strikeouts',
                      'last5_walks','last5_home_runs','last5_earned_runs','last_start_pitches',
                      'days_since_last_start')),pitcher['url'],filename))
                counts['pitcher_forms']+=1
            if snapshot['prior_final_games']:
                # All source boxscores must precede the fixture; incomplete coverage remains NULL.
                relevant=[c for c in captures.values() if c['kind']=='final_box' and
                          earlier(c,game['scheduled_start_utc'])]
                if relevant:
                    bp=bullpen_form(captures,snapshot['prior_final_games'],game,team)
                    observed=max(c['received_at_utc'] for c in relevant)
                    conn.execute('INSERT OR IGNORE INTO observed_bullpen_workload VALUES('+','.join('?'*12)+')',
                        (game['game_pk'],side,team,observed,game['scheduled_start_utc'],
                         *(bp[k] for k in ('prior_team_games','observed_team_games',
                           'relief_pitches_1d','relief_pitches_3d','relief_outs_3d',
                           'relievers_used_3d')),filename))
                    counts['bullpen_complete' if bp['prior_team_games']==bp['observed_team_games'] else 'bullpen_partial']+=1
    conn.commit()
    return dict(counts)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('snapshot',type=pathlib.Path)
    p.add_argument('--database',type=pathlib.Path,default=BASE/'output/mlb_time_machine.sqlite')
    args=p.parse_args()
    snapshot=json.loads(args.snapshot.read_text())
    with sqlite3.connect(args.database) as conn:
        report=import_context(conn,snapshot,args.snapshot.name)
        coverage={
          'game_sides':conn.execute('SELECT count(*) FROM latest_pregame_context').fetchone()[0],
          'pitcher_histories':conn.execute('SELECT count(*) FROM latest_pregame_context WHERE probable_pitcher_id IS NOT NULL').fetchone()[0],
          'clear_probable_starters':conn.execute('SELECT count(*) FROM decision_eligible_context WHERE pitcher_status_clear=1').fetchone()[0],
          'bullpen_complete':conn.execute('''SELECT count(*) FROM latest_pregame_context
            WHERE prior_team_games=observed_team_games AND prior_team_games IS NOT NULL''').fetchone()[0],
          'announced_lineups':conn.execute('SELECT count(*) FROM latest_pregame_context WHERE announced=1').fetchone()[0],
          'long_rest_review':conn.execute('SELECT count(*) FROM decision_eligible_context WHERE long_rest_review=1').fetchone()[0],
        }
    (BASE/'output/mlb_context_report.json').write_text(json.dumps({
        'latest_import_file':args.snapshot.name,'latest_import':report,'coverage':coverage,
        'interpretation':'Observed features only; no trained benefit or betting ROI established.'},
        indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
