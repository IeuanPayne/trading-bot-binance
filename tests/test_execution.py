import pandas as pd
import pytest

from trading_bot.execution import (
    _safe_float,
    _symbol_assets,
    _submit_with_retry,
    calculate_order_quantity,
    run_paper_trade,
)


class DummyConnector:
    def __init__(self, rounded_value):
        self.rounded_value = rounded_value

    def round_quantity(self, symbol: str, quantity: float) -> float:
        assert symbol == "BTCUSDT"
        assert quantity > 0
        return self.rounded_value


class FakeTrader:
    def __init__(self, symbol_price, quote_free, base_free, rounded_qty):
        self.client = True
        self.symbol_price = symbol_price
        self.quote_free = quote_free
        self.base_free = base_free
        self.rounded_qty = rounded_qty
        self.market_orders = []
        self.oco_orders = []

    def fetch_klines(self, symbol: str, interval: str, limit: int):
        rows = max(limit, 2)
        data = {
            "open": [1.0] * rows,
            "high": [1.0] * rows,
            "low": [1.0] * rows,
            "close": [1.0] * rows,
            "volume": [1.0] * rows,
            "open_time": pd.date_range("2024-01-01", periods=rows, freq="1min"),
            "close_time": pd.date_range("2024-01-01", periods=rows, freq="1min"),
        }
        return pd.DataFrame(data)

    def get_asset_balance(self, asset: str) -> dict:
        if asset == "USDT":
            return {"free": str(self.quote_free)}
        return {"free": str(self.base_free)}

    def get_symbol_price(self, symbol: str) -> dict:
        return {"price": str(self.symbol_price)}

    def create_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        self.market_orders.append({"symbol": symbol, "side": side, "quantity": quantity})
        return {"status": "created", "side": side, "qty": quantity}

    def create_oco_order(self, symbol: str, side: str, quantity: float, price: float, stop_price: float, stop_limit_price: float) -> dict:
        self.oco_orders.append({"symbol": symbol, "side": side, "quantity": quantity, "price": price, "stop_price": stop_price})
        return {"status": "oco_created"}

    def round_quantity(self, symbol: str, quantity: float) -> float:
        assert symbol == "BTCUSDT"
        return self.rounded_qty

    def round_price(self, symbol: str, price: float) -> float:
        assert symbol == "BTCUSDT"
        return round(price, 8)

    def validate_market_order(self, symbol: str, quantity: float, reference_price: float) -> tuple[bool, str]:
        assert symbol == "BTCUSDT"
        assert quantity > 0
        assert reference_price > 0
        return True, "ok"


def test_symbol_assets_returns_base_and_quote():
    assert _symbol_assets("BTCUSDT") == ("BTC", "USDT")


def test_symbol_assets_rejects_non_usdt_symbols():
    with pytest.raises(ValueError):
        _symbol_assets("BTCUSD")


def test_safe_float_parses_valid_values():
    assert _safe_float("123.45") == 123.45
    assert _safe_float(10) == 10.0


def test_safe_float_returns_default_for_invalid_input():
    assert _safe_float("abc", default=7.5) == 7.5
    assert _safe_float(None, default=-1.0) == -1.0


def test_calculate_order_quantity_applies_rounding():
    quantity = calculate_order_quantity(DummyConnector(0.001), "BTCUSDT", allocation_usdt=100.0, entry_price=50000.0)
    assert quantity == 0.001


def test_calculate_order_quantity_raises_for_zero_quantity():
    with pytest.raises(ValueError):
        calculate_order_quantity(DummyConnector(0.0), "BTCUSDT", allocation_usdt=100.0, entry_price=50000.0)


def test_run_paper_trade_requires_api_keys(monkeypatch, tmp_path):
    monkeypatch.setattr("trading_bot.execution.BINANCE_API_KEY", "")
    monkeypatch.setattr("trading_bot.execution.BINANCE_API_SECRET", "")
    recorded = []

    def fake_error(msg, *args, **kwargs):
        recorded.append(msg.format(*args))

    monkeypatch.setattr("trading_bot.execution.logger.error", fake_error)
    run_paper_trade("BTCUSDT", interval="15m", limit=1, state_file=str(tmp_path / "state.json"))
    assert any("Paper trading requires BINANCE_API_KEY" in entry for entry in recorded)


def test_run_paper_trade_refuses_live_without_explicit_allow(monkeypatch, tmp_path):
    monkeypatch.setattr("trading_bot.execution.BINANCE_API_KEY", "key")
    monkeypatch.setattr("trading_bot.execution.BINANCE_API_SECRET", "secret")
    monkeypatch.setattr("trading_bot.execution.BINANCE_TESTNET", False)
    monkeypatch.setattr("trading_bot.execution.ALLOW_LIVE_TRADING", False)

    recorded = []

    def fake_error(msg, *args, **kwargs):
        recorded.append(msg.format(*args))

    monkeypatch.setattr("trading_bot.execution.logger.error", fake_error)
    run_paper_trade("BTCUSDT", interval="15m", limit=2, state_file=str(tmp_path / "state.json"))
    assert any("Refusing to place live orders" in entry for entry in recorded)


def test_run_paper_trade_long_signal_places_market_buy(monkeypatch, tmp_path):
    monkeypatch.setattr("trading_bot.execution.BINANCE_API_KEY", "key")
    monkeypatch.setattr("trading_bot.execution.BINANCE_API_SECRET", "secret")
    monkeypatch.setattr("trading_bot.execution.BINANCE_TESTNET", True)

    fake = FakeTrader(symbol_price=50.0, quote_free=1000.0, base_free=0.0, rounded_qty=0.02)
    monkeypatch.setattr("trading_bot.execution.BinanceConnector", lambda *args, **kwargs: fake)

    def fake_signals(df, ema_fast, ema_slow, rsi_period):
        signals = df.copy()
        signals["long_signal"] = [False] * (len(df) - 1) + [True]
        signals["short_signal"] = [False] * len(df)
        return signals

    monkeypatch.setattr("trading_bot.execution.prepare_ema_rsi_signals", fake_signals)
    run_paper_trade("BTCUSDT", interval="15m", limit=2, state_file=str(tmp_path / "state.json"))

    assert len(fake.market_orders) == 1
    assert fake.market_orders[0]["side"] == "BUY"
    assert len(fake.oco_orders) == 1
    assert fake.oco_orders[0]["stop_price"] == pytest.approx(49.3)
    assert fake.oco_orders[0]["price"] == pytest.approx(50.7)


def test_run_paper_trade_short_signal_closes_position(monkeypatch, tmp_path):
    monkeypatch.setattr("trading_bot.execution.BINANCE_API_KEY", "key")
    monkeypatch.setattr("trading_bot.execution.BINANCE_API_SECRET", "secret")
    monkeypatch.setattr("trading_bot.execution.BINANCE_TESTNET", True)

    fake = FakeTrader(symbol_price=50.0, quote_free=0.0, base_free=0.01, rounded_qty=0.01)
    monkeypatch.setattr("trading_bot.execution.BinanceConnector", lambda *args, **kwargs: fake)

    def fake_signals(df, ema_fast, ema_slow, rsi_period):
        signals = df.copy()
        signals["long_signal"] = [False] * len(df)
        signals["short_signal"] = [False] * (len(df) - 1) + [True]
        return signals

    monkeypatch.setattr("trading_bot.execution.prepare_ema_rsi_signals", fake_signals)
    run_paper_trade("BTCUSDT", interval="15m", limit=2, state_file=str(tmp_path / "state.json"))

    assert len(fake.market_orders) == 1
    assert fake.market_orders[0]["side"] == "SELL"


def test_submit_with_retry_succeeds_after_transient_error(monkeypatch):
    calls = {"n": 0}

    def flaky_create_order(**kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("temporary api error")
        return {"status": "ok"}

    monkeypatch.setattr("trading_bot.execution.time.sleep", lambda *_args, **_kwargs: None)
    result = _submit_with_retry(flaky_create_order, retries=3, action="market buy", symbol="BTCUSDT", side="BUY", quantity=0.01)
    assert result["status"] == "ok"
    assert calls["n"] == 2


def test_run_paper_trade_skips_duplicate_signal(monkeypatch, tmp_path):
    monkeypatch.setattr("trading_bot.execution.BINANCE_API_KEY", "key")
    monkeypatch.setattr("trading_bot.execution.BINANCE_API_SECRET", "secret")
    monkeypatch.setattr("trading_bot.execution.BINANCE_TESTNET", True)

    fake = FakeTrader(symbol_price=50.0, quote_free=1000.0, base_free=0.0, rounded_qty=0.02)
    monkeypatch.setattr("trading_bot.execution.BinanceConnector", lambda *args, **kwargs: fake)

    def fake_signals(df, ema_fast, ema_slow, rsi_period):
        signals = df.copy()
        signals["long_signal"] = [False] * (len(df) - 1) + [True]
        signals["short_signal"] = [False] * len(df)
        return signals

    monkeypatch.setattr("trading_bot.execution.prepare_ema_rsi_signals", fake_signals)
    state_file = str(tmp_path / "state.json")

    run_paper_trade("BTCUSDT", interval="15m", limit=2, state_file=state_file)
    run_paper_trade("BTCUSDT", interval="15m", limit=2, state_file=state_file)

    assert len(fake.market_orders) == 1
