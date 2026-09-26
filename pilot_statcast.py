#!/usr/bin/env python3
"""One-game, cached feasibility check of Baseball Savant pitch-level CSV."""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import pathlib
import urllib.parse
import urllib.request

BASE=pathlib.Path(__file__).resolve().parent


def get(url):
    before=dt.datetime.now(dt.timezone.utc).isoformat()
    request=urllib.request.Request(url,headers={'User-Agent':'MLB-Time-Machine-research/1.0'})
    with urllib.request.urlopen(request,timeout=45) as response:body=response.read()
    return body,before,dt.datetime.now(dt.timezone.utc).isoformat()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--date',default='2024-06-01')
    args=p.parse_args()
    dt.date.fromisoformat(args.date)
    url='https://statsapi.mlb.com/api/v1/schedule?'+urllib.parse.urlencode(
        {'sportId':1,'date':args.date})
    body,requested,received=get(url)
    games=[g for day in json.loads(body).get('dates',[]) for g in day.get('games',[])
           if g.get('gameType')=='R' and g.get('officialDate')==args.date]
    if not games:raise SystemExit('No regular-season games found for that date.')
    game=min(games,key=lambda x:x['gamePk'])
    pk=game['gamePk']
    csv_url=f'https://baseballsavant.mlb.com/statcast_search/csv?all=true&type=details&game_pk={pk}'
    output=BASE/'raw'/f'statcast_pilot_game_{pk}.csv'
    if output.exists():
        data=output.read_bytes();statcast_requested=None;statcast_received=None;cached=True
    else:
        data,statcast_requested,statcast_received=get(csv_url);cached=False
    rows=list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
    required={'game_pk','game_date','pitcher','batter','release_speed',
              'release_spin_rate','launch_speed','launch_angle','estimated_woba_using_speedangle'}
    if not rows or not required.issubset(rows[0]) or {r['game_pk'] for r in rows}!={str(pk)}:
        raise SystemExit('Statcast pilot did not validate; CSV was not saved.')
    if not cached:output.write_bytes(data)
    meta={'game_pk':pk,'official_date':args.date,'selected_by':'lowest regular-season MLB game_pk for date',
          'pitch_rows':len(rows),'unique_pitch_keys':len({(r['game_pk'],r['at_bat_number'],r['pitch_number']) for r in rows}),
          'csv_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
          'schedule_url':url,'schedule_requested_utc':requested,'schedule_received_utc':received,
          'statcast_url':csv_url,'statcast_requested_utc':statcast_requested,
          'statcast_received_utc':statcast_received,'cached':cached,
          'note':'Retrospective schema pilot only; it does not establish an available 2024 betting quote.'}
    path=BASE/'output'/f'statcast_pilot_{pk}.json'
    path.write_text(json.dumps(meta,indent=2)+'\n')
    print(json.dumps({'csv':str(output),'report':str(path),
                      'game_pk':pk,'pitch_rows':len(rows),'unique_pitch_keys':meta['unique_pitch_keys']}))


if __name__=='__main__':main()
