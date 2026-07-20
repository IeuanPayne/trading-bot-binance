from __future__ import annotations

from types import SimpleNamespace

from trading_bot.mt5_connector import MT5Connector
import trading_bot.mt5_connector as mt5_connector_module


class _FakeMT5:
    ORDER_TYPE_BUY = 0

    def __init__(self, *, order_calc_profit_result=None, symbol_info_obj=None):
        self._order_calc_profit_result = order_calc_profit_result
        self._symbol_info_obj = symbol_info_obj

    def order_calc_profit(self, order_type, symbol, volume, price_open, price_close):
        return self._order_calc_profit_result

    def symbol_info(self, symbol):
        return self._symbol_info_obj


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
