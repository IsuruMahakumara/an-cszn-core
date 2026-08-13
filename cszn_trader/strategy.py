"""CSZN residual book: β-strip → Z → dollar-neutral → β-hedge → cost-gated orders.

Simons discipline: strip common factor, clip tails, diversify by Z, size from
margin-derived collateral only, skip trades that cannot clear fee drag.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config


def rolling_beta(asset_ret: pd.DataFrame, mkt_ret: pd.Series, window: int) -> pd.DataFrame:
    # β = Cov(r_i, r_m) / Var(r_m) over W (CSZN §1)
    cov = asset_ret.apply(lambda col: col.rolling(window).cov(mkt_ret))
    var = mkt_ret.rolling(window).var().replace(0, np.nan)
    return cov.div(var, axis=0)


def residuals(asset_ret: pd.DataFrame, mkt_ret: pd.Series, beta: pd.DataFrame) -> pd.DataFrame:
    # ε = r − β·r_m  (real factor strip, CSZN §2)
    return asset_ret - beta.mul(mkt_ret, axis=0)


def residual_signal(eps: pd.DataFrame, lookback: int) -> pd.Series:
    # short-window residual return strength (latest bar)
    return eps.rolling(lookback).sum().iloc[-1].dropna()


def cross_sectional_z(signal: pd.Series, clip: float = config.Z_CLIP) -> pd.Series:
    # CS mean / std across names (CSZN §3)
    mu = signal.mean()
    sigma = signal.std(ddof=1)
    if not np.isfinite(sigma) or sigma < 1e-12:
        return signal * 0.0
    # winsorize outliers — no hero names
    return ((signal - mu) / sigma).clip(-clip, clip)


def dollar_neutral_weights(z: pd.Series) -> pd.Series:
    """Long/short arms dollar-neutral; sum |w| == 1 (unit of gross notional). CSZN §4."""
    long_raw = z.clip(lower=0.0)
    short_raw = z.clip(upper=0.0)
    long_sum = float(long_raw.sum())
    short_sum = float(short_raw.abs().sum())
    # need both arms or stay flat
    if long_sum <= 0 or short_sum <= 0:
        return pd.Series(0.0, index=z.index)
    # each arm 50% of gross
    return long_raw / long_sum * 0.5 + short_raw / short_sum * 0.5


def beta_neutralize(weights: pd.Series, betas: pd.Series) -> pd.Series:
    # project out portfolio BTC beta: W' = W − (W·β / β·β) β
    b = betas.reindex(weights.index).fillna(0.0)
    w = weights.fillna(0.0)
    bb = float((b * b).sum())
    if bb < 1e-12:
        return w
    return w - b * (float((w * b).sum()) / bb)


def target_weights(closes: pd.DataFrame, btc: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Full CSZN pipeline → (weights, z, latest_beta). Weights: sum|w|≈1 after β-hedge."""
    # simple returns, drop first NaN row together
    r = closes.pct_change()
    rm = btc.pct_change().reindex(r.index)
    aligned = pd.concat([r, rm.rename("_mkt")], axis=1).dropna()
    rm = aligned["_mkt"]
    r = aligned.drop(columns=["_mkt"])

    beta = rolling_beta(r, rm, config.BETA_WINDOW)
    eps = residuals(r, rm, beta)
    # need a fully populated residual lookback row
    sig = residual_signal(eps, config.RESID_LOOKBACK)
    z = cross_sectional_z(sig)
    w = dollar_neutral_weights(z)
    beta_latest = beta.iloc[-1].reindex(w.index)
    # enforce zero first-order BTC exposure
    w = beta_neutralize(w, beta_latest)
    # renormalize to unit gross after hedge (keep risk budget meaning)
    gross = float(w.abs().sum())
    if gross > 1e-12:
        w = w / gross
    return w, z, beta_latest


def collateral_from_margin(margin_balance: float) -> float:
    """IM budget derived from account margin balance (Simons: risk from capital, not hope)."""
    if margin_balance <= 0:
        return 0.0
    # fraction of margin we allow to lock as initial margin
    cap = margin_balance * config.COLLATERAL_FRAC
    # optional absolute ceiling
    if config.MAX_COLLATERAL_USDT > 0:
        cap = min(cap, config.MAX_COLLATERAL_USDT)
    return max(0.0, cap)


def gross_notional_from_collateral(collateral: float) -> float:
    # notional capacity = IM budget × exchange leverage
    return collateral * max(config.EXCHANGE_LEVERAGE, 1)


def cost_floor(notional: float, min_notional: float) -> float:
    """Min |ΔV| to trade: max(exchange min, COST_MULT × fee on that notional)."""
    # fee drag estimate in USDT for a rebalance of this notional
    fee = abs(notional) * (config.FEE_BPS * 1e-4)
    return max(min_notional, config.COST_MULT * fee, config.MIN_NOTIONAL)


def rebalance_orders(
    target_w: pd.Series,
    price: pd.Series,
    pos_qty: dict,
    gross_notional: float,
    min_notional_by_sym: dict[str, float] | None = None,
) -> list[dict]:
    """Target notionals from gross budget; skip dust / fee-uneconomic deltas."""
    min_notional_by_sym = min_notional_by_sym or {}
    orders = []
    for sym, tw in target_w.items():
        px = float(price[sym])
        if px <= 0:
            continue
        tgt = float(tw) * gross_notional
        cur = float(pos_qty.get(sym, 0.0)) * px
        delta = tgt - cur
        # cost gate vs exchange min
        floor = cost_floor(delta, min_notional_by_sym.get(sym, config.MIN_NOTIONAL))
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
            }
        )
    return orders
