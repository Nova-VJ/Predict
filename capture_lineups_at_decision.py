#!/usr/bin/env python3
"""Free companion to the odds scheduler; refresh announced lineups near T-3h."""
import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys

from capture_decision_windows import target_groups,wait_until,utc_now

BASE=pathlib.Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser()
    p.add_argument('schedule_snapshot',type=pathlib.Path)
    p.add_argument('--max-calls',type=int,default=12)
    args=p.parse_args()
    schedule=json.loads(args.schedule_snapshot.read_text())
    groups=target_groups(schedule)[:args.max_calls]
    launch_date=utc_now().date()
    by_pk={g['game_pk']:g for g in schedule['games']}
    print(json.dumps({'lineup_targets':len(groups)}),flush=True)
    for target,pks in groups:
        tomorrow=any(dt.date.fromisoformat(by_pk[pk]['official_date'])>launch_date
                     for pk in pks)
        wait_until(target-dt.timedelta(minutes=8) if tomorrow else
                   target-dt.timedelta(seconds=75))
        try:
            if tomorrow:
                end=max(g['official_date'] for g in schedule['games'])
                refreshed=json.loads(subprocess.check_output([
                    sys.executable,str(BASE/'collect_mlb_public.py'),
                    '--season',str(target.year),'--end-date',end],text=True,timeout=90))
                path=pathlib.Path(refreshed['path'])
            else:
                candidates=sorted((x for x in (BASE/'raw').glob('mlb_schedule_*.json')
                                   if all(pk in {g['game_pk'] for g in json.loads(x.read_text())['games']}
                                          for pk in pks)),key=lambda x:x.stat().st_mtime)
                path=candidates[-1] if candidates else args.schedule_snapshot
            cmd=[sys.executable,str(BASE/'collect_mlb_game_context.py'),str(path),
                 '--game-pks',','.join(map(str,pks))]
            cmd += ['--reuse-final-boxes'] if tomorrow else ['--lineups-only']
            report=json.loads(subprocess.check_output(cmd,text=True,timeout=180))
            imported=json.loads(subprocess.check_output([
                sys.executable,str(BASE/'import_mlb_game_context.py'),report['file']],
                text=True,timeout=30))
            result={'target_utc':target.isoformat(),'game_pks':pks,
                    'capture':report,'import':imported}
        except Exception as ex:
            result={'target_utc':target.isoformat(),'game_pks':pks,
                    'error':type(ex).__name__+': '+str(ex)}
        with (BASE/'output/lineup_capture_log.jsonl').open('a') as f:
            f.write(json.dumps(result)+'\n')
        print(json.dumps(result),flush=True)


if __name__=='__main__':main()
