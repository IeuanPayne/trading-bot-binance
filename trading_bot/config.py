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


def _as_csv_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]

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

# Strategy defaults
EMA1_LEN = _as_int(os.getenv("EMA1_LEN"), default=8)
EMA2_LEN = _as_int(os.getenv("EMA2_LEN"), default=13)
EMA3_LEN = _as_int(os.getenv("EMA3_LEN"), default=21)
EMA4_LEN = _as_int(os.getenv("EMA4_LEN"), default=34)
EMA5_LEN = _as_int(os.getenv("EMA5_LEN"), default=55)
SESSION = os.getenv("SESSION", "Both")
LONDON_START = _as_int(os.getenv("LONDON_START"), default=11)
LONDON_END = _as_int(os.getenv("LONDON_END"), default=20)
NEWYORK_START = _as_int(os.getenv("NEWYORK_START"), default=16)
NEWYORK_END = _as_int(os.getenv("NEWYORK_END"), default=25)
SESSION_TZ_OFFSET = _as_int(os.getenv("SESSION_TZ_OFFSET"), default=3)
MAX_SPREAD_PIPS = _as_float(os.getenv("MAX_SPREAD_PIPS"), default=3.0)
MODELED_SPREAD_PIPS = _as_float(os.getenv("MODELED_SPREAD_PIPS"), default=0.0)
PIP_SIZE = _as_float(os.getenv("PIP_SIZE"), default=0.10)
MT5_USE_RISK_PCT = _as_bool(os.getenv("MT5_USE_RISK_PCT", "True"), default=True)
MT5_RISK_PCT = _as_float(os.getenv("MT5_RISK_PCT"), default=1.0)
MT5_SL_PIPS = _as_float(os.getenv("MT5_SL_PIPS"), default=70.0)
MT5_TP_PIPS = _as_float(os.getenv("MT5_TP_PIPS"), default=70.0)
MT5_SLIPPAGE = _as_int(os.getenv("MT5_SLIPPAGE"), default=30)
MT5_AUTO_MAGIC = _as_bool(os.getenv("MT5_AUTO_MAGIC", "True"), default=True)
MT5_BASE_MAGIC = _as_int(os.getenv("MT5_BASE_MAGIC"), default=20260629)
MT5_SIGNAL_DEBUG = _as_bool(os.getenv("MT5_SIGNAL_DEBUG", "False"), default=False)
TV_WEBHOOK_HOST = os.getenv("TV_WEBHOOK_HOST", "0.0.0.0")
TV_WEBHOOK_PORT = _as_int(os.getenv("TV_WEBHOOK_PORT"), default=8080)
TV_WEBHOOK_PATH = os.getenv("TV_WEBHOOK_PATH", "/tradingview/webhook")
TV_WEBHOOK_SECRET = os.getenv("TV_WEBHOOK_SECRET")
TV_ALLOWED_SYMBOLS = _as_csv_list(os.getenv("TV_ALLOWED_SYMBOLS"))
TV_ALLOWED_TIMEFRAMES = _as_csv_list(os.getenv("TV_ALLOWED_TIMEFRAMES"))

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
MT5_STATE_FILE = os.getenv("MT5_STATE_FILE", "mt5_trading_state.db")


def validate_runtime_args(mode: str, order_pct: float, stop_pips: float) -> None:
    """Validate runtime args and fail fast for unsafe/invalid settings."""
    if INITIAL_CAPITAL <= 0:
        raise ValueError("INITIAL_CAPITAL must be greater than zero")

    if mode in ("paper", "backtest"):
        if order_pct <= 0 or order_pct > 1:
            raise ValueError("order-pct must be in (0, 1], where 0.01 means 1%")
        if stop_pips <= 0:
            raise ValueError("stop-pips must be greater than zero (absolute price distance)")

    if mode in ("mt5", "tv-webhook"):
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
    if SESSION not in ("London", "NewYork", "Both", "Off"):
        raise ValueError("SESSION must be one of: London, NewYork, Both, Off")
    if MAX_SPREAD_PIPS < 0:
        raise ValueError("MAX_SPREAD_PIPS must be >= 0")
    if MODELED_SPREAD_PIPS < 0:
        raise ValueError("MODELED_SPREAD_PIPS must be >= 0")
    if PIP_SIZE <= 0:
        raise ValueError("PIP_SIZE must be > 0")
    if MT5_RISK_PCT < 0:
        raise ValueError("MT5_RISK_PCT must be >= 0")
    if MT5_SL_PIPS <= 0:
        raise ValueError("MT5_SL_PIPS must be > 0")
    if MT5_TP_PIPS <= 0:
        raise ValueError("MT5_TP_PIPS must be > 0")
    if MT5_SLIPPAGE < 0:
        raise ValueError("MT5_SLIPPAGE must be >= 0")
    if TV_WEBHOOK_PORT <= 0 or TV_WEBHOOK_PORT > 65535:
        raise ValueError("TV_WEBHOOK_PORT must be in 1..65535")

    if mode == "paper" and not BINANCE_TESTNET and not ALLOW_LIVE_TRADING:
        raise ValueError(
            "BINANCE_TESTNET is False but ALLOW_LIVE_TRADING is not enabled; refusing startup for safety"
        )
