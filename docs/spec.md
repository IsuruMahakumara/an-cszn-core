## System Specification: `AlphaNode::SpotHMM`

### Program objectives

| Goal | Spec |
|---|---|
| Exchange | Binance Spot REST + WS — data, account, orders; honor `LOT_SIZE`, `NOTIONAL`, tick |
| Universe | Target 50–100 liquid spot pairs on $1\text{h}$ / $4\text{h}$ closes; $N=1$ first-class for bring-up and fallback |
| Pipeline | Per-symbol: feed → HMM → $\mathbb{E}[R]$ → risk → execute; same path for $N=1$ and $N\gg 1$ |
| Edge gate | `HOLD` unless $\mathbb{E}[R_{t+1}] > \text{TakerFee} + \text{Slippage} + \text{SafetyMargin}$ |
| Risk | $V_t \times \text{StopLossDistance} \le 0.01 \times \text{AccountBalance}$ |
| Latency | Bar close → order dispatch $< 500\text{ms}$ |

| Component | Role |
|---|---|
| `MarketDataFeed` | OHLCV ingest, history, features $\mathbf{x}_t$ |
| `HMMInference` | Load Python HMM $(A,\boldsymbol{\mu}_k,\boldsymbol{\Sigma}_k)$; Forward $P(S_t=k\mid\mathbf{x}_{1:t})$ |
| `ExpectedReturnModel` | $\mathbb{E}[R_{t+1}]=\sum P(S_t=k)\cdot f_k(\mathbf{x}_t)$ + friction gate |
| `PortfolioRiskManager` | Size to fixed $1\%$ equity risk |
| `ExecutionRouter` | Auth, orders, positions |

| Invariant | Rule |
|---|---|
| Prob sum | $\lvert\sum_k P(S_t=k)-1\rvert < 10^{-7}$ |
| Prob bounds | $0 \le P(S_t=k) \le 1$ |
| Bad input | Zero volume / bad ticks / incomplete bars → `NaN`/`Invalid`, no crash |
| Disconnect | WS reconnect with exponential backoff; REST sync fallback |
| Param reload | Order-invariant state labels (e.g. sort by $\operatorname{Tr}(\boldsymbol{\Sigma}_k)$) |

---

### C++ tech

| Item | Spec |
|---|---|
| Namespace | `AlphaNode` only |
| Layout | Header-only core in `include/`; thin `main` / test `.cpp` only |
| Standard | C++20; `std::vector` / `std::unordered_map` OK |
| Build | `xmake.lua` |
| Deps | `ixwebsocket`, `openssl`, `simdjson`, `zstd`, `cpp-httplib`, `doctest` |
