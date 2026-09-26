import unittest
import sqlite3
from build_dataset import build_features, decimal_american
from import_snapshot import import_snapshot
from import_mlb_game_context import pitcher_form, earlier, bullpen_form


class PointInTimeTests(unittest.TestCase):
    def test_same_date_results_never_enter_features(self):
        games=[]
        for i,(day,ar,hr) in enumerate([("2024-04-01",1,5),
                                        ("2024-04-02",1,8),
                                        ("2024-04-02",2,9)]):
            games.append(dict(game_id=str(i),date=day,season=2024,away="B",
                              home="A",away_runs=ar,home_runs=hr,home_win=1))
        f=build_features(games)
        self.assertEqual([x["home_prior_5_games"] for x in f],[0,1,1])
        self.assertEqual([x["home_runs_for_5"] for x in f],[None,5,5])

    def test_american_odds(self):
        self.assertAlmostEqual(decimal_american(-120),1.8333333333333)
        self.assertEqual(decimal_american(110),2.1)
        self.assertIsNone(decimal_american(0))

    def test_pregame_pitcher_and_bullpen_exclude_same_day(self):
        target={'official_date':'2026-09-27','scheduled_start_utc':'2026-09-27T17:00:00Z'}
        pitcher={'received_at_utc':'2026-09-26T12:00:00Z','payload':{'stats':[{'splits':[
            {'date':'2026-09-25','stat':{'gamesStarted':1,'outs':18,'strikeOuts':4}},
            {'date':'2026-09-26','stat':{'gamesStarted':1,'outs':18,'strikeOuts':12}}]}]}}
        self.assertEqual(pitcher_form(pitcher,target)['last5_strikeouts'],4)
        prior={'game_pk':100,'official_date':'2026-09-25','home_team':'BOS','away_team':'NYY'}
        box={'received_at_utc':'2026-09-26T12:00:00Z',
             'payload':{'teams':{'home':{'pitchers':[1,2],'players':{
                 'ID1':{'stats':{'pitching':{'gamesStarted':1,'numberOfPitches':90,'outs':18}}},
                 'ID2':{'stats':{'pitching':{'gamesStarted':0,'numberOfPitches':25,'outs':3}}}}}}}}
        load=bullpen_form({('final_box',100):box},[prior],target,'BOS')
        self.assertEqual(load['relief_pitches_3d'],25)
        self.assertFalse(earlier(box,'2026-09-26T12:00:00Z'))

    def test_snapshot_requires_recent_public_quote(self):
        c=sqlite3.connect(':memory:')
        c.executescript('''CREATE TABLE games (game_id TEXT,home_team TEXT,away_team TEXT,game_date TEXT);
           CREATE TABLE archive_matches (game_id TEXT,archived_start_utc TEXT);
           CREATE TABLE odds_quotes (game_id TEXT,bookmaker TEXT,quote_kind TEXT,side TEXT,
             american_odds INTEGER,decimal_odds REAL,observed_at_utc TEXT,decision_at_utc TEXT,
             availability TEXT,quote_source TEXT);''')
        c.execute("INSERT INTO games VALUES ('g1','NYY','BOS','2024-06-01')")
        c.execute("INSERT INTO archive_matches VALUES ('g1','2024-06-01T19:00:00+00:00')")
        event={'id':'test-event','sport_key':'baseball_mlb',
               'home_team':'New York Yankees','away_team':'Boston Red Sox',
               'commence_time':'2024-06-01T19:00:00Z',
               'bookmakers':[{'key':'testbook','last_update':'2024-06-01T15:58:00Z',
                 'markets':[{'key':'h2h','outcomes':[
                   {'name':'New York Yankees','price':-120},
                   {'name':'Boston Red Sox','price':110}]}]}]}
        snap={'timestamp':'2024-06-01T16:00:00Z','data':[event]}
        self.assertEqual(import_snapshot(c,snap)['two_sided_book_quotes'],1)
        self.assertEqual(c.execute('SELECT count(*) FROM odds_quotes').fetchone()[0],2)
        event['bookmakers'][0]['last_update']='2024-06-01T10:00:00Z'
        self.assertEqual(import_snapshot(c,snap)['two_sided_book_quotes'],0)
        self.assertEqual(c.execute('SELECT count(*) FROM odds_quotes').fetchone()[0],2)
        c.close()


if __name__=="__main__": unittest.main()
