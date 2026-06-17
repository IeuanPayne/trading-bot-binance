import math
import requests
import pandas as pd
from binance.client import Client
from loguru import logger

BASE_URL = "https://api.binance.com"
TESTNET_BASE_URL = "https://testnet.binance.vision"


class BinanceConnector:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        testnet: bool = False,
    ):
        self.testnet = testnet
        self.base = base_url or (TESTNET_BASE_URL if testnet else BASE_URL)
        self.client = None

        if api_key and api_secret:
            self.client = Client(api_key, api_secret, testnet=testnet)
            self.client.API_URL = f"{self.base}/api"

    def fetch_klines(self, symbol: str, interval: str = "1h", limit: int = 500) -> pd.DataFrame:
        """Fetch recent klines from Binance and return a DataFrame."""
        if self.client:
            data = self.client.get_klines(symbol=symbol, interval=interval, limit=limit)
        else:
            endpoint = f"{self.base}/api/v3/klines"
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            logger.debug("Requesting klines: {}", params)
            r = requests.get(endpoint, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()

        cols = [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "ignore1",
            "ignore2",
            "ignore3",
            "ignore4",
            "ignore5",
        ]
        df = pd.DataFrame(data, columns=cols)
        df = df[["open_time", "open", "high", "low", "close", "volume", "close_time"]]
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df

    def get_symbol_price(self, symbol: str) -> dict:
        if self.client is None:
            return {"price": 0.0}
        return self.client.get_symbol_ticker(symbol=symbol)

    def get_asset_balance(self, asset: str) -> dict:
        if self.client is None:
            return {"free": 0.0, "locked": 0.0}
        balance = self.client.get_asset_balance(asset=asset)
        return balance or {"free": 0.0, "locked": 0.0}

    def create_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        if self.client is None:
            raise RuntimeError("Binance client is not initialized for trading")
        return self.client.create_order(symbol=symbol, side=side.upper(), type="MARKET", quantity=quantity)

    def create_oco_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        stop_price: float,
        stop_limit_price: float,
    ) -> dict:
        if self.client is None:
            raise RuntimeError("Binance client is not initialized for trading")
        return self.client.create_oco_order(
            symbol=symbol,
            side=side.upper(),
            quantity=quantity,
            price=str(price),
            stopPrice=str(stop_price),
            stopLimitPrice=str(stop_limit_price),
            stopLimitTimeInForce="GTC",
        )

    def round_quantity(self, symbol: str, quantity: float) -> float:
        if self.client is None:
            return quantity
        info = self.client.get_symbol_info(symbol)
        if not info:
            return quantity
        step_size = 1.0
        for f in info.get("filters", []):
            if f.get("filterType") == "LOT_SIZE":
                step_size = float(f.get("stepSize", 1.0))
                break

        if step_size <= 0:
            return quantity

        precision = max(0, -int(math.floor(math.log10(step_size))))
        rounded = math.floor(quantity / step_size) * step_size
        return round(rounded, precision)
