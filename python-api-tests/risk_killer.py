#!/usr/bin/env python3
"""
Portfolio risk kill switch (REST only — no user WebSocket).

Every POLL_SEC: GET positionRisk → if unrealized PnL ≤ -MAX_LOSS_USD → flatten.
Stdout: heartbeat every HEARTBEAT_SEC + kill/error events only (no spam).

  source python-api-tests/.venv/bin/activate
  python python-api-tests/risk_killer.py

Run alongside bar_signal_demo.py. This process never opens new risk.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone

import exchange
from exchange import (
    as_str,
    get,
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

# kill when unrealized PnL (quote USDT/USDC) is this bad or worse
MAX_LOSS_USD = 2.0

# positionRisk ~weight 5; 10s is fine under IP budgets
POLL_SEC = 10
# quiet heartbeat so you can see the process is alive
HEARTBEAT_SEC = 60
# don't spam flatten on the same symbol
KILL_COOLDOWN_SEC = 30
# refresh LOT_SIZE / percent bands (new listings, USDC pairs)
FILTER_REFRESH_SEC = 300

# symbols → last kill attempt time
_last_kill: dict[str, float] = {}


def log(level: str, msg: str) -> None:
    # always timestamped UTC so terminal scrolls make sense
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    # errors also guaranteed on stderr for pipes / redirection
    if level == "ERROR":
        print(line, file=sys.stderr, flush=True)


def ensure_filters(
    symbol: str,
    steps: dict,
    bands: dict,
) -> tuple[float, float] | None:
    """
    Return (qty_step, tick) for symbol.
    Reload exchangeInfo once if missing (stale cache / USDC listings).
    """
    if symbol in steps:
        return steps[symbol]

    # one reload then lookup again
    log("WARN", f"filters miss {symbol} — reloading exchangeInfo")
    steps.clear()
    steps.update(load_steps())
    bands.clear()
    bands.update(load_percent_bands())
    return steps.get(symbol)


def flatten(symbol: str, qty: float, steps: dict, bands: dict) -> str:
    """
    Close position ASAP.
    1) MARKET reduceOnly
    2) on -4131: LIMIT IOC at PERCENT_PRICE band edge
    Returns a short how-closed tag for the kill summary log.
    """
    if abs(qty) < 1e-12:
        return "skip_flat"

    # long → SELL to exit; short → BUY to exit
    side = "SELL" if qty > 0 else "BUY"

    # need LOT_SIZE (+ tick for IOC fallback)
    filt = ensure_filters(symbol, steps, bands)
    if not filt:
        # last resort: send absolute size as string
        qty_s = f"{abs(qty):.8f}".rstrip("0").rstrip(".")
        log("WARN", f"no filters for {symbol} — raw MARKET qty={qty_s}")
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
        return f"MARKET raw {side} qty={qty_s}"

    qty_step, tick = filt
    q = round_down(abs(qty), qty_step)
    if q < qty_step:
        return "skip_dust"
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
        return f"MARKET {side} qty={qty_s}"
    except Exception as e:
        body = str(getattr(e, "response", None) and e.response.text or e)
        if "-4131" not in body and "PERCENT_PRICE" not in body:
            raise
        log("WARN", f"{symbol} market blocked by PERCENT_PRICE — try IOC")

    # aggressive legal limit from mark × percent band
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
    return f"IOC {side} qty={qty_s} px={as_str(px, tick)} mark={mark}"


def maybe_kill(
    symbol: str,
    qty: float,
    up: float,
    steps: dict,
    bands: dict,
    *,
    entry: float,
    mark: float,
    lev: float,
) -> bool:
    """Return True if a kill was attempted this call."""
    # ignore flat
    if abs(qty) < 1e-12:
        return False
    # up = unrealized PnL in quote (USDT or USDC)
    if up > -MAX_LOSS_USD:
        return False
    now = time.monotonic()
    # avoid hammering the same symbol every poll
    if now - _last_kill.get(symbol, 0) < KILL_COOLDOWN_SEC:
        return False

    # LONG if positionAmt > 0 else SHORT
    pos_side = "LONG" if qty > 0 else "SHORT"
    # sustained loss is negative uPnL; print absolute too for skim-reading
    loss_abs = abs(up)

    # explicit trigger line (in addition to quiet [INFO] heartbeats)
    log(
        "KILL",
        f"TRIGGER {symbol} {pos_side} qty={qty} "
        f"sustained_loss={up:+.4f} (abs={loss_abs:.4f}) "
        f"threshold=-{MAX_LOSS_USD} "
        f"entry={entry} mark={mark} lev={lev}x → flatten",
    )
    try:
        how = flatten(symbol, qty, steps, bands)
        _last_kill[symbol] = now
        # success: timestamped summary so terminal clearly shows a kill fired
        log(
            "KILL",
            f"CLOSED {symbol} {pos_side} "
            f"sustained_loss={up:+.4f} threshold=-{MAX_LOSS_USD} "
            f"entry={entry} mark={mark} via {how}",
        )
        return True
    except Exception as e:
        # short cool-down so next poll can retry
        _last_kill[symbol] = now - KILL_COOLDOWN_SEC + 5
        err = e.response.text if getattr(e, "response", None) is not None else e
        log(
            "ERROR",
            f"flatten FAILED {symbol} {pos_side} "
            f"sustained_loss={up:+.4f} threshold=-{MAX_LOSS_USD}: {err}",
        )
        return True


def poll_once(steps: dict, bands: dict) -> dict:
    """
    One REST sweep. Quiet on success — returns a small status dict
    for the periodic heartbeat (not printed every poll).
    """
    # signed account snapshot of all positions
    rows = get("/fapi/v2/positionRisk", signed=True)
    open_n = 0
    total_up = 0.0
    worst_sym = ""
    worst_up = 0.0
    kills = 0

    for r in rows:
        qty = float(r.get("positionAmt") or 0)
        if abs(qty) < 1e-12:
            continue
        up = float(r.get("unRealizedProfit") or 0)
        # entry / mark / lev for kill detail lines
        entry = float(r.get("entryPrice") or 0)
        mark = float(r.get("markPrice") or 0)
        lev = float(r.get("leverage") or 0)
        open_n += 1
        total_up += up
        # track worst open uPnL for heartbeat
        if open_n == 1 or up < worst_up:
            worst_up = up
            worst_sym = r["symbol"]
        if maybe_kill(
            r["symbol"],
            qty,
            up,
            steps,
            bands,
            entry=entry,
            mark=mark,
            lev=lev,
        ):
            kills += 1

    return {
        "open": open_n,
        "total_up": total_up,
        "worst": worst_sym,
        "worst_up": worst_up,
        "kills": kills,
        "ok": True,
    }


def main() -> None:
    exchange.configure(api_key=API_KEY, api_secret=API_SECRET, base_url=FUTURES_BASE_URL)

    # mutable so ensure_filters can refresh in place
    steps = load_steps()
    bands = load_percent_bands()
    last_filter_load = time.monotonic()
    last_heartbeat = 0.0
    polls = 0
    last_status: dict = {"open": 0, "total_up": 0.0, "worst": "", "worst_up": 0.0, "ok": True}

    log(
        "INFO",
        f"start REST killer poll={POLL_SEC}s heartbeat={HEARTBEAT_SEC}s "
        f"max_loss_usd=-{MAX_LOSS_USD} pairs_cached={len(steps)}",
    )

    while True:
        # periodic full filter refresh (new listings / USDC)
        if time.monotonic() - last_filter_load >= FILTER_REFRESH_SEC:
            try:
                steps.clear()
                steps.update(load_steps())
                bands.clear()
                bands.update(load_percent_bands())
                last_filter_load = time.monotonic()
                log("INFO", f"filters refreshed pairs={len(steps)}")
            except Exception as e:
                log("ERROR", f"filter refresh failed: {e}")

        try:
            last_status = poll_once(steps, bands)
            polls += 1
        except Exception as e:
            # 5xx / network — show immediately, then sleep and retry
            err = e.response.text if getattr(e, "response", None) is not None else e
            log("ERROR", f"poll failed: {err}")
            last_status = {**last_status, "ok": False}

        # heartbeat: one line every ~1m so you know it's alive
        now = time.monotonic()
        if now - last_heartbeat >= HEARTBEAT_SEC:
            last_heartbeat = now
            st = last_status
            if st.get("open", 0) == 0:
                log(
                    "INFO",
                    f"ok polls={polls} open=0 max_loss=-{MAX_LOSS_USD} "
                    f"(next poll in {POLL_SEC}s)",
                )
            else:
                log(
                    "INFO",
                    f"ok polls={polls} open={st['open']} "
                    f"sum_up={st['total_up']:+.2f} "
                    f"worst={st['worst']}({st['worst_up']:+.2f}) "
                    f"threshold=-{MAX_LOSS_USD}",
                )

        # rate-limit friendly pause
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
