#!/usr/bin/env python3
"""Cross-check only suspicious probable starters against public ESPN summaries.

ESPN's endpoint is not a documented service contract. This evidence is an
independent review signal, never an automatic replacement for MLB observations.
"""
import concurrent.futures
import datetime as dt
import json
import pathlib
import sqlite3
import urllib.request
import unicodedata

BASE=pathlib.Path(__file__).resolve().parent
ROOT='https://site.api.espn.com/apis/site/v2/sports/baseball/mlb'


def name_key(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',value or '')
                   if not unicodedata.combining(c)).casefold().strip()


def fetch(url):
    started=dt.datetime.now(dt.timezone.utc).isoformat()
    result={'url':url,'requested_at_utc':started}
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'MLB-Time-Machine-research/1.0'})
        with urllib.request.urlopen(req,timeout=30) as response:
            result['payload']=json.load(response)
    except Exception as exc:result['error']=type(exc).__name__+': '+str(exc)
    result['received_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
    return result


def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('schedule_snapshot',type=pathlib.Path)
    args=p.parse_args()
    schedule=json.loads(args.schedule_snapshot.read_text())
    games={g['game_pk']:g for g in schedule['games']}
    with sqlite3.connect(BASE/'output/mlb_time_machine.sqlite') as conn:
        alerts=conn.execute('''SELECT c.official_game_pk,c.side,c.team,c.probable_pitcher_id,
            c.days_since_last_start,CASE WHEN p.player_id IS NULL THEN 'roster_conflict'
            ELSE 'long_rest' END
            FROM latest_pregame_context c LEFT JOIN nonconflicting_probable_starters p
            ON p.official_game_pk=c.official_game_pk AND p.side=c.side
            AND p.player_id=c.probable_pitcher_id
            WHERE c.probable_pitcher_id IS NOT NULL
            AND (p.player_id IS NULL OR c.days_since_last_start>14)''').fetchall()
    dates={games[pk]['official_date'] for pk,*_ in alerts if pk in games}
    boards={day:fetch(f'{ROOT}/scoreboard?dates={day.replace("-","")}') for day in sorted(dates)}
    tasks={}
    for pk,side,team,pid,rest,reason in alerts:
        game=games.get(pk)
        if not game:continue
        day=game['official_date'];board=boards[day]
        if 'payload' not in board:continue
        matches=[]
        for event in board['payload'].get('events',[]):
            competition=event.get('competitions',[{}])[0]
            teams={c.get('homeAway'):c.get('team',{}).get('abbreviation')
                   for c in competition.get('competitors',[])}
            if (teams.get('home'),teams.get('away'))==(game['home_team'],game['away_team']):
                matches.append(event)
        if len(matches)!=1:continue
        eid=matches[0]['id']
        tasks[eid]=f'{ROOT}/summary?event={eid}'
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        summaries=dict(zip(tasks,pool.map(fetch,tasks.values())))
    records=[]
    for pk,side,team,pid,rest,reason in alerts:
        game=games.get(pk)
        if not game:continue
        board=boards[game['official_date']]
        events=board.get('payload',{}).get('events',[])
        matches=[e for e in events if {c.get('homeAway'):c.get('team',{}).get('abbreviation')
                 for c in e.get('competitions',[{}])[0].get('competitors',[])}==
                 {'home':game['home_team'],'away':game['away_team']}]
        if len(matches)!=1:continue
        result=summaries.get(matches[0]['id'],{})
        if 'payload' not in result:continue
        summary=result['payload']
        injury_group=next((x for x in summary.get('injuries',[])
                           if x.get('team',{}).get('abbreviation')==team),{})
        injuries=[{'name':x.get('athlete',{}).get('fullName'),
                   'status':x.get('status'),'listed_at_utc':x.get('date')}
                  for x in injury_group.get('injuries',[])]
        competition=summary.get('header',{}).get('competitions',[{}])[0]
        competitor=next((c for c in competition.get('competitors',[])
                         if c.get('homeAway')==side),{})
        probable=(competitor.get('probables') or [{}])[0]
        espn_name=probable.get('athlete',{}).get('fullName') or probable.get('displayName')
        mlb_name=game.get(side+'_probable_pitcher_name_at_capture')
        injured=next((x for x in injuries if x['name'] and mlb_name and
                      name_key(x['name'])==name_key(mlb_name)),None)
        records.append({'mlb_game_pk':pk,'side':side,'team':team,
                        'mlb_probable_pitcher_id':pid,'mlb_probable_name':mlb_name,
                        'days_since_last_start':rest,'review_reason':reason,
                        'espn_event_id':matches[0]['id'],
                        'espn_probable_name':espn_name,
                        'espn_probable_matches':bool(mlb_name and espn_name and
                                                      name_key(mlb_name)==name_key(espn_name)),
                        'espn_injury_status_for_probable':injured['status'] if injured else None,
                        'team_injuries':injuries,'source_url':result['url'],
                        'received_at_utc':result['received_at_utc'],
                        'scheduled_start_utc':game['scheduled_start_utc']})
    snapshot={'created_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
              'schedule_snapshot_file':args.schedule_snapshot.name,
              'board_requests':[{k:v for k,v in value.items() if k!='payload'} for value in boards.values()],
              'summary_requests':[{k:v for k,v in value.items() if k!='payload'} for value in summaries.values()],
              'alerts':records,'disclaimer':'ESPN is a secondary, undocumented cross-check; null injury does not confirm health.'}
    path=BASE/'raw'/('espn_alert_audit_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
    path.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'file':str(path),'alerts':len(records),
                      'injury_corrob':sum(bool(x['espn_injury_status_for_probable']) for x in records),
                      'failed_requests':sum('error' in x for x in boards.values())+
                                        sum('error' in x for x in summaries.values())}))


if __name__=='__main__':main()
