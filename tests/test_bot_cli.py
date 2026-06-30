import pandas as pd
import pytest

from trading_bot.bot import main


def test_bot_main_calls_backtest_by_default(monkeypatch):
    args = ["trading_bot.bot", "--symbol", "BTCUSDT", "--interval", "15m", "--limit", "10"]
    monkeypatch.setattr("sys.argv", args)
    called = {"backtest": False}

    def fake_run_backtest(symbol, interval, limit, fast, slow, rsi_period, export_report=False):
        called["backtest"] = True
        assert symbol == "BTCUSDT"
        assert interval == "15m"
        assert limit == 10

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
