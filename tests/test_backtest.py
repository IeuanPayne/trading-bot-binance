import pandas as pd

from trading_bot.backtest import ema_channel_backtest, prepare_ema_channel_signals


def test_prepare_ema_channel_signals_includes_columns():
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
    signals = prepare_ema_channel_signals(df, ema_fast=3, ema_mid=4, ema_slow=5, ema_slower=6, ema_slowest=7)
    assert "ema_fast" in signals.columns
    assert "ema_mid" in signals.columns
    assert "ema_slow" in signals.columns
    assert "ema_slower" in signals.columns
    assert "ema_slowest" in signals.columns
    assert "long_signal" in signals.columns
    assert "short_signal" in signals.columns


def test_prepare_ema_channel_signals_emits_confirmed_long_signal():
    df = pd.DataFrame(
        {
            "open": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 16.8, 17.2],
            "high": [10.2, 11.2, 12.2, 13.2, 14.2, 15.2, 16.2, 17.0, 18.0],
            "low": [9.8, 10.8, 11.8, 12.8, 13.8, 14.8, 15.8, 15.4, 16.8],
            "close": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 16.2, 17.8],
            "volume": [1] * 9,
            "open_time": pd.date_range("2024-01-01", periods=9, freq="1min"),
            "close_time": pd.date_range("2024-01-01", periods=9, freq="1min"),
        }
    )

    signals = prepare_ema_channel_signals(
        df,
        ema_fast=2,
        ema_mid=3,
        ema_slow=4,
        ema_slower=5,
        ema_slowest=6,
    )

    assert signals["long_signal"].any()
    assert not signals.iloc[-1]["short_signal"]


def test_ema_channel_backtest_returns_expected_keys():
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
    results = ema_channel_backtest(
        df,
        ema_fast=3,
        ema_mid=4,
        ema_slow=5,
        ema_slower=6,
        ema_slowest=7,
        initial_capital=1000.0,
        pct_per_trade=0.1,
    )
    assert isinstance(results, dict)
    assert "pnl" in results
    assert "final_equity" in results
    assert "num_trades" in results
