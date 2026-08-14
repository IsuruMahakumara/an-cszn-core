"""
COMPARTMENT: strategy
ROLE:        pure math — no network
NODES:
  signal  IN  closes, btc, prev_w     OUT  weights, z, beta
  risk    IN  margin                  OUT  collateral, gross
  orders  IN  weights, prices, pos, entry, upnl, gross  OUT  order list / stop-only stubs
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
    # Long sleeve and short sleeve each get half of unit gross.
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
    # Hold prior weight when the move is tiny. A new zero always wins (signal off).
    if old_w is None or band <= 0:
        return new_w
    old = old_w.reindex(new_w.index).fillna(0.0)
    tiny_new = new_w.abs() < 1e-12
    small_move = (new_w - old).abs() < band
    out = new_w.where(tiny_new | ~small_move, old)
    g = float(out.abs().sum())
    return out / g if g > 1e-12 else out


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
    z = cross_sectional_z(residual_signal(residuals(r, rm, beta), config.RESID_LOOKBACK))
    z_trade = sparse_z(z)
    w = dollar_neutral_weights(z_trade)
    beta_latest = beta.iloc[-1].reindex(w.index)

    # Beta hedge only on names that cleared the z floor.
    active = z_trade.abs() >= 1e-12
    w = w.where(active, 0.0)
    if active.any():
        wa = beta_neutralize(w[active], beta_latest[active])
        w = pd.Series(0.0, index=z.index)
        w.loc[wa.index] = wa

    g = float(w.abs().sum())
    w = w / g if g > 1e-12 else pd.Series(0.0, index=z.index)
    return apply_weight_deadband(w, prev_w), z, beta_latest


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
        if sym in price.index:
            total += abs(float(qty) * float(price[sym]))
    return total / max(lev, 1)


def cap_name_weights(w: pd.Series, name_frac: float = config.NAME_FRAC) -> pd.Series:
    # IN: weights → OUT: concentration-capped unit-gross weights
    capped = w.clip(lower=-name_frac, upper=name_frac)
    g = float(capped.abs().sum())
    return capped / g if g > 1e-12 else capped


# ═══════════════════════════════════════════════════════════════════
# NODE: orders
# IN:  target weights, marks, open qty, entry, upnl, gross budget
# OUT: list of {symbol, side, qty, px, delta_notional, exit_reason, ...}
# ═══════════════════════════════════════════════════════════════════


def cost_floor(delta: float, min_notional: float, gross_notional: float) -> float:
    # IN: proposed delta → OUT: minimum |delta| worth trading as an add
    fee_floor = abs(delta) * (config.FEE_BPS * 1e-4) * config.COST_MULT
    band_floor = config.WEIGHT_DEADBAND * gross_notional
    return max(
        min_notional,
        config.MIN_NOTIONAL,
        config.MIN_REBALANCE_USDT,
        fee_floor,
        band_floor,
    )


def _unrealized(sym: str, qty: float, px: float, entry_px: dict, upnl: dict) -> float | None:
    # Venue upnl if present; else mark vs entry.
    if sym in upnl:
        return float(upnl[sym])
    entry = float(entry_px.get(sym, 0.0) or 0.0)
    if abs(qty) > 1e-12 and entry > 0:
        return qty * (px - entry)
    return None


def _stop_hit(qty: float, px: float, entry: float, pnl: float | None) -> bool:
    if abs(qty) < 1e-12 or pnl is None:
        return False
    notion = abs(qty) * (entry if entry > 0 else px)
    return notion > 1e-12 and pnl / notion <= -config.STOP_PCT


def rebalance_orders(
    target_w: pd.Series,
    price: pd.Series,
    pos_qty: dict,
    gross_notional: float,
    min_notional_by_sym: dict[str, float] | None = None,
    entry_px: dict | None = None,
    upnl: dict | None = None,
) -> list[dict]:
    # IN: weights + book → OUT: order stubs (closes before adds)
    min_notional_by_sym = min_notional_by_sym or {}
    entry_px = entry_px or {}
    upnl = upnl or {}
    tw = cap_name_weights(target_w)
    for s in pos_qty:
        if s not in tw.index:
            tw.loc[s] = 0.0

    orders = []
    for sym, weight in tw.items():
        if sym not in price.index:
            continue
        px = float(price[sym])
        if px <= 0:
            continue
        qty = float(pos_qty.get(sym, 0.0))
        cur = qty * px
        tgt_w = float(weight)
        entry = float(entry_px.get(sym, 0.0))
        pnl = _unrealized(sym, qty, px, entry_px, upnl)
        reason = "rebalance"

        if _stop_hit(qty, px, entry, pnl):
            tgt_w = 0.0
            reason = "stop"
        elif abs(tgt_w) < 1e-12 and abs(qty) > 1e-12:
            reason = "signal_off"

        tgt = tgt_w * gross_notional
        # Red names: never add size and never reverse through zero.
        if abs(qty) > 1e-12 and pnl is not None and pnl < 0 and reason != "stop":
            new_qty = tgt / px
            if new_qty * qty < -1e-12:
                tgt, tgt_w, reason = 0.0, 0.0, "rebalance"
            elif abs(new_qty) > abs(qty) + 1e-12:
                continue

        delta = tgt - cur
        if abs(delta) < 1e-12:
            continue
        increasing = abs(tgt) > abs(cur) + 1e-8
        floor = cost_floor(
            delta, min_notional_by_sym.get(sym, config.MIN_NOTIONAL), gross_notional
        )
        if increasing and abs(delta) < floor:
            continue
        reducing = abs(tgt) < abs(cur) - 1e-12
        orders.append(
            {
                "symbol": sym,
                "side": "BUY" if delta > 0 else "SELL",
                "qty": abs(delta / px),
                "px": px,
                "delta_notional": delta,
                "floor": floor,
                "target_w": tgt_w,
                "exit_reason": reason,
                "reducing": reducing,
            }
        )
    rank = {"stop": 0, "signal_off": 1, "rebalance": 2}
    orders.sort(key=lambda o: (0 if o["reducing"] else 1, rank.get(o["exit_reason"], 2)))
    return orders


def stop_flatten_orders(
    price: pd.Series,
    pos_qty: dict,
    entry_px: dict | None = None,
    upnl: dict | None = None,
) -> list[dict]:
    # IN: live book → OUT: flatten stubs for names past STOP_PCT only
    entry_px = entry_px or {}
    upnl = upnl or {}
    orders = []
    for sym, raw_qty in pos_qty.items():
        if sym not in price.index:
            continue
        qty = float(raw_qty)
        px = float(price[sym])
        entry = float(entry_px.get(sym, 0.0))
        pnl = _unrealized(sym, qty, px, entry_px, upnl)
        if px <= 0 or not _stop_hit(qty, px, entry, pnl):
            continue
        orders.append(
            {
                "symbol": sym,
                "side": "SELL" if qty > 0 else "BUY",
                "qty": abs(qty),
                "px": px,
                "delta_notional": -qty * px,
                "floor": 0.0,
                "target_w": 0.0,
                "exit_reason": "stop",
                "reducing": True,
            }
        )
    return orders
