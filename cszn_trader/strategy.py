"""Residual book math and risk gates.

Pipeline: Bitcoin beta strip, residual lookback, cross-section z-score,
sparse conviction, dollar-neutral arms, beta hedge inside the active set,
deadband versus prior weights, scarce gross sizing, then a cost gate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config


def rolling_beta(asset_ret: pd.DataFrame, mkt_ret: pd.Series, window: int) -> pd.DataFrame:
    # covariance of each name with Bitcoin over the window
    cov = asset_ret.apply(lambda col: col.rolling(window).cov(mkt_ret))
    # Bitcoin return variance over the same window
    var = mkt_ret.rolling(window).var().replace(0, np.nan)
    # beta = cov / var
    return cov.div(var, axis=0)


def residuals(asset_ret: pd.DataFrame, mkt_ret: pd.Series, beta: pd.DataFrame) -> pd.DataFrame:
    # strip the Bitcoin-explained piece: residual = return - beta * Bitcoin return
    return asset_ret - beta.mul(mkt_ret, axis=0)


def residual_signal(eps: pd.DataFrame, lookback: int) -> pd.Series:
    # short-window residual strength at the latest bar only
    return eps.rolling(lookback).sum().iloc[-1].dropna()


def cross_sectional_z(signal: pd.Series, clip: float = config.Z_CLIP) -> pd.Series:
    # mean and sample std across names at this timestamp
    mu = signal.mean()
    sigma = signal.std(ddof=1)
    # flat cross-section means no tradeable rank
    if not np.isfinite(sigma) or sigma < 1e-12:
        return signal * 0.0
    # unitless rank, then clip tails so no single name dominates
    return ((signal - mu) / sigma).clip(-clip, clip)


def sparse_z(z: pd.Series, z_min: float = config.Z_MIN) -> pd.Series:
    # keep only names with real cross-sectional strength
    out = z.copy()
    out[out.abs() < z_min] = 0.0
    return out


def dollar_neutral_weights(z: pd.Series) -> pd.Series:
    """Map signed z-scores to long and short arms that each sum to half of gross."""
    # positive ranks become the long arm
    long_raw = z.clip(lower=0.0)
    # negative ranks become the short arm
    short_raw = z.clip(upper=0.0)
    long_sum = float(long_raw.sum())
    short_sum = float(short_raw.abs().sum())
    # need both arms or stay flat
    if long_sum <= 0 or short_sum <= 0:
        return pd.Series(0.0, index=z.index)
    # each arm is fifty percent of unit gross
    return long_raw / long_sum * 0.5 + short_raw / short_sum * 0.5


def beta_neutralize(weights: pd.Series, betas: pd.Series) -> pd.Series:
    # project weights orthogonal to the Bitcoin beta vector
    b = betas.reindex(weights.index).fillna(0.0)
    w = weights.fillna(0.0)
    bb = float((b * b).sum())
    if bb < 1e-12:
        return w
    # subtract the component parallel to beta
    return w - b * (float((w * b).sum()) / bb)


def apply_weight_deadband(
    new_w: pd.Series, old_w: pd.Series | None, band: float = config.WEIGHT_DEADBAND
) -> pd.Series:
    """Keep the prior weight unless the change clears the deadband."""
    if old_w is None or band <= 0:
        return new_w
    old = old_w.reindex(new_w.index).fillna(0.0)
    out = new_w.copy()
    # hold steady on tiny reshuffles
    for s in out.index:
        if abs(float(out[s]) - float(old[s])) < band:
            out[s] = old[s]
    # restore unit gross after holding some names fixed
    g = float(out.abs().sum())
    if g > 1e-12:
        out = out / g
    return out


def target_weights(
    closes: pd.DataFrame,
    btc: pd.Series,
    prev_w: pd.Series | None = None,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Full residual pipeline → weights, raw z-scores, and latest betas."""
    # simple percentage returns
    r = closes.pct_change()
    rm = btc.pct_change().reindex(r.index)
    # drop the first missing return row together
    aligned = pd.concat([r, rm.rename("_mkt")], axis=1).dropna()
    rm = aligned["_mkt"]
    r = aligned.drop(columns=["_mkt"])

    # rolling Bitcoin sensitivity per name
    beta = rolling_beta(r, rm, config.BETA_WINDOW)
    # idiosyncratic leftover after the factor strip
    eps = residuals(r, rm, beta)
    # short-window residual rank input
    sig = residual_signal(eps, config.RESID_LOOKBACK)
    z = cross_sectional_z(sig)
    # conviction filter before any capital is assigned
    z_trade = sparse_z(z)
    w = dollar_neutral_weights(z_trade)
    beta_latest = beta.iloc[-1].reindex(w.index)
    # active set: names that passed the z-score floor
    active = z_trade.abs() >= 1e-12
    w = w.where(active, 0.0)
    # beta hedge only inside the active set so dust names stay zero
    if active.any():
        wa = beta_neutralize(w[active], beta_latest[active])
        w = pd.Series(0.0, index=z.index)
        w.loc[wa.index] = wa
    # unit gross so sizing maps cleanly to the budget
    g = float(w.abs().sum())
    if g > 1e-12:
        w = w / g
    else:
        w = pd.Series(0.0, index=z.index)
    # suppress jitter versus last live target
    w = apply_weight_deadband(w, prev_w)
    return w, z, beta_latest


def collateral_from_margin(margin_balance: float) -> float:
    """Initial-margin budget taken as a fraction of account margin balance."""
    if margin_balance <= 0:
        return 0.0
    cap = margin_balance * config.COLLATERAL_FRAC
    # optional hard ceiling
    if config.MAX_COLLATERAL_USDT > 0:
        cap = min(cap, config.MAX_COLLATERAL_USDT)
    return max(0.0, cap)


def gross_notional_budget(margin_balance: float, collateral: float) -> float:
    """Scarce gross: tighter of collateral times leverage and gross fraction of margin."""
    from_im = collateral * max(config.EXCHANGE_LEVERAGE, 1)
    from_margin = margin_balance * config.GROSS_FRAC
    return max(0.0, min(from_im, from_margin))


def cap_name_weights(w: pd.Series, name_frac: float = config.NAME_FRAC) -> pd.Series:
    # clip concentration then restore unit gross
    capped = w.clip(lower=-name_frac, upper=name_frac)
    g = float(capped.abs().sum())
    if g > 1e-12:
        return capped / g
    return capped


def cost_floor(delta: float, min_notional: float, gross_notional: float) -> float:
    """Minimum absolute notional change before a rebalance is worth sending."""
    # estimated fee on this delta
    fee = abs(delta) * (config.FEE_BPS * 1e-4)
    fee_floor = config.COST_MULT * fee
    # weight deadband expressed in United States dollars of gross
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
    """Turn target weights into marketable order stubs; skip uneconomic dust."""
    min_notional_by_sym = min_notional_by_sym or {}
    # enforce per-name concentration
    tw = cap_name_weights(target_w)
    orders = []
    for sym, weight in tw.items():
        px = float(price[sym])
        if px <= 0:
            continue
        # target dollars versus current mark-to-market
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


def derived_im(pos_qty: dict, price: pd.Series, lev: int = config.EXCHANGE_LEVERAGE) -> float:
    """Estimate initial margin as absolute notional divided by exchange leverage."""
    total = 0.0
    for sym, qty in pos_qty.items():
        if sym not in price.index:
            continue
        total += abs(float(qty) * float(price[sym]))
    return total / max(lev, 1)
