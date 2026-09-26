#!/usr/bin/env python3
"""Preselected deep-history MLB sample for an account with sufficient access.

Accepts an interactive, non-echoing key or PARLAY_API_KEY. Never prints or stores it.
The free plan's historical window is 48 hours, so the 2024-2025 sample is
guarded against accidental 403 requests. Deep-history access is tier-gated.
"""
import datetime as dt
import argparse
import getpass
import hashlib
import json
import os
import pathlib
import sqlite3
import urllib.error
import urllib.parse
import urllib.request

BASE=pathlib.Path(__file__).resolve().parent
OUT=BASE/'raw'/'parlay_pilot'


def select_games(conn):
    chosen=[]
    for year in (2024,2025):
        for month in range(4,10):
            candidates=conn.execute('''SELECT m.game_id,m.archived_start_utc
                FROM archive_matches m JOIN games g USING(game_id)
                WHERE g.season=? AND substr(g.game_date,6,2)=?
                AND m.archived_start_utc IS NOT NULL''',(year,f'{month:02d}')).fetchall()
            if not candidates:continue
            chosen.append(min(candidates,key=lambda item:hashlib.sha256(item[0].encode()).hexdigest()))
    return chosen


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--key-stdin',action='store_true',help='Prompt for an API key without terminal echo')
    p.add_argument('--limit',type=int,default=12,help='Maximum preselected games to consider')
    p.add_argument('--allow-deep-history',action='store_true',help='Confirm account has access to 2024-25 historical dates')
    args=p.parse_args()
    if not args.allow_deep_history:
        raise SystemExit('This 2024-25 pilot needs deep-history access; the free tier only covers 48 hours.')
    key=getpass.getpass('ParlayAPI key: ') if args.key_stdin else os.environ.get('PARLAY_API_KEY')
    if not key:raise SystemExit('Supply --key-stdin or PARLAY_API_KEY.')
    conn=sqlite3.connect(BASE/'output/mlb_time_machine.sqlite')
    games=select_games(conn)
    conn.close()
    OUT.mkdir(parents=True,exist_ok=True)
    manifest_path=OUT/'manifest.json'
    manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    done={row['game_id'] for row in manifest if row.get('saved_file') and (OUT/row['saved_file']).exists()}
    for gid,start in games[:args.limit]:
        if gid in done:
            continue
        decision=dt.datetime.fromisoformat(start)-dt.timedelta(hours=3)
        params=urllib.parse.urlencode({'date':decision.isoformat().replace('+00:00','Z'),
                                       'regions':'us','markets':'h2h','oddsFormat':'american'})
        url='https://parlay-api.com/v1/historical/sports/baseball_mlb/odds?'+params
        request=urllib.request.Request(url,headers={'X-API-Key':key,'Accept':'application/json'})
        row={'game_id':gid,'requested_decision_utc':decision.isoformat()}
        try:
            with urllib.request.urlopen(request,timeout=30) as resp:
                payload=json.load(resp)
            if isinstance(payload,dict):
                row['returned_snapshot_utc']=payload.get('timestamp')
                row['event_count']=len(payload.get('data') or [])
                filename=gid+'_'+decision.date().isoformat()+'.json'
                (OUT/filename).write_text(json.dumps(payload,separators=(',',':'))+'\n')
                row['saved_file']=filename
            else:row['error']='unexpected response shape'
        except urllib.error.HTTPError as ex:
            row['error']=f'HTTP {ex.code}'
            try:
                problem=json.loads(ex.read(2048))
                detail=problem.get('detail') or problem.get('message') or problem.get('error')
                if isinstance(detail,str):row['error_detail']=detail.replace(key,'[REDACTED]')[:250]
            except (ValueError,AttributeError):pass
        manifest=[old for old in manifest if old.get('game_id')!=gid]+[row]
        manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
        print(json.dumps(row))


if __name__=='__main__':main()
