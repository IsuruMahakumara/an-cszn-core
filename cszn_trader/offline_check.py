"""Smoke-test signal math offline (no orders).

python -m cszn_trader.offline_check  does not apply — run as script:
  cd cszn_trader && python offline_check.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategy import orders_from_weights, target_weights_from_closes


def main() -> None:
    # Synthetic cointegrated-ish panel
    rng = np.random.default_rng(7)
    n = 100
    idx = np.arange(n)
    # BTC random walk
    mkt = pd.Series(50_000 + np.cumsum(rng.normal(0, 100, n)), index=idx)
    # Alts = beta * BTC + residual noise
    cols = {}
    true_beta = {"ETHUSDT": 1.1, "SOLUSDT": 1.4, "AVAXUSDT": 1.2, "LINKUSDT": 0.9}
    for sym, b in true_beta.items():
        res = np.cumsum(rng.normal(0, 0.5, n))
        # Inject residual leader / lagger at the end
        if sym == "SOLUSDT":
            res[-12:] += np.linspace(0, 5, 12)
        if sym == "LINKUSDT":
            res[-12:] -= np.linspace(0, 5, 12)
        cols[sym] = 100 + b * (mkt - mkt.iloc[0]) / 100 + res
    closes = pd.DataFrame(cols, index=idx)

    w, z, beta = target_weights_from_closes(closes, mkt, beta_window=30, resid_lookback=12)
    print("z:\n", z.sort_values(ascending=False))
    print("w:\n", w.sort_values(ascending=False))
    print("beta:\n", beta)
    print("sum w long", w.clip(lower=0).sum(), "short", w.clip(upper=0).sum())

    prices = closes.iloc[-1]
    pos = pd.Series(0.0, index=w.index)
    orders = orders_from_weights(w, prices, pos, equity=10_000.0, min_notional=10.0)
    print("orders:\n", orders)


if __name__ == "__main__":
    main()
