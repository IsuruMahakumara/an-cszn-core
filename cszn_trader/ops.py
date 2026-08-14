"""
COMPARTMENT: ops
ROLE:        persistence + kill switch (no strategy math)
IN:          state dict / margin
OUT:         updated state, log file path
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

import config

_EMPTY = {
    "weights": {},
    "peak_margin": None,
    "halted": False,
    "halt_reason": None,
    "last_cycle_ts": None,
}


def load_state(path: Path = config.STATE_PATH) -> dict[str, Any]:
    # IN: path → OUT: state dict
    if not path.exists():
        return dict(_EMPTY)
    with path.open() as f:
        return json.load(f)


def save_state(state: dict[str, Any], path: Path = config.STATE_PATH) -> None:
    # Atomic replace so a crash cannot leave a half-written file.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    tmp.replace(path)


def weights_from_state(state: dict[str, Any]) -> pd.Series | None:
    # IN: state → OUT: prior weight series or None
    w = state.get("weights") or {}
    if not w:
        return None
    return pd.Series({k: float(v) for k, v in w.items()})


def log_cycle(row: dict[str, Any], log_dir: Path = config.LOG_DIR) -> Path:
    # IN: cycle row → OUT: append path
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"cycles_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
    row = dict(row)
    row["ts"] = datetime.now(timezone.utc).isoformat()
    with path.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")
    return path


def update_peak_and_kill(
    state: dict[str, Any], margin: float, max_dd: float = config.MAX_DRAWDOWN_FRAC
) -> dict[str, Any]:
    # Halt if live margin has fallen max_dd from the high-water mark.
    peak = state.get("peak_margin")
    if peak is None or margin > float(peak):
        state["peak_margin"] = margin
        peak = margin
    peak = float(peak)
    if peak > 0 and (peak - margin) / peak >= max_dd:
        state["halted"] = True
        state["halt_reason"] = (
            f"drawdown {(peak - margin) / peak:.2%} from peak {peak:.2f} >= {max_dd:.2%}"
        )
    return state
