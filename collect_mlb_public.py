#!/usr/bin/env python3
"""Capture official MLB schedule and probable starters with an observation time.

A probable pitcher observed after a past game is not a valid pregame feature.
"""
import argparse
import datetime as dt
import json
import pathlib
import urllib.parse
import urllib.request

BASE=pathlib.Path(__file__).resolve().parent
RAW=BASE/'raw'


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--season',type=int,default=dt.datetime.now(dt.timezone.utc).year)
    p.add_argument('--end-date',type=dt.date.fromisoformat,
                   default=dt.datetime.now(dt.timezone.utc).date())
    args=p.parse_args()
    params=urllib.parse.urlencode({'sportId':1,'startDate':f'{args.season}-01-01',
                                   'endDate':args.end_date.isoformat(),
                                   'hydrate':'probablePitcher,team'})
    url='https://statsapi.mlb.com/api/v1/schedule?'+params
    req=urllib.request.Request(url,headers={'User-Agent':'MLB-Time-Machine-research/1.0'})
    with urllib.request.urlopen(req,timeout=45) as resp:
        payload=json.load(resp)
    captured=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    games=[]
    for group in payload.get('dates',[]):
        for game in group.get('games',[]):
            if game.get('gameType')!='R':continue
            item={'game_pk':game['gamePk'],'official_date':game['officialDate'],
                  'scheduled_start_utc':game['gameDate'],
                  'status':game['status']['abstractGameState'],
                  'game_number':game.get('gameNumber',1),
                  'venue_id':game.get('venue',{}).get('id')}
            for side in ('home','away'):
                team=game['teams'][side]
                item[side+'_team']=team['team'].get('abbreviation')
                item[side+'_score']=team.get('score')
                probable=team.get('probablePitcher') or {}
                item[side+'_probable_pitcher_id_at_capture']=probable.get('id')
                item[side+'_probable_pitcher_name_at_capture']=probable.get('fullName')
            games.append(item)
    # MLB's schedule response may list one game twice (an empty placeholder
    # and its scored record). Retain the scored record for each stable gamePk.
    by_id={}
    for game in games:
        prior=by_id.get(game['game_pk'])
        if prior is None or (game['home_score'] is not None and prior['home_score'] is None):
            by_id[game['game_pk']]=game
    games=sorted(by_id.values(),key=lambda g:(g['official_date'],g['game_pk']))
    RAW.mkdir(exist_ok=True)
    name='mlb_schedule_'+str(args.season)+'_asof_'+captured[:10].replace('-','')+'T'+captured[11:19].replace(':','')+'Z.json'
    path=RAW/name
    path.write_text(json.dumps({'captured_at_utc':captured,'source_url':url,
                                'games':games},ensure_ascii=False,separators=(',',':'))+'\n')
    print(json.dumps({'path':str(path),'captured_at_utc':captured,
                      'regular_season_games':len(games),
                      'final_games':sum(g['status']=='Final' for g in games),
                      'future_games':sum(g['status']!='Final' for g in games)}))


if __name__=='__main__':main()
