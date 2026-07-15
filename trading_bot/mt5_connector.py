from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

import pandas as pd
from loguru import logger

try:
    import MetaTrader5 as mt5  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - environment dependent
    mt5 = None


_TIMEFRAME_MAP = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


@dataclass
class MT5Position:
    ticket: int
    side: str
    volume: float
    price_open: float
    magic: int


class MT5Connector:
    """Thin wrapper over MetaTrader 5 terminal API."""

    def __init__(
        self,
        login: int,
        password: str,
        server: str,
        terminal_path: Optional[str] = None,
        deviation: int = 20,
        magic: int = 90001,
    ) -> None:
        self.login = login
        self.password = password
        self.server = server
        self.terminal_path = terminal_path
        self.deviation = deviation
        self.magic = magic

    def connect(self) -> None:
        if mt5 is None:
            raise RuntimeError(
                "MetaTrader5 package is not available on this host. MT5 Python integration requires Windows + installed MT5 terminal."
            )

        init_ok = mt5.initialize(path=self.terminal_path) if self.terminal_path else mt5.initialize()
        if not init_ok:
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

        login_ok = mt5.login(self.login, password=self.password, server=self.server)
        if not login_ok:
            mt5.shutdown()
            raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")

    def shutdown(self) -> None:
        if mt5 is not None:
            mt5.shutdown()

    def _timeframe(self, interval: str) -> int:
        if interval not in _TIMEFRAME_MAP:
            raise ValueError(f"Unsupported MT5 interval: {interval}")
        minutes = _TIMEFRAME_MAP[interval]
        attr = f"TIMEFRAME_M{minutes}" if minutes < 60 else None
        if minutes == 60:
            attr = "TIMEFRAME_H1"
        elif minutes == 240:
            attr = "TIMEFRAME_H4"
        elif minutes == 1440:
            attr = "TIMEFRAME_D1"
        if not attr or not hasattr(mt5, attr):
            raise ValueError(f"Unsupported MT5 timeframe mapping for interval: {interval}")
        return getattr(mt5, attr)

    def ensure_symbol(self, symbol: str) -> None:
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"MT5 symbol not found: {symbol}")
        if not info.visible and not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"MT5 unable to select symbol: {symbol}")

    def fetch_rates(self, symbol: str, interval: str = "15m", limit: int = 500) -> pd.DataFrame:
        self.ensure_symbol(symbol)
        timeframe = self._timeframe(interval)
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, limit)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["open_time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        close_delta = timedelta(minutes=_TIMEFRAME_MAP[interval])
        df["close_time"] = df["open_time"] + close_delta
        df = df.rename(columns={"tick_volume": "volume"})
        return df[["open_time", "open", "high", "low", "close", "volume", "close_time"]]

    def get_account_balance(self) -> float:
        info = mt5.account_info()
        if info is None:
            return 0.0
        return float(info.balance)

    def get_account_equity(self) -> float:
        info = mt5.account_info()
        if info is None:
            return 0.0
        return float(info.equity)

    def get_symbol_price(self, symbol: str, side: str = "BUY") -> float:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return 0.0
        return float(tick.ask if side.upper() == "BUY" else tick.bid)

    def get_spread_pips(self, symbol: str, pip_size: float = 0.10) -> float:
        if pip_size <= 0:
            return 0.0
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return 0.0
        return float(tick.ask - tick.bid) / pip_size

    def get_net_position(self, symbol: str, magic: Optional[int] = None) -> Optional[MT5Position]:
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return None
        pos = None
        if magic is None:
            pos = positions[0]
        else:
            for candidate in positions:
                if int(getattr(candidate, "magic", 0)) == int(magic):
                    pos = candidate
                    break
        if pos is None:
            return None
        side = "BUY" if int(pos.type) == mt5.POSITION_TYPE_BUY else "SELL"
        return MT5Position(
            ticket=int(pos.ticket),
            side=side,
            volume=float(pos.volume),
            price_open=float(pos.price_open),
            magic=int(getattr(pos, "magic", 0)),
        )

    def volume_from_risk_pips(self, symbol: str, risk_amount: float, sl_pips: float, pip_size: float) -> float:
        """Mirror the EA risk model where risk is sized against SL in pips."""
        if risk_amount <= 0 or sl_pips <= 0 or pip_size <= 0:
            return 0.0

        # EA equivalent:
        # sl_value = SL_Pips * PipSize      (dollar risk per 0.01 lot)
        # lots = risk_amt / (sl_value * 100)
        sl_value = sl_pips * pip_size
        denominator = sl_value * 100.0
        if denominator <= 0:
            return 0.0
        lots = risk_amount / denominator
        return self.normalize_volume(symbol, lots)

    def normalize_volume(self, symbol: str, volume: float) -> float:
        info = mt5.symbol_info(symbol)
        if info is None:
            return volume
        step = float(getattr(info, "volume_step", 0.01) or 0.01)
        min_volume = float(getattr(info, "volume_min", step) or step)
        max_volume = float(getattr(info, "volume_max", 100.0) or 100.0)

        steps = int(volume / step)
        normalized = steps * step
        normalized = max(min_volume, min(normalized, max_volume))
        decimals = max(0, len(str(step).split(".")[-1].rstrip("0")))
        return round(normalized, decimals)

    def volume_from_allocation(self, symbol: str, allocation: float, entry_price: float) -> float:
        info = mt5.symbol_info(symbol)
        if info is None or entry_price <= 0:
            return 0.0
        contract_size = float(getattr(info, "trade_contract_size", 1.0) or 1.0)
        volume = allocation / (entry_price * contract_size)
        return self.normalize_volume(symbol, volume)

    def place_market_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        sl: float,
        tp: float,
        comment: str,
    ) -> dict[str, Any]:
        side_up = side.upper()
        order_type = mt5.ORDER_TYPE_BUY if side_up == "BUY" else mt5.ORDER_TYPE_SELL
        price = self.get_symbol_price(symbol, side=side_up)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": self.deviation,
            "magic": self.magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None:
            raise RuntimeError(f"MT5 order_send returned None: {mt5.last_error()}")
        if int(result.retcode) != int(mt5.TRADE_RETCODE_DONE):
            raise RuntimeError(f"MT5 order failed retcode={result.retcode}, comment={result.comment}")
        return {"retcode": int(result.retcode), "order": int(result.order), "deal": int(result.deal)}

    def close_position(self, symbol: str, position: MT5Position, comment: str) -> dict[str, Any]:
        close_side = "SELL" if position.side == "BUY" else "BUY"
        order_type = mt5.ORDER_TYPE_SELL if close_side == "SELL" else mt5.ORDER_TYPE_BUY
        price = self.get_symbol_price(symbol, side=close_side)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "position": position.ticket,
            "volume": position.volume,
            "type": order_type,
            "price": price,
            "deviation": self.deviation,
            "magic": self.magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None:
            raise RuntimeError(f"MT5 close order returned None: {mt5.last_error()}")
        if int(result.retcode) != int(mt5.TRADE_RETCODE_DONE):
            raise RuntimeError(f"MT5 close failed retcode={result.retcode}, comment={result.comment}")
        logger.info("Closed MT5 position ticket={} symbol={} side={}", position.ticket, symbol, position.side)
        return {"retcode": int(result.retcode), "order": int(result.order), "deal": int(result.deal)}
