from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


@dataclass
class MT5ClosedOutcome:
    side: str
    volume: float
    entry_price: float
    exit_price: float
    pnl: float
    close_time: str
    reason: str


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
        """Compute lot size from risk using broker economics for the symbol."""
        if risk_amount <= 0 or sl_pips <= 0 or pip_size <= 0:
            return 0.0

        sl_distance = sl_pips * pip_size
        if sl_distance <= 0:
            return 0.0

        # Prefer MT5's own profit model for a 1-lot adverse move to SL.
        loss_per_lot = 0.0
        entry = self.get_symbol_price(symbol, side="BUY")
        if entry > 0 and hasattr(mt5, "order_calc_profit") and hasattr(mt5, "ORDER_TYPE_BUY"):
            try:
                adverse_close = max(0.0, entry - sl_distance)
                estimated = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, symbol, 1.0, entry, adverse_close)
                if estimated is not None:
                    loss_per_lot = abs(float(estimated))
            except Exception:
                loss_per_lot = 0.0

        # Fallback: derive per-lot loss from symbol tick value and tick size.
        if loss_per_lot <= 0:
            info = mt5.symbol_info(symbol)
            if info is not None:
                tick_size = float(
                    getattr(info, "trade_tick_size", 0.0) or getattr(info, "point", 0.0) or 0.0
                )
                tick_value = float(
                    getattr(info, "trade_tick_value_loss", 0.0)
                    or getattr(info, "trade_tick_value", 0.0)
                    or 0.0
                )
                if tick_size > 0 and tick_value > 0:
                    ticks_to_sl = sl_distance / tick_size
                    loss_per_lot = abs(ticks_to_sl * tick_value)

        # Last-resort fallback keeps behavior predictable if broker metadata is unavailable.
        if loss_per_lot <= 0:
            loss_per_lot = sl_distance * 100.0

        lots = risk_amount / loss_per_lot if loss_per_lot > 0 else 0.0
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

    def get_latest_closed_outcome(self, symbol: str, magic: Optional[int] = None, lookback_days: int = 7) -> Optional[MT5ClosedOutcome]:
        """Return latest closed trade outcome for symbol/magic from MT5 deal history."""
        if mt5 is None:
            return None

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=max(1, lookback_days))
        deals = mt5.history_deals_get(start, end)
        if not deals:
            return None

        deal_entry_out = int(getattr(mt5, "DEAL_ENTRY_OUT", 1))
        deal_entry_out_by = int(getattr(mt5, "DEAL_ENTRY_OUT_BY", 3))
        deal_entry_in = int(getattr(mt5, "DEAL_ENTRY_IN", 0))
        buy_type = int(getattr(mt5, "DEAL_TYPE_BUY", 0))

        filtered = [d for d in deals if str(getattr(d, "symbol", "")) == symbol]
        if magic is not None:
            filtered = [d for d in filtered if int(getattr(d, "magic", 0)) == int(magic)]
        if not filtered:
            return None

        filtered.sort(key=lambda d: int(getattr(d, "time_msc", 0) or 0))
        out_deal = None
        for d in reversed(filtered):
            entry_code = int(getattr(d, "entry", -1))
            if entry_code in (deal_entry_out, deal_entry_out_by):
                out_deal = d
                break
        if out_deal is None:
            return None

        position_id = int(getattr(out_deal, "position_id", 0) or 0)
        in_deal = None
        if position_id > 0:
            for d in reversed(filtered):
                if int(getattr(d, "position_id", 0) or 0) != position_id:
                    continue
                if int(getattr(d, "entry", -1)) == deal_entry_in:
                    in_deal = d
                    break

        if in_deal is None:
            return None

        side = "BUY" if int(getattr(in_deal, "type", -1)) == buy_type else "SELL"
        volume = float(getattr(out_deal, "volume", 0.0) or 0.0)
        entry_price = float(getattr(in_deal, "price", 0.0) or 0.0)
        exit_price = float(getattr(out_deal, "price", 0.0) or 0.0)
        profit = float(getattr(out_deal, "profit", 0.0) or 0.0)
        commission = float(getattr(out_deal, "commission", 0.0) or 0.0)
        swap = float(getattr(out_deal, "swap", 0.0) or 0.0)
        pnl = profit + commission + swap
        close_ts = datetime.fromtimestamp(int(getattr(out_deal, "time", 0) or 0), tz=timezone.utc).isoformat()
        reason = str(getattr(out_deal, "comment", "") or "closed")

        return MT5ClosedOutcome(
            side=side,
            volume=volume,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
            close_time=close_ts,
            reason=reason,
        )
