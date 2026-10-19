# CSZN 1m excursion (`exp/cszn-1m`)

Hypothesis: refresh a **slow** residual every minute. Abandon 1h bars on this branch only.

Frozen windows: `INTERVAL=1m`, `BETA_WINDOW=720` (12h), `RESID_LOOKBACK=60` (1h). Live z recomputes when `time//60` rolls. Tape: `var/klines_1m.csv` (~14 days). Do not merge to `main` until this scorecard beats 1h after costs, or the branch is killed.

Weights: `signed_unit_weights` (sparse z / Σ|z|). One sleeve is allowed. `beta_neutralize` stays.
