"""
COMPARTMENT: config
ROLE:        knobs only — no logic
IN:          environment / .env
OUT:         module-level constants consumed by every other node
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# ── load ────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")

# ── credentials ─────────────────────────────────────────────────────
API_KEY = os.getenv("API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")

# ── venue (demo for data + orders) ──────────────────────────────────
FAPI_BASE = os.getenv("BINANCE_FAPI_URL", "https://demo-fapi.binance.com").rstrip("/")
MARKET_BASE = os.getenv("BINANCE_MARKET_URL", FAPI_BASE).rstrip("/")

# ── names ───────────────────────────────────────────────────────────
BENCHMARK = "BTCUSDT"
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

# ── signal windows ──────────────────────────────────────────────────
INTERVAL = os.getenv("KLINE_INTERVAL", "1h")
BETA_WINDOW = int(os.getenv("BETA_WINDOW", "48"))
RESID_LOOKBACK = int(os.getenv("RESID_LOOKBACK", "12"))
KLINE_LIMIT = min(1500, BETA_WINDOW + RESID_LOOKBACK + 50)
Z_CLIP = float(os.getenv("Z_CLIP", "3.0"))
Z_MIN = float(os.getenv("Z_MIN", "1.0"))

# ── risk budget ─────────────────────────────────────────────────────
COLLATERAL_FRAC = float(os.getenv("COLLATERAL_FRAC", "0.05"))
MAX_COLLATERAL_USDT = float(os.getenv("MAX_COLLATERAL_USDT", "200"))
EXCHANGE_LEVERAGE = int(os.getenv("EXCHANGE_LEVERAGE", "5"))
GROSS_FRAC = float(os.getenv("GROSS_FRAC", "0.25"))
NAME_FRAC = float(os.getenv("NAME_FRAC", "0.25"))

# ── turnover / cost ─────────────────────────────────────────────────
FEE_BPS = float(os.getenv("FEE_BPS", "8"))
COST_MULT = float(os.getenv("COST_MULT", "10.0"))
WEIGHT_DEADBAND = float(os.getenv("WEIGHT_DEADBAND", "0.03"))
MIN_REBALANCE_USDT = float(os.getenv("MIN_REBALANCE_USDT", "40"))
MIN_NOTIONAL = float(os.getenv("MIN_NOTIONAL", "5"))

# ── clock + halt ────────────────────────────────────────────────────
REBALANCE_S = int(os.getenv("REBALANCE_SECONDS", "14400"))
MAX_DRAWDOWN_FRAC = float(os.getenv("MAX_DRAWDOWN_FRAC", "0.03"))
DRY_RUN = os.getenv("DRY_RUN", "1") not in ("0", "false", "False")
RUN_ONCE = os.getenv("RUN_ONCE", "0") in ("1", "true", "True")

# ── persistence paths ───────────────────────────────────────────────
STATE_PATH = Path(os.getenv("CSZN_STATE", str(Path(__file__).resolve().parent / "state.json")))
LOG_DIR = Path(os.getenv("CSZN_LOG_DIR", str(_ROOT / "logs" / "cszn")))
