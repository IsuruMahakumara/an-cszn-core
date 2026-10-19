# an-cszn-core

Cross-sectional residual fade vs Bitcoin on Binance USDT-M demo futures. See `docs/residual-trader.md`.

cd cszn_trader
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# offline math
python sim/offline_check.py

# proof of fade (prod 1m cache on exp/cszn-1m, not demo)
# agent/knob search: docs/cszn-backtest-constitution.md
python sim/backtest.py

# universe screen (prod liquidity; demo gate). --apply rewrites frozen list.
python sim/refresh_universe.py
# python sim/refresh_universe.py --apply --top 30

# append-only venue income ledger (realized / commission / funding)
python tools/sync_ledger.py

# demo cycle (orders off by default)
DRY_RUN=1 RUN_ONCE=1 python run.py

# live demo send + fixed clock
DRY_RUN=0 python run.py
