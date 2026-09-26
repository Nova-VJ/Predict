#!/usr/bin/env python3
"""Fetch original public research archives; source terms remain with providers."""
import pathlib
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent / "raw"
BASE.mkdir(exist_ok=True)
for year in range(2014,2026):
    name=f"gl{year}.zip"
    url=f"https://www.retrosheet.org/gamelogs/{name}"
    target=BASE/name
    if not target.exists():
        urllib.request.urlretrieve(url,target)
    print(name,target.stat().st_size)
name="mlb_odds_dataset.json"
url="https://github.com/ArnavSaraogi/mlb-odds-scraper/releases/download/dataset/"+name
target=BASE/name
if not target.exists():
    urllib.request.urlretrieve(url,target)
print(name,target.stat().st_size)

# V2: player-by-game files (starters, relievers, lineups) from the Chadwick Bureau
# retrosplits project, derived from Retrosheet. Free, no key.
SPLITS = BASE / "retrosplits"
SPLITS.mkdir(exist_ok=True)
for year in range(2013, 2026):
    name = f"playing-{year}.csv"
    target = SPLITS / name
    if not target.exists():
        urllib.request.urlretrieve(
            f"https://raw.githubusercontent.com/chadwickbureau/retrosplits/master/daybyday/{name}", target)
    print(name, target.stat().st_size)

# Handedness (BATS/THROWS) for platoon features: Retrosheet biofile via the Chadwick mirror.
REF = BASE / "retrosheet_ref"
REF.mkdir(exist_ok=True)
target = REF / "biofile.csv"
if not target.exists():
    urllib.request.urlretrieve(
        "https://raw.githubusercontent.com/chadwickbureau/retrosheet/master/reference/biofile.csv", target)
print("biofile.csv", target.stat().st_size)
