"""Cross-sectional residual signal and dollar-neutral weights (CSZN.md).

Jim Simons alignment (concrete, not folklore):
- Trade a mechanical residual rank, not stories about coins.
- Strip common BTC factor; bet only on idiosyncratic cross-section.
- Diversify: weight many names, clip tails, no single-name heroism.
- Fixed rules every rebalance; no discretionary hold overrides.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config


def pct_returns(closes: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    # Simple returns as in CSZN §1: (P_t - P_{t-1}) / P_{t-1}
    return closes.pct_change()


def rolling_beta(
    asset_ret: pd.DataFrame, mkt_ret: pd.Series, window: int
) -> pd.DataFrame:
    # β_i,t = Cov(r_i, r_m) / Var(r_m) over window W
    cov = asset_ret.apply(lambda col: col.rolling(window).cov(mkt_ret))
    var = mkt_ret.rolling(window).var()
    # Guard against zero market variance
    return cov.div(var.replace(0, np.nan), axis=0)


def residuals(
    asset_ret: pd.DataFrame, mkt_ret: pd.Series, beta: pd.DataFrame
) -> pd.DataFrame:
    # ε_i,t = r_i,t − β_i,t · r_m,t  (CSZN §2)
    systematic = beta.mul(mkt_ret, axis=0)
    return asset_ret - systematic


def residual_window_signal(
    resid: pd.DataFrame, lookback: int
) -> pd.Series:
    """Short-window residual return, vol-standardized (latest bar only).

    Rank input = sum(ε over W) / std(ε over W). Pure residual path strength.
    """
    # Rolling sum of residuals over short lookback
    roll_sum = resid.rolling(lookback).sum()
    # Residual vol for scale-free rank
    roll_std = resid.rolling(lookback).std()
    # Latest cross-section only (rebalance clock uses one row)
    latest = roll_sum.iloc[-1] / (roll_std.iloc[-1] + 1e-8)
    return latest.dropna()


def cross_sectional_z(signal: pd.Series, clip: float = config.Z_CLIP) -> pd.Series:
    # μ, σ across names at this rebalance (CSZN §3)
    mu = signal.mean()
    sigma = signal.std(ddof=1)
    if sigma is None or not np.isfinite(sigma) or sigma < 1e-12:
        # Flat cross-section → no trade
        return signal * 0.0
    z = (signal - mu) / sigma
    # Winsorize outliers to [-3, 3]
    return z.clip(-clip, clip)


def dollar_neutral_weights(
    z: pd.Series, leverage: float = config.LEVERAGE_TARGET
) -> pd.Series:
    """100% long / 100% short dollar neutrality, then L_target / 2 scale (CSZN §4–5)."""
    # Positive Z → long arm
    long_raw = z.clip(lower=0.0)
    # Negative Z → short arm (keep signed)
    short_raw = z.clip(upper=0.0)

    long_sum = long_raw.sum()
    short_sum = short_raw.abs().sum()

    # No long names or no short names → stay flat (need both sides)
    if long_sum <= 0 or short_sum <= 0:
        return pd.Series(0.0, index=z.index)

    # Normalize each arm to unit mass, then half-leverage each side
    w_long = long_raw / long_sum * (leverage / 2.0)
    w_short = short_raw / short_sum * (leverage / 2.0)
    return w_long + w_short


def beta_neutralize(weights: pd.Series, betas: pd.Series) -> pd.Series:
    """Project out residual portfolio beta (from new_code.py).

    W' = W − (W·β / β·β) β
    Keeps dollar-ish ranks but zeroes first-order BTC exposure.
    """
    # Align indices (missing beta → 0 weight already)
    b = betas.reindex(weights.index).fillna(0.0)
    w = weights.fillna(0.0)
    bb = float((b * b).sum())
    if bb < 1e-12:
        return w
    # Portfolio beta under current weights
    port_beta = float((w * b).sum())
    # Subtract beta-parallel component
    return w - b * (port_beta / bb)


def target_weights_from_closes(
    closes: pd.DataFrame,
    mkt_close: pd.Series,
    beta_window: int = config.BETA_WINDOW,
    resid_lookback: int = config.RESID_LOOKBACK,
    leverage: float = config.LEVERAGE_TARGET,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Full CSZN pipeline → final weight vector.

    Returns (weights, z_scores, latest_betas).
    """
    # Returns for assets and BTC benchmark
    r = pct_returns(closes).dropna(how="all")
    rm = pct_returns(mkt_close).reindex(r.index)
    # Drop first NaN row consistently
    r = r.iloc[1:]
    rm = rm.iloc[1:]

    # Rolling market sensitivity
    beta = rolling_beta(r, rm, beta_window)
    # Idiosyncratic residuals
    eps = residuals(r, rm, beta)
    # Short-window residual rank signal (latest bar)
    sig = residual_window_signal(eps, resid_lookback)
    # Cross-sectional Z + winsorize
    z = cross_sectional_z(sig)
    # Dollar-neutral arms
    w = dollar_neutral_weights(z, leverage=leverage)
    # Latest betas for neutralization
    beta_latest = beta.iloc[-1].reindex(w.index)
    # Enforce zero portfolio beta vs BTC
    w = beta_neutralize(w, beta_latest)
    return w, z, beta_latest


def orders_from_weights(
    weights: pd.Series,
    prices: pd.Series,
    positions_qty: pd.Series,
    equity: float,
    min_notional: float = config.MIN_NOTIONAL,
) -> pd.DataFrame:
    """Convert target weights to rebalance notionals / qty (CSZN §5)."""
    # Target dollar exposure per name
    target_notional = weights * equity
    # Current dollar exposure from open positions
    current_notional = positions_qty.reindex(weights.index).fillna(0.0) * prices
    # Trade the gap
    delta_v = target_notional - current_notional
    # Qty to send (signed); price from mark
    qty = delta_v / prices
    # Side string for the exchange
    side = np.where(qty > 0, "BUY", "SELL")

    df = pd.DataFrame(
        {
            "weight": weights,
            "price": prices,
            "target_notional": target_notional,
            "delta_notional": delta_v,
            "qty": qty.abs(),
            "side": side,
        },
        index=weights.index,
    )
    # Skip dust: |ΔV| below exchange / cost threshold
    mask = df["delta_notional"].abs() >= min_notional
    return df.loc[mask]
