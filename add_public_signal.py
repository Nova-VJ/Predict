#!/usr/bin/env python3
"""Import manually verified PUBLIC news after as-of checks; CSV input in UTC."""
import argparse
import csv
import datetime as dt
import pathlib
import sqlite3
from urllib.parse import urlparse

BASE=pathlib.Path(__file__).resolve().parent
COLS=("game_id","team","player_id","signal_type","source_url",
      "published_at_utc","collected_at_utc","decision_at_utc","status",
      "impact_note","impact_rating")


def utc(text):
    value=dt.datetime.fromisoformat(text.replace("Z","+00:00"))
    if value.tzinfo is None or value.utcoffset()!=dt.timedelta(0):
        raise ValueError("UTC offset +00:00 required")
    return value


def main():
    p=argparse.ArgumentParser()
    p.add_argument("csv_path",type=pathlib.Path)
    p.add_argument("--database",type=pathlib.Path,default=BASE/"output/mlb_time_machine.sqlite")
    args=p.parse_args()
    conn=sqlite3.connect(args.database)
    with args.csv_path.open(newline="",encoding="utf-8-sig") as f:
        rows=list(csv.DictReader(f))
    for i,row in enumerate(rows,2):
        try:
            if not set(COLS).issubset(row): raise ValueError("missing column")
            pub,col,dec=(utc(row[name]) for name in
                         ("published_at_utc","collected_at_utc","decision_at_utc"))
            if not (pub<=col<=dec): raise ValueError("future or unknown publication/collection")
            if urlparse(row["source_url"]).scheme not in ("http","https"):
                raise ValueError("public source URL required")
            if row["status"] not in ("confirmed","credible_report","unconfirmed"):
                raise ValueError("invalid status")
            game=conn.execute("SELECT game_date,home_team,away_team FROM games WHERE game_id=?",
                              (row["game_id"],)).fetchone()
            if not game or row["team"] not in game[1:]: raise ValueError("game or team not found")
            if dec.date().isoformat()>game[0]: raise ValueError("decision after game date")
            start=conn.execute("SELECT archived_start_utc FROM archive_matches WHERE game_id=?",
                               (row["game_id"],)).fetchone()
            if start and dec >= utc(start[0]): raise ValueError("decision at/after archived game start")
            row["published_at_utc"]=pub.isoformat()
            row["collected_at_utc"]=col.isoformat()
            row["decision_at_utc"]=dec.isoformat()
            vals=[row.get(name) or None for name in COLS]
            conn.execute("INSERT INTO public_signals ("+','.join(COLS)+") VALUES ("+
                         ','.join('?' for _ in COLS)+")", vals)
        except Exception as ex:
            conn.rollback()
            raise ValueError(f"row {i}: {ex}") from ex
    conn.commit()
    print("Imported",len(rows),"public signals")

if __name__=="__main__":main()
