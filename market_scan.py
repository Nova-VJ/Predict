#!/usr/bin/env python3
"""Free local cross-book calculation on already captured board snapshots.

Pinnacle's two-sided no-vig price is a market reference, not a known truth.
Candidate edges are never described as executable bets or model ROI.
"""
import argparse
import collections
import datetime as dt
import json
import pathlib
import sqlite3

from import_snapshot import parse_utc

BASE=pathlib.Path(__file__).resolve().parent


def scan(conn,table,maximum_age_minutes):
    rows=conn.execute('SELECT official_game_pk,bookmaker,side,decimal_odds,market_last_update_utc,received_utc,capture_file,regions_requested FROM '+table).fetchall()
    groups=collections.defaultdict(dict)
    for pk,book,side,price,updated,received,file,regions in rows:
        age=(parse_utc(received)-parse_utc(updated)).total_seconds()/60
        if age<0 or age>maximum_age_minutes:continue
        groups[(pk,file)][(book,side)]=(price,regions)
    candidates=[]
    coverage=collections.Counter()
    for (pk,file),quotes in groups.items():
        sharp_h=quotes.get(('pinnacle','home'))
        sharp_a=quotes.get(('pinnacle','away'))
        if not sharp_h or not sharp_a:
            coverage['without_fresh_two_sided_pinnacle']+=1;continue
        coverage['with_fresh_two_sided_pinnacle']+=1
        fair_h=(1/sharp_h[0])/((1/sharp_h[0])+(1/sharp_a[0]))
        for (book,side),(price,regions) in quotes.items():
            if book=='pinnacle':continue
            if (book,'home') not in quotes or (book,'away') not in quotes:continue
            ev=(fair_h if side=='home' else 1-fair_h)*price-1
            if ev>0:
                candidates.append({'game_pk':pk,'bookmaker':book,'side':side,'decimal_odds':price,
                                   'market_reference_ev':ev,'regions_requested':regions,'capture_file':file})
    return {'snapshots_scanned':len(groups),'coverage':dict(coverage),
            'positive_market_reference_comparisons':len(candidates),
            'maximum_indicative_edge':max((c['market_reference_ev'] for c in candidates),default=None),
            'limitations':'Same-response market comparison only; no executable price, jurisdiction, limit, or superior predictive model established.'}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--early-diagnostic',action='store_true',help='Include observations far before T-3h for feed QA only')
    p.add_argument('--max-market-age-minutes',type=int,default=15)
    args=p.parse_args()
    table='observed_live_quotes' if args.early_diagnostic else 'decision_window_quotes'
    with sqlite3.connect(BASE/'output/mlb_time_machine.sqlite') as conn:
        report=scan(conn,table,args.max_market_age_minutes)
    report['scope']=table
    print(json.dumps(report,indent=2))
    if args.early_diagnostic:
        (BASE/'output/market_scan_early_diagnostic.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
