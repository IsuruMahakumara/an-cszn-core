"""Production CSZN knobs. Credentials from project-root .env.

Simons alignment: scarce risk, sparse signals, slow clock, cost-aware turnover.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")

API_KEY = os.getenv("API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")

# one venue: demo for orders + klines
FAPI_BASE = os.getenv("BINANCE_FAPI_URL", "https://demo-fapi.binance.com").rstrip("/")
MARKET_BASE = os.getenv("BINANCE_MARKET_URL", FAPI_BASE).rstrip("/")

BENCHMARK = "BTCUSDT"
# Liquid USDT-M perps verified TRADING on demo-fapi (exclude BTC = benchmark).
# Dropped thinner names (FIL/ATOM/APT/DOT) that dominated fee drag in prior run.
UNIVERSE = [
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "BCHUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "NEARUSDT",
    "SUIUSDT",
    "UNIUSDT",
    "OPUSDT",
    "ARBUSDT",
    "INJUSDT",
    "WLDUSDT",
    "TIAUSDT",
    "LTCUSDT",
]

INTERVAL = os.getenv("KLINE_INTERVAL", "1h")
BETA_WINDOW = int(os.getenv("BETA_WINDOW", "48"))
RESID_LOOKBACK = int(os.getenv("RESID_LOOKBACK", "12"))
KLINE_LIMIT = min(1500, BETA_WINDOW + RESID_LOOKBACK + 50)

Z_CLIP = float(os.getenv("Z_CLIP", "3.0"))
# sparse book: zero weight unless |Z| >= Z_MIN (crush crumb turnover)
Z_MIN = float(os.getenv("Z_MIN", "1.0"))

# --- scarce risk: IM from margin, gross hard-capped vs margin ---
# fraction of margin balance lockable as IM
COLLATERAL_FRAC = float(os.getenv("COLLATERAL_FRAC", "0.05"))
# absolute IM ceiling USDT; 0 = off
MAX_COLLATERAL_USDT = float(os.getenv("MAX_COLLATERAL_USDT", "200"))
EXCHANGE_LEVERAGE = int(os.getenv("EXCHANGE_LEVERAGE", "5"))
# hard cap: gross notional <= GROSS_FRAC * margin (prevents frac×lev ≈ full wallet)
GROSS_FRAC = float(os.getenv("GROSS_FRAC", "0.25"))
# per-name |notional| <= NAME_FRAC * gross
NAME_FRAC = float(os.getenv("NAME_FRAC", "0.25"))

# --- turnover / cost gates ---
FEE_BPS = float(os.getenv("FEE_BPS", "8"))
# |ΔV| must clear COST_MULT × fee(ΔV)
COST_MULT = float(os.getenv("COST_MULT", "10.0"))
# ignore weight changes smaller than this (unit gross)
WEIGHT_DEADBAND = float(os.getenv("WEIGHT_DEADBAND", "0.03"))
# absolute min rebalance notional USDT (binds when fee×mult is tiny)
MIN_REBALANCE_USDT = float(os.getenv("MIN_REBALANCE_USDT", "40"))
MIN_NOTIONAL = float(os.getenv("MIN_NOTIONAL", "5"))

# slow clock — residual books should be boring
REBALANCE_S = int(os.getenv("REBALANCE_SECONDS", "14400"))  # 4h

# kill-switch: halt new risk if margin drawdown from session peak
MAX_DRAWDOWN_FRAC = float(os.getenv("MAX_DRAWDOWN_FRAC", "0.03"))  # 3%

DRY_RUN = os.getenv("DRY_RUN", "1") not in ("0", "false", "False")
RUN_ONCE = os.getenv("RUN_ONCE", "0") in ("1", "true", "True")

# persistence
STATE_PATH = Path(os.getenv("CSZN_STATE", str(Path(__file__).resolve().parent / "state.json")))
LOG_DIR = Path(os.getenv("CSZN_LOG_DIR", str(_ROOT / "logs" / "cszn")))
