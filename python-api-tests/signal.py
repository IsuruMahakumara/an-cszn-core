"""Turn feature dict(s) into LONG / SHORT / HOLD.

This module is the *policy* layer on top of pure measurements in
`features.compute()`. It does not fetch market data and does not place
orders; it only answers:

    Given these bar features and these knobs, are we allowed to open,
    and if so on which side?

Demo / experiment mode (default book policy)
--------------------------------------------
`decide_universe` ranks every name by |lean_score| and assigns:

  - bottom `hold_frac` (default 10%) → HOLD
  - remaining 90% → LONG if lean > 0 else SHORT

So the scan intentionally takes a stance on almost the whole book; HOLD is a
thin middle band of near-zero conviction, not a large vol/score filter set.

Per-symbol `decide` remains for single-name / debug use: soft vol wreck
filter only, then always a side from the lean (no large HOLD rate).

Lean arithmetic
---------------
  +1 if last close > SMA(window)     (price above trend)
  -1 if last close ≤ SMA(window)     (price at/below trend)

  +(2·drr − 1)                       continuous path vote in [-1, +1]
                                     (drr=0.5 → 0; drr→1 → +1; drr→0 → −1)

Net lean in roughly [-2, +2]. Sign picks side; magnitude ranks conviction.
"""

from __future__ import annotations

from enum import Enum


class Side(Enum):
    """Discrete action for one symbol on one scan tick.

    HOLD  — no new entry; leave any existing position alone
    LONG  — runner may open a long (+ market) with trail
    SHORT — runner may open a short with trail
    """

    # no trade intent on this scan
    HOLD = 0
    # bullish entry intent
    LONG = 1
    # bearish entry intent
    SHORT = 2


def lean_score(feat: dict) -> float:
    """Signed continuous conviction for ranking and side.

    Positive → long lean; negative → short lean; near 0 → chop / weak.
    Used by `decide_universe` to pick which 10% sit HOLD.
    """
    # start neutral before votes
    score = 0.0

    # Vote 1 — trend vs moving average (hard ±1, never zero)
    # close > ma → price above recent average → long lean
    # else → at/below average → short lean
    score += 1.0 if feat["close"] > feat["ma"] else -1.0

    # Vote 2 — directional return ratio as a continuous tilt
    # drr≈0.5 contributes ~0; extremes pull toward ±1
    # no dead zone: experiment book wants a stance almost always
    score += (float(feat["drr"]) - 0.5) * 2.0

    return score


def _side_from_lean(lean: float, feat: dict) -> Side:
    """Map signed lean to LONG/SHORT; tie breaks on MA."""
    # strict positive lean → long
    if lean > 0:
        return Side.LONG
    # strict negative lean → short
    if lean < 0:
        return Side.SHORT
    # exact zero (rare): still take a stance for demo density
    return Side.LONG if feat["close"] > feat["ma"] else Side.SHORT


def decide(
    feat: dict,
    *,
    min_signal_score: int = 1,
    min_parkinson_vol: float = 0.0,
    max_parkinson_vol: float = 1.0,
) -> Side:
    """Map one feature dict → Side (single-symbol / debug path).

    Almost always LONG or SHORT after a soft Parkinson wreck band.
    `min_signal_score` is accepted for call-site compatibility but is ignored
    in demo mode (stance comes from lean sign / MA tiebreak).

    For a hard ~10% HOLD / ~90% trade split across many symbols, use
    `decide_universe` instead of calling this in a loop.
    """
    # silence unused legacy knob (kept so older runners still import)
    _ = min_signal_score

    # Parkinson σ on the feature window
    park = feat["park"]

    # hard reject only pure dead / wreck extremes
    if park < min_parkinson_vol:
        return Side.HOLD
    if park > max_parkinson_vol:
        return Side.HOLD

    # continuous lean from MA + DRR path → always a side when band passes
    return _side_from_lean(lean_score(feat), feat)


def decide_universe(
    feats: dict[str, dict],
    *,
    hold_frac: float = 0.10,
    min_parkinson_vol: float = 0.0,
    max_parkinson_vol: float = 1.0,
) -> dict[str, Side]:
    """Assign LONG/SHORT/HOLD for a whole scan with a target HOLD rate.

    Default: ~10% HOLD (weakest |lean|), ~90% take a long or short stance.

    Steps
    -----
    1) Optional soft wreck filter (park out of band → forced HOLD, does not
       count toward the ranked 10% — those are unsafe trials).
    2) Rank remaining symbols by |lean_score| ascending (weakest first).
    3) Bottom `hold_frac` of the ranked set → HOLD.
    4) Rest → LONG if lean > 0 else SHORT (MA tiebreak if lean == 0).

    Parameters
    ----------
    feats
        symbol → feature dict from `features.compute`.
    hold_frac
        Fraction of *rank-eligible* names to leave flat (default 0.10).
    min_parkinson_vol / max_parkinson_vol
        Soft wreck gates; leave wide open for dense demo experiment.
    """
    # forced holds for wreck / dead (outside experiment ranking)
    forced_hold: set[str] = set()
    # rank pool: (symbol, lean)
    ranked: list[tuple[str, float]] = []

    for sym, feat in feats.items():
        # Parkinson from the same window as votes
        park = feat["park"]
        # wreck / dead: never open even when chasing 90% fill rate
        if park < min_parkinson_vol or park > max_parkinson_vol:
            forced_hold.add(sym)
            continue
        # continuous lean for side + |lean| ranking
        ranked.append((sym, lean_score(feat)))

    # how many of the rank pool sit HOLD (weak conviction)
    n = len(ranked)
    n_hold = int(round(n * hold_frac)) if n else 0
    # at least 0; never hold the entire pool unless hold_frac says so
    n_hold = max(0, min(n_hold, n))

    # weakest |lean| first so the middle of cross-section stays flat
    ranked.sort(key=lambda item: abs(item[1]))

    out: dict[str, Side] = {}

    # wrecks already decided
    for sym in forced_hold:
        out[sym] = Side.HOLD

    for i, (sym, lean) in enumerate(ranked):
        # bottom hold_frac of conviction → stay flat this scan
        if i < n_hold:
            out[sym] = Side.HOLD
            continue
        # remaining 90% (or 1-hold_frac) take the side of the lean
        out[sym] = _side_from_lean(lean, feats[sym])

    return out
