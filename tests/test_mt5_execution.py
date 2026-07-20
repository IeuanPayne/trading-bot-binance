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
    sl: float = 0.0
    tp: float = 0.0


class FakeMT5Connector:
    def __init__(self):
        self.market_orders = []
        self.closed = []
        self.sltp_updates = []
        self.position = None
        self.risk_calls = []

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
        self.risk_calls.append({"symbol": symbol, "risk_amount": risk_amount, "sl_pips": sl_pips, "pip_size": pip_size})
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

    def normalize_volume(self, symbol: str, volume: float) -> float:
        return volume

    def close_position(self, symbol: str, position, comment: str, volume: float | None = None):
        self.closed.append(
            {
                "symbol": symbol,
                "ticket": position.ticket,
                "comment": comment,
                "volume": position.volume if volume is None else volume,
            }
        )
        return {"retcode": 0, "order": 3, "deal": 4}

    def modify_position_sltp(self, symbol: str, position, sl: float, tp: float | None = None):
        self.sltp_updates.append({"symbol": symbol, "ticket": position.ticket, "sl": sl, "tp": tp})
        return {"retcode": 0, "order": 5, "deal": 6}


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


def test_mt5_trade_dynamic_sltp_uses_atr_distance(monkeypatch, tmp_path):
    connector = FakeMT5Connector()

    def fake_signals(df, ema_fast, ema_mid, ema_slow, ema_slower, ema_slowest, include_state=False):
        signals = df.copy()
        signals["long_signal"] = [False] * (len(df) - 1) + [True]
        signals["short_signal"] = [False] * len(df)
        return signals

    monkeypatch.setattr("trading_bot.mt5_execution.prepare_ema_channel_signals", fake_signals)

    state_file = str(tmp_path / "mt5_state.db")
    run_mt5_trade(
        connector=connector,
        symbol="BTCUSD",
        limit=20,
        state_file=state_file,
        dynamic_sltp=True,
        atr_period=14,
        sl_atr_mult=1.0,
        tp_atr_mult=2.0,
        pip_size=0.10,
    )

    assert len(connector.market_orders) == 1
    order = connector.market_orders[0]
    # Fake data in this file yields ATR ~= 2.0, entry=100.0.
    assert order["sl"] == 98.0
    assert order["tp"] == 104.0
    assert len(connector.risk_calls) == 1
    assert connector.risk_calls[0]["sl_pips"] == 20.0


def test_mt5_trade_trailing_stop_updates_sl_after_activation(monkeypatch, tmp_path):
    connector = FakeMT5Connector()
    connector.position = _FakePosition(ticket=42, side="BUY", volume=0.01, price_open=100.0, sl=95.0, tp=110.0)

    def fake_signals(df, ema_fast, ema_mid, ema_slow, ema_slower, ema_slowest, include_state=False):
        signals = df.copy()
        signals["long_signal"] = [False] * len(df)
        signals["short_signal"] = [False] * len(df)
        return signals

    monkeypatch.setattr("trading_bot.mt5_execution.prepare_ema_channel_signals", fake_signals)
    monkeypatch.setattr(connector, "get_symbol_price", lambda symbol, side="BUY": 108.0 if side == "SELL" else 108.1)

    state_file = str(tmp_path / "mt5_state.db")
    store = TradingStateStore(state_file)
    store.set_position("BTCUSD", {"side": "BUY", "qty": 0.01, "entry_price": 100.0, "sl": 95.0, "tp": 110.0})

    run_mt5_trade(
        connector=connector,
        symbol="BTCUSD",
        limit=20,
        state_file=state_file,
        trailing_stop=True,
        trail_activate_r=1.0,
        trail_atr_period=14,
        trail_atr_mult=1.0,
    )

    assert len(connector.sltp_updates) == 1
    assert connector.sltp_updates[0]["sl"] == 106.0
    updated = store.get_position("BTCUSD")
    assert updated is not None
    assert updated["sl"] == 106.0


def test_mt5_trade_trailing_stop_respects_min_step(monkeypatch, tmp_path):
    connector = FakeMT5Connector()
    connector.position = _FakePosition(ticket=42, side="BUY", volume=0.01, price_open=100.0, sl=106.0, tp=110.0)

    def fake_signals(df, ema_fast, ema_mid, ema_slow, ema_slower, ema_slowest, include_state=False):
        signals = df.copy()
        signals["long_signal"] = [False] * len(df)
        signals["short_signal"] = [False] * len(df)
        return signals

    monkeypatch.setattr("trading_bot.mt5_execution.prepare_ema_channel_signals", fake_signals)
    # mark for BUY uses SELL quote in trailing logic
    monkeypatch.setattr(connector, "get_symbol_price", lambda symbol, side="BUY": 108.4 if side == "SELL" else 108.5)

    state_file = str(tmp_path / "mt5_state.db")
    store = TradingStateStore(state_file)
    store.set_position("BTCUSD", {"side": "BUY", "qty": 0.01, "entry_price": 100.0, "sl": 95.0, "tp": 110.0})

    run_mt5_trade(
        connector=connector,
        symbol="BTCUSD",
        limit=20,
        state_file=state_file,
        trailing_stop=True,
        trail_activate_r=1.0,
        trail_atr_period=14,
        trail_atr_mult=1.0,
        trail_min_step_atr=0.5,
    )

    assert len(connector.sltp_updates) == 0


def test_mt5_trade_staged_exit_takes_tp1_and_moves_stop(monkeypatch, tmp_path):
    connector = FakeMT5Connector()
    connector.position = _FakePosition(ticket=42, side="BUY", volume=0.04, price_open=100.0, sl=70.0, tp=400.0)

    def fake_signals(df, ema_fast, ema_mid, ema_slow, ema_slower, ema_slowest, include_state=False):
        signals = df.copy()
        signals["long_signal"] = [False] * len(df)
        signals["short_signal"] = [False] * len(df)
        return signals

    monkeypatch.setattr("trading_bot.mt5_execution.prepare_ema_channel_signals", fake_signals)
    monkeypatch.setattr(connector, "get_symbol_price", lambda symbol, side="BUY": 131.0 if side == "SELL" else 131.1)

    state_file = str(tmp_path / "mt5_state.db")
    store = TradingStateStore(state_file)
    store.set_position(
        "BTCUSD",
        {
            "side": "BUY",
            "qty": 0.04,
            "initial_qty": 0.04,
            "entry_price": 100.0,
            "sl": 70.0,
            "initial_sl": 70.0,
            "initial_r": 30.0,
            "tp": 400.0,
            "tp1": 130.0,
            "tp2": 160.0,
            "tp3": 190.0,
            "tp4": 400.0,
            "tp1_hit": False,
            "tp2_hit": False,
            "tp3_hit": False,
            "tp4_hit": False,
            "moved_to_be": False,
            "trailing_active": False,
            "be_trigger_price": 130.0,
            "be_stop_price": 105.0,
            "trail_distance": 50.0,
            "staged_exit_enabled": True,
            "tp4_open": False,
            "realized_pnl": 0.0,
        },
    )

    run_mt5_trade(
        connector=connector,
        symbol="BTCUSD",
        limit=20,
        state_file=state_file,
        staged_exit_enabled=True,
        pip_size=1.0,
        staged_be_trigger_pips=30.0,
        staged_be_offset_pips=5.0,
        staged_trail_pips=50.0,
    )

    assert len(connector.closed) == 1
    assert connector.closed[0]["comment"] == "spec-ema-channel-tp1"
    assert connector.closed[0]["volume"] == 0.01
    assert len(connector.sltp_updates) == 1
    assert connector.sltp_updates[0]["sl"] == 105.0
    updated = store.get_position("BTCUSD")
    assert updated is not None
    assert updated["qty"] == 0.03
    assert updated["tp1_hit"] is True
    assert updated["trailing_active"] is True


def test_mt5_trade_staged_exit_pins_stop_after_tp2(monkeypatch, tmp_path):
    connector = FakeMT5Connector()
    connector.position = _FakePosition(ticket=42, side="BUY", volume=0.04, price_open=100.0, sl=70.0, tp=400.0)

    def fake_signals(df, ema_fast, ema_mid, ema_slow, ema_slower, ema_slowest, include_state=False):
        signals = df.copy()
        signals["long_signal"] = [False] * len(df)
        signals["short_signal"] = [False] * len(df)
        return signals

    monkeypatch.setattr("trading_bot.mt5_execution.prepare_ema_channel_signals", fake_signals)
    monkeypatch.setattr(connector, "get_symbol_price", lambda symbol, side="BUY": 165.0 if side == "SELL" else 165.1)

    state_file = str(tmp_path / "mt5_state.db")
    store = TradingStateStore(state_file)
    store.set_position(
        "BTCUSD",
        {
            "side": "BUY",
            "qty": 0.04,
            "initial_qty": 0.04,
            "entry_price": 100.0,
            "sl": 70.0,
            "initial_sl": 70.0,
            "initial_r": 30.0,
            "tp": 400.0,
            "tp1": 130.0,
            "tp2": 160.0,
            "tp3": 190.0,
            "tp4": 400.0,
            "tp1_hit": False,
            "tp2_hit": False,
            "tp3_hit": False,
            "tp4_hit": False,
            "moved_to_be": False,
            "trailing_active": False,
            "be_trigger_price": 130.0,
            "be_stop_price": 105.0,
            "trail_distance": 50.0,
            "staged_exit_enabled": True,
            "tp4_open": False,
            "realized_pnl": 0.0,
        },
    )

    run_mt5_trade(
        connector=connector,
        symbol="BTCUSD",
        limit=20,
        state_file=state_file,
        staged_exit_enabled=True,
        pip_size=1.0,
        staged_be_trigger_pips=30.0,
        staged_be_offset_pips=5.0,
        staged_trail_pips=50.0,
    )

    assert len(connector.closed) == 2
    assert [close["comment"] for close in connector.closed] == ["spec-ema-channel-tp1", "spec-ema-channel-tp2"]
    assert len(connector.sltp_updates) == 1
    assert connector.sltp_updates[0]["sl"] == 130.0
    updated = store.get_position("BTCUSD")
    assert updated is not None
    assert updated["qty"] == 0.02
    assert updated["tp1_hit"] is True
    assert updated["tp2_hit"] is True
    assert updated["trailing_active"] is False
