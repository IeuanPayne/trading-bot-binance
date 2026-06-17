import os
from dotenv import load_dotenv

load_dotenv()

# Binance/testnet settings
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
BINANCE_TESTNET = os.getenv("BINANCE_TESTNET", "True").lower() in ("1", "true", "yes")

# Backtest / risk defaults
INITIAL_CAPITAL = 10000.0
MAX_PCT_PER_TRADE = 0.01  # 1% default
MAX_CONCURRENT_TRADES = 3
