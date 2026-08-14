"""
COMPARTMENT: sync_ledger
ROLE:        standalone income tape — not the poll loop, not strategy
IN:          demo signed GET /fapi/v1/income + account
OUT:         append-only data/income_ledger.csv + printed totals

Rerun: only new venue rows are appended (tran_id / fingerprint).
Existing CSV lines are never rewritten or deleted.
"""

from __future__ import annotations

import csv
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import config
from exchange import Client

# Frozen path. Gitignored — account P&L stays local.
LEDGER = Path(__file__).resolve().parent / "data" / "income_ledger.csv"
# First run pulls this many days; later runs start at last csv time.
LOOKBACK_DAYS = 30
# Venue types we keep. Other income types are ignored.
KEEP = {"REALIZED_PNL", "COMMISSION", "FUNDING_FEE"}
FIELDS = [
    "time_utc",
    "time_ms",
    "tran_id",
    "trade_id",
    "symbol",
    "income_type",
    "income",
    "asset",
]


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _fp(row: dict) -> str:
    # IN: venue or csv row → OUT: stable id so reruns do not double-append
    tid = str(row.get("tran_id") or row.get("tranId") or "").strip()
    if tid and tid != "0":
        return f"tran:{tid}"
    return "|".join(
        [
            str(row.get("time_ms") or row.get("time") or ""),
            str(row.get("income_type") or row.get("incomeType") or ""),
            str(row.get("symbol") or ""),
            str(row.get("income") or ""),
            str(row.get("trade_id") or row.get("tradeId") or ""),
        ]
    )


def _load_seen(path: Path) -> tuple[set[str], int]:
    # IN: existing ledger → OUT: (fingerprints, last time_ms)
    if not path.exists():
        return set(), 0
    seen: set[str] = set()
    last = 0
    with path.open() as f:
        for row in csv.DictReader(f):
            seen.add(_fp(row))
            last = max(last, int(float(row.get("time_ms") or 0)))
    return seen, last


def _pull(client: Client, start_ms: int, end_ms: int) -> list[dict]:
    # IN: window → OUT: raw income rows (paginated)
    out: list[dict] = []
    cursor = start_ms
    while cursor < end_ms:
        batch = client._req(
            "GET",
            "/fapi/v1/income",
            {"startTime": cursor, "endTime": end_ms, "limit": 1000},
            signed=True,
        )
        if not batch:
            break
        out.extend(batch)
        last_t = int(batch[-1]["time"])
        if last_t <= cursor:
            break
        cursor = last_t + 1
        if len(batch) < 1000:
            break
    return out


def _append(path: Path, rows: list[dict]) -> None:
    # IN: new rows → OUT: bytes appended (header once)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def _sum_ledger(path: Path) -> dict[str, float]:
    # IN: csv → OUT: sums by income_type (full tape, not just this run)
    tot: dict[str, float] = defaultdict(float)
    if not path.exists():
        return tot
    with path.open() as f:
        for row in csv.DictReader(f):
            tot[row.get("income_type") or "?"] += float(row.get("income") or 0.0)
    return tot


def main() -> None:
    if not config.API_KEY or not config.SECRET_KEY:
        raise SystemExit("missing API_KEY/SECRET_KEY in .env")
    client = Client()
    end_ms = int(time.time() * 1000)
    seen, last_ms = _load_seen(LEDGER)
    # Overlap one minute so late-arriving venue rows are not missed; fingerprints drop dupes.
    if last_ms > 0:
        start_ms = max(0, last_ms - 60_000)
    else:
        start_ms = end_ms - LOOKBACK_DAYS * 24 * 60 * 60 * 1000

    print(f"ledger {LEDGER}")
    print(f"venue  {client.base}")
    print(f"fetch  {_iso(start_ms)} -> {_iso(end_ms)}  seen={len(seen)}")

    raw = _pull(client, start_ms, end_ms)
    new_rows: list[dict] = []
    for x in raw:
        kind = x.get("incomeType") or ""
        if kind not in KEEP:
            continue
        rec = {
            "time_utc": _iso(int(x["time"])),
            "time_ms": str(int(x["time"])),
            "tran_id": str(x.get("tranId") or ""),
            "trade_id": str(x.get("tradeId") or ""),
            "symbol": x.get("symbol") or "",
            "income_type": kind,
            "income": f"{float(x.get('income') or 0.0):.8f}",
            "asset": x.get("asset") or "USDT",
        }
        if _fp(rec) in seen:
            continue
        seen.add(_fp(rec))
        new_rows.append(rec)
    # Keep append order chronological.
    new_rows.sort(key=lambda r: int(r["time_ms"]))
    _append(LEDGER, new_rows)
    print(f"appended {len(new_rows)}  skipped_dupes={len(raw) - len(new_rows)}")

    tot = _sum_ledger(LEDGER)
    rp = tot.get("REALIZED_PNL", 0.0)
    cm = tot.get("COMMISSION", 0.0)
    fu = tot.get("FUNDING_FEE", 0.0)
    margin = client.margin_balance()
    print(
        f"ledger_all  realized={rp:.8f}  commission={cm:.8f}  funding={fu:.8f}  "
        f"net={rp + cm + fu:.8f}"
    )
    print(f"account     margin_balance={margin:.8f}  (includes unrealized; not equal to ledger net)")


if __name__ == "__main__":
    main()
