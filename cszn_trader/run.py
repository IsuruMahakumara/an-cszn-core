"""
COMPARTMENT: run
ROLE:        wire the graph — 60s poll / 1m z-rebalance
GRAPH (nodes → edges):
  config ──knobs──► all
  exchange ──closes,marks,balances,pos──► run
  ops ──state,prev_w──► run
  strategy.signal ──w,z,beta──► run
  strategy.risk ──collat,gross,im──► run
  strategy.orders ──order stubs or empty──► run
  run ──market orders only if gates clear──► exchange
  run ──state,logs──► ops
"""

from __future__ import annotations

import math
import time
from datetime import datetime

import pandas as pd

import config
from exchange import Client
from ops import (
    load_state,
    log_cycle,
    save_state,
    update_peak_and_kill,
    weights_from_state,
)
from strategy import (
    collateral_from_margin,
    derived_im,
    gross_notional_budget,
    rebalance_orders,
    stop_flatten_orders,
    target_weights,
)


def log(*args) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}]", *args)


# How many newest 1m candles to fetch when the bar cache is already warm.
_TAIL = 5


def pull_closes(client: Client, cache: dict[str, pd.Series]) -> tuple[pd.DataFrame, pd.Series]:
    # IN: client + per-symbol cache → OUT: (asset closes, Bitcoin closes)
    # Boot: full KLINE_LIMIT. Later ticks: tail merge so demo-fapi is not hammered.
    names = list(config.UNIVERSE) + [config.BENCHMARK]
    want = config.KLINE_LIMIT
    for sym in names:
        if sym not in cache or len(cache[sym]) < want:
            raw = client.klines(sym, config.INTERVAL, want)
            cache[sym] = pd.Series(
                [float(x[4]) for x in raw],
                index=[int(x[0]) for x in raw],
                name=sym,
            )
            continue
        raw = client.klines(sym, config.INTERVAL, _TAIL)
        tail = pd.Series(
            [float(x[4]) for x in raw],
            index=[int(x[0]) for x in raw],
            name=sym,
        )
        s = pd.concat([cache[sym], tail])
        s = s[~s.index.duplicated(keep="last")].sort_index()
        cache[sym] = s.iloc[-want:]
    df = pd.DataFrame({s: cache[s] for s in names}).dropna()
    return df.drop(columns=[config.BENCHMARK]), df[config.BENCHMARK]


def floor_qty(qty: float, step: float) -> float:
    # IN: raw qty → OUT: lot-floored qty
    if step <= 0:
        return qty
    return math.floor(qty / step + 1e-12) * step


def flatten_all(client: Client) -> list[dict]:
    # IN: open positions → OUT: close fills (or dry-run stubs)
    sent = []
    book = client.position_book()
    if not book:
        log("flatten: already flat")
        return sent
    for sym, row in book.items():
        amt = float(row["qty"])
        side = "SELL" if amt > 0 else "BUY"
        qty = floor_qty(abs(amt), client.filters(sym)["stepSize"])
        if qty <= 0:
            continue
        if config.DRY_RUN:
            log("flatten DRY_RUN", side, sym, qty)
            sent.append({"symbol": sym, "side": side, "qty": qty, "dry_run": True})
            continue
        try:
            resp = client.market(sym, side, qty, reduce_only=not client.hedge_mode)
            log("FLATTEN", side, sym, qty, resp.get("orderId"))
            sent.append(
                {"symbol": sym, "side": side, "qty": qty, "orderId": resp.get("orderId")}
            )
        except Exception as e:
            log("FLATTEN FAIL", sym, e)
    return sent


def execute_orders(
    client: Client,
    orders: list[dict],
    pos: dict,
    collat: float,
    avail: float,
    im: float,
) -> list[dict]:
    # IN: stubs → OUT: sent fills; mutates pos
    sent: list[dict] = []
    if not orders or config.DRY_RUN:
        if orders and config.DRY_RUN:
            log("DRY_RUN — no send")
        return sent
    im_est = im
    # Stubs are already closes-first; covering a name frees IM for later adds.
    for o in orders:
        filt = client.filters(o["symbol"])
        step = filt["stepSize"]
        min_n = max(filt["minNotional"], config.MIN_NOTIONAL)
        qty = floor_qty(float(o["qty"]), step)
        notional = qty * o["px"]
        if qty <= 0 or notional < min_n:
            log("skip lot", o["symbol"], qty, notional)
            continue
        cur_amt = float(pos.get(o["symbol"], 0.0))
        new_amt = cur_amt + qty if o["side"] == "BUY" else cur_amt - qty
        reducing = abs(new_amt) < abs(cur_amt) - 1e-12
        add_im = notional / max(config.EXCHANGE_LEVERAGE, 1)
        reason = o.get("exit_reason", "rebalance")
        if not reducing and im_est + add_im > collat + 1e-6:
            log(f"BLOCK IM {o['symbol']}: {im_est:.2f}+{add_im:.2f} > {collat:.2f}")
            continue
        if not reducing and avail + 1e-6 < add_im:
            log(f"BLOCK AVAIL {o['symbol']}: need {add_im:.2f} > {avail:.2f}")
            continue
        try:
            client.set_leverage(o["symbol"], config.EXCHANGE_LEVERAGE)
        except Exception as e:
            log("leverage warn", o["symbol"], e)
        try:
            resp = client.market(
                o["symbol"],
                o["side"],
                qty,
                reduce_only=reducing and not client.hedge_mode,
            )
            oid = resp.get("orderId")
            log("SENT", o["side"], o["symbol"], qty, reason, oid)
            sent.append(
                {
                    "symbol": o["symbol"],
                    "side": o["side"],
                    "qty": qty,
                    "orderId": oid,
                    "exit_reason": reason,
                }
            )
            pos[o["symbol"]] = new_amt
            im_est = im_est - add_im if reducing else im_est + add_im
            if not reducing:
                avail = max(0.0, avail - add_im)
        except Exception as e:
            log("FAIL", o["symbol"], e)
    return sent


def once(client: Client, state: dict, cache: dict[str, pd.Series]) -> dict:
    cycle_start_ms = int(time.time() * 1000)
    # 1m z updates when the UTC minute rolls. Stops still run on every poll.
    bar_id = int(time.time() // 60)
    full = state.get("last_full_bar") != bar_id

    # ── node: halt
    margin, avail = client.balances()
    prev_peak = state.get("peak_margin")
    state = update_peak_and_kill(state, margin)
    peak = float(state.get("peak_margin") or margin or 0.0)
    is_new_peak = prev_peak is None or margin > float(prev_peak) + 1e-12
    dd = (peak - margin) / peak if peak > 0 else 0.0
    if is_new_peak:
        log(f"PEAK margin={margin:.2f}")
    else:
        log(f"margin={margin:.2f} peak={peak:.2f} dd_from_peak={dd:.2%}")
    if state.get("halted"):
        log("HALTED:", state.get("halt_reason"))
        flat_sent = flatten_all(client)
        state["weights"] = {}
        log_cycle(
            {
                "event": "halted_flatten",
                "margin": margin,
                "peak_margin": peak,
                "dd_from_peak": dd,
                "reason": state.get("halt_reason"),
                "flatten": flat_sent,
            }
        )
        save_state(state)
        return state

    # ── node: risk + book
    collat = collateral_from_margin(margin)
    gross = gross_notional_budget(margin, collat)
    if collat <= 0 or gross <= 0:
        log("no risk budget — skip")
        return state
    book = client.position_book()
    pos = {s: v["qty"] for s, v in book.items()}
    entry_px = {s: v["entry"] for s, v in book.items()}
    upnl = {s: v["upnl"] for s, v in book.items()}
    px = pd.Series({s: float(v["mark"] or 0.0) for s, v in book.items()})
    im = derived_im(pos, px) if pos else 0.0

    n_stop = 0
    orders: list[dict] = []
    sent: list[dict] = []
    z = pd.Series(dtype=float)
    w = weights_from_state(state)
    if w is None:
        w = pd.Series(dtype=float)
    active = w[w.abs() > 1e-12] if len(w) else w
    bars = 0

    if not full:
        # ── node: orders (stop tick only)
        orders = stop_flatten_orders(px, pos, entry_px, upnl)
        n_stop = len(orders)
        log(f"STOP tick n={n_stop}", orders if orders else "none")
        sent = execute_orders(client, orders, pos, collat, avail, im)
    else:
        # ── node: market + signal (once per 1m bar)
        assets, btc = pull_closes(client, cache)
        bars = len(assets)
        log(f"bars={bars} venue={config.MARKET_BASE} interval={config.INTERVAL} full=1")
        w, z, beta = target_weights(assets, btc, prev_w=weights_from_state(state))
        active = w[w.abs() > 1e-12]
        log("z:\n", z.sort_values(ascending=False).to_string())
        log("w_active:\n", active.sort_values(ascending=False).to_string())
        log(
            "n_active",
            len(active),
            "port_beta",
            float((w * beta.reindex(w.index).fillna(0)).sum()),
        )
        names = set(w.index) | set(pos)
        for s in names:
            if s not in px.index or float(px.get(s, 0) or 0) <= 0:
                px[s] = client.mark(s)
        log(
            f"collat={collat:.2f} gross={gross:.2f} lev={config.EXCHANGE_LEVERAGE}x "
            f"im_derived={im:.2f} avail={avail:.2f}"
        )
        mins = {s: client.filters(s)["minNotional"] for s in names}
        orders = rebalance_orders(
            w.reindex(list(names)).fillna(0.0), px, pos, gross, mins, entry_px, upnl
        )
        n_stop = sum(1 for o in orders if o.get("exit_reason") == "stop")
        if not orders:
            log("HOLD — no trade (z_min / deadband / cost floor / no-add-loser)")
        else:
            log(f"FIRE orders_n={len(orders)}", orders)
        sent = execute_orders(client, orders, pos, collat, avail, im)
        state["weights"] = {k: float(v) for k, v in w.items() if abs(float(v)) > 1e-12}
        state["last_full_bar"] = bar_id

    # ── node: persist
    state["last_cycle_ts"] = time.time()
    state["last_gross"] = gross
    state["last_margin"] = margin
    state["peak_margin"] = peak
    income = {}
    try:
        income = client.income_since(cycle_start_ms - 1000)
    except Exception as e:
        log("income reconcile warn", e)
    log_cycle(
        {
            "event": "rebalance" if full else "stop_tick",
            "full": full,
            "bars": bars,
            "n_active": int(len(active)),
            "n_orders": len(orders),
            "n_stop": n_stop,
            "n_sent": len(sent),
            "dry_run": config.DRY_RUN,
            "margin": margin,
            "peak_margin": peak,
            "dd_from_peak": dd,
            "collat": collat,
            "gross": gross,
            "im_derived": im,
            "z": {k: float(v) for k, v in z.items()} if full else {},
            "w": state.get("weights") or {},
            "orders": orders,
            "sent": sent,
            "income_delta": income,
        }
    )
    save_state(state)
    if income:
        log("income_delta", income)
    return state


def main() -> None:
    # ── node: boot
    if not config.API_KEY or not config.SECRET_KEY:
        raise SystemExit("missing API_KEY/SECRET_KEY in .env")
    if config.MARKET_BASE != config.FAPI_BASE:
        log("WARN: MARKET_BASE != FAPI_BASE", config.MARKET_BASE, config.FAPI_BASE)

    client = Client()
    hedge = client.detect_hedge_mode()
    state = load_state()
    log(
        "CSZN 60s poll / 1m z",
        f"fapi={config.FAPI_BASE}",
        f"hedge={hedge}",
        f"dry_run={config.DRY_RUN}",
        f"interval={config.INTERVAL}",
        f"z_min={config.Z_MIN}",
        f"deadband={config.WEIGHT_DEADBAND}",
        f"min_reb={config.MIN_REBALANCE_USDT}",
        f"stop={config.STOP_PCT}",
        f"poll={config.POLL_S}s",
        f"trade=gated",
        f"halted={state.get('halted')}",
        f"peak={state.get('peak_margin')}",
    )

    cache: dict[str, pd.Series] = {}
    # ── node: poll clock
    while True:
        try:
            state = once(client, state, cache)
        except Exception as e:
            log("error:", e)
            log_cycle({"event": "error", "error": str(e)})
        if config.RUN_ONCE:
            return
        now = time.time()
        wake = (math.floor(now / config.POLL_S) + 1) * config.POLL_S
        wait = wake - now
        wake_str = datetime.fromtimestamp(wake).strftime("%Y-%m-%d-%H-%M-%S")
        log(f"poll sleep until {wake_str}")
        time.sleep(max(1.0, wait))


if __name__ == "__main__":
    main()
