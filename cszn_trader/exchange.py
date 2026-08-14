"""
COMPARTMENT: exchange
ROLE:        Binance demo Hypertext Transfer Protocol adapter
IN:          config credentials + method args
OUT:         candles, marks, balances, positions, order responses
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from urllib.parse import urlencode

import requests

import config


class Client:
    def __init__(self) -> None:
        self.base = config.FAPI_BASE.rstrip("/")
        self.mkt = config.MARKET_BASE.rstrip("/")
        self.secret = config.SECRET_KEY
        self.s = requests.Session()
        self.s.headers["X-MBX-APIKEY"] = config.API_KEY
        self._filters: dict[str, dict[str, float]] | None = None
        self.hedge_mode: bool | None = None

    def _req(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        signed: bool = False,
        base: str | None = None,
    ) -> Any:
        # IN: verb + path → OUT: JSON (or raise)
        host = (base or self.base).rstrip("/")
        params = dict(params or {})
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = 5000
            q = urlencode(params)
            params["signature"] = hmac.new(
                self.secret.encode(), q.encode(), hashlib.sha256
            ).hexdigest()
        r = self.s.request(method, f"{host}{path}", params=params, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} {r.status_code}: {r.text}")
        return r.json()

    def klines(self, symbol: str, interval: str, limit: int) -> list:
        return self._req(
            "GET",
            "/fapi/v1/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
            base=self.mkt,
        )

    def mark(self, symbol: str) -> float:
        d = self._req("GET", "/fapi/v1/premiumIndex", {"symbol": symbol}, base=self.mkt)
        return float(d["markPrice"])

    def filters(self, symbol: str) -> dict[str, float]:
        # IN: symbol → OUT: {stepSize, minNotional} (cached exchangeInfo)
        if self._filters is None:
            info = self._req("GET", "/fapi/v1/exchangeInfo", base=self.mkt)
            out: dict[str, dict[str, float]] = {}
            for s in info["symbols"]:
                step, min_n = 0.001, config.MIN_NOTIONAL
                for f in s["filters"]:
                    if f["filterType"] == "LOT_SIZE":
                        step = float(f["stepSize"])
                    if f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
                        min_n = float(f.get("notional") or f.get("minNotional") or min_n)
                out[s["symbol"]] = {"stepSize": step, "minNotional": min_n}
            self._filters = out
        return self._filters.get(
            symbol, {"stepSize": 0.001, "minNotional": config.MIN_NOTIONAL}
        )

    def account(self) -> dict:
        return self._req("GET", "/fapi/v2/account", signed=True)

    def balances(self) -> tuple[float, float]:
        # IN: — → OUT: (margin, available) from one snapshot
        a = self.account()
        margin = 0.0
        for key in ("totalMarginBalance", "totalWalletBalance"):
            if a.get(key) is not None:
                margin = float(a[key])
                break
        return margin, float(a.get("availableBalance") or 0.0)

    def margin_balance(self) -> float:
        return self.balances()[0]

    def position_book(self) -> dict[str, dict[str, float]]:
        # IN: — → OUT: {symbol: qty, entry, mark, upnl}
        out: dict[str, dict[str, float]] = {}
        for p in self._req("GET", "/fapi/v2/positionRisk", signed=True):
            amt = float(p.get("positionAmt", 0.0))
            if abs(amt) < 1e-12:
                continue
            sym = p["symbol"]
            row = {
                "qty": amt,
                "entry": float(p.get("entryPrice") or 0.0),
                "mark": float(p.get("markPrice") or 0.0),
                "upnl": float(p.get("unRealizedProfit") or 0.0),
            }
            if sym not in out:
                out[sym] = row
                continue
            # Hedge dual-side: net qty, size-weighted entry, summed pnl.
            prev = out[sym]
            tot = prev["qty"] + amt
            notion = abs(prev["qty"]) * prev["entry"] + abs(amt) * row["entry"]
            out[sym] = {
                "qty": tot,
                "entry": notion / max(abs(tot), 1e-12),
                "mark": row["mark"],
                "upnl": prev["upnl"] + row["upnl"],
            }
        return out

    def detect_hedge_mode(self) -> bool:
        try:
            d = self._req("GET", "/fapi/v1/positionSide/dual", signed=True)
            self.hedge_mode = bool(d.get("dualSidePosition"))
        except Exception:
            self.hedge_mode = False
        return bool(self.hedge_mode)

    def set_leverage(self, symbol: str, lev: int) -> Any:
        return self._req(
            "POST",
            "/fapi/v1/leverage",
            {"symbol": symbol, "leverage": int(lev)},
            signed=True,
        )

    def market(self, symbol: str, side: str, qty: float, reduce_only: bool = False) -> Any:
        q = f"{qty:.8f}".rstrip("0").rstrip(".")
        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": q,
        }
        if self.hedge_mode:
            params["positionSide"] = "LONG" if side == "BUY" else "SHORT"
        elif reduce_only:
            params["reduceOnly"] = "true"
        return self._req("POST", "/fapi/v1/order", params, signed=True)

    def income_since(self, start_ms: int) -> dict[str, float]:
        # IN: start time → OUT: {incomeType: sum}
        end = int(time.time() * 1000)
        totals: dict[str, float] = {}
        cursor = start_ms
        while cursor < end:
            batch = self._req(
                "GET",
                "/fapi/v1/income",
                {"startTime": cursor, "endTime": end, "limit": 1000},
                signed=True,
            )
            if not batch:
                break
            for x in batch:
                t = x.get("incomeType") or "?"
                totals[t] = totals.get(t, 0.0) + float(x.get("income") or 0.0)
            last_t = int(batch[-1]["time"])
            if last_t <= cursor:
                break
            cursor = last_t + 1
            if len(batch) < 1000:
                break
        return totals
