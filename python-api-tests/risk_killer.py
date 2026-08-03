#!/usr/bin/env python3
"""
Portfolio risk kill switch (separate from the signal bot).

Listens to Binance Futures user stream ACCOUNT_UPDATE.
If a position's ROE drops to -MAX_LOSS_ROE or worse → market flatten.

  source python-api-tests/.venv/bin/activate
  pip install websocket-client requests
  python python-api-tests/risk_killer.py

Run this alongside bar_signal_demo.py. It only exits losers; it never opens trades.
"""

from __future__ import annotations

import json
import threading
import time

import requests
import websocket  # websocket-client package

import exchange
from exchange import (
    as_str,
    load_percent_bands,
    load_steps,
    mark_price,
    post,
    round_down,
)

# --- settings (same demo account as the signal bot) ---

API_KEY = "lghlDGfe8KmFCPhkJk6L6JVmYJVpaazSr2B2YcwZlLymyfTmmWWmayLcJHLtuQZZ"
API_SECRET = "NFlBmBhkB93jrxI7f7TTQpyazYUNw90RKol9lVhap0wr9yxk5Fqj5cOI3LEAnb8J"
FUTURES_BASE_URL = "https://demo-fapi.binance.com"

# User-data WS host. If demo never connects, try:
#   wss://fstream.binancefuture.com/ws
USER_WS_BASE = "wss://fstream.binance.com/ws"

LEVERAGE = 20                 # used to turn USDT uPnL → approx ROE
MAX_LOSS_ROE = 0.10           # kill at ≈ -10% ROE (same idea as trail width)
POLL_BACKUP_SEC = 15          # REST safety net if WS is quiet / drops
KEEPALIVE_SEC = 30 * 60       # refresh listenKey before it expires (~60m)
KILL_COOLDOWN_SEC = 30        # don't spam flatten on the same symbol


# symbols we already tried to kill recently → symbol → monotonic time
_last_kill: dict[str, float] = {}


def listen_key_create() -> str:
    # Futures listenKey: API-key header only (no HMAC body)
    r = requests.post(
        FUTURES_BASE_URL.rstrip("/") + "/fapi/v1/listenKey",
        headers={"X-MBX-APIKEY": API_KEY},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["listenKey"]


def listen_key_ping(key: str) -> None:
    requests.put(
        FUTURES_BASE_URL.rstrip("/") + "/fapi/v1/listenKey",
        headers={"X-MBX-APIKEY": API_KEY},
        params={"listenKey": key},
        timeout=15,
    ).raise_for_status()


def approx_roe(up_usdt: float, qty: float, entry: float) -> float:
    """
    Socket gives unrealized PnL in USDT (`up`), not %.
    ROE ≈ up / initial_margin, initial_margin ≈ notional / leverage.
    """
    notional = abs(qty) * entry
    if notional <= 0:
        return 0.0
    margin = notional / LEVERAGE
    return up_usdt / margin


def flatten(symbol: str, qty: float, steps: dict, bands: dict) -> None:
    """
    Close position ASAP.
    1) MARKET reduceOnly
    2) on -4131 (illiquid / PERCENT_PRICE): LIMIT IOC at the legal mark band edge
       — may still not fill if the book is empty inside the band
    """
    if abs(qty) < 1e-12:
        return
    side = "SELL" if qty > 0 else "BUY"
    qty_step, tick = steps.get(symbol, (None, None))
    if not qty_step or not tick:
        print(f"  cannot flatten {symbol}: unknown filters")
        return
    q = round_down(abs(qty), qty_step)
    if q < qty_step:
        return
    qty_s = as_str(q, qty_step)

    try:
        post(
            "/fapi/v1/order",
            {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": qty_s,
                "reduceOnly": "true",
                "newOrderRespType": "RESULT",
            },
        )
        print(f"  KILL market {symbol} {side} qty={qty_s}")
        return
    except Exception as e:
        body = str(getattr(e, "response", None) and e.response.text or e)
        if "-4131" not in body and "PERCENT_PRICE" not in body:
            raise
        print(f"  market blocked by PERCENT_PRICE — try IOC at band edge")

    # Aggressive but legal limit: sell at mark*sell_mult, buy at mark*buy_mult
    buy_m, sell_m = bands.get(symbol, (1.05, 0.95))
    mark = mark_price(symbol)
    raw = mark * sell_m if side == "SELL" else mark * buy_m
    px = round_down(raw, tick) if side == "SELL" else round_down(raw + tick * 0.999, tick)
    if px <= 0:
        raise RuntimeError(f"bad IOC price for {symbol}")
    post(
        "/fapi/v1/order",
        {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "timeInForce": "IOC",
            "price": as_str(px, tick),
            "quantity": qty_s,
            "reduceOnly": "true",
            "newOrderRespType": "RESULT",
        },
    )
    print(f"  KILL IOC {symbol} {side} qty={qty_s} px={as_str(px, tick)} mark={mark}")


def maybe_kill(symbol: str, qty: float, entry: float, up: float, steps: dict, bands: dict) -> None:
    if abs(qty) < 1e-12:
        return
    roe = approx_roe(up, qty, entry)
    if roe > -MAX_LOSS_ROE:
        return
    now = time.monotonic()
    if now - _last_kill.get(symbol, 0) < KILL_COOLDOWN_SEC:
        return
    print(f"{symbol} ROE={roe:.1%} up={up:.4f} USDT → flatten")
    try:
        flatten(symbol, qty, steps, bands)
        _last_kill[symbol] = now  # cooldown only after an attempt that did not hard-crash
    except Exception as e:
        # allow quick retry on next poll — illiquid books often need several tries
        _last_kill[symbol] = now - KILL_COOLDOWN_SEC + 5
        err = e.response.text if getattr(e, "response", None) is not None else e
        print(f"  flatten failed: {err}")


def on_account_update(msg: dict, steps: dict, bands: dict) -> None:
    positions = msg.get("a", {}).get("P", [])
    for p in positions:
        symbol = p.get("s", "")
        qty = float(p.get("pa") or 0)
        entry = float(p.get("ep") or 0)
        up = float(p.get("up") or 0)
        maybe_kill(symbol, qty, entry, up, steps, bands)


def poll_positions(steps: dict, bands: dict) -> None:
    rows = exchange.get("/fapi/v2/positionRisk", signed=True)
    for r in rows:
        qty = float(r.get("positionAmt") or 0)
        if abs(qty) < 1e-12:
            continue
        entry = float(r.get("entryPrice") or 0)
        up = float(r.get("unRealizedProfit") or 0)
        maybe_kill(r["symbol"], qty, entry, up, steps, bands)


def main() -> None:
    exchange.configure(api_key=API_KEY, api_secret=API_SECRET, base_url=FUTURES_BASE_URL)
    steps = load_steps()
    bands = load_percent_bands()

    key = listen_key_create()
    ws_url = f"{USER_WS_BASE.rstrip('/')}/{key}"
    print(f"risk killer up  max_loss_roe=-{MAX_LOSS_ROE:.0%}  ws={USER_WS_BASE}")

    # keep listenKey alive in the background
    def keepalive():
        while True:
            time.sleep(KEEPALIVE_SEC)
            try:
                listen_key_ping(key)
            except Exception as e:
                print("listenKey ping failed:", e)

    threading.Thread(target=keepalive, daemon=True).start()

    # periodic REST backup
    def backup_poll():
        while True:
            time.sleep(POLL_BACKUP_SEC)
            try:
                poll_positions(steps, bands)
            except Exception as e:
                print("poll failed:", e)

    threading.Thread(target=backup_poll, daemon=True).start()

    def on_message(_ws, raw: str):
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        if msg.get("e") == "ACCOUNT_UPDATE":
            on_account_update(msg, steps, bands)

    def on_error(_ws, err):
        print("ws error:", err)

    def on_close(_ws, status, msg):
        print("ws closed:", status, msg)

    def on_open(_ws):
        print("ws connected — waiting for ACCOUNT_UPDATE")
        try:
            poll_positions(steps, bands)
        except Exception as e:
            print("startup poll failed:", e)

    ws = websocket.WebSocketApp(
        ws_url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    while True:
        ws.run_forever(ping_interval=60, ping_timeout=10)
        print("ws reconnecting in 3s…")
        time.sleep(3)
        try:
            key = listen_key_create()
            ws.url = f"{USER_WS_BASE.rstrip('/')}/{key}"
        except Exception as e:
            print("listenKey refresh failed:", e)


if __name__ == "__main__":
    main()
