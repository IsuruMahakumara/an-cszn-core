"""
COMPARTMENT: klines
ROLE:        production 1h close cache — no trading, no demo host
IN:          BACKTEST_FAPI + frozen universe
OUT:         (asset closes DataFrame, Bitcoin close Series)

Simons: one tape, frozen names. Refetch only when BACKTEST_REFRESH=1.
"""

from __future__ import annotations

import time

import pandas as pd
import requests

import config

# Binance kline cap per call. Paginate with startTime; never pull demo-fapi.
_LIMIT = 1500


def _fetch_symbol(session: requests.Session, symbol: str, start_ms: int, end_ms: int) -> pd.Series:
    # IN: one perp → OUT: close series indexed by open time (ms)
    times: list[int] = []
    closes: list[float] = []
    cursor = start_ms
    while cursor < end_ms:
        r = session.get(
            f"{config.BACKTEST_FAPI}/fapi/v1/klines",
            params={
                "symbol": symbol,
                "interval": config.INTERVAL,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": _LIMIT,
            },
            timeout=30,
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        for row in rows:
            times.append(int(row[0]))
            closes.append(float(row[4]))
        # Next page starts after the last open we already have.
        cursor = int(rows[-1][0]) + 1
        if len(rows) < _LIMIT:
            break
    if not times:
        raise RuntimeError(f"no klines for {symbol} on {config.BACKTEST_FAPI}")
    s = pd.Series(closes, index=times, name=symbol)
    return s[~s.index.duplicated(keep="last")]


def _download_panel() -> pd.DataFrame:
    # IN: config universe → OUT: wide close matrix (inner-joined timestamps)
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - config.BACKTEST_DAYS * 24 * 60 * 60 * 1000
    names = list(config.UNIVERSE) + [config.BENCHMARK]
    session = requests.Session()
    cols = []
    for i, sym in enumerate(names):
        print(f"klines fetch {i + 1}/{len(names)} {sym}")
        # Public klines; no API key. Demo host is never used here.
        cols.append(_fetch_symbol(session, sym, start_ms, end_ms))
    # Inner join: a bar exists only if every frozen name printed a close.
    panel = pd.concat(cols, axis=1).sort_index().dropna()
    if panel.empty:
        raise RuntimeError("empty panel after align")
    return panel


def load_panel() -> tuple[pd.DataFrame, pd.Series]:
    # IN: cache path or refresh flag → OUT: (asset closes, btc closes)
    path = config.BACKTEST_DATA
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not config.BACKTEST_REFRESH:
        panel = pd.read_csv(path, index_col=0)
        panel.index = panel.index.astype(int)
        print(f"klines cache {path} bars={len(panel)}")
    else:
        panel = _download_panel()
        panel.to_csv(path)
        print(f"klines wrote {path} bars={len(panel)}")
    if config.BENCHMARK not in panel.columns:
        raise RuntimeError(f"cache missing {config.BENCHMARK}")
    missing = [s for s in config.UNIVERSE if s not in panel.columns]
    if missing:
        raise RuntimeError(f"cache missing names {missing}")
    btc = panel[config.BENCHMARK]
    assets = panel.drop(columns=[config.BENCHMARK])
    return assets, btc
