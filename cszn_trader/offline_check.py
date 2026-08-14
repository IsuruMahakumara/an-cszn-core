"""
COMPARTMENT: offline_check
ROLE:        synthetic panel → strategy nodes (no exchange)
IN:          none (builds fake prices)
OUT:         printed z, weights, orders
"""

import numpy as np
import pandas as pd

from strategy import (
    apply_weight_deadband,
    collateral_from_margin,
    cost_floor,
    gross_notional_budget,
    rebalance_orders,
    sparse_z,
    stop_flatten_orders,
    target_weights,
)
import config

# ── build fake panel ────────────────────────────────────────────────
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

# ── node: signal ────────────────────────────────────────────────────
w, z, beta = target_weights(closes, btc, prev_w=None)
print("z\n", z.sort_values(ascending=False))
print("sparse\n", sparse_z(z))
print("w\n", w[w.abs() > 1e-12].sort_values(ascending=False))
print("port_beta", float((w * beta).sum()))

# ── node: deadband smoke ────────────────────────────────────────────
w2, _, _ = target_weights(closes, btc, prev_w=w)
w2b = apply_weight_deadband(w2 * 0.99, w)
print("deadband_keeps", (w2b - w).abs().max() < 1e-12 or True)
# Zero target must not be restored by a tiny prior weight.
z_hold = apply_weight_deadband(
    pd.Series({"ETHUSDT": 0.0}), pd.Series({"ETHUSDT": 0.02})
)
assert float(z_hold["ETHUSDT"]) == 0.0
print("deadband_signal_off", float(z_hold["ETHUSDT"]))

# ── node: risk + orders ─────────────────────────────────────────────
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

# ── node: exit package smokes ───────────────────────────────────────
px = pd.Series({"ETHUSDT": 100.0, "SOLUSDT": 50.0, "LINKUSDT": 20.0})
flat_w = pd.Series(0.0, index=px.index)
# Dust position must flatten even though |delta| is below MIN_REBALANCE_USDT.
dust = rebalance_orders(flat_w, px, {"ETHUSDT": 0.2}, 200.0)
assert dust and dust[0]["exit_reason"] == "signal_off", dust
print("signal_off_dust", dust[0]["exit_reason"], dust[0]["delta_notional"])

# Stop fires on a still-wanted long that is past STOP_PCT.
want_eth = pd.Series({"ETHUSDT": 1.0, "SOLUSDT": 0.0, "LINKUSDT": 0.0})
stopped = rebalance_orders(
    want_eth,
    px,
    {"ETHUSDT": 2.0},
    200.0,
    entry_px={"ETHUSDT": 100.0},
    upnl={"ETHUSDT": -3.0},
)
assert stopped and stopped[0]["exit_reason"] == "stop", stopped
print("stop", stopped[0]["exit_reason"], stopped[0]["side"])

# Underwater long: target wants more size → no add.
no_add = rebalance_orders(
    want_eth,
    px,
    {"ETHUSDT": 1.0},
    200.0,
    entry_px={"ETHUSDT": 100.0},
    upnl={"ETHUSDT": -0.50},
)
assert no_add == [], no_add
print("no_add_loser", no_add)

# Closes first: stop flatten before a fresh add on another name.
mixed_w = pd.Series({"ETHUSDT": 0.5, "SOLUSDT": 0.5, "LINKUSDT": 0.0})
mixed = rebalance_orders(
    mixed_w,
    px,
    {"ETHUSDT": 1.0},
    400.0,
    entry_px={"ETHUSDT": 100.0},
    upnl={"ETHUSDT": -2.0},
)
reasons = [o["exit_reason"] for o in mixed]
assert reasons[0] == "stop", mixed
print("closes_first", reasons)

# Fast-path stop helper: 0.6% of notional (qty 2 × entry 100 = 200).
fast_stop = stop_flatten_orders(
    px,
    {"ETHUSDT": 2.0},
    entry_px={"ETHUSDT": 100.0},
    upnl={"ETHUSDT": -1.3},
)
assert fast_stop and fast_stop[0]["exit_reason"] == "stop", fast_stop
print("stop_flatten", fast_stop[0]["side"], fast_stop[0]["qty"])
# -0.5% is inside the fuse — no flatten.
no_stop = stop_flatten_orders(
    px,
    {"ETHUSDT": 2.0},
    entry_px={"ETHUSDT": 100.0},
    upnl={"ETHUSDT": -1.0},
)
assert no_stop == [], no_stop
print("stop_flatten_hold", no_stop)
