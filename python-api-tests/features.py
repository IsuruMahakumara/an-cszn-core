"""Pure bar features — no network I/O."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Bars:
    o: list[float]
    h: list[float]
    l: list[float]
    c: list[float]
    v: list[float]


def sma(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def parkinson(h: list[float], l: list[float]) -> float:
    # σ_P = sqrt( (1/(4 ln 2)) * mean( ln(H/L)^2 ) )
    acc = 0.0
    for hi, lo in zip(h, l):
        if hi <= 0 or lo <= 0 or hi < lo:
            continue
        lr = math.log(hi / lo)
        acc += lr * lr
    return math.sqrt(acc / (len(h) * 4.0 * math.log(2)))


def drr(closes: list[float]) -> float:
    # sum(up returns) / sum(|returns|) → ~1 bullish, ~0 bearish, ~0.5 mixed
    up = tot = 0.0
    for a, b in zip(closes, closes[1:]):
        if a <= 0:
            continue
        r = math.log(b / a)
        tot += abs(r)
        if r > 0:
            up += r
    return 0.5 if tot == 0 else up / tot


def vre_series(h: list[float], l: list[float], v: list[float]) -> list[float]:
    # volume / range (elasticity proxy)
    return [vol / max(hi - lo, 1e-12) for hi, lo, vol in zip(h, l, v)]


def zscore(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mu = sma(xs)
    var = sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)
    sd = math.sqrt(var)
    return 0.0 if sd == 0 else (xs[-1] - mu) / sd


def compute(bars: Bars) -> dict:
    vre = vre_series(bars.h, bars.l, bars.v)
    return {
        "ma": sma(bars.c),
        "park": parkinson(bars.h, bars.l),
        "drr": drr(bars.c),
        "vre_z": zscore(vre),
        "vol_z": zscore(bars.v),
        "bull_bar": bars.c[-1] > bars.o[-1],
        "close": bars.c[-1],
    }
