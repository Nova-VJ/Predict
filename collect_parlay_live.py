#!/usr/bin/env python3
"""Capture an authenticated MLB board with UTC request/receipt times.

The key is prompted without terminal echo or read from PARLAY_API_KEY. It is
never placed in a URL or saved. A capture is evidence of a board response,
not evidence that a particular customer could execute a wager.
"""
import argparse
import datetime as dt
import getpass
import json
import os
import pathlib
import urllib.parse
import urllib.error
import urllib.request

BASE=pathlib.Path(__file__).resolve().parent
OUT=BASE/'raw'/'parlay_live'


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--key-stdin',action='store_true')
    p.add_argument('--closing-date',help='Optional YYYY-MM-DD daily closing CSV')
    p.add_argument('--regions',default='us',help='Comma-separated odds regions (default: us)')
    args=p.parse_args()
    key=getpass.getpass('ParlayAPI key: ') if args.key_stdin else os.environ.get('PARLAY_API_KEY')
    if not key:raise SystemExit('Supply --key-stdin or PARLAY_API_KEY.')
    if not all(x in {'us','eu','uk','au'} for x in args.regions.split(',')):
        raise SystemExit('Unsupported region name.')
    tasks=[('live_'+args.regions.replace(',','_'),'https://parlay-api.com/v1/sports/baseball_mlb/odds?'+
            urllib.parse.urlencode({'regions':args.regions,'markets':'h2h'}),'json')]
    if args.closing_date:
        dt.date.fromisoformat(args.closing_date)
        tasks.append(('closing_'+args.closing_date,
                      'https://parlay-api.com/v1/historical/closing-lines.csv?date='+args.closing_date+'&sport_key=baseball_mlb','csv'))
    OUT.mkdir(parents=True,exist_ok=True)
    for name,url,extension in tasks:
        before=utc_now()
        request=urllib.request.Request(url,headers={'X-API-Key':key,'Accept':'application/json, text/csv'})
        try:
            with urllib.request.urlopen(request,timeout=35) as response:
                body=response.read()
                receipt=utc_now()
                headers={h:response.headers.get(h) for h in ('X-Credits-Cost','X-Credits-Remaining','X-Historical-Window-Hours','Content-Type')}
        except urllib.error.HTTPError as ex:
            print(json.dumps({'task':name,'status':ex.code,'credits_remaining':ex.headers.get('X-Credits-Remaining')}))
            continue
        except Exception as ex:
            print(json.dumps({'task':name,'error':type(ex).__name__}))
            continue
        stamp=before.replace(':','').replace('+00:00','Z').replace('-','')
        file=OUT/(name+'_'+stamp+'.'+extension)
        file.write_bytes(body)
        meta={'task':name,'request_utc':before,'received_utc':receipt,
              'file':file.name,'bytes':len(body),'response_headers':headers,
              'regions_requested':args.regions if name.startswith('live_') else None}
        (OUT/(file.stem+'.meta.json')).write_text(json.dumps(meta,indent=2)+'\n')
        print(json.dumps(meta))


if __name__=='__main__':main()
