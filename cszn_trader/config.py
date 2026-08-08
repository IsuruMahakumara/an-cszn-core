"""Knobs for residual CSZN demo futures trading.

Simons discipline: fixed rules, fixed schedule, no discretionary overrides.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root .env (API_KEY / SECRET_KEY)
_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")

# --- credentials (demo account) ---
API_KEY = os.getenv("API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")

# Demo futures REST (orders / account). Market data may use prod klines.
FAPI_BASE = os.getenv("BINANCE_FAPI_URL", "https://demo-fapi.binance.com")
# Public klines: prod has long history; override if your demo serves klines.
MARKET_BASE = os.getenv("BINANCE_MARKET_URL", "https://fapi.binance.com")

# BTC is the market factor only — never in the trade universe.
BENCHMARK = "BTCUSDT"

# Liquid USDT-M perpetual basket (cross-section for residual ranks).
UNIVERSE = [
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
    "NEARUSDT",
    "APTUSDT",
    "SUIUSDT",
    "LTCUSDT",
    "ATOMUSDT",
    "FILUSDT",
]

# Bar interval for residual window (short-horizon statistical edge).
KLINE_INTERVAL = os.getenv("KLINE_INTERVAL", "15m")
# Bars to pull (beta window + residual lookback + buffer).
KLINE_LIMIT = int(os.getenv("KLINE_LIMIT", "120"))

# Rolling β window W (CSZN §1).
BETA_WINDOW = int(os.getenv("BETA_WINDOW", "48"))
# Residual return lookback (short window rank signal).
RESID_LOOKBACK = int(os.getenv("RESID_LOOKBACK", "12"))

# Gross leverage L_target (CSZN §5). Final weight scale = L / 2 each side.
LEVERAGE_TARGET = float(os.getenv("LEVERAGE_TARGET", "1.0"))
# Exchange min notional filter |ΔV| (USDT).
MIN_NOTIONAL = float(os.getenv("MIN_NOTIONAL", "20.0"))
# Winsorize cross-sectional Z (CSZN §3).
Z_CLIP = 3.0

# Fixed-clock rebalance period (seconds). Default 15m aligns with bars.
REBALANCE_SECONDS = int(os.getenv("REBALANCE_SECONDS", "900"))

# 1 = compute orders only; 0 = send market orders on demo.
DRY_RUN = os.getenv("DRY_RUN", "1") not in ("0", "false", "False")
# 1 = single rebalance then exit (useful for first wiring check).
RUN_ONCE = os.getenv("RUN_ONCE", "0") in ("1", "true", "True")

# Signed-request clock skew tolerance (ms).
RECV_WINDOW = int(os.getenv("RECV_WINDOW", "5000"))

# Market orders only — mechanical fill, no limit discretion.
ORDER_TYPE = "MARKET"
