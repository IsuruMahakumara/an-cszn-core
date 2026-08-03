"""Turn feature dict into LONG / SHORT / HOLD."""

from __future__ import annotations

from enum import Enum


class Side(Enum):
    HOLD = 0
    LONG = 1
    SHORT = 2


def decide(feat: dict, *, min_signal_score: int, max_parkinson_vol: float) -> Side:
    # Parkinson is a skip filter, not a direction vote
    if feat["park"] > max_parkinson_vol:
        return Side.HOLD

    score = 0
    score += 1 if feat["close"] > feat["ma"] else -1

    if feat["drr"] > 0.55:
        score += 1
    elif feat["drr"] < 0.45:
        score -= 1

    # volume / VRE confirm only with bar direction
    if feat["vol_z"] > 1.0:
        score += 1 if feat["bull_bar"] else -1
    if feat["vre_z"] > 0.5:
        score += 1 if feat["bull_bar"] else -1

    if score >= min_signal_score:
        return Side.LONG
    if score <= -min_signal_score:
        return Side.SHORT
    return Side.HOLD
