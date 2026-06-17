import pandas as pd

from trading_bot.backtest import calculate_rsi, prepare_ema_rsi_signals, emarsi_backtest


def test_calculate_rsi_has_values_within_range():
    series = pd.Series([1, 2, 3, 2, 3, 4, 3, 4, 5, 4, 5, 6, 7, 6, 7])
    rsi = calculate_rsi(series, period=3)
    assert rsi.iloc[:3].isna().all()
    assert rsi.iloc[-1] >= 0
    assert rsi.iloc[-1] <= 100


def test_prepare_ema_rsi_signals_includes_columns():
    prices = list(range(1, 16))
    df = pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1] * len(prices),
            "open_time": pd.date_range("2024-01-01", periods=len(prices), freq="1min"),
            "close_time": pd.date_range("2024-01-01", periods=len(prices), freq="1min"),
        }
    )
    signals = prepare_ema_rsi_signals(df, ema_fast=3, ema_slow=5, rsi_period=3)
    assert "ema_fast" in signals.columns
    assert "ema_slow" in signals.columns
    assert "rsi" in signals.columns
    assert "long_signal" in signals.columns
    assert "short_signal" in signals.columns


def test_emarsi_backtest_returns_expected_keys():
    prices = [10, 11, 12, 11, 12, 13, 12, 11, 10, 11, 12, 13, 14, 13, 12]
    df = pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1] * len(prices),
            "open_time": pd.date_range("2024-01-01", periods=len(prices), freq="1min"),
            "close_time": pd.date_range("2024-01-01", periods=len(prices), freq="1min"),
        }
    )
    results = emarsi_backtest(df, ema_fast=3, ema_slow=5, rsi_period=3, initial_capital=1000.0, pct_per_trade=0.1)
    assert isinstance(results, dict)
    assert "pnl" in results
    assert "final_equity" in results
    assert "num_trades" in results
