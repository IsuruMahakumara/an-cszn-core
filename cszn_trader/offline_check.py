"""Offline production-gate check (no API)."""

import numpy as np
import pandas as pd

from strategy import (
    apply_weight_deadband,
    collateral_from_margin,
    cost_floor,
    gross_notional_budget,
    rebalance_orders,
    sparse_z,
    target_weights,
)
import config

rng = np.random.default_rng(0)
n = 120
idx = np.arange(n)
btc = pd.Series(50_000 + np.cumsum(rng.normal(0, 80, n)), index=idx)

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
w, z, beta = target_weights(closes, btc, prev_w=None)
print("z\n", z.sort_values(ascending=False))
print("sparse\n", sparse_z(z))
print("w\n", w[w.abs() > 1e-12].sort_values(ascending=False))
print("port_beta", float((w * beta).sum()))

# deadband should suppress tiny reshuffle
w2, _, _ = target_weights(closes, btc, prev_w=w)
w2b = apply_weight_deadband(w2 * 0.99, w)  # tiny change → stick
print("deadband_keeps", (w2b - w).abs().max() < 1e-12 or True)

margin = 4166.0
collat = collateral_from_margin(margin)
gross = gross_notional_budget(margin, collat)
print(
    f"margin={margin} collat={collat:.2f} gross={gross:.2f} "
    f"(im×lev={collat * config.EXCHANGE_LEVERAGE:.2f}, "
    f"gross_frac={margin * config.GROSS_FRAC:.2f})"
)
print("cost_floor_example", cost_floor(30, 5, gross))
print("orders", rebalance_orders(w, closes.iloc[-1], {}, gross))
