"""
COMPARTMENT: config
ROLE:        knobs only — no logic
IN:          environment / .env / frozen universe.csv
OUT:         module-level constants consumed by every other node
"""

from pathlib import Path
import csv
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
# Frozen membership file. Refresh snapshots with refresh_universe.py;
# rewrite this list only via refresh_universe.py --apply (never in the poll loop).
UNIVERSE_CSV = Path(
    os.getenv("CSZN_UNIVERSE_CSV", str(Path(__file__).resolve().parent / "data" / "universe.csv"))
)
# Safety net if the CSV is missing or empty.
_FALLBACK_UNIVERSE = [
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


def _load_universe(path: Path) -> list[str]:
    # IN: frozen CSV → OUT: enabled symbols (BTC never traded)
    if not path.exists():
        return list(_FALLBACK_UNIVERSE)
    out: list[str] = []
    with path.open() as f:
        for row in csv.DictReader(f):
            sym = (row.get("symbol") or "").strip()
            if not sym or sym == BENCHMARK:
                continue
            if str(row.get("enabled", "0")).strip() not in ("1", "true", "True"):
                continue
            out.append(sym)
    return out or list(_FALLBACK_UNIVERSE)


UNIVERSE = _load_universe(UNIVERSE_CSV)

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
# Per-name hard stop as a fraction of that name's notional. No take-profit.
# 0.6% checked every POLL_S — loser fuse is threshold × poll, not the 1h bar.
STOP_PCT = float(os.getenv("STOP_PCT", "0.006"))

# ── poll clock + halt ───────────────────────────────────────────────
# Watch often (default 60s) for stops. Full z-rebalance only when the 1h bar rolls.
# Adds still wait for Z_MIN + deadband + cost floor. No take-profit.
# REBALANCE_SECONDS kept as alias for older env files.
POLL_S = int(os.getenv("POLL_SECONDS", os.getenv("REBALANCE_SECONDS", "60")))
MAX_DRAWDOWN_FRAC = float(os.getenv("MAX_DRAWDOWN_FRAC", "0.03"))
DRY_RUN = os.getenv("DRY_RUN", "1") not in ("0", "false", "False")
RUN_ONCE = os.getenv("RUN_ONCE", "0") in ("1", "true", "True")

# ── persistence paths ───────────────────────────────────────────────
STATE_PATH = Path(os.getenv("CSZN_STATE", str(Path(__file__).resolve().parent / "state.json")))
LOG_DIR = Path(os.getenv("CSZN_LOG_DIR", str(_ROOT / "logs" / "cszn")))

# ── backtest (prod tape, not demo). Frozen rules. No optimizer. ─────
# Public klines only. Live orders stay on FAPI_BASE (demo).
BACKTEST_FAPI = os.getenv("BACKTEST_FAPI_URL", "https://fapi.binance.com").rstrip("/")
BACKTEST_DATA = Path(
    os.getenv("CSZN_BACKTEST_DATA", str(Path(__file__).resolve().parent / "data" / "klines_1h.csv"))
)
# Starting paper margin (equity before any trade).
BACKTEST_MARGIN = float(os.getenv("BACKTEST_MARGIN", "4000"))
# How many calendar days of 1h closes to cache.
BACKTEST_DAYS = int(os.getenv("BACKTEST_DAYS", "730"))
BACKTEST_REFRESH = os.getenv("BACKTEST_REFRESH", "0") in ("1", "true", "True")
# How many prod∩demo names --apply enables into universe.csv.
UNIVERSE_TOP_N = int(os.getenv("UNIVERSE_TOP_N", "30"))
