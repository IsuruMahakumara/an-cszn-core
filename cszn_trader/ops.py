"""Session state + JSONL cycle logs (ops grade)."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

import config


def load_state(path: Path = config.STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {
            "weights": {},
            "peak_margin": None,
            "halted": False,
            "halt_reason": None,
            "last_cycle_ts": None,
        }
    with path.open() as f:
        return json.load(f)


def save_state(state: dict[str, Any], path: Path = config.STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    tmp.replace(path)


def weights_from_state(state: dict[str, Any]) -> pd.Series | None:
    w = state.get("weights") or {}
    if not w:
        return None
    return pd.Series({k: float(v) for k, v in w.items()})


def log_cycle(row: dict[str, Any], log_dir: Path = config.LOG_DIR) -> Path:
    # one JSON object per line, file per UTC day
    log_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = log_dir / f"cycles_{day}.jsonl"
    row = dict(row)
    row["ts"] = datetime.now(timezone.utc).isoformat()
    with path.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")
    return path


def update_peak_and_kill(
    state: dict[str, Any], margin: float, max_dd: float = config.MAX_DRAWDOWN_FRAC
) -> dict[str, Any]:
    """Track peak margin; halt if drawdown from peak exceeds max_dd."""
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
