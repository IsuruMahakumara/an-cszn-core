## 1. Directional HMM Strategy

Applies Simons' early regime-classification model to single assets, replacing rigid indicators with continuous feature vectors. An HMM estimates state probabilities to forecast expected returns $\mathbb{E}[R_{t+1}]$, executing only when predicted edge clears fee hurdles.

* **Regime Inference:** Unsupervised HMM maps features into hidden volatility/trend states.
* **Value Filter:** Trades execute if $\mathbb{E}[R_{t+1}] > \text{Fees} + \text{Slippage}$.
* **Solo LLN Scaling:** Runs across 50+ uncorrelated crypto assets on 1h/4h bars to compound sample size ($N$) without incurring high-frequency friction.

---

## 2. Non-Directional Stat-Arb Strategy

Reflects Medallion's mature market-neutral framework. Trades the cointegrated spread ($Z$-score) between correlated asset pairs using perpetual futures. An HMM monitors spread variance, pausing execution during structural correlation breaks.

* **Delta Neutrality:** Longs undervalued assets while shorting overvalued paired legs.
* **HMM Guardrail:** Halts mean-reversion entries when the model detects non-stationary breakdown regimes.
* **Solo LLN Scaling:** Executes simultaneous cross-pair spreads continuously across a broad pair universe, generating thousands of independent trades to let statistical edge converge.