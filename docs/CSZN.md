# Cross-Sectional Beta-Neutral Statistical Arbitrage

## 1. Time-Series Parameter Estimation (Rolling Beta)

For each asset `i` in `{1, …, N}` at timestamp `t`, rolling market sensitivity `β_i,t` vs benchmark `m` (Bitcoin) over lookback window `W`:

```text
β_i,t = Cov(r_i[t-W:t], r_m[t-W:t]) / Var(r_m[t-W:t])
```

Where `r` is the log or percentage return series:

```text
r_i,t = (P_i,t − P_i,t−1) / P_i,t−1
```

---

## 2. Residual Signal Isolation

Idiosyncratic excess return `x_i,t` = asset return minus market-explained component:

```text
x_i,t = ε_i,t = r_i,t − (β_i,t · r_m,t)
```

---

## 3. Cross-Sectional Normalization (Latitudinal Z-Score)

At each `t`, cross-sectional mean `μ_t` and std `σ_t` across `N` residual assets:

```text
μ_t = (1/N) · Σ_{i=1..N} x_i,t

σ_t = sqrt( (1/(N−1)) · Σ_{i=1..N} (x_i,t − μ_t)² )
```

Unitless Z-scores:

```text
Z_i,t = (x_i,t − μ_t) / σ_t
```

Winsorize outliers to `[-3, 3]`:

```text
Ẑ_i,t = max(−3.0, min(3.0, Z_i,t))
```

---

## 4. Market-Neutral Weight Construction

Split into long (`Ẑ > 0`) and short (`Ẑ < 0`) arms for 100% long / 100% short dollar neutrality:

```text
w_i,t^long  = max(0, Ẑ_i,t) / Σ_{j: Ẑ_j > 0} Ẑ_j,t

w_i,t^short = min(0, Ẑ_i,t) / Σ_{j: Ẑ_j < 0} |Ẑ_j,t|

w_i,t^raw   = w_i,t^long + w_i,t^short
```

---

## 5. Leverage Scaling & Order Execution

Scale by target gross leverage `L_target`, notional vs equity `E`:

```text
w_i,t^final   = w_i,t^raw · (L_target / 2)

V_i,t^target  = w_i,t^final · E

ΔV_i,t        = V_i,t^target − V_i,t^current
```

Enforce exchange minimum notional `V_min` before routing:

```text
ΔV_i,t^exec =
  ΔV_i,t    if |ΔV_i,t| ≥ V_min
  0        if |ΔV_i,t| < V_min
```
