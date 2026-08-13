"""
COMPARTMENT: book
ROLE:        paper USDT-M inventory — fees and realized only
IN:          order stubs + next-bar fill price
OUT:         qty, entry, cash, per-name upnl, equity

Futures: cash does not pay the notional. Cash moves by fee and realized pnl.
"""

from __future__ import annotations

import pandas as pd

import config


def empty(cash: float) -> dict:
    # IN: starting margin → OUT: flat book
    return {"qty": {}, "entry": {}, "cash": float(cash), "fees": 0.0}


def upnl_map(book: dict, px: pd.Series) -> dict[str, float]:
    # IN: book + marks → OUT: {symbol: unrealized}
    out: dict[str, float] = {}
    for sym, qty in book["qty"].items():
        if abs(qty) < 1e-12 or sym not in px.index:
            continue
        entry = float(book["entry"].get(sym, 0.0))
        out[sym] = qty * (float(px[sym]) - entry)
    return out


def equity(book: dict, px: pd.Series) -> float:
    # IN: book + marks → OUT: cash + sum of unrealized
    return float(book["cash"]) + sum(upnl_map(book, px).values())


def apply_fills(book: dict, orders: list[dict], fill_px: pd.Series) -> float:
    # IN: stubs + next close → OUT: turnover; mutates book
    fee_rate = config.FEE_BPS * 1e-4
    turnover = 0.0
    for o in orders:
        sym = o["symbol"]
        if sym not in fill_px.index:
            continue
        px = float(fill_px[sym])
        if px <= 0:
            continue
        signed = float(o["qty"]) if o["side"] == "BUY" else -float(o["qty"])
        old = float(book["qty"].get(sym, 0.0))
        entry = float(book["entry"].get(sym, 0.0))
        notion = abs(signed) * px
        # Commission on the filled notional, both opens and covers.
        fee = notion * fee_rate
        book["cash"] -= fee
        book["fees"] += fee
        turnover += notion

        new = old + signed
        # Cover: realize pnl on the closed piece against average entry.
        if abs(old) > 1e-12 and old * signed < 0:
            closed = min(abs(signed), abs(old))
            sign = 1.0 if old > 0 else -1.0
            book["cash"] += closed * (px - entry) * sign

        if abs(new) < 1e-12:
            book["qty"][sym] = 0.0
            book["entry"][sym] = 0.0
        elif old * new < 0:
            # Flip: leftover is a fresh ticket at this fill.
            book["qty"][sym] = new
            book["entry"][sym] = px
        elif abs(new) > abs(old) + 1e-12:
            # Add to a winner (or a flat): size-weighted entry.
            old_abs = abs(old)
            new_abs = abs(new)
            prior = old_abs * entry if old_abs > 1e-12 else 0.0
            book["qty"][sym] = new
            book["entry"][sym] = (prior + abs(signed) * px) / new_abs
        else:
            # Reduce: keep the old average; cash already took realized.
            book["qty"][sym] = new
    return turnover
