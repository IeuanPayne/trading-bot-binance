from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import trading_bot.mt5_connector as mt5_connector_module
from trading_bot.mt5_connector import MT5Connector


class _FakeMT5:
    ORDER_TYPE_BUY = 0

    def __init__(self, *, order_calc_profit_result=None, symbol_info_obj=None):
        self._order_calc_profit_result = order_calc_profit_result
        self._symbol_info_obj = symbol_info_obj

    def order_calc_profit(self, order_type, symbol, volume, price_open, price_close):
        return self._order_calc_profit_result

    def symbol_info(self, symbol):
        return self._symbol_info_obj

    def history_deals_get(self, start, end):
        return self._history_deals


def _deal(*, symbol, magic, entry, deal_type, position_id, time, price, volume=1.0, profit=0.0, commission=0.0, swap=0.0, comment="closed"):
    return SimpleNamespace(
        symbol=symbol,
        magic=magic,
        entry=entry,
        type=deal_type,
        position_id=position_id,
        time=time,
        time_msc=time * 1000,
        price=price,
        volume=volume,
        profit=profit,
        commission=commission,
        swap=swap,
        comment=comment,
    )


def test_volume_from_risk_pips_uses_order_calc_profit(monkeypatch):
    fake_mt5 = _FakeMT5(order_calc_profit_result=-140.0)
    monkeypatch.setattr(mt5_connector_module, "mt5", fake_mt5)

    connector = MT5Connector(login=1, password="x", server="demo")
    monkeypatch.setattr(connector, "get_symbol_price", lambda symbol, side="BUY": 4000.0)
    monkeypatch.setattr(connector, "normalize_volume", lambda symbol, volume: volume)

    volume = connector.volume_from_risk_pips(symbol="XAUUSD", risk_amount=100.0, sl_pips=70.0, pip_size=0.10)

    assert volume == 100.0 / 140.0


def test_volume_from_risk_pips_falls_back_to_tick_value(monkeypatch):
    symbol_info = SimpleNamespace(
        trade_tick_size=0.01,
        point=0.01,
        trade_tick_value_loss=1.0,
        trade_tick_value=1.0,
    )
    fake_mt5 = _FakeMT5(order_calc_profit_result=None, symbol_info_obj=symbol_info)
    monkeypatch.setattr(mt5_connector_module, "mt5", fake_mt5)

    connector = MT5Connector(login=1, password="x", server="demo")
    monkeypatch.setattr(connector, "get_symbol_price", lambda symbol, side="BUY": 4000.0)
    monkeypatch.setattr(connector, "normalize_volume", lambda symbol, volume: volume)

    volume = connector.volume_from_risk_pips(symbol="XAUUSD", risk_amount=100.0, sl_pips=70.0, pip_size=0.10)

    assert volume == 100.0 / 700.0


def test_volume_from_risk_pips_invalid_inputs_return_zero():
    connector = MT5Connector(login=1, password="x", server="demo")

    assert connector.volume_from_risk_pips(symbol="XAUUSD", risk_amount=0.0, sl_pips=70.0, pip_size=0.10) == 0.0
    assert connector.volume_from_risk_pips(symbol="XAUUSD", risk_amount=100.0, sl_pips=0.0, pip_size=0.10) == 0.0
    assert connector.volume_from_risk_pips(symbol="XAUUSD", risk_amount=100.0, sl_pips=70.0, pip_size=0.0) == 0.0


def test_get_latest_closed_outcome_ignores_deals_before_not_before(monkeypatch):
    fake_mt5 = _FakeMT5()
    fake_mt5.DEAL_ENTRY_OUT = 1
    fake_mt5.DEAL_ENTRY_IN = 0
    fake_mt5.DEAL_TYPE_BUY = 0
    fake_mt5.DEAL_ENTRY_OUT_BY = 3
    fake_mt5._history_deals = [
        _deal(symbol="XAUUSD", magic=20260634, entry=0, deal_type=0, position_id=1, time=1_690_000_000, price=4050.0, profit=-10.0),
        _deal(symbol="XAUUSD", magic=20260634, entry=1, deal_type=0, position_id=1, time=1_690_000_060, price=4040.0, profit=-10.0),
    ]
    monkeypatch.setattr(mt5_connector_module, "mt5", fake_mt5)

    connector = MT5Connector(login=1, password="x", server="demo")
    outcome = connector.get_latest_closed_outcome(
        symbol="XAUUSD",
        magic=20260634,
        not_before="2026-07-24T13:40:00Z",
    )

    assert outcome is None
