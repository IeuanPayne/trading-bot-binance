from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trading_bot.mt5_execution import _today_key, run_mt5_trade
from trading_bot.state_store import TradingStateStore


@dataclass
class _FakePosition:
    ticket: int
    side: str
    volume: float
    price_open: float


class FakeMT5Connector:
    def __init__(self):
        self.market_orders = []
        self.closed = []
        self.position = None

    def fetch_rates(self, symbol: str, interval: str = "15m", limit: int = 500):
        rows = max(limit, 2)
        df = pd.DataFrame(
            {
                "open": [100.0] * rows,
                "high": [101.0] * rows,
                "low": [99.0] * rows,
                "close": [100.0] * rows,
                "volume": [1.0] * rows,
                "open_time": pd.date_range("2026-01-01 14:00", periods=rows, freq="15min", tz="UTC"),
                "close_time": pd.date_range("2026-01-01 14:00", periods=rows, freq="15min", tz="UTC"),
            }
        )
        return df

    def get_net_position(self, symbol: str, magic: int | None = None):
        return self.position

    def get_symbol_price(self, symbol: str, side: str = "BUY") -> float:
        return 100.0 if side.upper() == "BUY" else 99.9

    def get_spread_pips(self, symbol: str, pip_size: float = 0.10) -> float:
        return 1.0

    def get_account_balance(self) -> float:
        return 10_000.0

    def get_account_equity(self) -> float:
        return 10_000.0

    def volume_from_allocation(self, symbol: str, allocation: float, entry_price: float) -> float:
        assert allocation > 0
        assert entry_price > 0
        return 0.01

    def volume_from_risk_pips(self, symbol: str, risk_amount: float, sl_pips: float, pip_size: float) -> float:
        assert risk_amount > 0
        assert sl_pips > 0
        assert pip_size > 0
        return 0.01

    def place_market_order(self, symbol: str, side: str, volume: float, sl: float, tp: float, comment: str):
        self.market_orders.append(
            {
                "symbol": symbol,
                "side": side,
                "volume": volume,
                "sl": sl,
                "tp": tp,
                "comment": comment,
            }
        )
        return {"retcode": 0, "order": 1, "deal": 2}

    def get_latest_closed_outcome(self, symbol: str, magic: int | None = None):
        return None

    def close_position(self, symbol: str, position, comment: str):
        self.closed.append({"symbol": symbol, "ticket": position.ticket, "comment": comment})
        return {"retcode": 0, "order": 3, "deal": 4}


def test_mt5_trade_marks_signal_and_skips_duplicate(monkeypatch, tmp_path):
    connector = FakeMT5Connector()

    def fake_signals(df, ema_fast, ema_mid, ema_slow, ema_slower, ema_slowest, include_state=False):
        signals = df.copy()
        signals["long_signal"] = [False] * (len(df) - 1) + [True]
        signals["short_signal"] = [False] * len(df)
        return signals

    monkeypatch.setattr("trading_bot.mt5_execution.prepare_ema_channel_signals", fake_signals)

    state_file = str(tmp_path / "mt5_state.db")
    run_mt5_trade(connector=connector, symbol="BTCUSD", limit=10, state_file=state_file)
    run_mt5_trade(connector=connector, symbol="BTCUSD", limit=10, state_file=state_file)

    assert len(connector.market_orders) == 1


def test_mt5_trade_breaker_blocks_entry(monkeypatch, tmp_path):
    connector = FakeMT5Connector()

    def fake_signals(df, ema_fast, ema_mid, ema_slow, ema_slower, ema_slowest, include_state=False):
        signals = df.copy()
        signals["long_signal"] = [False] * (len(df) - 1) + [True]
        signals["short_signal"] = [False] * len(df)
        return signals

    monkeypatch.setattr("trading_bot.mt5_execution.prepare_ema_channel_signals", fake_signals)
    monkeypatch.setattr("trading_bot.mt5_execution.MAX_TRADES_PER_DAY", 1)
    monkeypatch.setattr("trading_bot.mt5_execution.MAX_DAILY_LOSS_USDT", 0.0)
    monkeypatch.setattr("trading_bot.mt5_execution.MAX_DRAWDOWN_PCT", 0.0)
    monkeypatch.setattr("trading_bot.mt5_execution.MAX_CONSECUTIVE_LOSSES", 0)

    state_file = str(tmp_path / "mt5_state.db")
    store = TradingStateStore(state_file)
    store.set_runtime_state(
        "mt5_risk_state",
        {
            "day": _today_key(),
            "realized_pnl_today": 0.0,
            "trades_today": 1,
            "consecutive_losses": 0,
            "day_start_equity": 10_000.0,
            "peak_equity": 10_000.0,
            "breaker_tripped": False,
            "breaker_reason": "",
        },
    )

    run_mt5_trade(connector=connector, symbol="BTCUSD", limit=10, state_file=state_file)

    assert len(connector.market_orders) == 0
    runtime = store.get_runtime_state("mt5_risk_state", default={}) or {}
    assert runtime.get("breaker_tripped") is True


def test_mt5_trade_does_not_flip_existing_position(monkeypatch, tmp_path):
    connector = FakeMT5Connector()
    connector.position = _FakePosition(ticket=42, side="BUY", volume=0.01, price_open=100.0)

    def fake_signals(df, ema_fast, ema_mid, ema_slow, ema_slower, ema_slowest, include_state=False):
        signals = df.copy()
        signals["long_signal"] = [False] * len(df)
        signals["short_signal"] = [False] * (len(df) - 1) + [True]
        return signals

    monkeypatch.setattr("trading_bot.mt5_execution.prepare_ema_channel_signals", fake_signals)

    state_file = str(tmp_path / "mt5_state.db")
    store = TradingStateStore(state_file)
    store.set_position("BTCUSD", {"side": "BUY", "qty": 0.01, "entry_price": 100.0})

    run_mt5_trade(connector=connector, symbol="BTCUSD", limit=10, state_file=state_file)

    assert len(connector.closed) == 0
    assert len(connector.market_orders) == 0


def test_mt5_trade_skips_wide_spread(monkeypatch, tmp_path):
    connector = FakeMT5Connector()
    connector.get_spread_pips = lambda symbol, pip_size=0.10: 4.0

    def fake_signals(df, ema_fast, ema_mid, ema_slow, ema_slower, ema_slowest, include_state=False):
        signals = df.copy()
        signals["long_signal"] = [False] * (len(df) - 1) + [True]
        signals["short_signal"] = [False] * len(df)
        return signals

    monkeypatch.setattr("trading_bot.mt5_execution.prepare_ema_channel_signals", fake_signals)

    state_file = str(tmp_path / "mt5_state.db")
    run_mt5_trade(connector=connector, symbol="BTCUSD", limit=10, state_file=state_file)

    assert len(connector.market_orders) == 0
