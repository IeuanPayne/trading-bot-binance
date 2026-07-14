import os
from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes")


def _as_float(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _as_int(value: str | None, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default

# Binance/testnet settings
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
BINANCE_TESTNET = _as_bool(os.getenv("BINANCE_TESTNET", "True"), default=True)
ALLOW_LIVE_TRADING = _as_bool(os.getenv("ALLOW_LIVE_TRADING", "False"), default=False)

# Backtest / risk defaults
INITIAL_CAPITAL = 10000.0
MAX_PCT_PER_TRADE = 0.01  # 1% default
MAX_CONCURRENT_TRADES = 3
MAX_DAILY_LOSS_USDT = _as_float(os.getenv("MAX_DAILY_LOSS_USDT"), default=0.0)
MAX_DRAWDOWN_PCT = _as_float(os.getenv("MAX_DRAWDOWN_PCT"), default=0.0)
MAX_CONSECUTIVE_LOSSES = _as_int(os.getenv("MAX_CONSECUTIVE_LOSSES"), default=0)
MAX_TRADES_PER_DAY = _as_int(os.getenv("MAX_TRADES_PER_DAY"), default=0)

# Alerting settings
ALERTS_ENABLED = _as_bool(os.getenv("ALERTS_ENABLED", "False"), default=False)
ALERT_SMS_PROVIDER = os.getenv("ALERT_SMS_PROVIDER", "twilio")
ALERT_PHONE_TO = os.getenv("ALERT_PHONE_TO")
ALERT_PHONE_FROM = os.getenv("ALERT_PHONE_FROM")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

# MT5 settings
MT5_ENABLED = _as_bool(os.getenv("MT5_ENABLED", "False"), default=False)
MT5_LOGIN = os.getenv("MT5_LOGIN")
MT5_PASSWORD = os.getenv("MT5_PASSWORD")
MT5_SERVER = os.getenv("MT5_SERVER")
MT5_TERMINAL_PATH = os.getenv("MT5_TERMINAL_PATH")
MT5_SYMBOL = os.getenv("MT5_SYMBOL", "BTCUSD")


def validate_runtime_args(mode: str, order_pct: float, stop_pips: float) -> None:
    """Validate runtime args and fail fast for unsafe/invalid settings."""
    if INITIAL_CAPITAL <= 0:
        raise ValueError("INITIAL_CAPITAL must be greater than zero")

    if mode in ("paper", "backtest"):
        if order_pct <= 0 or order_pct > 1:
            raise ValueError("order-pct must be in (0, 1], where 0.01 means 1%")
        if stop_pips <= 0:
            raise ValueError("stop-pips must be greater than zero (absolute price distance)")

    if mode == "mt5":
        if not MT5_ENABLED:
            raise ValueError("MT5 mode requires MT5_ENABLED=True")
        if not MT5_LOGIN or not MT5_PASSWORD or not MT5_SERVER:
            raise ValueError("MT5 mode requires MT5_LOGIN, MT5_PASSWORD and MT5_SERVER")
        if order_pct <= 0 or order_pct > 1:
            raise ValueError("order-pct must be in (0, 1], where 0.01 means 1%")
        if stop_pips <= 0:
            raise ValueError("stop-pips must be greater than zero (absolute price distance)")

    if MAX_DAILY_LOSS_USDT < 0:
        raise ValueError("MAX_DAILY_LOSS_USDT must be >= 0")
    if MAX_DRAWDOWN_PCT < 0:
        raise ValueError("MAX_DRAWDOWN_PCT must be >= 0")
    if MAX_CONSECUTIVE_LOSSES < 0:
        raise ValueError("MAX_CONSECUTIVE_LOSSES must be >= 0")
    if MAX_TRADES_PER_DAY < 0:
        raise ValueError("MAX_TRADES_PER_DAY must be >= 0")

    if mode == "paper" and not BINANCE_TESTNET and not ALLOW_LIVE_TRADING:
        raise ValueError(
            "BINANCE_TESTNET is False but ALLOW_LIVE_TRADING is not enabled; refusing startup for safety"
        )
