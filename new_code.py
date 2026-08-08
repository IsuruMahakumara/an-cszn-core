import numpy as np
import pandas as pd


def compute_beta_and_residuals(
    returns_df: pd.DataFrame, market_series: pd.Series, window: int = 30
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Step 1: Extract rolling Beta (β) and Idiosyncratic Residuals (ε) using rolling linear regression.

    Y = alpha + beta * X + residual
    """
    # Rolling covariance and variance
    cov = returns_df.apply(lambda col: col.rolling(window).cov(market_series))
    var = market_series.rolling(window).var()

    # Rolling Beta: Cov(R_i, R_m) / Var(R_m)
    beta_df = cov.div(var, axis=0)

    # Reconstructed systematic return: Beta * R_m
    systematic_returns = beta_df.mul(market_series, axis=0)

    # Idiosyncratic residual return: R_i - Systematic
    residual_df = returns_df - systematic_returns

    return beta_df, residual_df


def compute_residual_momentum(
    residual_df: pd.DataFrame, lookback: int = 14
) -> pd.DataFrame:
    """Step 2: Calculate volatility-standardized Residual Momentum Signal.

    Sum of residuals over lookback window divided by residual volatility.
    """
    rolling_sum = residual_df.rolling(lookback).sum()
    rolling_std = residual_df.rolling(lookback).std()

    # Avoid zero division
    residual_momentum = rolling_sum / (rolling_std + 1e-8)
    return residual_momentum


def compute_cross_sectional_zscore(signal_df: pd.DataFrame) -> pd.DataFrame:
    """Step 3: Cross-sectional Z-Score ranking across all assets at each timestamp t."""
    mean_cs = signal_df.mean(axis=1)
    std_cs = signal_df.std(axis=1)

    # Standardize across columns (axis=0 after subtracting row mean)
    z_scores = signal_df.sub(mean_cs, axis=0).div(std_cs + 1e-8, axis=0)
    return z_scores


def construct_beta_neutral_weights(
    z_scores: pd.DataFrame, beta_df: pd.DataFrame, leverage: float = 1.0
) -> pd.DataFrame:
    """Step 4: Translate Z-scores to long/short weights and enforce zero total market beta."""
    raw_weights = z_scores.copy()

    # Separate long (+Z) and short (-Z) allocations
    pos_mask = raw_weights > 0
    neg_mask = raw_weights < 0

    # Dollar balance long and short legs to 0.5 * leverage each
    long_weights = raw_weights.mask(~pos_mask, 0)
    short_weights = raw_weights.mask(~neg_mask, 0)

    long_sum = long_weights.sum(axis=1).replace(0, 1)
    short_sum = short_weights.abs().sum(axis=1).replace(0, 1)

    norm_long = long_weights.div(long_sum, axis=0) * (0.5 * leverage)
    norm_short = short_weights.div(short_sum, axis=0) * (0.5 * leverage)

    unadjusted_weights = norm_long + norm_short  # Sums to 0 net cash exposure

    # Enforce Beta Neutrality: W_adjusted = W - (W . Beta / Beta . Beta) * Beta
    portfolio_beta = (unadjusted_weights * beta_df).sum(axis=1)
    beta_sq_sum = (beta_df**2).sum(axis=1)

    beta_adjustment = beta_df.mul(portfolio_beta / (beta_sq_sum + 1e-8), axis=0)
    neutral_weights = unadjusted_weights - beta_adjustment

    return neutral_weights


def generate_binance_orders(
    target_weights: pd.Series,
    current_positions: pd.Series,
    portfolio_value: float,
    current_prices: pd.Series,
) -> pd.DataFrame:
    """Step 5: Portfolio rebalancing module - convert target weight vector to Binance Futures contract quantities.
    """
    target_notional = target_weights * portfolio_value
    current_notional = current_positions * current_prices

    rebalance_notional = target_notional - current_notional
    rebalance_qty = rebalance_notional / current_prices

    order_df = pd.DataFrame(
        {
            "target_weight": target_weights,
            "target_notional": target_notional,
            "rebalance_notional": rebalance_notional,
            "order_qty": rebalance_qty,
            "side": np.where(rebalance_qty > 0, "BUY", "SELL"),
        }
    )

    # Filter out small noise rebalances
    return order_df[order_df["rebalance_notional"].abs() > 10.0]


# ==========================================
# Execution Workflow Example
# ==========================================
if __name__ == "__main__":
    # Simulated 1-hour price matrix for 5 Binance perpetuals + BTC market benchmark
    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=100, freq="1h")
    symbols = ["SOLUSDT", "AVAXUSDT", "NEARUSDT", "APTUSDT", "SUIUSDT"]

    prices = pd.DataFrame(
        100 + np.random.randn(100, 5).cumsum(axis=0),
        index=dates,
        columns=symbols,
    )
    market_prices = pd.Series(
        40000 + np.random.randn(100).cumsum(axis=0) * 100, index=dates
    )

    returns = prices.pct_change().dropna()
    market_returns = market_prices.pct_change().dropna()

    # Pipeline execution
    beta_df, residual_df = compute_beta_and_residuals(
        returns, market_returns, window=24
    )
    res_mom = compute_residual_momentum(residual_df, lookback=12)
    z_scores = compute_cross_sectional_zscore(res_mom)
    target_weights = construct_beta_neutral_weights(
        z_scores, beta_df, leverage=1.0
    )

    # Latest timestamp rebalance execution
    latest_weights = target_weights.iloc[-1]
    latest_prices = prices.iloc[-1]
    current_positions = pd.Series(0.0, index=symbols)  # Flat starting portfolio

    orders = generate_binance_orders(
        target_weights=latest_weights,
        current_positions=current_positions,
        portfolio_value=100_000.0,  # $100k USDT capital
        current_prices=latest_prices,
    )

    print("--- Rebalance Target Weights & Orders ---")
    print(orders)