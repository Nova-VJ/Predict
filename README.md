# Predict — MLB Time Machine

Research system for MLB moneyline markets, built so that every prediction only uses
information available before first pitch and every idea is registered before it is tested.

- **Current status and all experiments:** [`EXPERIMENTS.md`](EXPERIMENTS.md) (14 so far).
- **What is built:** [`README_V2.md`](README_V2.md) · earlier V1 notes in [`docs/README_V1.md`](docs/README_V1.md).
- **Target market:** US sportsbooks (US consensus of DraftKings, FanDuel, BetMGM, Caesars, BetRivers, bet365 US as reference; Pinnacle as sharp benchmark).

## Main pieces

| Area | Files |
|---|---|
| Free data sources | `fetch_sources.py` (Retrosheet, retrosplits, odds archive, biofile), MLB Stats API collectors in `pipeline/` |
| Point-in-time features | `build_dataset.py`, `build_player_features.py`, `build_platoon_features.py`, `build_sim_inputs.py` |
| Models | `evaluate_v2.py` (V2 fundamentals + market stack), `models/model_v2_frozen.json`, `simulator.py` (plate-appearance simulator v0) |
| Evaluation | `backtest_engine.py` (daily walk-forward), `evaluate_2026_blind.py`, `portfolio_sim.py`, `exp_*.py` |
| Market comparison | `pipeline/market_compare.py`, `config/bookmakers.json` |
| Automation | `.github/workflows/capture.yml` (every 20 min), `.github/workflows/rebuild.yml` (manual) |

## Keys

API keys are read from environment variables only (`PARLAY_API_KEY`, `ODDS_API_KEY`, `ODDSPAPI_KEY`) — in GitHub, *Settings → Secrets and variables → Actions*. Never commit a key. Without keys, the capture workflow still records the official MLB schedule, probable pitchers and lineups with timestamps.

**This repository is public.** Third-party odds data is excluded via `.gitignore`. Make the repository private before adding odds keys, so captured odds are not published.

## Run locally

```bash
pip install -r requirements.txt
make all            # data, build, features, tests, evaluation
python backtest_engine.py --name baseline
```
