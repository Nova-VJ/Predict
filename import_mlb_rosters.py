#!/usr/bin/env python3
"""Link observed 40-man roster statuses and probable starters to future games."""
import argparse
import collections
import json
import pathlib
import sqlite3

from import_snapshot import parse_utc

BASE=pathlib.Path(__file__).resolve().parent


def import_rosters(conn,rosters,schedule,filename):
    conn.executescript('''CREATE TABLE IF NOT EXISTS observed_roster_status (
      official_game_pk INTEGER NOT NULL, team TEXT NOT NULL, player_id INTEGER NOT NULL,
      player_name TEXT NOT NULL, status_code TEXT, status_description TEXT,
      roster_type TEXT NOT NULL, requested_at_utc TEXT NOT NULL,
      received_at_utc TEXT NOT NULL, source_url TEXT NOT NULL, capture_file TEXT NOT NULL,
      PRIMARY KEY(official_game_pk,team,player_id,capture_file));
      CREATE TABLE IF NOT EXISTS observed_probable_starters (
      official_game_pk INTEGER NOT NULL, team TEXT NOT NULL, side TEXT NOT NULL,
      player_id INTEGER NOT NULL, player_name TEXT NOT NULL,
      observed_at_utc TEXT NOT NULL, scheduled_start_utc TEXT NOT NULL,
      source_url TEXT NOT NULL, capture_file TEXT NOT NULL,
      PRIMARY KEY(official_game_pk,side,capture_file));
      DROP VIEW IF EXISTS nonconflicting_probable_starters;
      CREATE VIEW nonconflicting_probable_starters AS
      WITH latest_probable AS (
        SELECT p.*,ROW_NUMBER() OVER (PARTITION BY official_game_pk,side
          ORDER BY observed_at_utc DESC) AS observation_rank
        FROM observed_probable_starters p
      ), latest_status AS (
        SELECT r.*,ROW_NUMBER() OVER (PARTITION BY official_game_pk,player_id
          ORDER BY received_at_utc DESC) AS status_rank
        FROM observed_roster_status r
      )
      SELECT p.* FROM latest_probable p LEFT JOIN latest_status r
        ON r.official_game_pk=p.official_game_pk AND r.player_id=p.player_id
        AND r.status_rank=1
      WHERE p.observation_rank=1
        AND COALESCE(r.status_description,'') NOT LIKE 'Injured%';''')
    counts=collections.Counter()
    fixtures=[g for g in schedule['games'] if g['status']!='Final']
    schedule_at=parse_utc(schedule['captured_at_utc'])
    for g in fixtures:
        start=parse_utc(g['scheduled_start_utc'])
        if schedule_at>=start:counts['schedule_after_start']+=1;continue
        for side in ('home','away'):
            code=g[side+'_team']
            pid=g.get(side+'_probable_pitcher_id_at_capture')
            if pid:
                conn.execute('''INSERT OR IGNORE INTO observed_probable_starters
                    VALUES(?,?,?,?,?,?,?,?,?)''',
                    (g['game_pk'],code,side,pid,g[side+'_probable_pitcher_name_at_capture'],
                     schedule['captured_at_utc'],g['scheduled_start_utc'],schedule['source_url'],
                     rosters['schedule_snapshot_file']))
                counts['probable_starters']+=conn.execute('SELECT changes()').fetchone()[0]
            capture=rosters['rosters'].get(code)
            if not capture:counts['team_capture_missing']+=1;continue
            received=parse_utc(capture['received_at_utc'])
            if received>=start:counts['roster_received_after_start']+=1;continue
            if capture['payload'].get('rosterType')!='40Man':
                counts['unexpected_roster_type']+=1;continue
            for row in capture['payload'].get('roster',[]):
                person=row.get('person') or {}
                if not person.get('id'):continue
                status=row.get('status') or {}
                conn.execute('''INSERT OR IGNORE INTO observed_roster_status
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                    (g['game_pk'],code,person['id'],person.get('fullName',''),
                     status.get('code'),status.get('description'),'40Man',
                     capture['requested_at_utc'],capture['received_at_utc'],capture['url'],filename))
                changed=conn.execute('SELECT changes()').fetchone()[0]
                counts['roster_rows']+=changed
                if 'Injured' in (status.get('description') or ''):
                    counts['injured_status_rows']+=changed
    conn.commit()
    return dict(counts)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('rosters_snapshot',type=pathlib.Path)
    p.add_argument('schedule_snapshot',type=pathlib.Path)
    p.add_argument('--database',type=pathlib.Path,default=BASE/'output/mlb_time_machine.sqlite')
    args=p.parse_args()
    rosters=json.loads(args.rosters_snapshot.read_text())
    schedule=json.loads(args.schedule_snapshot.read_text())
    if rosters['schedule_snapshot_file']!=args.schedule_snapshot.name:
        raise SystemExit('Roster capture references a different schedule file.')
    with sqlite3.connect(args.database) as conn:
        report=import_rosters(conn,rosters,schedule,args.rosters_snapshot.name)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
