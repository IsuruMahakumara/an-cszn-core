"""
COMPARTMENT: refresh_universe
ROLE:        screen snapshots — not the poll loop, not order filters
IN:          prod + demo public (and optional signed) REST
OUT:         var/universe_prod.csv
             var/universe_demo.csv
             cszn_trader/universe.csv   (--apply only)

Screen liquidity on PROD. Check demo only for "can we send this symbol?".
minNotional / step for live orders still come from exchangeInfo at send time.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

# Live package sits one directory up (config).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

# Snapshots under var/; frozen list next to config.py.
PROD_CSV = config.VAR_DIR / "universe_prod.csv"
DEMO_CSV = config.VAR_DIR / "universe_demo.csv"
FROZEN_CSV = config.UNIVERSE_CSV

# Snapshot columns: filters are informational; runtime still uses exchangeInfo.
_FIELDS = [
    "symbol",
    "status",
    "quote_asset",
    "step_size",
    "min_notional",
    "max_leverage",
    "quote_volume_24h",
    "screened_at",
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get(session: requests.Session, base: str, path: str, params: dict | None = None) -> Any:
    # IN: host + path → OUT: JSON
    r = session.get(f"{base.rstrip('/')}{path}", params=params or {}, timeout=60)
    r.raise_for_status()
    return r.json()


def _get_signed(
    session: requests.Session, base: str, path: str, params: dict | None = None
) -> Any:
    # IN: signed GET → OUT: JSON (leverage brackets)
    params = dict(params or {})
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    q = urlencode(params)
    params["signature"] = hmac.new(
        config.SECRET_KEY.encode(), q.encode(), hashlib.sha256
    ).hexdigest()
    r = session.get(
        f"{base.rstrip('/')}{path}",
        params=params,
        headers={"X-MBX-APIKEY": config.API_KEY},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def _parse_filters(sym_row: dict) -> tuple[float, float]:
    # IN: exchangeInfo symbol blob → OUT: (stepSize, minNotional)
    step, min_n = 0.001, float(config.MIN_NOTIONAL)
    for f in sym_row.get("filters") or []:
        if f.get("filterType") == "LOT_SIZE":
            step = float(f["stepSize"])
        if f.get("filterType") in ("MIN_NOTIONAL", "NOTIONAL"):
            min_n = float(f.get("notional") or f.get("minNotional") or min_n)
    return step, min_n


def _volume_map(session: requests.Session, base: str) -> dict[str, float]:
    # IN: host → OUT: {symbol: quoteVolume}
    rows = _get(session, base, "/fapi/v1/ticker/24hr")
    out: dict[str, float] = {}
    for r in rows:
        out[r["symbol"]] = float(r.get("quoteVolume") or 0.0)
    return out


def _leverage_map(session: requests.Session, base: str) -> dict[str, float]:
    # IN: host → OUT: {symbol: max initial leverage}
    if not config.API_KEY or not config.SECRET_KEY:
        return {}
    try:
        rows = _get_signed(session, base, "/fapi/v1/leverageBracket")
    except Exception as e:
        print(f"leverageBracket skip on {base}: {e}")
        return {}
    out: dict[str, float] = {}
    for r in rows:
        brackets = r.get("brackets") or []
        if not brackets:
            continue
        # Highest leverage the venue allows on the top bracket.
        out[r["symbol"]] = max(float(b.get("initialLeverage") or 0.0) for b in brackets)
    return out


def _snapshot(session: requests.Session, base: str, label: str) -> list[dict]:
    # IN: one fapi host → OUT: rows for CSV
    print(f"screen {label} exchangeInfo {base}")
    info = _get(session, base, "/fapi/v1/exchangeInfo")
    print(f"screen {label} ticker/24hr")
    vol = _volume_map(session, base)
    print(f"screen {label} leverageBracket")
    lev = _leverage_map(session, base)
    ts = _now()
    rows: list[dict] = []
    for s in info.get("symbols") or []:
        # USDT-M perps only; skip delivery and non-USDT quotes.
        if s.get("contractType") and s.get("contractType") != "PERPETUAL":
            continue
        if s.get("quoteAsset") != "USDT":
            continue
        sym = s["symbol"]
        step, min_n = _parse_filters(s)
        rows.append(
            {
                "symbol": sym,
                "status": s.get("status") or "",
                "quote_asset": s.get("quoteAsset") or "USDT",
                "step_size": f"{step:.10f}".rstrip("0").rstrip(".") or "0",
                "min_notional": f"{min_n:.8f}".rstrip("0").rstrip(".") or "0",
                "max_leverage": lev.get(sym, 0.0),
                "quote_volume_24h": vol.get(sym, 0.0),
                "screened_at": ts,
            }
        )
    rows.sort(key=lambda r: float(r["quote_volume_24h"]), reverse=True)
    return rows


def _write_csv(path: Path, rows: list[dict]) -> None:
    # IN: rows → OUT: CSV on disk
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"wrote {path} n={len(rows)}")


def _apply_frozen(prod: list[dict], demo: list[dict], top_n: int) -> None:
    # IN: snapshots → OUT: frozen universe.csv (explicit membership bump)
    # Prod ranks by liquidity. Demo only gates "tradeable on sandbox".
    demo_ok = {r["symbol"] for r in demo if r.get("status") == "TRADING"}
    need_lev = float(config.EXCHANGE_LEVERAGE)
    picked: list[dict] = []
    for r in prod:
        sym = r["symbol"]
        if sym == config.BENCHMARK:
            continue
        if r.get("status") != "TRADING":
            continue
        if sym not in demo_ok:
            continue
        max_lev = float(r.get("max_leverage") or 0.0)
        # Unknown leverage (0) is allowed; known-too-low is dropped.
        if max_lev > 0 and max_lev + 1e-9 < need_lev:
            continue
        picked.append(r)
        if len(picked) >= top_n:
            break

    ts = _now()
    frozen_fields = [
        "symbol",
        "enabled",
        "quote_volume_24h",
        "max_leverage",
        "demo_ok",
        "screened_at",
    ]
    FROZEN_CSV.parent.mkdir(parents=True, exist_ok=True)
    with FROZEN_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=frozen_fields)
        w.writeheader()
        for r in picked:
            w.writerow(
                {
                    "symbol": r["symbol"],
                    "enabled": "1",
                    "quote_volume_24h": r["quote_volume_24h"],
                    "max_leverage": r["max_leverage"],
                    "demo_ok": "1",
                    "screened_at": ts,
                }
            )
    print(f"APPLY wrote {FROZEN_CSV} enabled={len(picked)} top_n={top_n}")
    print("freeze note: refresh klines (BACKTEST_REFRESH=1) before scoring a new universe")


def main() -> None:
    p = argparse.ArgumentParser(description="CSZN universe screen (prod liquidity, demo gate)")
    # Default: refresh snapshots only. Membership changes need an explicit flag.
    p.add_argument(
        "--apply",
        action="store_true",
        help=f"rewrite {FROZEN_CSV.name} from prod∩demo top-N (not the poll loop)",
    )
    p.add_argument(
        "--top",
        type=int,
        default=config.UNIVERSE_TOP_N,
        help="how many names to enable on --apply",
    )
    args = p.parse_args()

    session = requests.Session()
    prod_base = config.BACKTEST_FAPI
    demo_base = config.FAPI_BASE

    prod_rows = _snapshot(session, prod_base, "prod")
    _write_csv(PROD_CSV, prod_rows)

    demo_rows = _snapshot(session, demo_base, "demo")
    _write_csv(DEMO_CSV, demo_rows)

    # Human preview: top prod names and whether demo lists them.
    demo_set = {r["symbol"] for r in demo_rows if r.get("status") == "TRADING"}
    print("top prod by quote_volume_24h (demo_ok):")
    for r in prod_rows[:15]:
        if r["symbol"] == config.BENCHMARK:
            continue
        ok = "Y" if r["symbol"] in demo_set else "N"
        print(f"  {r['symbol']:16} vol={float(r['quote_volume_24h']):.0f}  demo={ok}")

    if args.apply:
        _apply_frozen(prod_rows, demo_rows, args.top)
    else:
        print("snapshots only — pass --apply to rewrite frozen universe.csv")


if __name__ == "__main__":
    main()
