#!/usr/bin/env python3
"""Precommitted season-forward probability baselines, with no odds as features.

2015-22 train; 2023 choose hyperparameters; 2024 validation; 2025 final check.
Fixed search space and metrics are declared before looking at 2024/25 labels.
"""
import collections
import datetime as dt
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

BASE=pathlib.Path(__file__).resolve().parent
DB=BASE/'output/mlb_time_machine.sqlite'
CS=(0.01,0.1,1.0,10.0)
ELO_K=(10,20,40)
ELO_HOME=(25,50,75)
RNG_SEED=260926


def cap(p): return max(1e-6,min(1-1e-6,float(p)))
def ll(p,y):
    p=cap(p)
    return -(y*math.log(p)+(1-y)*math.log(1-p))


def elo_preds(games,k,home_points):
    rating=collections.defaultdict(lambda:1500.0)
    pred={}
    pending=[]
    last_day=None
    last_year=None
    def update():
        for g,p in pending:
            delta=k*(g['y']-p)
            rating[g['home']]+=delta
            rating[g['away']]-=delta
    for g in games:
        if g['date']!=last_day:
            update()
            pending=[]
            if g['year']!=last_year:
                # predeclared 65% carryover from previous season
                for team in rating: rating[team]=1500+0.65*(rating[team]-1500)
                last_year=g['year']
            last_day=g['date']
        p=1/(1+10**((rating[g['away']]-rating[g['home']]-home_points)/400))
        pred[g['id']]=p
        pending.append((g,p))
    return pred


def metrics(rows):
    n=len(rows)
    bins=[]
    for lo in (0.0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9):
        v=[x for x in rows if lo<=x[0]<(lo+0.1 if lo<0.9 else 1.001)]
        if v: bins.append({'p_range':f'{lo:.1f}-{lo+0.1:.1f}',
                            'n':len(v),'predicted':round(sum(p for p,y in v)/len(v),4),
                            'actual':round(sum(y for p,y in v)/len(v),4)})
    return {'n':n,'brier':round(sum((p-y)**2 for p,y in rows)/n,6),
            'log_loss':round(sum(ll(p,y) for p,y in rows)/n,6),
            'calibration':bins}


def blocked_ci(predictions, games, challenger, baseline, year):
    byday=collections.defaultdict(list)
    for g in games:
        if g['year']==year:
            byday[g['date']].append(ll(predictions[challenger][g['id']],g['y'])-
                                   ll(predictions[baseline][g['id']],g['y']))
    days=list(byday)
    rng=random.Random(RNG_SEED+year)
    diffs=[]
    for _ in range(1000):
        draws=(byday[days[rng.randrange(len(days))]] for _ in days)
        vals=[x for dayvals in draws for x in dayvals]
        diffs.append(sum(vals)/len(vals))
    diffs.sort()
    return [round(diffs[25],6),round(diffs[975],6)]


def main():
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    numeric=[x[1] for x in c.execute('PRAGMA table_info(pregame_features)')
             if x[1] not in ('game_id','cutoff_date_exclusive')]
    raw=c.execute('''SELECT g.game_id, g.game_date, g.season, g.home_team,
       g.away_team,g.home_win,'''+','.join('f.'+x for x in numeric)+'''
       FROM games g JOIN pregame_features f USING(game_id)
       ORDER BY g.game_date,g.doubleheader_number,g.game_id''').fetchall()
    games=[{'id':x['game_id'],'date':x['game_date'],'year':x['season'],
            'home':x['home_team'],'away':x['away_team'],'y':x['home_win']} for x in raw]
    all_games=[dict(id=x['game_id'],date=x['game_date'],year=x['season'],
                    home=x['home_team'],away=x['away_team'],y=x['home_win'])
               for x in c.execute('SELECT game_id,game_date,season,home_team,away_team,home_win FROM games ORDER BY game_date,doubleheader_number,game_id')]
    X=np.asarray([[np.nan if x[z] is None else x[z] for z in numeric] for x in raw],dtype=float)
    y=np.asarray([g['y'] for g in games],dtype=int)
    index={g['id']:i for i,g in enumerate(games)}
    # Fix search on 2023 only. Ties resolved in listed hyperparameter order.
    elo_candidates={(k,h):elo_preds(all_games,k,h) for k in ELO_K for h in ELO_HOME}
    y23=[g for g in games if g['year']==2023]
    elo_choice=min(elo_candidates,key=lambda params:sum(ll(elo_candidates[params][g['id']],g['y']) for g in y23)/len(y23))
    logistic_losses={}
    train=np.array([g['year']<=2022 for g in games])
    valid=np.array([g['year']==2023 for g in games])
    for regularization in CS:
        m=make_pipeline(SimpleImputer(strategy='median',add_indicator=True),
                        StandardScaler(),LogisticRegression(C=regularization,max_iter=500,random_state=RNG_SEED))
        m.fit(X[train],y[train]); probs=m.predict_proba(X[valid])[:,1]
        logistic_losses[regularization]=sum(ll(p,z) for p,z in zip(probs,y[valid]))/len(probs)
    c_choice=min(CS,key=lambda v:logistic_losses[v])

    predictions={'home_only':{},'elo':{},'logistic':{}}
    for season in (2023,2024,2025):
        train=np.array([g['year']<season for g in games])
        target=np.array([g['year']==season for g in games])
        home_rate=float(y[train].mean())
        m=make_pipeline(SimpleImputer(strategy='median',add_indicator=True),
                        StandardScaler(),LogisticRegression(C=c_choice,max_iter=500,random_state=RNG_SEED))
        m.fit(X[train],y[train]); probabilities=m.predict_proba(X[target])[:,1]
        target_games=[g for g in games if g['year']==season]
        for g,p in zip(target_games,probabilities):
            predictions['home_only'][g['id']]=home_rate
            predictions['elo'][g['id']]=elo_candidates[elo_choice][g['id']]
            predictions['logistic'][g['id']]=float(p)

    c.execute('DROP TABLE IF EXISTS model_predictions')
    c.execute('''CREATE TABLE model_predictions (
       game_id TEXT,phase TEXT,model TEXT,p_home REAL,home_win INTEGER,
       training_through_season INTEGER,PRIMARY KEY(game_id,model))''')
    rows=[]
    report={'protocol':{'train_seasons':'2015-2022 initially; each later season refits on all preceding seasons',
                        'tuning':2023,'validation':2024,'final':2025,
                        'model_inputs':'sports features only; no odds, actual starter or public signals',
                        'fixed_C_grid':CS,'fixed_elo_K':ELO_K,'fixed_elo_home_points':ELO_HOME,
                        'elo_previous_season_carryover':0.65,
                        'random_seed':RNG_SEED},
            'chosen_on_2023':{'logistic_C':c_choice,'elo_K':elo_choice[0],
                              'elo_home_points':elo_choice[1],
                              'logistic_tuning_logloss':{str(k):round(v,6) for k,v in logistic_losses.items()}},
            'scores':{}}
    for year in (2023,2024,2025):
        phase={2023:'tuning',2024:'validation',2025:'final'}[year]
        match=[g for g in games if g['year']==year]
        report['scores'][str(year)]={}
        for model in predictions:
            v=[(predictions[model][g['id']],g['y']) for g in match]
            report['scores'][str(year)][model]=metrics(v)
            rows.extend((g['id'],phase,model,predictions[model][g['id']],g['y'],year-1) for g in match)
        if year>2023:
            report['scores'][str(year)]['paired_logloss_diff_95pct_day_bootstrap']={
                model+'_minus_home_only':blocked_ci(predictions,games,model,'home_only',year)
                for model in ('elo','logistic')}
    c.executemany('INSERT INTO model_predictions VALUES (?,?,?,?,?,?)',rows)
    c.commit()
    c.close()
    (BASE/'output/model_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'chosen':report['chosen_on_2023'],
                      'scores':{yr:{k:{m:v for m,v in model.items() if m in ('n','brier','log_loss')}
                                  for k,model in val.items() if k in predictions}
                                for yr,val in report['scores'].items()}},indent=2))


if __name__=='__main__':main()
