"""
COMPARTMENT: backtest
ROLE:        bar clock — proof of the frozen CSZN fade after costs
GRAPH:
  data ──closes,btc──► backtest
  strategy ──w,z,orders──► backtest
  book ──qty,entry,cash──► backtest
  backtest ──scorecard──► stdout

Simons: one rule set, no lookahead, no optimizer, next-bar fill, costs on.
Account-level halt is live ops, not alpha — max drawdown is reported, not censored.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

import config
from book import apply_fills, empty, equity, upnl_map
from data import load_panel
from strategy import (
    collateral_from_margin,
    gross_notional_budget,
    rebalance_orders,
    target_weights,
)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _window(closes: pd.DataFrame, btc: pd.Series, t: int) -> tuple[pd.DataFrame, pd.Series]:
    # IN: full tape + bar index → OUT: the same lookback live would see
    start = max(0, t + 1 - config.KLINE_LIMIT)
    return closes.iloc[start : t + 1], btc.iloc[start : t + 1]


def run() -> dict:
    # IN: cache + frozen knobs → OUT: scorecard dict
    closes, btc = load_panel()
    n = len(closes)
    warmup = config.BETA_WINDOW + config.RESID_LOOKBACK + 2
    if n < warmup + 2:
        raise SystemExit(f"need >{warmup + 2} bars, got {n}")

    book = empty(config.BACKTEST_MARGIN)
    prev_w: pd.Series | None = None
    peak = config.BACKTEST_MARGIN
    max_dd = 0.0
    turnover = 0.0
    reasons = {"stop": 0, "signal_off": 0, "rebalance": 0}
    in_mkt = 0
    n_orders = 0

    # Last bar is fill-only; signal stops at n-2 so t+1 exists.
    for t in range(warmup, n - 1):
        px = closes.iloc[t]
        # Next close is the only fill we are allowed to take.
        fill_px = closes.iloc[t + 1]
        eq = equity(book, px)
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)

        # Same collateral / gross math as live, using marked equity as margin.
        collat = collateral_from_margin(eq)
        gross = gross_notional_budget(eq, collat)
        if collat <= 0 or gross <= 0:
            prev_w = None
            continue

        # Live sees only KLINE_LIMIT bars, not the full tape.
        assets, btc_w = _window(closes, btc, t)
        w, _z, _beta = target_weights(assets, btc_w, prev_w=prev_w)
        pos = {s: q for s, q in book["qty"].items() if abs(q) > 1e-12}
        names = set(w.index) | set(pos)
        full_w = w.reindex(list(names)).fillna(0.0)
        px_all = px.reindex(list(names)).dropna()
        upnl = upnl_map(book, px)
        # Stops, signal-off flatten, no-add-to-losers live in this call.
        orders = rebalance_orders(
            full_w,
            px_all,
            pos,
            gross,
            entry_px=book["entry"],
            upnl=upnl,
        )
        # Fill on the next close: z at t cannot trade t.
        if orders:
            turnover += apply_fills(book, orders, fill_px)
            n_orders += len(orders)
            for o in orders:
                r = o.get("exit_reason", "rebalance")
                reasons[r] = reasons.get(r, 0) + 1
        if any(abs(q) > 1e-12 for q in book["qty"].values()):
            in_mkt += 1
        # Deadband needs the last target, even when this bar held.
        prev_w = w
        if (t - warmup) % 500 == 0:
            print(f"backtest bar {t}/{n - 1} eq={equity(book, fill_px):.2f}")

    last_px = closes.iloc[-1]
    end_eq = equity(book, last_px)
    start = config.BACKTEST_MARGIN
    score = {
        "start_day": _iso(int(closes.index[warmup])),
        "end_day": _iso(int(closes.index[-1])),
        "bars": n - 1 - warmup,
        "start_margin": start,
        "end_equity": end_eq,
        "net_pnl": end_eq - start,
        "ret": (end_eq - start) / start if start else 0.0,
        "max_dd": max_dd,
        "turnover": turnover,
        "fees": book["fees"],
        "n_orders": n_orders,
        "time_in_market": in_mkt / max(n - 1 - warmup, 1),
        **{f"n_{k}": v for k, v in reasons.items()},
    }
    return score


def main() -> None:
    print(
        "CSZN backtest",
        f"tape={config.BACKTEST_FAPI}",
        f"interval={config.INTERVAL}",
        f"z_min={config.Z_MIN}",
        f"stop={config.STOP_PCT}",
        f"fee_bps={config.FEE_BPS}",
        "optimizer=off",
    )
    s = run()
    print(
        f"window {s['start_day']} → {s['end_day']}  bars={s['bars']}\n"
        f"net_pnl={s['net_pnl']:.2f}  ret={s['ret']:.2%}  max_dd={s['max_dd']:.2%}\n"
        f"turnover={s['turnover']:.0f}  fees={s['fees']:.2f}  n_orders={s['n_orders']}\n"
        f"time_in_mkt={s['time_in_market']:.1%}  "
        f"stop={s['n_stop']}  signal_off={s['n_signal_off']}  rebalance={s['n_rebalance']}"
    )
    # One number decides: net after costs. If this is dead, there is no edge to run live.
    if s["net_pnl"] <= 0:
        print("VERDICT: no edge after costs on this frozen tape")
    else:
        print("VERDICT: positive after costs — still one tape, not a license to add knobs")


if __name__ == "__main__":
    main()
