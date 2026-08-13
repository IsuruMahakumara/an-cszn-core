"""Fixed-clock CSZN residual L/S on Binance demo (signal + fills same host)."""

from __future__ import annotations

import math
import time

import pandas as pd

import config
from binance_futures import Client
from strategy import (
    collateral_from_margin,
    gross_notional_from_collateral,
    rebalance_orders,
    target_weights,
)


def pull_closes(client: Client) -> tuple[pd.DataFrame, pd.Series]:
    book = {}
    for sym in config.UNIVERSE + [config.BENCHMARK]:
        raw = client.klines(sym, config.INTERVAL, config.KLINE_LIMIT)
        book[sym] = pd.Series(
            [float(x[4]) for x in raw],
            index=[int(x[0]) for x in raw],
        )
    df = pd.DataFrame(book).dropna()
    return df.drop(columns=[config.BENCHMARK]), df[config.BENCHMARK]


def floor_qty(qty: float, step: float) -> float:
    if step <= 0:
        return qty
    return math.floor(qty / step + 1e-12) * step


def once(client: Client) -> None:
    assets, btc = pull_closes(client)
    print(f"bars={len(assets)} venue={config.MARKET_BASE}")

    # 1+3+4: real β-strip residual → Z → dollar-neutral → β-hedge
    w, z, beta = target_weights(assets, btc)
    print("z:\n", z.sort_values(ascending=False).to_string())
    print("beta:\n", beta.reindex(w.index).to_string())
    print("w:\n", w[w.abs() > 1e-12].sort_values(ascending=False).to_string())

    # 5: collateral from account margin balance
    margin = client.margin_balance()
    avail = client.available_balance()
    collat = collateral_from_margin(margin)
    gross = gross_notional_from_collateral(collat)
    im_used = client.initial_margin_used()
    print(
        f"margin_bal={margin:.2f} avail={avail:.2f} "
        f"collat_cap={collat:.2f} ({config.COLLATERAL_FRAC:.0%} of margin) "
        f"gross={gross:.2f} lev={config.EXCHANGE_LEVERAGE}x im_used={im_used:.2f}"
    )
    if collat <= 0 or gross <= 0:
        print("no collateral budget — skip")
        return

    pos = client.positions()
    names = set(w.index) | set(pos)
    px = pd.Series({s: client.mark(s) for s in names})
    full_w = w.reindex(list(names)).fillna(0.0)

    # per-symbol exchange mins for cost gate
    mins = {s: client.filters(s)["minNotional"] for s in names}
    orders = rebalance_orders(full_w, px, pos, gross, mins)
    print("orders:", orders)
    if config.DRY_RUN:
        print("DRY_RUN — no send")
        return

    # 7: execution hygiene
    im_est = im_used
    for o in orders:
        filt = client.filters(o["symbol"])
        step = filt["stepSize"]
        min_n = max(filt["minNotional"], config.MIN_NOTIONAL)
        qty = floor_qty(float(o["qty"]), step)
        notional = qty * o["px"]
        if qty <= 0 or notional < min_n:
            print("skip lot/notional", o["symbol"], qty, notional)
            continue

        cur_amt = float(pos.get(o["symbol"], 0.0))
        new_amt = cur_amt + qty if o["side"] == "BUY" else cur_amt - qty
        reducing = abs(new_amt) < abs(cur_amt) - 1e-12
        add_im = notional / max(config.EXCHANGE_LEVERAGE, 1)
        # hard IM block: never lock more collateral than margin-derived cap
        if not reducing and im_est + add_im > collat + 1e-6:
            print(f"BLOCK {o['symbol']}: im {im_est:.2f}+{add_im:.2f} > collat {collat:.2f}")
            continue
        # available balance soft check on risk adds
        if not reducing and avail + 1e-6 < add_im:
            print(f"BLOCK {o['symbol']}: need IM {add_im:.2f} > avail {avail:.2f}")
            continue

        try:
            client.set_leverage(o["symbol"], config.EXCHANGE_LEVERAGE)
        except Exception as e:
            print("leverage warn", o["symbol"], e)

        try:
            resp = client.market(
                o["symbol"], o["side"], qty, reduce_only=reducing and not client.hedge_mode
            )
            print("SENT", o["side"], o["symbol"], qty, resp.get("orderId"))
            pos[o["symbol"]] = new_amt
            im_est = im_est - add_im if reducing else im_est + add_im
            if not reducing:
                avail = max(0.0, avail - add_im)
        except Exception as e:
            print("FAIL", o["symbol"], e)


def main() -> None:
    if not config.API_KEY or not config.SECRET_KEY:
        raise SystemExit("missing API_KEY/SECRET_KEY in .env")
    # refuse accidental prod/demo split unless user forced both
    if config.MARKET_BASE != config.FAPI_BASE:
        print(
            "WARN: MARKET_BASE != FAPI_BASE — signal venue differs from order venue:",
            config.MARKET_BASE,
            config.FAPI_BASE,
        )

    client = Client()
    hedge = client.detect_hedge_mode()
    print(
        "CSZN residual demo",
        f"fapi={config.FAPI_BASE}",
        f"market={config.MARKET_BASE}",
        f"hedge={hedge}",
        f"dry_run={config.DRY_RUN}",
        f"collat_frac={config.COLLATERAL_FRAC}",
        f"lev={config.EXCHANGE_LEVERAGE}",
        f"fee_bps={config.FEE_BPS}",
        f"clock={config.REBALANCE_S}s",
    )

    while True:
        try:
            once(client)
        except Exception as e:
            print("error:", e)
        if config.RUN_ONCE:
            return
        now = time.time()
        wait = (math.floor(now / config.REBALANCE_S) + 1) * config.REBALANCE_S - now
        print(f"sleep {wait:.0f}s")
        time.sleep(max(1.0, wait))


if __name__ == "__main__":
    main()
