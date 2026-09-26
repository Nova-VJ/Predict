#!/usr/bin/env python3
"""Descriptive, non-executable odds/model edge diagnostic.

One fixed archived bookmaker avoids choosing a winning book after the fact.
Its opening quote has no observation timestamp, so returns here are not a
betting backtest or evidence of an executable ROI.
"""
import collections
import json
import pathlib
import random
import sqlite3

BASE=pathlib.Path(__file__).resolve().parent
QUERY='''SELECT g.season,g.game_date,p.p_home,p.home_win,h.decimal_odds,a.decimal_odds
 FROM model_predictions p JOIN games g USING(game_id)
 JOIN odds_quotes h ON h.game_id=p.game_id AND h.bookmaker='fanduel'
   AND h.quote_kind='opening' AND h.side='home' AND h.availability='timestamp_unknown'
 JOIN odds_quotes a ON a.game_id=p.game_id AND a.bookmaker='fanduel'
   AND a.quote_kind='opening' AND a.side='away' AND a.availability='timestamp_unknown'
 WHERE p.model='elo' AND g.season IN (2024,2025)'''


def interval_by_day(records,seed=20260926):
    by_day=collections.defaultdict(list)
    for date,profit,edge in records:by_day[date].append(profit)
    days=list(by_day)
    if not days:return None
    rng=random.Random(seed)
    samples=[]
    for _ in range(1500):
        picked=[profit for day in rng.choices(days,k=len(days)) for profit in by_day[day]]
        samples.append(sum(picked)/len(picked))
    samples.sort()
    return [samples[int(.025*len(samples))],samples[int(.975*len(samples))]]


def summarize(records):
    if not records:return None
    return {'selections':len(records),'gross_return_per_unit':sum(x[1] for x in records)/len(records),
            'model_mean_expected_return_per_unit':sum(x[2] for x in records)/len(records),
            'day_resampled_95pct_interval':interval_by_day(records)}


def main():
    with sqlite3.connect(BASE/'output/mlb_time_machine.sqlite') as conn:
        rows=conn.execute(QUERY).fetchall()
    selected={2024:[],2025:[]}
    for year,date,p,won,home,away in rows:
        home_ev=p*home-1
        away_ev=(1-p)*away-1
        if max(home_ev,away_ev)<=0:continue
        if home_ev>=away_ev:profit=(home-1) if won else -1;edge=home_ev
        else:profit=(away-1) if not won else -1;edge=away_ev
        selected[year].append((date,profit,edge))
    report={'status':'descriptive_only_non_executable','model':'elo','bookmaker':'fanduel',
            'quote_kind':'archived_opening_without_observation_time',
            'rule':'one side per game: take greater estimated EV only if greater than zero; flat one-unit stake',
            'available_games_by_season':dict(collections.Counter(row[0] for row in rows)),
            'by_season':{year:summarize(records) for year,records in selected.items()},
            'combined':summarize(selected[2024]+selected[2025]),
            'limitations':['Opening timestamps and executable availability unknown',
                           'FanDuel may not be available in the relevant jurisdiction',
                           '2025 archive only through August and already examined',
                           'No stake acceptance, fees, line movement or CLV verified',
                           'Day bootstrap describes sampling variation, not data-quality bias']}
    out=BASE/'output/edge_diagnostic.json'
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
