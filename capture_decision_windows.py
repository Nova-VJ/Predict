#!/usr/bin/env python3
"""One unattended pass of scheduled MLB T-minus-three-hour board captures.

Keep this process running in a persistent machine. The secret stays in process
memory, never in the URL, files, task list or command line.
"""
import argparse
import datetime as dt
import getpass
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import time
import urllib.request

from import_parlay_live import import_board
from import_snapshot import parse_utc

BASE=pathlib.Path(__file__).resolve().parent
OUT=BASE/'raw/parlay_live'
REGIONS='us,eu'
URL='https://parlay-api.com/v1/sports/baseball_mlb/odds?regions=us,eu&markets=h2h'


def utc_now():return dt.datetime.now(dt.timezone.utc)


def target_groups(schedule):
    targets=sorted((parse_utc(g['scheduled_start_utc'])-dt.timedelta(hours=3),g['game_pk'])
                   for g in schedule['games'] if g['status']!='Final')
    groups=[]
    for target,pk in targets:
        if target<utc_now()-dt.timedelta(minutes=2):continue
        if groups and target-groups[-1][0]<=dt.timedelta(minutes=4):
            groups[-1][1].append(pk)
        else:groups.append((target,[pk]))
    return groups


def capture(key,schedule_path,schedule,game_pks):
    before=utc_now().isoformat()
    request=urllib.request.Request(URL,headers={'X-API-Key':key,'Accept':'application/json'})
    with urllib.request.urlopen(request,timeout=40) as resp:
        body=resp.read()
    after=utc_now().isoformat()
    board=json.loads(body)
    if not isinstance(board,list):raise ValueError('Unexpected live board shape')
    OUT.mkdir(parents=True,exist_ok=True)
    stamp=before.replace(':','').replace('-','').replace('+00:00','Z')
    name='decision_'+stamp+'.json'
    (OUT/name).write_bytes(body)
    meta={'task':'Tminus3h','requested_game_pks':game_pks,
          'request_utc':before,'received_utc':after,'file':name,
          'schedule_snapshot_file':schedule_path.name,'regions_requested':REGIONS}
    (OUT/(name[:-5]+'.meta.json')).write_text(json.dumps(meta,indent=2)+'\n')
    with sqlite3.connect(BASE/'output/mlb_time_machine.sqlite') as conn:
        report=import_board(conn,board,meta,schedule_path)
        conn.execute('''CREATE VIEW IF NOT EXISTS decision_window_quotes AS
          WITH captures AS (
            SELECT DISTINCT official_game_pk,capture_file,scheduled_start_utc,received_utc
            FROM observed_live_quotes
            WHERE (julianday(scheduled_start_utc)-julianday(received_utc))*1440
              BETWEEN 165 AND 195
          ), ranked AS (
            SELECT *,ROW_NUMBER() OVER (
              PARTITION BY official_game_pk
              ORDER BY ABS((julianday(scheduled_start_utc)-julianday(received_utc))*1440-180),
                       received_utc) AS capture_rank
            FROM captures
          )
          SELECT q.* FROM observed_live_quotes q JOIN ranked r
            ON q.official_game_pk=r.official_game_pk AND q.capture_file=r.capture_file
          WHERE r.capture_rank=1''')
    return {'meta':meta,'import':report}


def wait_until(moment):
    while True:
        remaining=(moment-utc_now()).total_seconds()
        if remaining<=0:return
        time.sleep(min(remaining,45))


def preflight(schedule,game_pks):
    """Observe the latest schedule, probable pitchers and due-team rosters."""
    end=max(g['official_date'] for g in schedule['games'])
    by_pk={g['game_pk']:g for g in schedule['games']}
    teams=sorted({by_pk[pk][side+'_team'] for pk in game_pks for side in ('home','away')})
    def run(script,*args):
        proc=subprocess.run([sys.executable,str(BASE/script),*map(str,args)],
                            check=True,capture_output=True,text=True,timeout=150)
        return json.loads(proc.stdout)
    refreshed=run('collect_mlb_public.py','--season',2026,'--end-date',end)
    schedule_path=pathlib.Path(refreshed['path'])
    roster=run('collect_mlb_rosters.py',schedule_path,'--team-codes',','.join(teams))
    imported=run('import_mlb_rosters.py',roster['file'],schedule_path)
    return schedule_path,{'schedule':refreshed,'rosters':roster,'import':imported}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('schedule_snapshot',type=pathlib.Path)
    p.add_argument('--key-stdin',action='store_true')
    p.add_argument('--max-calls',type=int,default=20)
    p.add_argument('--dry-run',action='store_true')
    args=p.parse_args()
    schedule=json.loads(args.schedule_snapshot.read_text())
    groups=target_groups(schedule)[:args.max_calls]
    print(json.dumps({'planned_calls':len(groups),'targets_utc':[
        {'at':t.isoformat(),'game_pks':pks} for t,pks in groups]}),flush=True)
    if args.dry_run:return
    key=getpass.getpass('ParlayAPI key: ') if args.key_stdin else os.environ.get('PARLAY_API_KEY')
    if not key:raise SystemExit('Supply --key-stdin or PARLAY_API_KEY.')
    log=BASE/'output/decision_capture_log.jsonl'
    for target,pks in groups:
        wait_until(target-dt.timedelta(minutes=2))
        current_path=args.schedule_snapshot
        try:current_path,source_report=preflight(schedule,pks)
        except Exception as ex:source_report={'error':type(ex).__name__}
        wait_until(target)
        try:result=capture(key,current_path,schedule,pks)
        except Exception as ex:result={'error':type(ex).__name__,'target_utc':target.isoformat(),'game_pks':pks}
        result['preflight']=source_report
        with log.open('a') as f:f.write(json.dumps(result)+'\n')
        print(json.dumps(result),flush=True)


if __name__=='__main__':main()
