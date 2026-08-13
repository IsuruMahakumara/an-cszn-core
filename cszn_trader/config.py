"""Knobs for demo CSZN residual book. Credentials from project-root .env."""

from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API_KEY = os.getenv("API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")

# --- 2. one venue: demo for BOTH orders and klines/marks ---
FAPI_BASE = os.getenv("BINANCE_FAPI_URL", "https://demo-fapi.binance.com").rstrip("/")
# default market host = trade host (no prod/demo mix)
MARKET_BASE = os.getenv("BINANCE_MARKET_URL", FAPI_BASE).rstrip("/")

BENCHMARK = "BTCUSDT"
UNIVERSE = [
    "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "NEARUSDT",
    "APTUSDT", "SUIUSDT", "LTCUSDT", "ATOMUSDT", "FILUSDT",
]

INTERVAL = os.getenv("KLINE_INTERVAL", "15m")
# rolling β window W (CSZN §1)
BETA_WINDOW = int(os.getenv("BETA_WINDOW", "48"))
# residual lookback for signal strength (bars of ε summed)
RESID_LOOKBACK = int(os.getenv("RESID_LOOKBACK", "12"))
# need β window + residual lookback + buffer bars from demo
KLINE_LIMIT = BETA_WINDOW + RESID_LOOKBACK + 10

# CSZN §3 winsorize
Z_CLIP = float(os.getenv("Z_CLIP", "3.0"))

# --- 5. collateral from account margin balance ---
# fraction of margin balance allowed as initial-margin budget (Simons: hard risk budget)
COLLATERAL_FRAC = float(os.getenv("COLLATERAL_FRAC", "0.10"))
# optional absolute ceiling USDT; 0 = disabled (purely margin-derived)
MAX_COLLATERAL_USDT = float(os.getenv("MAX_COLLATERAL_USDT", "0"))
# exchange leverage amplifies notional from that collateral only
EXCHANGE_LEVERAGE = int(os.getenv("EXCHANGE_LEVERAGE", "10"))

# --- 6. cost gate ---
# taker fee round-trip estimate per name (bps of notional); demo often ~4–8
FEE_BPS = float(os.getenv("FEE_BPS", "8"))
# require |ΔV| >= COST_MULT × estimated fee notional drag before trading
COST_MULT = float(os.getenv("COST_MULT", "3.0"))
MIN_NOTIONAL = float(os.getenv("MIN_NOTIONAL", "5"))

# fixed clock (wider default: less churn)
REBALANCE_S = int(os.getenv("REBALANCE_SECONDS", "3600"))

DRY_RUN = os.getenv("DRY_RUN", "1") not in ("0", "false", "False")
RUN_ONCE = os.getenv("RUN_ONCE", "0") in ("1", "true", "True")
