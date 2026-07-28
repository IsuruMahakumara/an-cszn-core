## Test cases: `AlphaNode::SpotHMM`

TDD map of the per-symbol pipeline. Implement steps in order; each case fails until the named unit exists.

```mermaid
flowchart LR
  S1[1 Feed] --> S2[2 HMM]
  S2 --> S3[3 Edge gate]
  S3 --> S4[4 Risk size]
  S4 --> S5[5 Execute]
```

| Step | Objective | Unit |
|---|---|---|
| 1 | Ingest OHLCV → stationary features $\mathbf{x}_t$ | `MarketDataFeed` |
| 2 | Online regime probs $P(S_t=k\mid\mathbf{x}_{1:t})$ | `HMMInference` |
| 3 | $\mathbb{E}[R_{t+1}]$ + friction `HOLD` / trade | `ExpectedReturnModel` |
| 4 | Size $V_t$ to $1\%$ equity risk | `PortfolioRiskManager` |
| 5 | Binance order under exchange filters | `ExecutionRouter` |

Universe: $N=1$ first; multi-asset reuses the same cases over a symbol list.

---

### Step 1 — Feed

| ID | Case | Assert |
|---|---|---|
| F1 | Valid closed bar (OHLCV) | Appended to history; `status=Ok` |
| F2 | Build $\mathbf{x}_t$ from rolling window | Feature vector finite; dim matches model |
| F3 | Zero volume bar | `status=Invalid`; no crash; no trade path |
| F4 | Bad / NaN price tick | `status=Invalid`; history unchanged |
| F5 | Incomplete bar sequence (gap) | `status=Invalid` or gap flag; engine continues |
| F6 | $N=1$ symbol universe | Feed runs for one pair only |

---

### Step 2 — HMM

| ID | Case | Assert |
|---|---|---|
| H1 | Load Python params $(A,\boldsymbol{\mu}_k,\boldsymbol{\Sigma}_k)$ | Shapes valid; ready for Forward |
| H2 | Forward on known $\mathbf{x}_{1:t}$ fixture | $P(S_t=k)$ matches golden within tol |
| H3 | Prob bounds | $\forall k:\ 0 \le P_k \le 1$ |
| H4 | Prob sum | $\lvert\sum_k P_k - 1\rvert < 10^{-7}$ |
| H5 | Param reload order-invariance | States sorted by $\operatorname{Tr}(\boldsymbol{\Sigma}_k)$; labels stable across reload |
| H6 | Invalid / NaN feature in | Returns Invalid; probs not updated |

---

### Step 3 — Edge gate

| ID | Case | Assert |
|---|---|---|
| E1 | $\mathbb{E}[R]=\sum P_k\,f_k(\mathbf{x}_t)$ fixture | Matches golden within tol |
| E2 | $\mathbb{E}[R] >$ fee + slip + margin | Decision = trade (side from model) |
| E3 | $\mathbb{E}[R] \le$ friction hurdle | Decision = `HOLD`; no size/execute call |
| E4 | Boundary: $\mathbb{E}[R]$ equals hurdle | `HOLD` (strict `>`) |
| E5 | Upstream Invalid | Propagates `HOLD` / Invalid; no order |

---

### Step 4 — Risk size

| ID | Case | Assert |
|---|---|---|
| R1 | Known balance, stop distance | $V_t \times \text{stop} \le 0.01 \times \text{balance}$ |
| R2 | Wider stop | Smaller $V_t$ (inverse to stop) |
| R3 | Floor to `LOT_SIZE` / step | Qty after floor still $\ge$ minQty when possible |
| R4 | After floor, notional $<$ `NOTIONAL` | Reject / skip; no send |
| R5 | `HOLD` from step 3 | Sizer not invoked (or returns zero qty) |

---

### Step 5 — Execute

| ID | Case | Assert |
|---|---|---|
| X1 | Demo / mock Send with valid qty | Status OK; position updated |
| X2 | Qty respects tick / step / `NOTIONAL` | Request matches Binance filter rules |
| X3 | Auth failure | Error status; no silent success |
| X4 | WS drop mid-session | Reconnect with backoff; REST sync restores state |
| X5 | Bar close → dispatch (local clock) | Elapsed $< 500\text{ms}$ on fixture path (no live RTT) |
| X6 | Multi-asset fan-out | Same router path per symbol; isolation of fills |

---

### TDD order

1. Red: write failing `doctest` for F1 → X1 in step order.  
2. Green: minimal header-only impl in `AlphaNode`.  
3. Refactor only after the step’s table is green.  
4. Live Binance cases (X1–X4) stay behind demo/mock until unit tables pass.
