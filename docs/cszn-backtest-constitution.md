# CSZN backtest constitution

Rules for any human or agent that changes the fade and runs `backtest.py`.
The goal is **proof of edge after costs**, not a green number.

First frozen tape (2024-08-16 → 2026-08-13) showed no edge after costs.
An unconstrained search will “fix” that by overfitting. This document forbids that.

Companion: `docs/cszn-backtest.md` (how the bar clock works).

---

## Mission

1. One hypothesis: cross-sectional residual fade vs Bitcoin.
2. Frozen rules per run. Costs on. No lookahead.
3. Walk-forward out-of-sample decides. In-sample green is not a win.
4. If OOS is still dead after a capped trial budget, stop. Do not invent a new strategy to rescue the project.

---

## Coding constraints (hard)

1. Do not edit `strategy.py` / `config.py` in the same loop that is “searching” without a written hypothesis and a trial log entry.
2. Reuse `target_weights`, `rebalance_orders`, and `book.apply_fills`. No parallel backtest math.
3. No new dependencies, no optimizer library, no research platform.
4. One change per iteration. Diff ≤ ~20 lines or one named knob. Reject multi-file rewrites.
5. Never weaken the fill model to improve PnL: no same-bar fill, no `FEE_BPS = 0`, no lookahead.
6. Tape fixed. Same `cszn_trader/data/klines_1h.csv`. `BACKTEST_REFRESH` off unless explicitly refreshing history for everyone.
7. Do not drop losing names from the universe mid-loop. Universe membership changes only via explicit `refresh_universe.py --apply`, then a new frozen tape.
8. `offline_check.py` must pass after every code change.
9. Log every run to JSONL: knobs, git hash / description, `net_pnl`, turnover, fees, `max_dd`, OOS window. Never overwrite prior rows.
10. Stop condition: fixed trial budget (e.g. 20) or first **OOS** pass — not “until green.”

---

## Strategy constraints (hard)

1. One bet only: CSZN residual fade vs BTC. No second signal, no HMM, no momentum overlay in the search loop.
2. Allowed to change: a small declared set only (example: `{Z_MIN, RESID_LOOKBACK, STOP_PCT}` or one time-in-market gate). Not all knobs at once.
3. Forbidden: universe cherry-picking, per-name exceptions, take-profit, fee/haircut games, raising leverage/gross to hide fees.
4. Must stay: dollar-neutral, β-hedge on active set, next-bar fill, `FEE_BPS` ≥ live, cost floor on adds, no-add-to-losers / per-name stop if part of the frozen live policy.
5. Scarce risk stays scarce. Do not “find edge” by lifting `GROSS_FRAC` / collateral until fees look small.
6. Primary score is not raw PnL alone. Require jointly:
   - `net_pnl > 0` on **OOS**
   - fees small relative to turnover / start capital (declare thresholds before the loop)
   - `time_in_mkt` and `max_dd` under declared caps
7. Walk-forward: tune only on the first ~70% of the tape; **report only** the last ~30%. In-sample green + OOS red → reject.
8. Null baseline: flat / random signs / shuffled residuals. Candidate must beat the null OOS.
9. One-sentence hypothesis before code. If the agent cannot state why the change should help after costs, discard.

---

## Allowed agent loop

```text
1. State hypothesis (one sentence)
2. Change at most one knob or one gate
3. Run offline_check
4. Run backtest on frozen tape
5. Score OOS window only
6. Append JSONL result
7. If OOS fail → revert; do not stack fixes
8. Cap trials (e.g. 20), then human review
```

---

## First loop priority (if searching at all)

Not a new z formula. Cut time-in-market / fire rate under the **same** fade
(stricter `Z_MIN`, longer deadband, rarer adds) and check OOS bleed.

If that still fails, the bet is wrong. Stop.

---

## Verdict language

| Result | Meaning |
|---|---|
| OOS `net_pnl` ≤ 0 after costs | No edge. Do not go live larger. |
| OOS green, in-sample only green | Reject. Overfit. |
| OOS green + fees/turnover/dd pass + null beaten | Candidate for human review only. |

Live demo PnL is not proof. This constitution outranks a green backtest print.
