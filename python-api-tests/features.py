"""Pure bar features — no network I/O.

This module turns a fixed-length window of OHLCV candles into scalar
statistics that `signal.decide()` later uses for LONG / SHORT / HOLD.

Philosophy
----------
All functions here are pure (inputs → outputs only). They never call
Binance, never read files, and never look at account state. That keeps
feature math easy to unit-test and impossible to accidentally trade from.

Data window convention
----------------------
`Bars` holds equal-length lists `o,h,l,c,v`. Index 0 is the *oldest*
closed candle; index -1 is the *most recent* closed candle. Callers
(see `exchange.fetch_bars`) must already drop the still-forming bar;
features assume every candle is finished.

What each feature means for trading
-----------------------------------
- ma      : average close — crude trend anchor (price above/below)
- park    : Parkinson range volatility — "is the book loud enough?"
- drr     : directional return ratio — bullish vs bearish log-return mass
- vre_z   : volume-range elasticity z-score (computed, may be unused by signal)
- vol_z   : volume z-score (computed, may be unused by signal)
- bull_bar: last bar was green (close > open)
- close   : last close price (for comparison to ma)

Only the runner / signal policy decides which of these get used as votes;
this file just measures them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Bars:
    """Fixed-length OHLCV window for one symbol.

    Every list must have the same length N (typically FEATURE_BAR_COUNT
    from the runner). Units:
      - o,h,l,c : price in quote (USDT / USDC)
      - v       : base-asset volume for that bar (exchange kline qty)
    """

    # open prices, oldest → newest
    o: list[float]
    # high prices over each bar
    h: list[float]
    # low prices over each bar
    l: list[float]
    # close prices (last traded in the interval)
    c: list[float]
    # traded volume in base asset for the bar
    v: list[float]


def sma(xs: list[float]) -> float:
    """Simple moving average = arithmetic mean of the series.

    Why SMA not EMA? For a short fixed window (e.g. 20 bars) SMA is the
    most transparent baseline: every bar weights equally, no decay
    hyperparameters, easy to recompute by hand from logged closes.
    """
    # sum of all points, then divide by count (caller guarantees non-empty)
    return sum(xs) / len(xs)


def parkinson(h: list[float], l: list[float]) -> float:
    """Parkinson high–low volatility estimator over the window.

    Formula used here (per-bar range, averaged, sqrt):

        σ_P = sqrt( (1 / (4 ln 2)) * mean_i[ ln(H_i / L_i)^2 ] )

    Intuition
    ---------
    Classic close-to-close volatility only sees end-of-bar marks. Parkinson
    uses the high/low range *inside* each bar, so it captures more of the
    true path length for the same sample size. That makes it a cheap
    "how much did price thrash?" measure for our LLN sleeve:

      - too small → noise dominates fee / trail → we HOLD
      - mid range → enough swing for trail to matter → allow direction
      - too large → gap / PERCENT_PRICE / stop-out risk → HOLD ceiling

    Implementation notes
    --------------------
    - Bad bars (non-positive prices, H < L) are *skipped from the sum* but
      the denominator still uses `len(h)` (full window size). That slightly
      understates vol when bars are broken rather than dropping the sample;
      for live exchange klines this almost never matters.
    - Result is unitless (log-return space), not annualized. Compare it only
      against thresholds calibrated on the *same* interval (e.g. 15m).
    """
    # accumulator for sum of squared log-ranges
    acc = 0.0
    # walk each bar's (high, low) pair in lockstep
    for hi, lo in zip(h, l):
        # refuse nonsense prices / inverted ranges (data glitch)
        if hi <= 0 or lo <= 0 or hi < lo:
            continue
        # natural log of high/low = one-bar range return
        lr = math.log(hi / lo)
        # square contribution (sign cancelled; larger range → more vol)
        acc += lr * lr
    # Parkinson scale factor: 1/(4 ln 2) · mean(·) under the outer sqrt
    # denom = N * 4 * ln(2), so overall = sqrt(acc / (N * 4 ln 2))
    return math.sqrt(acc / (len(h) * 4.0 * math.log(2)))


def drr(closes: list[float]) -> float:
    """Directional Return Ratio from consecutive log-returns of closes.

    For each step a → b (adjacent closes):

        r_t = ln(b / a)

    Then:

        drr = sum( max(r_t, 0) )  /  sum( |r_t| )

    Interpretation of the scalar in (0, 1) (or 0.5 if flat):
      ~1.0  almost all up-move magnitude, almost no down
      ~0.5  balanced / choppy (up mass ≈ down mass)
      ~0.0  almost all down-move magnitude

    Why use this instead of "last return only"?
      A single bar can flip sign from noise. Ratio of *path* up-move mass
      vs total variation over the whole window is a more stable bullishness
      score for short lookbacks. Signal maps:
          drr > 0.55 → bullish vote
          drr < 0.45 → bearish vote
          else        → no DRR vote

    Edge case: if total variation is zero (all closes equal / filtered),
    return 0.5 so we do **not** invent a fake bullish or bearish lean.
    """
    # up-move mass and total absolute move mass
    up = tot = 0.0
    # pairs of consecutive closes: (older, newer)
    for a, b in zip(closes, closes[1:]):
        # skip non-positive older close (log undefined)
        if a <= 0:
            continue
        # continuously compounded one-step return
        r = math.log(b / a)
        # always count absolute contribution in the denominator
        tot += abs(r)
        # only positive returns add to the "up" mass
        if r > 0:
            up += r
    # no path movement → neutral midpoint
    return 0.5 if tot == 0 else up / tot


def vre_series(h: list[float], l: list[float], v: list[float]) -> list[float]:
    """Per-bar volume / price-range "elasticity" series.

    For each bar:

        VRE_i = volume_i / max(high_i - low_i, ε)

    Heuristic idea:
      High volume on a *narrow* range → liquid, two-sided interest (elastic).
      Low volume on a *wide* range → thin book, easier to squeeze.

    Returned list keeps one value per bar so `zscore` can compare the
    *latest* VRE to the window mean. 1e-12 floor avoids division by zero
    when H ≈ L (doji-style flat bar).

    Note: the current signal vote path may ignore VRE; it is still computed
    so logs / future gates can use it without re-parsing klines.
    """
    # element-wise volume divided by (high - low), with tiny epsilon floor
    return [vol / max(hi - lo, 1e-12) for hi, lo, vol in zip(h, l, v)]


def zscore(xs: list[float]) -> float:
    """Sample z-score of the *last* element vs the rest of the window.

        z = (x_last - mean(xs)) / sample_std(xs)

    sample_std uses Bessel's correction (divide by N-1), matching a small-
    sample "is the latest bar special?" framing.

    Returns 0.0 when:
      - fewer than 2 points (undefined dispersion)
      - sample std is 0 (every bar identical → no surprise)

    Positive z ⇒ last bar higher than recent typical level.
    Negative z ⇒ last bar lower than recent typical level.
    Magnitude is in σ units (e.g. |z| > 2 is a rough outlier).
    """
    # need mean and variance → need at least two observations
    if len(xs) < 2:
        return 0.0
    # window mean used as the "normal" level
    mu = sma(xs)
    # unbiased sample variance of the whole series (incl. last point)
    var = sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)
    # sample standard deviation
    sd = math.sqrt(var)
    # degenerate flat series → no useful z
    return 0.0 if sd == 0 else (xs[-1] - mu) / sd


def compute(bars: Bars) -> dict:
    """Bundle every feature used (or reserved) by the strategy pipeline.

    Input: one `Bars` window already trimmed to closed candles only.
    Output: a flat dict so `signal.decide` and logs can index by name.

    Keys
    ----
    ma       float  SMA of closes over the full window
    park     float  Parkinson σ of the high/low path
    drr      float  directional return ratio in [0, 1] (or ~0.5 neutral)
    vre_z    float  z-score of latest volume/range elasticity
    vol_z    float  z-score of latest bar volume
    bull_bar bool   True if last candle closed green (c > o)
    close    float  last close (the price we compare to ma)

    Call order is measurement-only: nothing here implies a trade side.
    Direction / gates live entirely in `signal.decide`.
    """
    # build VRE path once so both series and z-score share the same math
    vre = vre_series(bars.h, bars.l, bars.v)
    # package named features for the decision layer + logging
    return {
        # trend anchor: average of closes
        "ma": sma(bars.c),
        # vol gate input: range-based Parkinson estimator
        "park": parkinson(bars.h, bars.l),
        # direction vote input: up-move mass / total variation
        "drr": drr(bars.c),
        # optional volume-structure z (not required by current decide())
        "vre_z": zscore(vre),
        # optional volume z (not required by current decide())
        "vol_z": zscore(bars.v),
        # last bar direction micro-signal (available if policy wants it)
        "bull_bar": bars.c[-1] > bars.o[-1],
        # raw last mark for ma comparison
        "close": bars.c[-1],
    }
