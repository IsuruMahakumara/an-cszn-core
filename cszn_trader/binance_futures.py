"""Minimal Binance USDT-M futures REST client (demo + public market data)."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from urllib.parse import urlencode

import requests

import config


class BinanceFutures:
    """Thin HMAC client. No abstractions beyond request + sign."""

    def __init__(
        self,
        api_key: str = config.API_KEY,
        secret: str = config.SECRET_KEY,
        fapi_base: str = config.FAPI_BASE,
        market_base: str = config.MARKET_BASE,
    ) -> None:
        # Trading host (demo account keys)
        self.fapi = fapi_base.rstrip("/")
        # Public kline host (can differ from demo)
        self.market = market_base.rstrip("/")
        self.api_key = api_key
        self.secret = secret
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": api_key})

    def _sign(self, params: dict[str, Any]) -> dict[str, Any]:
        # Millisecond timestamp required on every signed call
        params = dict(params)
        params["timestamp"] = int(time.time() * 1000)
        # Allow modest local/server clock skew
        params.setdefault("recvWindow", config.RECV_WINDOW)
        # Canonical query string before HMAC
        query = urlencode(params, doseq=True)
        # HMAC-SHA256 with secret key
        sig = hmac.new(
            self.secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        params["signature"] = sig
        return params

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        signed: bool = False,
        base: str | None = None,
    ) -> Any:
        # Default host is trading base; market data uses market_base
        host = (base or self.fapi).rstrip("/")
        params = dict(params or {})
        # Attach signature when endpoint is private
        if signed:
            params = self._sign(params)
        url = f"{host}{path}"
        # Single attempt — fail loud; Simons systems log errors, do not invent fills
        r = self.session.request(method, url, params=params, timeout=30)
        # Raise HTTP errors with body for demo debugging
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} {r.status_code}: {r.text}")
        return r.json()

    # ----- public market data -----

    def klines(
        self, symbol: str, interval: str, limit: int
    ) -> list[list[Any]]:
        # Close-time series from public futures API
        return self._request(
            "GET",
            "/fapi/v1/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
            base=self.market,
        )

    def mark_price(self, symbol: str) -> float:
        # Single mark for notional conversion
        data = self._request(
            "GET",
            "/fapi/v1/premiumIndex",
            {"symbol": symbol},
            base=self.market,
        )
        return float(data["markPrice"])

    def exchange_filters(self, symbol: str) -> dict[str, float]:
        # LOT_SIZE step + MIN_NOTIONAL for qty flooring
        info = self._request(
            "GET", "/fapi/v1/exchangeInfo", base=self.market
        )
        for s in info["symbols"]:
            if s["symbol"] != symbol:
                continue
            step = 0.001
            min_notional = config.MIN_NOTIONAL
            for f in s["filters"]:
                if f["filterType"] == "LOT_SIZE":
                    step = float(f["stepSize"])
                if f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
                    min_notional = float(
                        f.get("notional") or f.get("minNotional") or min_notional
                    )
            return {"stepSize": step, "minNotional": min_notional}
        raise KeyError(f"symbol not found: {symbol}")

    # ----- private account / positions / orders -----

    def account(self) -> dict[str, Any]:
        return self._request("GET", "/fapi/v2/account", signed=True)

    def balance_usdt(self) -> float:
        # Wallet equity proxy: available + cross wallet when present
        acct = self.account()
        # totalWalletBalance is standard on v2 account
        if "totalWalletBalance" in acct:
            return float(acct["totalWalletBalance"])
        # Fallback: sum USDT asset balances
        for a in acct.get("assets", []):
            if a.get("asset") == "USDT":
                return float(a.get("walletBalance", 0.0))
        return 0.0

    def positions(self) -> dict[str, float]:
        # Map symbol -> signed position amount (contracts / base qty)
        risk = self._request("GET", "/fapi/v2/positionRisk", signed=True)
        out: dict[str, float] = {}
        for p in risk:
            amt = float(p.get("positionAmt", 0.0))
            if abs(amt) > 0:
                out[p["symbol"]] = amt
        return out

    def set_leverage(self, symbol: str, leverage: int) -> Any:
        # Cap per-symbol futures leverage (risk budget, not signal)
        return self._request(
            "POST",
            "/fapi/v1/leverage",
            {"symbol": symbol, "leverage": leverage},
            signed=True,
        )

    def market_order(
        self, symbol: str, side: str, quantity: float
    ) -> Any:
        # Mechanical market order — side BUY or SELL, one-way positionSide BOTH
        qty_str = _fmt_qty(quantity)
        params = {
            "symbol": symbol,
            "side": side,
            "type": config.ORDER_TYPE,
            "quantity": qty_str,
        }
        return self._request("POST", "/fapi/v1/order", params, signed=True)


def _fmt_qty(q: float) -> str:
    # Avoid scientific notation on the wire
    s = f"{q:.8f}".rstrip("0").rstrip(".")
    return s if s else "0"
