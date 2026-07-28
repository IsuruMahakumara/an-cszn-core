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
| 1 | Ingest OHLCV → stationary features `x_t` | `MarketDataFeed` |
| 2 | Online regime probs `P(S_t=k \| x_{1:t})` | `HMMInference` |
| 3 | `E[R_{t+1}]` + friction `HOLD` / trade | `ExpectedReturnModel` |
| 4 | Size `V_t` to 1% equity risk | `PortfolioRiskManager` |
| 5 | Binance order under exchange filters | `ExecutionRouter` |

Universe: `N=1` first; multi-asset reuses the same cases over a symbol list.

---

### Step 1 — Feed

| ID | Case | Assert |
|---|---|---|
| F1 | Valid closed bar (OHLCV) | Appended to history; `status=Ok` |
| F2 | Build `x_t` from rolling window | Feature vector finite; dim matches model |
| F3 | Zero volume bar | `status=Invalid`; no crash; no trade path |
| F4 | Bad / NaN price tick | `status=Invalid`; history unchanged |
| F5 | Incomplete bar sequence (gap) | `status=Invalid` or gap flag; engine continues |
| F6 | `N=1` symbol universe | Feed runs for one pair only |

---

### Step 2 — HMM

| ID | Case | Assert |
|---|---|---|
| H1 | Load Python params `(A, μ_k, Σ_k)` | Shapes valid; ready for Forward |
| H2 | Forward on known `x_{1:t}` fixture | `P(S_t=k)` matches golden within tol |
| H3 | Prob bounds | for all k: `0 ≤ P_k ≤ 1` |
| H4 | Prob sum | `|Σ_k P_k − 1| < 1e-7` |
| H5 | Param reload order-invariance | States sorted by `Tr(Σ_k)`; labels stable across reload |
| H6 | Invalid / NaN feature in | Returns Invalid; probs not updated |

---

### Step 3 — Edge gate

| ID | Case | Assert |
|---|---|---|
| E1 | `E[R] = Σ P_k f_k(x_t)` fixture | Matches golden within tol |
| E2 | `E[R] >` fee + slip + margin | Decision = trade (side from model) |
| E3 | `E[R] ≤` friction hurdle | Decision = `HOLD`; no size/execute call |
| E4 | Boundary: `E[R]` equals hurdle | `HOLD` (strict `>`) |
| E5 | Upstream Invalid | Propagates `HOLD` / Invalid; no order |

---

### Step 4 — Risk size

| ID | Case | Assert |
|---|---|---|
| R1 | Known balance, stop distance | `V_t * stop ≤ 0.01 * balance` |
| R2 | Wider stop | Smaller `V_t` (inverse to stop) |
| R3 | Floor to `LOT_SIZE` / step | Qty after floor still `≥` minQty when possible |
| R4 | After floor, notional `<` `NOTIONAL` | Reject / skip; no send |
| R5 | `HOLD` from step 3 | Sizer not invoked (or returns zero qty) |

---

### Step 5 — Execute

| ID | Case | Assert |
|---|---|---|
| X1 | Demo / mock Send with valid qty | Status OK; position updated |
| X2 | Qty respects tick / step / `NOTIONAL` | Request matches Binance filter rules |
| X3 | Auth failure | Error status; no silent success |
| X4 | WS drop mid-session | Reconnect with backoff; REST sync restores state |
| X5 | Bar close → dispatch (local clock) | Elapsed `< 500ms` on fixture path (no live RTT) |
| X6 | Multi-asset fan-out | Same router path per symbol; isolation of fills |

---

### TDD order

1. Red: failing `doctest` cases live under `tests/` (see map below).  
2. Green: fill header-only stubs in `include/` until the step table is green.  
3. Refactor only after the step’s table is green.  
4. Live Binance behind demo/mock until unit tables pass.

| Step | Tests | Header stub |
|---|---|---|
| 1 Feed | `tests/feed_test.cpp` | `include/MarketDataFeed.hpp` |
| 2 HMM | `tests/hmm_test.cpp` | `include/HMMInference.hpp` |
| 3 Edge | `tests/edge_gate_test.cpp` | `include/ExpectedReturnModel.hpp` |
| 4 Risk | `tests/risk_size_test.cpp` | `include/PortfolioRiskManager.hpp` |
| 5 Execute | `tests/execute_test.cpp` | `include/ExecutionRouter.hpp` |

```bash
xmake build tests && ./build/macosx/arm64/release/tests
# or: clang++ -std=c++20 -Iinclude -Ithird_party -o build/tests tests/*.cpp && ./build/tests
```
