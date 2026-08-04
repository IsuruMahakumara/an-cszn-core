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
    # TRADING linear pairs only — USDT- and USDC-quoted both allowed
    out: dict[str, tuple[float, float]] = {}
    for s in get("/fapi/v1/exchangeInfo")["symbols"]:
        if s["status"] != "TRADING":
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
    # pull one extra bar so we can drop a still-open candle
    raw = get(
        "/fapi/v1/klines",
        {
            "symbol": symbol,
            "interval": kline_interval,
            "limit": feature_bar_count + 1,
        },
    )
    now = int(time.time() * 1000)
    # k[6] = closeTime; keep only closed bars
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


# --- positions + trail insurance ---

def open_positions() -> dict[str, float]:
    """Signed snapshot: symbol → positionAmt (signed; +long / -short)."""
    # private account path — must sign
    rows = get("/fapi/v2/positionRisk", signed=True)
    out: dict[str, float] = {}
    for r in rows:
        # zero means flat on that contract
        qty = float(r.get("positionAmt") or 0)
        if abs(qty) < 1e-12:
            continue
        out[r["symbol"]] = qty
    return out


def open_algo_symbols() -> set[str]:
    """
    Symbols that already have a live conditional/algo order.
    v1: any open algo on the symbol counts as protected.
    """
    # private — signed; works after Dec 2025 algo migration
    rows = get("/fapi/v1/openAlgoOrders", signed=True)
    if not isinstance(rows, list):
        # some errors surface as dict; treat as empty so insurance may re-place
        return set()
    out: set[str] = set()
    for r in rows:
        sym = r.get("symbol")
        if sym:
            out.add(sym)
    return out


def has_position(symbol: str, positions: dict[str, float]) -> bool:
    # true if we already hold size on this symbol
    return abs(positions.get(symbol, 0.0)) > 1e-12


def is_protected(symbol: str, algo_symbols: set[str]) -> bool:
    # true if an open algo (e.g. trailing stop) exists for symbol
    return symbol in algo_symbols


def ensure_trail(
    symbol: str,
    qty: float,
    *,
    trail_callback_rate_pct: float,
    steps: dict[str, tuple[float, float]] | None = None,
) -> str:
    """
    Place TRAILING_STOP_MARKET for an existing position.
    qty signed: +long → SELL trail; -short → BUY trail.
    Returns stop side string.
    """
    if abs(qty) < 1e-12:
        raise RuntimeError(f"{symbol}: no size for trail")
    # exit side opposite to position
    stop_side = "SELL" if qty > 0 else "BUY"
    # use absolute size; floor to LOT_SIZE when steps available
    raw_qty = abs(qty)
    if steps and symbol in steps:
        qty_step, _ = steps[symbol]
        raw_qty = round_down(raw_qty, qty_step)
        if raw_qty < qty_step:
            raise RuntimeError(f"{symbol}: trail qty below step")
        qty_s = as_str(raw_qty, qty_step)
    else:
        # fall back to exchange string (already from fill / positionRisk)
        qty_s = f"{raw_qty:.8f}".rstrip("0").rstrip(".")
    # exchange trails callbackRate % behind mark extremes
    post(
        "/fapi/v1/algoOrder",
        {
            "algoType": "CONDITIONAL",
            "symbol": symbol,
            "side": stop_side,
            "type": "TRAILING_STOP_MARKET",
            "callbackRate": f"{trail_callback_rate_pct:.1f}",
            "quantity": qty_s,
            "workingType": "MARK_PRICE",
        },
    )
    return stop_side


def open_with_trail(
    symbol: str,
    side_str: str,
    qty_str: str,
    *,
    leverage: int,
    trail_callback_rate_pct: float,
) -> tuple[str, str]:
    # force leverage (account setting; not used for trail width math)
    post("/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})
    # market entry
    order = post("/fapi/v1/order", {
        "symbol": symbol,
        "side": side_str,
        "type": "MARKET",
        "quantity": qty_str,
        "newOrderRespType": "RESULT",
    })
    # filled size anchors the trail qty
    filled = order.get("executedQty") or qty_str
    # signed qty for ensure_trail: long positive, short negative
    signed_qty = float(filled) if side_str == "BUY" else -float(filled)
    try:
        # dual-place: trail immediately after entry
        stop_side = ensure_trail(
            symbol,
            signed_qty,
            trail_callback_rate_pct=trail_callback_rate_pct,
        )
    except Exception:
        # trail failed → flatten so we are not naked
        stop_side = "SELL" if side_str == "BUY" else "BUY"
        post("/fapi/v1/order", {
            "symbol": symbol,
            "side": stop_side,
            "type": "MARKET",
            "quantity": filled,
            "newOrderRespType": "RESULT",
        })
        raise
    return str(filled), stop_side
