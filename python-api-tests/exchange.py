"""Binance Futures demo REST: market data + orders.

Call configure(...) once from the runner before any get/post.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import time

import requests

from features import Bars

# set by configure()
_API_KEY = ""
_API_SECRET = ""
_BASE_URL = ""


def configure(*, api_key: str, api_secret: str, base_url: str) -> None:
    global _API_KEY, _API_SECRET, _BASE_URL
    _API_KEY = api_key
    _API_SECRET = api_secret
    _BASE_URL = base_url.rstrip("/")


def sign(params: dict) -> dict:
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    query = "&".join(f"{k}={v}" for k, v in params.items())
    params["signature"] = hmac.new(
        _API_SECRET.encode(), query.encode(), hashlib.sha256
    ).hexdigest()
    return params


def get(path: str, params: dict | None = None, *, signed: bool = False):
    # public market data: signed=False; account/positions: signed=True
    params = sign(params or {}) if signed else (params or {})
    r = requests.get(
        _BASE_URL + path,
        params=params,
        headers={"X-MBX-APIKEY": _API_KEY},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and isinstance(data.get("code"), int) and data["code"] < 0:
        raise RuntimeError(data)
    return data


def post(path: str, params: dict):
    r = requests.post(
        _BASE_URL + path,
        params=sign(params),
        headers={"X-MBX-APIKEY": _API_KEY},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and isinstance(data.get("code"), int) and data["code"] < 0:
        raise RuntimeError(data)
    return data


def round_down(value: float, step: float) -> float:
    return math.floor(value / step + 1e-12) * step


def as_str(value: float, step: float) -> str:
    if step >= 1:
        return str(int(value))
    decimals = max(0, -int(math.floor(math.log10(step))))
    return f"{value:.{decimals}f}"


def err_text(e) -> object:
    return e.response.text if getattr(e, "response", None) is not None else e


def load_steps() -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for s in get("/fapi/v1/exchangeInfo")["symbols"]:
        if s["status"] != "TRADING" or not s["symbol"].endswith("USDT"):
            continue
        qty_step = price_tick = None
        for f in s["filters"]:
            if f["filterType"] == "LOT_SIZE":
                qty_step = float(f["stepSize"])
            if f["filterType"] == "PRICE_FILTER":
                price_tick = float(f["tickSize"])
        if qty_step and price_tick:
            out[s["symbol"]] = (qty_step, price_tick)
    return out


def load_percent_bands() -> dict[str, tuple[float, float]]:
    """
    symbol → (buy_mult, sell_mult) for aggressive flatten inside PERCENT_PRICE.
    BUY limit ≤ mark * buy_mult; SELL limit ≥ mark * sell_mult.
    """
    out: dict[str, tuple[float, float]] = {}
    for s in get("/fapi/v1/exchangeInfo")["symbols"]:
        if s["status"] != "TRADING":
            continue
        buy_m = sell_m = None
        for f in s["filters"]:
            if f["filterType"] == "PERCENT_PRICE_BY_SIDE":
                buy_m = float(f["askMultiplierUp"])
                sell_m = float(f["bidMultiplierDown"])
            elif f["filterType"] == "PERCENT_PRICE" and buy_m is None:
                buy_m = float(f["multiplierUp"])
                sell_m = float(f["multiplierDown"])
        if buy_m and sell_m:
            out[s["symbol"]] = (buy_m, sell_m)
    return out


def mark_price(symbol: str) -> float:
    return float(get("/fapi/v1/premiumIndex", {"symbol": symbol})["markPrice"])


def fetch_bars(symbol: str, *, kline_interval: str, feature_bar_count: int) -> Bars:
    raw = get(
        "/fapi/v1/klines",
        {
            "symbol": symbol,
            "interval": kline_interval,
            "limit": feature_bar_count + 1,
        },
    )
    now = int(time.time() * 1000)
    rows = [k for k in raw if int(k[6]) <= now]
    rows = rows[-feature_bar_count:]
    if len(rows) < feature_bar_count:
        raise RuntimeError(f"need {feature_bar_count} closed bars, got {len(rows)}")
    return Bars(
        o=[float(k[1]) for k in rows],
        h=[float(k[2]) for k in rows],
        l=[float(k[3]) for k in rows],
        c=[float(k[4]) for k in rows],
        v=[float(k[5]) for k in rows],
    )


def open_with_trail(
    symbol: str,
    side_str: str,
    qty_str: str,
    *,
    leverage: int,
    trail_callback_rate_pct: float,
) -> tuple[str, str]:
    post("/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})
    order = post("/fapi/v1/order", {
        "symbol": symbol,
        "side": side_str,
        "type": "MARKET",
        "quantity": qty_str,
        "newOrderRespType": "RESULT",
    })
    filled = order.get("executedQty") or qty_str
    stop_side = "SELL" if side_str == "BUY" else "BUY"
    try:
        post("/fapi/v1/algoOrder", {
            "algoType": "CONDITIONAL",
            "symbol": symbol,
            "side": stop_side,
            "type": "TRAILING_STOP_MARKET",
            "callbackRate": f"{trail_callback_rate_pct:.1f}",
            "quantity": filled,
            "workingType": "MARK_PRICE",
        })
    except Exception:
        post("/fapi/v1/order", {
            "symbol": symbol,
            "side": stop_side,
            "type": "MARKET",
            "quantity": filled,
            "newOrderRespType": "RESULT",
        })
        raise
    return str(filled), stop_side
