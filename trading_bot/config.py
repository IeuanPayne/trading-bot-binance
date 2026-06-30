import os
from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes")

# Binance/testnet settings
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
BINANCE_TESTNET = _as_bool(os.getenv("BINANCE_TESTNET", "True"), default=True)
ALLOW_LIVE_TRADING = _as_bool(os.getenv("ALLOW_LIVE_TRADING", "False"), default=False)

# Backtest / risk defaults
INITIAL_CAPITAL = 10000.0
MAX_PCT_PER_TRADE = 0.01  # 1% default
MAX_CONCURRENT_TRADES = 3


def validate_runtime_args(mode: str, order_pct: float, stop_pips: float) -> None:
    """Validate runtime args and fail fast for unsafe/invalid settings."""
    if INITIAL_CAPITAL <= 0:
        raise ValueError("INITIAL_CAPITAL must be greater than zero")

    if mode in ("paper", "backtest"):
        if order_pct <= 0 or order_pct > 1:
            raise ValueError("order-pct must be in (0, 1], where 0.01 means 1%")
        if stop_pips <= 0:
            raise ValueError("stop-pips must be greater than zero (absolute price distance)")

    if mode == "paper" and not BINANCE_TESTNET and not ALLOW_LIVE_TRADING:
        raise ValueError(
            "BINANCE_TESTNET is False but ALLOW_LIVE_TRADING is not enabled; refusing startup for safety"
        )
