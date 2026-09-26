#!/usr/bin/env python3
"""Retrospective odds sanity check. Archive opening times are UNVERIFIED.

No ROI, CLV or executable betting decisions are calculated here.
"""
import collections
import json
import math
import pathlib
import sqlite3

BASE=pathlib.Path(__file__).resolve().parent
c=sqlite3.connect(BASE/'output/mlb_time_machine.sqlite')
quoted=collections.defaultdict(lambda:collections.defaultdict(dict))
for gid,book,side,decimal in c.execute('''SELECT game_id,bookmaker,side,decimal_odds
 FROM odds_quotes WHERE quote_kind='opening' AND availability='timestamp_unknown'
 AND decimal_odds>1'''):
    quoted[gid][book][side]=decimal
consensus={}
for gid,books in quoted.items():
    probs=[]
    for offer in books.values():
        if 'home' in offer and 'away' in offer:
            h,a=1/offer['home'],1/offer['away']
            probs.append(h/(h+a))
    if probs: consensus[gid]=sum(probs)/len(probs)

report={'warning':'Archive opening odds are not time verified; this is descriptive only.',
        'opening_market_reference':{}}
for year in (2023,2024,2025):
    rows=c.execute('''SELECT g.game_id,g.home_win,p.model,p.p_home
       FROM games g JOIN model_predictions p USING(game_id) WHERE g.season=?''',(year,)).fetchall()
    bygame=collections.defaultdict(dict)
    for gid,y,model,p in rows:
        if gid in consensus:
            bygame[gid][model]=p
            bygame[gid]['archive_opening_consensus']=consensus[gid]
            bygame[gid]['y']=y
    report['opening_market_reference'][str(year)]={'games':len(bygame)}
    for model in ('home_only','elo','logistic','archive_opening_consensus'):
        vals=[(item[model],item['y']) for item in bygame.values() if model in item]
        report['opening_market_reference'][str(year)][model]={
            'brier':round(sum((p-y)**2 for p,y in vals)/len(vals),6),
            'log_loss':round(sum(-y*math.log(max(1e-6,p))-(1-y)*math.log(max(1e-6,1-p))
                                  for p,y in vals)/len(vals),6)}
c.close()
(BASE/'output/market_diagnostic.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
