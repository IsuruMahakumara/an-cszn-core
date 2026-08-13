"""
COMPARTMENT: strategy
ROLE:        pure math — no network
NODES:
  signal  IN  closes, btc, prev_w     OUT  weights, z, beta
  risk    IN  margin                  OUT  collateral, gross
  orders  IN  weights, prices, pos, gross  OUT  order list
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config


# ═══════════════════════════════════════════════════════════════════
# NODE: signal
# IN:  asset closes, Bitcoin closes, optional prior weights
# OUT: unit-gross weights, raw z-scores, latest betas
# ═══════════════════════════════════════════════════════════════════


def rolling_beta(asset_ret: pd.DataFrame, mkt_ret: pd.Series, window: int) -> pd.DataFrame:
    # IN: returns → OUT: rolling beta vs Bitcoin
    cov = asset_ret.apply(lambda col: col.rolling(window).cov(mkt_ret))
    var = mkt_ret.rolling(window).var().replace(0, np.nan)
    return cov.div(var, axis=0)


def residuals(asset_ret: pd.DataFrame, mkt_ret: pd.Series, beta: pd.DataFrame) -> pd.DataFrame:
    # IN: returns + beta → OUT: residual returns
    return asset_ret - beta.mul(mkt_ret, axis=0)


def residual_signal(eps: pd.DataFrame, lookback: int) -> pd.Series:
    # IN: residual panel → OUT: latest lookback sum per name
    return eps.rolling(lookback).sum().iloc[-1].dropna()


def cross_sectional_z(signal: pd.Series, clip: float = config.Z_CLIP) -> pd.Series:
    # IN: residual signal → OUT: clipped cross-section z-scores
    mu = signal.mean()
    sigma = signal.std(ddof=1)
    if not np.isfinite(sigma) or sigma < 1e-12:
        return signal * 0.0
    return ((signal - mu) / sigma).clip(-clip, clip)


def sparse_z(z: pd.Series, z_min: float = config.Z_MIN) -> pd.Series:
    # IN: z → OUT: z with weak names zeroed
    out = z.copy()
    out[out.abs() < z_min] = 0.0
    return out


def dollar_neutral_weights(z: pd.Series) -> pd.Series:
    # IN: sparse z → OUT: dollar-neutral weights (sum |w| = 1)
    long_raw = z.clip(lower=0.0)
    short_raw = z.clip(upper=0.0)
    long_sum = float(long_raw.sum())
    short_sum = float(short_raw.abs().sum())
    if long_sum <= 0 or short_sum <= 0:
        return pd.Series(0.0, index=z.index)
    return long_raw / long_sum * 0.5 + short_raw / short_sum * 0.5


def beta_neutralize(weights: pd.Series, betas: pd.Series) -> pd.Series:
    # IN: weights + betas → OUT: weights with zero portfolio beta
    b = betas.reindex(weights.index).fillna(0.0)
    w = weights.fillna(0.0)
    bb = float((b * b).sum())
    if bb < 1e-12:
        return w
    return w - b * (float((w * b).sum()) / bb)


def apply_weight_deadband(
    new_w: pd.Series, old_w: pd.Series | None, band: float = config.WEIGHT_DEADBAND
) -> pd.Series:
    # IN: new + prior weights → OUT: weights with tiny changes held
    if old_w is None or band <= 0:
        return new_w
    old = old_w.reindex(new_w.index).fillna(0.0)
    out = new_w.copy()
    for s in out.index:
        if abs(float(out[s]) - float(old[s])) < band:
            out[s] = old[s]
    g = float(out.abs().sum())
    if g > 1e-12:
        out = out / g
    return out


def target_weights(
    closes: pd.DataFrame,
    btc: pd.Series,
    prev_w: pd.Series | None = None,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    # IN: closes, btc, prev_w → OUT: (weights, z, beta)
    r = closes.pct_change()
    rm = btc.pct_change().reindex(r.index)
    aligned = pd.concat([r, rm.rename("_mkt")], axis=1).dropna()
    rm = aligned["_mkt"]
    r = aligned.drop(columns=["_mkt"])

    beta = rolling_beta(r, rm, config.BETA_WINDOW)
    eps = residuals(r, rm, beta)
    sig = residual_signal(eps, config.RESID_LOOKBACK)
    z = cross_sectional_z(sig)
    z_trade = sparse_z(z)
    w = dollar_neutral_weights(z_trade)
    beta_latest = beta.iloc[-1].reindex(w.index)

    active = z_trade.abs() >= 1e-12
    w = w.where(active, 0.0)
    if active.any():
        wa = beta_neutralize(w[active], beta_latest[active])
        w = pd.Series(0.0, index=z.index)
        w.loc[wa.index] = wa

    g = float(w.abs().sum())
    if g > 1e-12:
        w = w / g
    else:
        w = pd.Series(0.0, index=z.index)

    w = apply_weight_deadband(w, prev_w)
    return w, z, beta_latest


# ═══════════════════════════════════════════════════════════════════
# NODE: risk
# IN:  margin balance
# OUT: collateral cap, gross notional budget, derived initial margin
# ═══════════════════════════════════════════════════════════════════


def collateral_from_margin(margin_balance: float) -> float:
    # IN: margin → OUT: initial-margin budget
    if margin_balance <= 0:
        return 0.0
    cap = margin_balance * config.COLLATERAL_FRAC
    if config.MAX_COLLATERAL_USDT > 0:
        cap = min(cap, config.MAX_COLLATERAL_USDT)
    return max(0.0, cap)


def gross_notional_budget(margin_balance: float, collateral: float) -> float:
    # IN: margin + collateral → OUT: max gross notional
    from_im = collateral * max(config.EXCHANGE_LEVERAGE, 1)
    from_margin = margin_balance * config.GROSS_FRAC
    return max(0.0, min(from_im, from_margin))


def derived_im(pos_qty: dict, price: pd.Series, lev: int = config.EXCHANGE_LEVERAGE) -> float:
    # IN: positions + marks → OUT: estimated initial margin
    total = 0.0
    for sym, qty in pos_qty.items():
        if sym not in price.index:
            continue
        total += abs(float(qty) * float(price[sym]))
    return total / max(lev, 1)


def cap_name_weights(w: pd.Series, name_frac: float = config.NAME_FRAC) -> pd.Series:
    # IN: weights → OUT: concentration-capped unit-gross weights
    capped = w.clip(lower=-name_frac, upper=name_frac)
    g = float(capped.abs().sum())
    if g > 1e-12:
        return capped / g
    return capped


# ═══════════════════════════════════════════════════════════════════
# NODE: orders
# IN:  target weights, marks, open qty, gross budget
# OUT: list of {symbol, side, qty, px, delta_notional, ...}
# ═══════════════════════════════════════════════════════════════════


def cost_floor(delta: float, min_notional: float, gross_notional: float) -> float:
    # IN: proposed delta → OUT: minimum |delta| worth trading
    fee = abs(delta) * (config.FEE_BPS * 1e-4)
    fee_floor = config.COST_MULT * fee
    band_floor = config.WEIGHT_DEADBAND * gross_notional
    return max(
        min_notional,
        config.MIN_NOTIONAL,
        config.MIN_REBALANCE_USDT,
        fee_floor,
        band_floor,
    )


def rebalance_orders(
    target_w: pd.Series,
    price: pd.Series,
    pos_qty: dict,
    gross_notional: float,
    min_notional_by_sym: dict[str, float] | None = None,
) -> list[dict]:
    # IN: weights + book → OUT: economic order stubs
    min_notional_by_sym = min_notional_by_sym or {}
    tw = cap_name_weights(target_w)
    orders = []
    for sym, weight in tw.items():
        px = float(price[sym])
        if px <= 0:
            continue
        tgt = float(weight) * gross_notional
        cur = float(pos_qty.get(sym, 0.0)) * px
        delta = tgt - cur
        floor = cost_floor(
            delta, min_notional_by_sym.get(sym, config.MIN_NOTIONAL), gross_notional
        )
        if abs(delta) < floor:
            continue
        orders.append(
            {
                "symbol": sym,
                "side": "BUY" if delta > 0 else "SELL",
                "qty": abs(delta / px),
                "px": px,
                "delta_notional": delta,
                "floor": floor,
                "target_w": float(weight),
            }
        )
    return orders
