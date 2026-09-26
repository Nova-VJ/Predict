#!/usr/bin/env python3
"""Timestamp MLB pitcher logs, prior boxscores and announced pregame lineups."""
import argparse
import concurrent.futures
import datetime as dt
import json
import pathlib
import urllib.request

BASE=pathlib.Path(__file__).resolve().parent
ROOT='https://statsapi.mlb.com/api/v1'


def now():
    return dt.datetime.now(dt.timezone.utc)


def fetch(item):
    kind,identifier,url=item
    requested=now().isoformat()
    record={'kind':kind,'id':identifier,'url':url,'requested_at_utc':requested}
    try:
        request=urllib.request.Request(url,headers={'User-Agent':'MLB-Time-Machine-research/1.0'})
        with urllib.request.urlopen(request,timeout=30) as response:
            record['payload']=json.load(response)
    except Exception as exc:
        record['error']=type(exc).__name__+': '+str(exc)
    record['received_at_utc']=now().isoformat()
    return record


def main():
    p=argparse.ArgumentParser()
    p.add_argument('schedule_snapshot',type=pathlib.Path)
    p.add_argument('--game-pks',help='Comma-separated future MLB game IDs')
    p.add_argument('--lineups-only',action='store_true')
    p.add_argument('--lookback-days',type=int,default=3)
    p.add_argument('--workers',type=int,default=5)
    p.add_argument('--reuse-final-boxes',action='store_true',
                   help='Reuse successful dated official boxscores already captured locally')
    args=p.parse_args()
    schedule=json.loads(args.schedule_snapshot.read_text())
    select={int(x) for x in args.game_pks.split(',')} if args.game_pks else None
    today=now().date()
    future=[g for g in schedule['games'] if g['status']!='Final' and
            (select is None or g['game_pk'] in select) and
            (select is not None or today<=dt.date.fromisoformat(g['official_date'])<=today+dt.timedelta(days=1))]
    if not future:raise SystemExit('No eligible future games in schedule snapshot.')
    tasks=[('lineup',g['game_pk'],f"{ROOT}/game/{g['game_pk']}/boxscore") for g in future]
    if not args.lineups_only:
        ids={g[side+'_probable_pitcher_id_at_capture'] for g in future
             for side in ('home','away') if g.get(side+'_probable_pitcher_id_at_capture')}
        tasks += [('pitcher',pid,f'{ROOT}/people/{pid}/stats?stats=gameLog&group=pitching&season={today.year}')
                  for pid in sorted(ids)]
        earliest=min(dt.date.fromisoformat(g['official_date']) for g in future)
        previous=[g for g in schedule['games'] if g['status']=='Final' and
                  earliest-dt.timedelta(days=args.lookback_days)<=dt.date.fromisoformat(g['official_date'])<earliest and
                  dt.date.fromisoformat(g['official_date'])<today]
        tasks += [('final_box',g['game_pk'],f"{ROOT}/game/{g['game_pk']}/boxscore") for g in previous]
    reused={}
    if args.reuse_final_boxes:
        for old_path in sorted((BASE/'raw').glob('mlb_context_*.json')):
            old=json.loads(old_path.read_text())
            for capture in old.get('captures',[]):
                if capture['kind']=='final_box' and 'payload' in capture:
                    reused[('final_box',capture['id'])]=capture
    reused_records=[reused[(kind,identifier)] for kind,identifier,_ in tasks
                    if (kind,identifier) in reused]
    to_fetch=[task for task in tasks if (task[0],task[1]) not in reused]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        captures=reused_records+list(executor.map(fetch,to_fetch))
    stamp=now().strftime('%Y%m%dT%H%M%S%fZ')
    path=BASE/'raw'/f'mlb_context_{stamp}.json'
    path.write_text(json.dumps({'schedule_snapshot_file':args.schedule_snapshot.name,
                                'created_at_utc':now().isoformat(),
                                'future_games':future,'prior_final_games':previous if not args.lineups_only else [],
                                'captures':captures},ensure_ascii=False,separators=(',',':'))+'\n')
    print(json.dumps({'file':str(path),'future_games':len(future),
                      'requests':len(to_fetch),'reused_final_boxscores':len(reused_records),
                      'errors':sum('error' in c for c in captures),
                      'lineups_announced':sum(bool(c.get('payload',{}).get('teams',{}).get('home',{}).get('battingOrder')) and
                                               bool(c.get('payload',{}).get('teams',{}).get('away',{}).get('battingOrder'))
                                               for c in captures if c['kind']=='lineup')}))


if __name__=='__main__':main()
