"""Load klines → residual CSZN weights → market rebalance on a fixed clock.

No discretionary gates. Rebalance only when the clock fires.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone

import pandas as pd

import config
from binance_futures import BinanceFutures
from strategy import orders_from_weights, target_weights_from_closes


def floor_step(qty: float, step: float) -> float:
    # LOT_SIZE floor: never round up into notional the account did not size for
    if step <= 0:
        return qty
    return math.floor(qty / step + 1e-12) * step


def pull_closes(
    client: BinanceFutures, symbols: list[str], interval: str, limit: int
) -> tuple[pd.DataFrame, pd.Series]:
    """Close prices for universe + BTC benchmark index-aligned on open time."""
    frames: dict[str, pd.Series] = {}
    # Fetch each symbol sequentially (MVP; no async)
    for sym in symbols + [config.BENCHMARK]:
        raw = client.klines(sym, interval, limit)
        # kline: [open_time, o, h, l, c, ...]
        idx = [int(row[0]) for row in raw]
        closes = [float(row[4]) for row in raw]
        frames[sym] = pd.Series(closes, index=idx, name=sym)

    # Align on intersection of timestamps so β regression is clean
    book = pd.DataFrame(frames).dropna(how="any")
    mkt = book[config.BENCHMARK]
    assets = book.drop(columns=[config.BENCHMARK])
    return assets, mkt


def run_once(client: BinanceFutures) -> None:
    """One mechanical rebalance cycle."""
    ts = datetime.now(timezone.utc).isoformat()
    print(f"\n=== rebalance {ts} ===")

    # 1) Market data: short-window residual universe
    closes, mkt = pull_closes(
        client,
        config.UNIVERSE,
        config.KLINE_INTERVAL,
        config.KLINE_LIMIT,
    )
    print(f"bars={len(closes)} symbols={list(closes.columns)}")

    # 2) Signal pipeline (CSZN + residual window rank)
    weights, z, betas = target_weights_from_closes(
        closes,
        mkt,
        beta_window=config.BETA_WINDOW,
        resid_lookback=config.RESID_LOOKBACK,
        leverage=config.LEVERAGE_TARGET,
    )
    print("z-scores:\n", z.sort_values(ascending=False).to_string())
    print("weights:\n", weights.sort_values(ascending=False).to_string())
    print("betas:\n", betas.reindex(weights.index).to_string())

    # 3) Equity for notional sizing (Simons: size to capital, not hope)
    equity = client.balance_usdt()
    print(f"equity_usdt={equity:.4f}")
    if equity <= 0:
        print("no equity — skip orders")
        return

    # 4) Marks + open positions
    prices = pd.Series(
        {s: client.mark_price(s) for s in weights.index}, dtype=float
    )
    pos_map = client.positions()
    positions = pd.Series(
        {s: pos_map.get(s, 0.0) for s in weights.index}, dtype=float
    )

    # 5) Target orders with min-notional dust filter
    orders = orders_from_weights(
        weights, prices, positions, equity, config.MIN_NOTIONAL
    )
    if orders.empty:
        print("no orders above min notional")
        return

    print("orders:\n", orders.to_string())

    # 6) Execute market orders (demo), or stop after print when DRY_RUN.
    if config.DRY_RUN:
        print("DRY_RUN=1 — not sending orders")
        return

    for sym, row in orders.iterrows():
        # Exchange step size so qty is accepted
        filt = client.exchange_filters(sym)
        step = filt["stepSize"]
        min_n = max(filt["minNotional"], config.MIN_NOTIONAL)
        qty = floor_step(float(row["qty"]), step)
        # Re-check notional after floor
        notional = qty * float(row["price"])
        if qty <= 0 or notional < min_n:
            print(f"skip {sym}: qty={qty} notional={notional:.4f} < {min_n}")
            continue
        side = str(row["side"])
        try:
            # Optional: set modest exchange leverage ceiling
            client.set_leverage(sym, max(1, int(math.ceil(config.LEVERAGE_TARGET * 2))))
        except Exception as e:
            # Demo may reject leverage if already set — continue
            print(f"leverage warn {sym}: {e}")
        try:
            resp = client.market_order(sym, side, qty)
            print(f"SENT {side} {sym} qty={qty} -> {resp.get('orderId', resp)}")
        except Exception as e:
            print(f"ORDER FAIL {side} {sym} qty={qty}: {e}")


def sleep_until_next_clock(period_s: int) -> None:
    """Fixed wall-clock alignment: rebalance at epoch multiples of period."""
    now = time.time()
    # Next boundary strictly after now
    nxt = (math.floor(now / period_s) + 1) * period_s
    wait = max(1.0, nxt - now)
    print(f"sleep {wait:.1f}s until next clock ({period_s}s)")
    time.sleep(wait)


def main() -> None:
    # Credential gate — refuse silent empty keys
    if not config.API_KEY or not config.SECRET_KEY:
        raise SystemExit("API_KEY / SECRET_KEY missing in .env")

    client = BinanceFutures()
    print("CSZN residual-vs-BTC futures demo")
    print(f"fapi={config.FAPI_BASE}")
    print(f"market={config.MARKET_BASE}")
    print(f"interval={config.KLINE_INTERVAL} rebalance={config.REBALANCE_SECONDS}s")
    print(f"dry_run={config.DRY_RUN} run_once={config.RUN_ONCE}")
    print(f"universe={config.UNIVERSE}")

    # Immediate first pass, then fixed clock (unless RUN_ONCE)
    while True:
        try:
            run_once(client)
        except Exception as e:
            # Log and continue — system must not die on one bad bar
            print(f"cycle error: {e}")
        if config.RUN_ONCE:
            print("RUN_ONCE — exit")
            return
        sleep_until_next_clock(config.REBALANCE_SECONDS)


if __name__ == "__main__":
    main()
