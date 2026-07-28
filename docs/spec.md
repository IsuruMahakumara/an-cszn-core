## System Specification: `AlphaNode::SpotHMM`

### Program objectives

| Goal | Spec |
|---|---|
| Exchange | Binance Spot REST + WS — data, account, orders; honor `LOT_SIZE`, `NOTIONAL`, tick |
| Universe | Target 50–100 liquid spot pairs on 1h / 4h closes; `N=1` first-class for bring-up and fallback |
| Pipeline | Per-symbol: feed → HMM → `E[R]` → risk → execute; same path for `N=1` and `N >> 1` |
| Edge gate | `HOLD` unless `E[R_{t+1}] > TakerFee + Slippage + SafetyMargin` |
| Risk | `V_t * StopLossDistance ≤ 0.01 * AccountBalance` |
| Latency | Bar close → order dispatch `< 500ms` |

| Component | Role |
|---|---|
| `MarketDataFeed` | OHLCV ingest, history, features `x_t` |
| `HMMInference` | Load Python HMM `(A, μ_k, Σ_k)`; Forward `P(S_t=k \| x_{1:t})` |
| `ExpectedReturnModel` | `E[R_{t+1}] = Σ P(S_t=k) · f_k(x_t)` + friction gate |
| `PortfolioRiskManager` | Size to fixed 1% equity risk |
| `ExecutionRouter` | Auth, orders, positions |

| Invariant | Rule |
|---|---|
| Prob sum | `|Σ_k P(S_t=k) − 1| < 1e-7` |
| Prob bounds | `0 ≤ P(S_t=k) ≤ 1` |
| Bad input | Zero volume / bad ticks / incomplete bars → `NaN`/`Invalid`, no crash |
| Disconnect | WS reconnect with exponential backoff; REST sync fallback |
| Param reload | Order-invariant state labels (e.g. sort by `Tr(Σ_k)`) |

---

### C++ tech

| Item | Spec |
|---|---|
| Namespace | `AlphaNode` only |
| Layout | Header-only core in `include/`; thin `main` / test `.cpp` only |
| Standard | C++20; `std::vector` / `std::unordered_map` OK |
| Build | `xmake.lua` |
| Deps | `ixwebsocket`, `openssl`, `simdjson`, `zstd`, `cpp-httplib`, `doctest` |
