#!/usr/bin/env python3
"""Observe official MLB 40-man roster statuses for upcoming games.

The capture time proves the roster response existed then; transaction dates
are not substituted for a publication timestamp.
"""
import argparse
import concurrent.futures
import datetime as dt
import json
import pathlib
import urllib.parse
import urllib.request

BASE=pathlib.Path(__file__).resolve().parent


def now():return dt.datetime.now(dt.timezone.utc).isoformat()


def fetch(url):
    requested=now()
    with urllib.request.urlopen(url,timeout=25) as response:
        payload=json.load(response)
    return {'requested_at_utc':requested,'received_at_utc':now(),'url':url,'payload':payload}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('schedule_snapshot',type=pathlib.Path)
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--team-codes',help='Comma-separated official team codes; default: all future teams')
    args=p.parse_args()
    official=json.loads(args.schedule_snapshot.read_text())
    future=[g for g in official['games'] if g['status']!='Final']
    codes={g[side+'_team'] for g in future for side in ('home','away')}
    if args.team_codes:
        codes=codes.intersection(args.team_codes.split(','))
        if not codes:raise SystemExit('None of the selected teams has a future game.')
    teams=fetch('https://statsapi.mlb.com/api/v1/teams?sportId=1&season=2026')
    team_by_code={t['abbreviation']:t for t in teams['payload']['teams']}
    missing=codes-team_by_code.keys()
    if missing:raise SystemExit('Official team abbreviations missing: '+str(sorted(missing)))
    requests={code:'https://statsapi.mlb.com/api/v1/teams/'+str(team_by_code[code]['id'])+
              '/roster?'+urllib.parse.urlencode({'rosterType':'40Man','season':2026})
              for code in sorted(codes)}
    result={'captured_at_utc':now(),'schedule_snapshot_file':args.schedule_snapshot.name,
            'schedule_observed_at_utc':official['captured_at_utc'],
            'team_metadata':teams,'rosters':{},'errors':{}}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,min(args.workers,5))) as pool:
        jobs={pool.submit(fetch,url):code for code,url in requests.items()}
        for job in concurrent.futures.as_completed(jobs):
            code=jobs[job]
            try:result['rosters'][code]=job.result()
            except Exception as ex:result['errors'][code]=type(ex).__name__
    out=BASE/'raw'/('mlb_rosters_40man_2026_asof_'+now().replace(':','').replace('-','').replace('+00:00','Z')+'.json')
    out.write_text(json.dumps(result,separators=(',',':'))+'\n')
    print(json.dumps({'file':str(out),'teams':len(result['rosters']),
                      'errors':result['errors'],'rows':sum(len(x['payload'].get('roster',[])) for x in result['rosters'].values())}))


if __name__=='__main__':main()
