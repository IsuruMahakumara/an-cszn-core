"""
COMPARTMENT: run
ROLE:        wire the graph — clock loop only
GRAPH (nodes → edges):
  config ──knobs──► all
  exchange ──closes,marks,balances,pos──► run
  ops ──state,prev_w──► run
  strategy.signal ──w,z,beta──► run
  strategy.risk ──collat,gross,im──► run
  strategy.orders ──order stubs──► run
  run ──market orders──► exchange
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
    target_weights,
)


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H-%M-%S")


def log(*args, **kwargs) -> None:
    print(f"[{ts()}]", *args, **kwargs)


def pull_closes(client: Client) -> tuple[pd.DataFrame, pd.Series]:
    # IN: client → OUT: (asset closes, Bitcoin closes)
    book = {}
    for sym in config.UNIVERSE + [config.BENCHMARK]:
        raw = client.klines(sym, config.INTERVAL, config.KLINE_LIMIT)
        book[sym] = pd.Series(
            [float(x[4]) for x in raw],
            index=[int(x[0]) for x in raw],
        )
    df = pd.DataFrame(book).dropna()
    return df.drop(columns=[config.BENCHMARK]), df[config.BENCHMARK]


def floor_qty(qty: float, step: float) -> float:
    # IN: raw qty → OUT: lot-floored qty
    if step <= 0:
        return qty
    return math.floor(qty / step + 1e-12) * step


def flatten_all(client: Client) -> list[dict]:
    # IN: open positions → OUT: close fills (or dry-run stubs)
    sent = []
    pos = client.positions()
    if not pos:
        log("flatten: already flat")
        return sent
    for sym, amt in pos.items():
        side = "SELL" if amt > 0 else "BUY"
        qty = floor_qty(abs(float(amt)), client.filters(sym)["stepSize"])
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


def once(client: Client, state: dict) -> dict:
    """One clock tick through the concern graph."""
    cycle_start_ms = int(time.time() * 1000)

    # ── node: market ── IN client → OUT assets, btc ────────────────
    assets, btc = pull_closes(client)
    log(f"bars={len(assets)} venue={config.MARKET_BASE} interval={config.INTERVAL}")

    # ── node: signal ── IN assets,btc,prev_w → OUT w,z,beta ────────
    prev_w = weights_from_state(state)
    w, z, beta = target_weights(assets, btc, prev_w=prev_w)
    active = w[w.abs() > 1e-12]
    log("z:\n", z.sort_values(ascending=False).to_string())
    log("w_active:\n", active.sort_values(ascending=False).to_string())
    log(
        "n_active",
        len(active),
        "port_beta",
        float((w * beta.reindex(w.index).fillna(0)).sum()),
    )

    # ── node: halt ── IN margin,state → OUT maybe flatten ───────────
    margin = client.margin_balance()
    avail = client.available_balance()
    state = update_peak_and_kill(state, margin)
    if state.get("halted"):
        log("HALTED:", state.get("halt_reason"))
        flat_sent = flatten_all(client)
        state["weights"] = {}
        log_cycle(
            {
                "event": "halted_flatten",
                "margin": margin,
                "reason": state.get("halt_reason"),
                "flatten": flat_sent,
            }
        )
        save_state(state)
        return state

    # ── node: risk ── IN margin,pos → OUT collat,gross,im ───────────
    collat = collateral_from_margin(margin)
    gross = gross_notional_budget(margin, collat)
    pos = client.positions()
    names = set(w.index) | set(pos)
    px = pd.Series({s: client.mark(s) for s in names})
    im = derived_im(pos, px)
    log(
        f"margin={margin:.2f} avail={avail:.2f} peak={state.get('peak_margin'):.2f} "
        f"collat={collat:.2f} gross={gross:.2f} lev={config.EXCHANGE_LEVERAGE}x "
        f"im_derived={im:.2f} im_rpt={client.exchange_im_reported():.2f}"
    )
    if collat <= 0 or gross <= 0:
        log("no risk budget — skip")
        return state

    # ── node: orders ── IN w,px,pos,gross → OUT order stubs ─────────
    full_w = w.reindex(list(names)).fillna(0.0)
    mins = {s: client.filters(s)["minNotional"] for s in names}
    orders = rebalance_orders(full_w, px, pos, gross, mins)
    log(f"orders_n={len(orders)}", orders)

    # ── node: execute ── IN orders → OUT fills ──────────────────────
    sent = []
    if config.DRY_RUN:
        log("DRY_RUN — no send")
    else:
        im_est = im
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
                log("SENT", o["side"], o["symbol"], qty, oid)
                sent.append(
                    {"symbol": o["symbol"], "side": o["side"], "qty": qty, "orderId": oid}
                )
                pos[o["symbol"]] = new_amt
                im_est = im_est - add_im if reducing else im_est + add_im
                if not reducing:
                    avail = max(0.0, avail - add_im)
            except Exception as e:
                log("FAIL", o["symbol"], e)

    # ── node: persist ── IN results → OUT state + log ───────────────
    state["weights"] = {k: float(v) for k, v in w.items() if abs(float(v)) > 1e-12}
    state["last_cycle_ts"] = time.time()
    state["last_gross"] = gross
    state["last_margin"] = margin

    income = {}
    try:
        income = client.income_since(cycle_start_ms - 1000)
    except Exception as e:
        log("income reconcile warn", e)

    log_cycle(
        {
            "event": "cycle",
            "bars": len(assets),
            "n_active": len(active),
            "n_orders": len(orders),
            "n_sent": len(sent),
            "dry_run": config.DRY_RUN,
            "margin": margin,
            "collat": collat,
            "gross": gross,
            "im_derived": im,
            "z": {k: float(v) for k, v in z.items()},
            "w": state["weights"],
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
    # ── node: boot ── IN env → OUT client, state ────────────────────
    if not config.API_KEY or not config.SECRET_KEY:
        raise SystemExit("missing API_KEY/SECRET_KEY in .env")
    if config.MARKET_BASE != config.FAPI_BASE:
        log("WARN: MARKET_BASE != FAPI_BASE", config.MARKET_BASE, config.FAPI_BASE)

    client = Client()
    hedge = client.detect_hedge_mode()
    state = load_state()
    log(
        "CSZN production residual",
        f"fapi={config.FAPI_BASE}",
        f"hedge={hedge}",
        f"dry_run={config.DRY_RUN}",
        f"z_min={config.Z_MIN}",
        f"collat_frac={config.COLLATERAL_FRAC}",
        f"gross_frac={config.GROSS_FRAC}",
        f"lev={config.EXCHANGE_LEVERAGE}",
        f"deadband={config.WEIGHT_DEADBAND}",
        f"min_reb={config.MIN_REBALANCE_USDT}",
        f"clock={config.REBALANCE_S}s",
        f"halted={state.get('halted')}",
    )

    # ── node: clock ── loop once → sleep until wake stamp ───────────
    while True:
        try:
            state = once(client, state)
        except Exception as e:
            log("error:", e)
            log_cycle({"event": "error", "error": str(e)})
        if config.RUN_ONCE:
            return
        now = time.time()
        wake = (math.floor(now / config.REBALANCE_S) + 1) * config.REBALANCE_S
        wait = wake - now
        wake_str = datetime.fromtimestamp(wake).strftime("%Y-%m-%d-%H-%M-%S")
        log(f"sleep until {wake_str}")
        time.sleep(max(1.0, wait))


if __name__ == "__main__":
    main()
