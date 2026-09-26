#!/usr/bin/env python3
"""Exploratory market-first MLB probability experiment.

Archived opening quotes have unknown observation time. The experiment tests
incremental predictive information, never claims executable ROI or verified
pregame price availability. Hyperparameters are selected on 2023 only.
"""
import collections
import json
import math
import pathlib
import random
import sqlite3

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from evaluate_models import elo_preds, ll

BASE=pathlib.Path(__file__).resolve().parent
CS=(0.01,0.1,1.0,10.0)
FEATURES=('prior_season_win_pct','win_pct_10','runs_for_10','runs_against_10','rest_days')


def logit(p):
    p=max(1e-5,min(1-1e-5,p))
    return math.log(p/(1-p))


def fit(X,y,C):
    model=make_pipeline(SimpleImputer(strategy='median',add_indicator=True),
                        StandardScaler(),LogisticRegression(C=C,max_iter=500,random_state=260926))
    model.fit(X,y)
    return model


def metrics(rows):
    n=len(rows)
    return {'games':n,'brier':sum((p-y)**2 for p,y in rows)/n,
            'log_loss':sum(ll(p,y) for p,y in rows)/n}


def paired_days(rows,year):
    days=collections.defaultdict(list)
    for date,p,y,reference in rows:
        days[date].append(ll(p,y)-ll(reference,y))
    keys=list(days)
    rng=random.Random(260926+year)
    draws=[]
    for _ in range(1000):
        values=[v for day in rng.choices(keys,k=len(keys)) for v in days[day]]
        draws.append(sum(values)/len(values))
    draws.sort()
    return [draws[25],draws[975]]


def main():
    c=sqlite3.connect(BASE/'output/mlb_time_machine.sqlite')
    games=[{'id':gid,'date':date,'year':year,'home':home,'away':away,'y':won}
           for gid,date,year,home,away,won in c.execute('''SELECT game_id,game_date,season,
              home_team,away_team,home_win FROM games
              ORDER BY game_date,doubleheader_number,game_id''')]
    chosen=json.loads((BASE/'output/model_report.json').read_text())['chosen_on_2023']
    elo=elo_preds(games,chosen['elo_K'],chosen['elo_home_points'])
    quoted=collections.defaultdict(lambda:collections.defaultdict(dict))
    for gid,book,side,price in c.execute('''SELECT game_id,bookmaker,side,decimal_odds
      FROM odds_quotes WHERE quote_kind='opening' AND availability='timestamp_unknown'
      AND decimal_odds>1'''):
        quoted[gid][book][side]=price
    market={}
    for gid,books in quoted.items():
        ps=[(1/b['home'])/((1/b['home'])+(1/b['away'])) for b in books.values()
            if 'home' in b and 'away' in b]
        if ps:market[gid]=sum(ps)/len(ps)
    feature_sql=','.join('f.'+side+'_'+name for name in FEATURES for side in ('home','away'))
    feature_rows={row[0]:row[1:] for row in c.execute(
        'SELECT g.game_id,'+feature_sql+' FROM games g JOIN pregame_features f USING(game_id)')}
    data=[]
    for g in games:
        gid=g['id']
        if g['year'] not in range(2021,2026) or gid not in market or gid not in feature_rows:
            continue
        m,e=market[gid],elo[gid]
        pair=feature_rows[gid]
        differences=[(pair[2*i]-pair[2*i+1]) if pair[2*i] is not None and
                     pair[2*i+1] is not None else np.nan for i in range(len(FEATURES))]
        data.append((g,m,e,[logit(m),logit(e)-logit(m)],differences))
    result={'status':'exploratory_archived_opening_timestamp_unknown',
            'source':'consensus of two-sided per-book no-vig opening probabilities',
            'training_seasons':[2021,2022],'tuning_season':2023,
            'later_seasons_already_inspected':[2024,2025],
            'feature_differences':FEATURES,'C_grid':CS,'chosen_C':{},'scores':{}}
    output=[]
    for variant in ('market_plus_elo','market_plus_elo_and_team_form'):
        def vector(d):return d[3] if variant=='market_plus_elo' else d[3]+d[4]
        train=[d for d in data if d[0]['year']<=2022]
        tune=[d for d in data if d[0]['year']==2023]
        losses={C:sum(ll(p,d[0]['y']) for p,d in zip(
                    fit(np.asarray([vector(x) for x in train],float),
                        np.asarray([x[0]['y'] for x in train]),C).predict_proba(
                        np.asarray([vector(x) for x in tune],float))[:,1],tune))/len(tune)
                for C in CS}
        choice=min(CS,key=lambda C:losses[C])
        result['chosen_C'][variant]={'C':choice,'tuning_log_loss':losses}
        for year in (2023,2024,2025):
            training=[d for d in data if d[0]['year']<year]
            target=[d for d in data if d[0]['year']==year]
            model=fit(np.asarray([vector(x) for x in training],float),
                      np.asarray([x[0]['y'] for x in training]),choice)
            probs=model.predict_proba(np.asarray([vector(x) for x in target],float))[:,1]
            score=result['scores'].setdefault(str(year),{})
            if 'archive_market' not in score:
                score['archive_market']=metrics([(d[1],d[0]['y']) for d in target])
                score['elo']=metrics([(d[2],d[0]['y']) for d in target])
            pairs=[(d[0]['date'],float(p),d[0]['y'],d[1]) for d,p in zip(target,probs)]
            score[variant]=metrics([(p,y) for date,p,y,m in pairs])
            score[variant]['paired_logloss_minus_market_95pct_day_bootstrap']=paired_days(pairs,year)
            output.extend((d[0]['id'],year,variant,float(p),d[1],d[0]['y'],year-1)
                          for d,p in zip(target,probs))
    c.execute('''CREATE TABLE IF NOT EXISTS market_hybrid_predictions (
      game_id TEXT NOT NULL,season INTEGER NOT NULL,variant TEXT NOT NULL,
      p_home REAL NOT NULL,archive_market_p_home REAL NOT NULL,home_win INTEGER NOT NULL,
      training_through_season INTEGER NOT NULL,PRIMARY KEY(game_id,variant))''')
    c.executemany('INSERT OR REPLACE INTO market_hybrid_predictions VALUES (?,?,?,?,?,?,?)',output)
    c.commit();c.close()
    result['warning']='Opening quote observation times unknown. No ROI/CLV or verified T-3h feature claim.'
    (BASE/'output/market_anchor_experiment.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'chosen_C':result['chosen_C'],
                      'scores':{y:{m:{k:round(v,6) if isinstance(v,float) else v
                                      for k,v in a.items() if k in ('games','brier','log_loss')}
                                    for m,a in row.items()}
                                for y,row in result['scores'].items()}},indent=2))


if __name__=='__main__':main()
