# CSZN universe screen

Frozen trade list + offline liquidity screen. Not part of the poll loop.

## Files (all under `cszn_trader/`)

| Path | Role |
|---|---|
| `data/universe.csv` | **Frozen** membership. `config.UNIVERSE` = rows with `enabled=1`. |
| `data/universe_prod.csv` | Prod screen snapshot (liquidity + filters info). |
| `data/universe_demo.csv` | Demo listing snapshot (tradeable on sandbox?). |
| `refresh_universe.py` | One script → two snapshots; `--apply` rewrites frozen list. |
| `config.py` | Reads `universe.csv` only. Does not call the screen. |

`minNotional` / `stepSize` on the CSV are **informational**. Live and demo orders still size from `exchangeInfo` in `exchange.py`.

`data/klines_1h.csv` stays the backtest tape cache (gitignored). Universe CSVs are tracked.

## Rules (aligned with constitution)

1. **Prod liquidity** ranks candidates (`quote_volume_24h` on `fapi.binance.com`).
2. **Demo** only gates “symbol is TRADING on demo-fapi.”
3. **`--apply` is explicit.** Snapshots alone never change what the bot trades.
4. After `--apply`, refresh the kline cache before backtesting the new set.
5. Do not grow the universe every week to chase a green scorecard.

## Run

```bash
cd cszn_trader
source .venv/bin/activate

# snapshots only (safe)
python refresh_universe.py

# rewrite frozen membership (prod∩demo top-N)
python refresh_universe.py --apply --top 30
# or: UNIVERSE_TOP_N=30 python refresh_universe.py --apply

# then, if membership changed:
BACKTEST_REFRESH=1 python backtest.py
```

## Frozen CSV columns

`symbol,enabled,quote_volume_24h,max_leverage,demo_ok,screened_at`

Bitcoin stays `BENCHMARK` only and is never enabled as a traded name.
