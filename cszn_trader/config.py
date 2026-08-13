"""Settings for the residual demo futures book.

Jim Simons alignment here means fixed rules, scarce risk, sparse signals,
slow clock, and cost-aware turnover — no discretionary overrides.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# project root so .env sits beside the package
_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")

# demo account keys
API_KEY = os.getenv("API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")

# one venue for both market data and orders (no live/demo mix)
FAPI_BASE = os.getenv("BINANCE_FAPI_URL", "https://demo-fapi.binance.com").rstrip("/")
MARKET_BASE = os.getenv("BINANCE_MARKET_URL", FAPI_BASE).rstrip("/")

# Bitcoin futures: factor only, never a traded target
BENCHMARK = "BTCUSDT"
# liquid United States dollar perpetual names verified trading on demo
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

# candle size for residual and beta estimation
INTERVAL = os.getenv("KLINE_INTERVAL", "1h")
# rolling window length for Bitcoin beta
BETA_WINDOW = int(os.getenv("BETA_WINDOW", "48"))
# how many residual bars to sum for the rank signal
RESID_LOOKBACK = int(os.getenv("RESID_LOOKBACK", "12"))
# pull enough bars for beta + lookback + buffer (exchange cap applies)
KLINE_LIMIT = min(1500, BETA_WINDOW + RESID_LOOKBACK + 50)

# clip cross-sectional z-scores to this absolute value
Z_CLIP = float(os.getenv("Z_CLIP", "3.0"))
# ignore names weaker than this absolute z-score (sparse book)
Z_MIN = float(os.getenv("Z_MIN", "1.0"))

# fraction of margin balance allowed as initial-margin budget
COLLATERAL_FRAC = float(os.getenv("COLLATERAL_FRAC", "0.05"))
# hard United States dollar ceiling on that budget; zero disables the ceiling
MAX_COLLATERAL_USDT = float(os.getenv("MAX_COLLATERAL_USDT", "200"))
# exchange leverage amplifies notional from the collateral budget only
EXCHANGE_LEVERAGE = int(os.getenv("EXCHANGE_LEVERAGE", "5"))
# gross notional may not exceed this fraction of margin
GROSS_FRAC = float(os.getenv("GROSS_FRAC", "0.25"))
# one name may not exceed this fraction of gross notional
NAME_FRAC = float(os.getenv("NAME_FRAC", "0.25"))

# taker fee estimate in basis points of notional
FEE_BPS = float(os.getenv("FEE_BPS", "8"))
# require trade size to clear this many times estimated fee
COST_MULT = float(os.getenv("COST_MULT", "10.0"))
# ignore weight changes smaller than this (unit-gross space)
WEIGHT_DEADBAND = float(os.getenv("WEIGHT_DEADBAND", "0.03"))
# absolute minimum rebalance notional in United States dollars
MIN_REBALANCE_USDT = float(os.getenv("MIN_REBALANCE_USDT", "40"))
# exchange-style minimum notional fallback
MIN_NOTIONAL = float(os.getenv("MIN_NOTIONAL", "5"))

# seconds between fixed-clock rebalances (default four hours)
REBALANCE_S = int(os.getenv("REBALANCE_SECONDS", "14400"))

# halt and flatten if margin falls this fraction from session peak
MAX_DRAWDOWN_FRAC = float(os.getenv("MAX_DRAWDOWN_FRAC", "0.03"))

# one means compute only; zero means send live demo orders
DRY_RUN = os.getenv("DRY_RUN", "1") not in ("0", "false", "False")
# one means exit after a single cycle
RUN_ONCE = os.getenv("RUN_ONCE", "0") in ("1", "true", "True")

# where prior weights and halt flag live
STATE_PATH = Path(os.getenv("CSZN_STATE", str(Path(__file__).resolve().parent / "state.json")))
# structured cycle logs
LOG_DIR = Path(os.getenv("CSZN_LOG_DIR", str(_ROOT / "logs" / "cszn")))
