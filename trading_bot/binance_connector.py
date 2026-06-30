import math
import requests
import pandas as pd
from binance.client import Client
from loguru import logger
from typing import Optional, Dict, Any, Tuple

BASE_URL: str = "https://api.binance.com"
TESTNET_BASE_URL: str = "https://testnet.binance.vision"


class BinanceConnector:
    """Wrapper around Binance API for fetching klines and placing orders."""
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        testnet: bool = False,
    ) -> None:
        """Initialize Binance connector.
        
        Args:
            base_url: Override base URL (default: testnet or live based on testnet flag)
            api_key: Binance API key for authenticated calls
            api_secret: Binance API secret for authenticated calls
            testnet: If True, use testnet endpoints
        """
        self.testnet: bool = testnet
        self.base: str = base_url or (TESTNET_BASE_URL if testnet else BASE_URL)
        self.client: Optional[Client] = None

        if api_key and api_secret:
            self.client = Client(api_key, api_secret, testnet=testnet)
            self.client.API_URL = f"{self.base}/api"

    def fetch_klines(self, symbol: str, interval: str = "1h", limit: int = 500) -> pd.DataFrame:
        """Fetch recent klines (candlesticks) from Binance.
        
        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            interval: Candle interval (1m, 5m, 15m, 1h, 4h, 1d, etc.)
            limit: Number of candles to fetch (max 1000)
        
        Returns:
            DataFrame with columns: open_time, open, high, low, close, volume, close_time
        """
        raw_data: list
        if self.client:
            raw_data = self.client.get_klines(symbol=symbol, interval=interval, limit=limit)
        else:
            endpoint: str = f"{self.base}/api/v3/klines"
            params: Dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
            logger.debug("Requesting klines: {}", params)
            r: requests.Response = requests.get(endpoint, params=params, timeout=10)
            r.raise_for_status()
            raw_data = r.json()

        cols: list = [
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
        df: pd.DataFrame = pd.DataFrame(raw_data, columns=cols)
        df = df[["open_time", "open", "high", "low", "close", "volume", "close_time"]]
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df

    def get_symbol_price(self, symbol: str) -> Dict[str, Any]:
        """Get current price of a trading pair.
        
        Args:
            symbol: Trading pair symbol
        
        Returns:
            Dict with 'price' key
        """
        if self.client is None:
            return {"price": 0.0}
        return self.client.get_symbol_ticker(symbol=symbol)

    def get_asset_balance(self, asset: str) -> Dict[str, Any]:
        """Get account balance for an asset.
        
        Args:
            asset: Asset symbol (e.g., 'USDT', 'BTC')
        
        Returns:
            Dict with 'free' and 'locked' balance
        """
        if self.client is None:
            return {"free": 0.0, "locked": 0.0}
        balance: Optional[Dict[str, Any]] = self.client.get_asset_balance(asset=asset)
        return balance or {"free": 0.0, "locked": 0.0}

    def create_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a market order.
        
        Args:
            symbol: Trading pair
            side: 'BUY' or 'SELL'
            quantity: Order quantity
        
        Returns:
            Order response dict
        
        Raises:
            RuntimeError: If client is not authenticated
        """
        if self.client is None:
            raise RuntimeError("Binance client is not initialized for trading")
        payload: Dict[str, Any] = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "MARKET",
            "quantity": quantity,
        }
        if client_order_id:
            payload["newClientOrderId"] = client_order_id
        return self.client.create_order(**payload)

    def create_oco_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        stop_price: float,
        stop_limit_price: float,
        list_client_order_id: Optional[str] = None,
        limit_client_order_id: Optional[str] = None,
        stop_client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create One-Cancels-Other order (take profit + stop loss).
        
        Args:
            symbol: Trading pair
            side: 'BUY' or 'SELL'
            quantity: Order quantity
            price: Take profit price (limit order price)
            stop_price: Stop-loss trigger price
            stop_limit_price: Stop-loss limit price
        
        Returns:
            OCO order response dict
        
        Raises:
            RuntimeError: If client is not authenticated
        """
        if self.client is None:
            raise RuntimeError("Binance client is not initialized for trading")
        payload: Dict[str, Any] = {
            "symbol": symbol,
            "side": side.upper(),
            "quantity": quantity,
            "price": str(price),
            "stopPrice": str(stop_price),
            "stopLimitPrice": str(stop_limit_price),
            "stopLimitTimeInForce": "GTC",
        }
        if list_client_order_id:
            payload["listClientOrderId"] = list_client_order_id
        if limit_client_order_id:
            payload["limitClientOrderId"] = limit_client_order_id
        if stop_client_order_id:
            payload["stopClientOrderId"] = stop_client_order_id
        return self.client.create_oco_order(
            **payload,
        )

    def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get Binance symbol metadata (filters, precision, etc.)."""
        if self.client is None:
            return None
        return self.client.get_symbol_info(symbol)

    def round_price(self, symbol: str, price: float) -> float:
        """Round price to Binance tick size for the symbol."""
        if self.client is None:
            return price
        info = self.get_symbol_info(symbol)
        if not info:
            return price

        tick_size = 0.0
        for f in info.get("filters", []):
            if f.get("filterType") == "PRICE_FILTER":
                tick_size = float(f.get("tickSize", 0.0))
                break

        if tick_size <= 0:
            return price

        precision = max(0, -int(math.floor(math.log10(tick_size))))
        rounded = math.floor(price / tick_size) * tick_size
        return round(rounded, precision)

    def round_quantity(self, symbol: str, quantity: float) -> float:
        """Round quantity to valid step size for symbol.
        
        Args:
            symbol: Trading pair
            quantity: Desired quantity
        
        Returns:
            Rounded quantity that matches Binance lot size requirements
        """
        if self.client is None:
            return quantity
        info: Optional[Dict[str, Any]] = self.client.get_symbol_info(symbol)
        if not info:
            return quantity
        step_size: float = 1.0
        for f in info.get("filters", []):
            if f.get("filterType") == "LOT_SIZE":
                step_size = float(f.get("stepSize", 1.0))
                break

        if step_size <= 0:
            return quantity

        precision: int = max(0, -int(math.floor(math.log10(step_size))))
        rounded: float = math.floor(quantity / step_size) * step_size
        return round(rounded, precision)

    def validate_market_order(self, symbol: str, quantity: float, reference_price: float) -> Tuple[bool, str]:
        """Validate a spot market order against Binance symbol filters.

        Args:
            symbol: Trading pair
            quantity: Base asset quantity
            reference_price: Latest price used for notional checks

        Returns:
            Tuple of (is_valid, message).
        """
        if quantity <= 0:
            return False, "quantity must be greater than zero"
        if reference_price <= 0:
            return False, "reference price must be greater than zero"

        info = self.get_symbol_info(symbol)
        if not info:
            return False, f"symbol info unavailable for {symbol}"

        filters = {f.get("filterType"): f for f in info.get("filters", [])}

        lot_filter = filters.get("LOT_SIZE") or filters.get("MARKET_LOT_SIZE")
        if lot_filter:
            min_qty = float(lot_filter.get("minQty", 0.0))
            max_qty = float(lot_filter.get("maxQty", 0.0))
            if min_qty and quantity < min_qty:
                return False, f"quantity {quantity} is below minQty {min_qty}"
            if max_qty and quantity > max_qty:
                return False, f"quantity {quantity} is above maxQty {max_qty}"

        notional = quantity * reference_price
        min_notional = 0.0
        if "MIN_NOTIONAL" in filters:
            min_notional = float(filters["MIN_NOTIONAL"].get("minNotional", 0.0))
        elif "NOTIONAL" in filters:
            min_notional = float(filters["NOTIONAL"].get("minNotional", 0.0))

        if min_notional and notional < min_notional:
            return False, f"notional {notional} is below minNotional {min_notional}"

        return True, "ok"
