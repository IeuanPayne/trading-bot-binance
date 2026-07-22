import pandas as pd
import pytest

from trading_bot.bot import main


def test_bot_main_calls_backtest_by_default(monkeypatch):
    args = ["trading_bot.bot", "--symbol", "BTCUSDT", "--interval", "15m", "--limit", "10"]
    monkeypatch.setattr("sys.argv", args)
    called = {"backtest": False}

    def fake_run_backtest(**kwargs):
        called["backtest"] = True
        assert kwargs["symbol"] == "BTCUSDT"
        assert kwargs["interval"] == "15m"
        assert kwargs["limit"] == 10

    monkeypatch.setattr("trading_bot.bot.run_backtest", fake_run_backtest)
    main()
    assert called["backtest"]


def test_bot_main_calls_paper_mode(monkeypatch):
    args = [
        "trading_bot.bot",
        "--mode",
        "paper",
        "--symbol",
        "BTCUSDT",
        "--interval",
        "15m",
        "--limit",
        "10",
    ]
    monkeypatch.setattr("sys.argv", args)
    called = {"paper": False}

    def fake_run_paper_trade(**kwargs):
        called["paper"] = True
        assert kwargs["symbol"] == "BTCUSDT"
        assert kwargs["interval"] == "15m"
        assert kwargs["limit"] == 10

    monkeypatch.setattr("trading_bot.bot.run_paper_trade", fake_run_paper_trade)
    main()
    assert called["paper"]


def test_bot_main_rejects_invalid_order_pct(monkeypatch):
    args = [
        "trading_bot.bot",
        "--mode",
        "paper",
        "--order-pct",
        "2",
    ]
    monkeypatch.setattr("sys.argv", args)

    with pytest.raises(SystemExit):
        main()


def test_bot_main_calls_mt5_mode(monkeypatch):
    args = [
        "trading_bot.bot",
        "--mode",
        "mt5",
        "--interval",
        "15m",
    ]
    monkeypatch.setattr("sys.argv", args)

    monkeypatch.setattr("trading_bot.bot.MT5_LOGIN", "123456")
    monkeypatch.setattr("trading_bot.bot.MT5_PASSWORD", "pass")
    monkeypatch.setattr("trading_bot.bot.MT5_SERVER", "server")
    monkeypatch.setattr("trading_bot.bot.MT5_SYMBOL", "BTCUSD")
    monkeypatch.setattr("trading_bot.bot.validate_runtime_args", lambda mode, order_pct, stop_pips: None)

    called = {"connect": 0, "shutdown": 0, "run": 0}

    class FakeConnector:
        def connect(self):
            called["connect"] += 1

        def shutdown(self):
            called["shutdown"] += 1

    monkeypatch.setattr("trading_bot.bot.MT5Connector", lambda **kwargs: FakeConnector())

    def fake_run_mt5_trade(**kwargs):
        called["run"] += 1
        assert kwargs["symbol"] == "BTCUSD"

    monkeypatch.setattr("trading_bot.bot.run_mt5_trade", fake_run_mt5_trade)
    main()

    assert called["connect"] == 1
    assert called["run"] == 1
    assert called["shutdown"] == 1


def test_bot_main_backtest_smoke_runs_real_backtest(monkeypatch):
    args = ["trading_bot.bot", "--mode", "backtest", "--symbol", "BTCUSDT", "--interval", "15m", "--limit", "10"]
    monkeypatch.setattr("sys.argv", args)

    class FakeConnector:
        def fetch_klines(self, symbol: str, interval: str, limit: int):
            data = {
                "open": [1.0, 1.1, 1.2, 1.15, 1.16, 1.18, 1.2, 1.22, 1.25, 1.24],
                "high": [1.01, 1.12, 1.22, 1.16, 1.18, 1.2, 1.21, 1.24, 1.26, 1.25],
                "low": [0.99, 1.05, 1.15, 1.1, 1.14, 1.16, 1.18, 1.2, 1.23, 1.22],
                "close": [1.0, 1.1, 1.18, 1.15, 1.17, 1.19, 1.2, 1.21, 1.25, 1.23],
                "volume": [1.0] * 10,
                "open_time": pd.date_range("2024-01-01", periods=10, freq="1min"),
                "close_time": pd.date_range("2024-01-01", periods=10, freq="1min"),
            }
            return pd.DataFrame(data)

    monkeypatch.setattr("trading_bot.bot.BinanceConnector", lambda *args, **kwargs: FakeConnector())
    main()


def test_bot_main_passes_full_ema_set(monkeypatch):
    args = [
        "trading_bot.bot",
        "--mode",
        "paper",
        "--ema1-len",
        "9",
        "--ema2-len",
        "14",
        "--ema3-len",
        "22",
        "--ema4-len",
        "35",
        "--ema5-len",
        "56",
    ]
    monkeypatch.setattr("sys.argv", args)

    received = {}

    def fake_run_paper_trade(**kwargs):
        received.update(kwargs)

    monkeypatch.setattr("trading_bot.bot.run_paper_trade", fake_run_paper_trade)
    main()

    assert received["fast"] == 9
    assert received["ema2"] == 14
    assert received["slow"] == 22
    assert received["ema4"] == 35
    assert received["ema5"] == 56


def test_bot_main_passes_modeled_spread_to_paper(monkeypatch):
    args = ["trading_bot.bot", "--mode", "paper", "--modeled-spread-pips", "2.5"]
    monkeypatch.setattr("sys.argv", args)

    received = {}

    def fake_run_paper_trade(**kwargs):
        received.update(kwargs)

    monkeypatch.setattr("trading_bot.bot.run_paper_trade", fake_run_paper_trade)
    main()

    assert received["modeled_spread_pips"] == 2.5


def test_bot_main_tv_webhook_passes_allowed_timeframes(monkeypatch):
    args = [
        "trading_bot.bot",
        "--mode",
        "tv-webhook",
        "--tv-secret",
        "test-secret",
        "--tv-allowed-timeframes",
        "5m,15m",
    ]
    monkeypatch.setattr("sys.argv", args)

    monkeypatch.setattr("trading_bot.bot.MT5_LOGIN", "123456")
    monkeypatch.setattr("trading_bot.bot.MT5_PASSWORD", "pass")
    monkeypatch.setattr("trading_bot.bot.MT5_SERVER", "server")
    monkeypatch.setattr("trading_bot.bot.validate_runtime_args", lambda mode, order_pct, stop_pips: None)

    captured: dict[str, object] = {}

    def fake_start_server(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("trading_bot.bot.start_tradingview_webhook_server", fake_start_server)
    main()

    assert captured["allowed_timeframes"] == ["5m", "15m"]
    settings = captured["settings"]
    assert getattr(settings, "auto_magic") is True
    assert getattr(settings, "base_magic") == 20260629
