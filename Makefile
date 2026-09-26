PY ?= python3

.PHONY: data build features evaluate test all capture

data:        ## download Retrosheet game logs, odds archive and retrosplits (free)
	$(PY) fetch_sources.py

build:       ## rebuild the SQLite base (games, team form, archived odds)
	$(PY) build_dataset.py
	$(PY) evaluate_models.py

features:    ## starter / bullpen / lineup features, point-in-time
	$(PY) build_player_features.py

evaluate:    ## walk-forward V2 evaluation vs market -> output/v2_report.json
	$(PY) evaluate_v2.py

test:
	$(PY) tests.py
	$(PY) tests_v2.py
	$(PY) tests_market.py

capture:     ## one capture run (same as the GitHub Action)
	$(PY) pipeline/collect_snapshot.py

all: data build features test evaluate
