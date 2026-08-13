"""Offline CSZN pipeline check (no API)."""

import numpy as np
import pandas as pd

from strategy import (
    collateral_from_margin,
    gross_notional_from_collateral,
    rebalance_orders,
    target_weights,
)
import config

rng = np.random.default_rng(0)
n = 120
idx = np.arange(n)
# BTC path
btc = pd.Series(50_000 + np.cumsum(rng.normal(0, 80, n)), index=idx)

# alts = true_beta * BTC move + idiosyncratic; SOL residual up, LINK down at end
true_b = {"ETHUSDT": 1.1, "SOLUSDT": 1.4, "AVAXUSDT": 1.2, "LINKUSDT": 0.9}
cols = {}
for sym, b in true_b.items():
    noise = np.cumsum(rng.normal(0, 0.15, n))
    if sym == "SOLUSDT":
        noise[-config.RESID_LOOKBACK :] += np.linspace(0, 2.5, config.RESID_LOOKBACK)
    if sym == "LINKUSDT":
        noise[-config.RESID_LOOKBACK :] -= np.linspace(0, 2.5, config.RESID_LOOKBACK)
    cols[sym] = 100 + b * (btc - btc.iloc[0]) / 150 + noise

closes = pd.DataFrame(cols, index=idx)
w, z, beta = target_weights(closes, btc)
print("z\n", z.sort_values(ascending=False))
print("beta\n", beta)
print("w\n", w[w.abs() > 1e-12].sort_values(ascending=False))
print("port_beta", float((w * beta).sum()))

margin = 4166.0
collat = collateral_from_margin(margin)
gross = gross_notional_from_collateral(collat)
print(
    f"margin={margin} frac={config.COLLATERAL_FRAC} "
    f"collat={collat} gross={gross} lev={config.EXCHANGE_LEVERAGE}"
)
print("orders", rebalance_orders(w, closes.iloc[-1], {}, gross))
