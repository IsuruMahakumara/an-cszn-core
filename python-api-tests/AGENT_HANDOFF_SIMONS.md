# Agent handoff: Jim Simons–style / residual market-neutral path

## Mission (user goal)

User wants a **profitable Binance Futures strategy in the spirit of Jim Simons / RenTech**:

- Market-neutral / non-directional  
- Driven by **Law of Large Numbers** on many small trials  
- Not narrative discretionary crypto trading  

Core architecture agreed in conversation:

1. Keep the **whole book** (full portfolio of open positions) **market-factor beta ≈ 0** (usually BTC).  
2. Trade only a **repeatable residual edge after costs**.  

Beta here means **co-movement with the crypto market factor** (typically BTC returns), not a separate vague “macro” model. Shared crypto beta makes many directional longs fail together; neutrality removes that common shock so LLN-style averaging is meaningful.

**Important correction already made:** current code is a **directional** vol-filtered trendlet on demo, **not** yet Simons-like.

---

## Current project state

**Location:** `python-api-tests/` in repo `an-markov-core` (parallel to C++ AlphaNode/SpotHMM work; do not conflate).

| Piece | Role | State |
|---|---|---|
| `bar_signal_demo.py` | Runner + settings | Demo futures entry + trail; skip if open; insurance trail at scan end |
| `features.py` | Pure OHLCV features | Heavily commented: MA, Parkinson, DRR, VRE z, vol z |
| `signal.py` | LONG/SHORT/HOLD | Parkinson floor/ceiling; votes = close vs MA + DRR; default need score \|2\| |
| `exchange.py` | REST client | Demo-friendly orders, trail via algo API, filters |
| `risk_killer.py` | Separate kill process | REST poll `positionRisk`; kill if uPnL ≤ −MAX_LOSS_USD; timestamped INFO heartbeat (~60s) + detailed KILL logs |
| `refresh_universe.py` | Rebuilds `universe.txt` | Live `fapi.binance.com`; TRADING perp USDT/USDC; minNotional==5; top N by 24h quoteVolume |
| `universe.txt` | Explicit symbol list | Generated; live liquidity ≠ demo UI volumes |

**Venue:** Binance **Futures Demo** (`demo-fapi.binance.com`) for execution. **Research/volume ranking should use live `fapi`.** User previously mistook demo quote volumes (e.g. XAN ~1B USDT on demo vs ~3M on live) for real liquidity. NILUSDT similar confusion: UI base vol vs quote vol.

**Strategy actually live in code:**

- Scan universe → features on closed N 15m bars → LONG/SHORT/HOLD  
- Enter market + trailing stop (`TRAILING_STOP_MARKET` algo; quantity not `closePosition`)  
- Small notional (e.g. QUOTE_PER_TRADE ~200), high leverage settings present historically  
- Risk: per-name dollar uPnL kill + trail; **no book-level beta neutrality**  
- Dual process: signal bot + kill switch  

**Known technical lessons already burned in:**

- Private GET needs timestamp  
- Algo order path for conditionals  
- minNotional / step / PERCENT_PRICE −4131 / leverage −4028  
- Kill path REST-only (WS ACCOUNT_UPDATE was irregular)  
- Secrets often hardcoded in demos (security risk)  

**Comprehension progress:** User can restate the two-step target (beta-neutral book + residual edge after costs). Earlier probes mixed LLN rhetoric with directional MA/DRR. Demo vs live volume is now explained.

---

## Residual edge ideas (the “strategies” list)

These were given as **examples of step 2** (repeatable residual edge after costs), not as five finished systems already coded. Goal framing for all of them: **Jim Simons–like residual book on binance perps**, after neutralizing market beta.

### 1. Residual cross-section rank (baseline recipe)

- Estimate residual = coin return − β · BTC return over a short window.  
- Long top residual names; short bottom residual names.  
- Rebalance on a fixed clock.  
- Size so net book beta ≈ 0 (dollar-neutral alone is not enough if β differs).  

This is the primary “minimal Simons-shaped” starting sleeve for this user.

### 2. Residual mean reversion

- If residual is extreme high vs recent residual average → short; extreme low → long.  
- Portfolio stays long residual laggards / short residual leaders.  
- Still rebalance and beta-weight for neutrality.  

### 3. Residual momentum

- Hold residual winners; short residual losers for one or several intervals.  
- Orthogonal **hypothesis** to mean reversion; pick **one** horizon and test, do not stack both without research.  

### 4. Cross-sectional relative features only

- Score names with residual-domain stats only (residual DRR, residual vs residual MA, residual vol-adjusted return).  
- Do **not** use raw “close > MA” on price when that mostly tracks BTC.  
- Current `features.py` / `signal.py` are still **price-level** directional; mapping to residual space is a **rewrite**, not a knob tweak.  

### 5. One tiny testable hypothesis (process, not alpha)

- One edge idea, one horizon, one rebalance rule, one universe filter.  
- Prove OOS after costs before multi-signal complexity.  
- Simons culture in user’s terms: no narrative; kill models that fail after costs.  

**Validation common to all five:**

- Live historical klines (not demo volumes).  
- Simulate long/short residual book with intended sizing.  
- Subtract taker fees + half-spread + slippage buffer each rebalance.  
- Walk-forward / held-out period; require positive residual-book PnL and low book–BTC correlation.  
- Log trials: features → residual scores → side/size → fill → exit → PnL.  

**Concrete toy example already given to user:**

- Window: last 24 closed 15m bars.  
- Residual vs rolling BTC β.  
- Long 10 highest residual totals; short 10 lowest.  
- Dollar or beta weights to net β ≈ 0.  
- Edge metric: average next residual of longs minus shorts, after fees.  

---

## User traits and working style

- Builder-first: ship runnable Python on demo and iterate ops (kill logs, universe refresh, dual place + trail).  
- Learns well from concrete API contradictions (XAN demo vs live); expects agents to verify vs Binance REST.  
- Prefers **short complete sentences**, bullet lists, briefs for handoff and recaps.  
- Asks progressively tighter conceptual questions (LLN → shared beta → whole book → confirm two-step plan → edge examples).  
- Goals aspirational (**Simons / market-neutral**); implementation currently **directional LLN sleeve** — be honest about that gap.  
- Uses **demo trading** heavily; must be steered away from treating demo volume/PnL as live edge.  
- Strategy interest aligns with many small trials, cut losers (trail / kill $), high turnover; agent should re-map that energy to **residual two-sided book + book risk**, not more directional kill polish alone.  
- Rule-sensitive repo: inter-line comments on code edits; no commits unless asked; Ask mode previously requested for pure Q&A.  
- Secrets may appear in demo scripts — do not spread or commit recklessly.  

**Communication defaults that work:**

- Direct, concise; complete short sentences.  
- Use “whole book,” “market-factor beta (BTC),” “residual after costs.”  
- Separate “project can execute” from “strategy is Simons-like.”  

---

## Gaps next agent should not relearn wrong

| Claim to avoid | Truth |
|---|---|
| Current strategy is market-neutral | It is **directional** LONG/SHORT from MA+DRR after Parkinson gates |
| Many symbols = independent LLN trials | Shared **crypto beta** correlates losses |
| Demo 1B quote vol names for universe | Use **live** `quoteVolume`; demo is inflated/sim |
| minNotional=5 and quoteVol≥1B pure perps | ≈ **1** name (SOL) live last check; TRADIFI was separate |
| Kill-switch polish = path to Simons | Needed ops; **residual + neutrality + OOS** is the strategy path |

---

## Suggested next work for the continuing agent

1. If coding: residualize features / new decision layer; long–short book with β weights; trial logging; live-data research notebook or script.  
2. If research-only: pick strategy **#1** (residual rank) as sole hypothesis; OOS after costs before live size.  
3. Keep demo for execution sandbox; ranks and history from live fapi.  
4. Elevate risk: net β kill / gross caps, not only per-name uPnL.  
5. Avoid expanding directional MA/DRR as if it were market-neutral.  

**Success criteria user verbally accepted:** beta-neutral whole book + **repeatable residual edge after costs**, Jim Simons–like non-directional futures system — not more polished directional demo spray.


