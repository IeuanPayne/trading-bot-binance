import pandas as pd
from loguru import logger
from typing import List, Dict
from .metrics import compute_trade_metrics
from .risk import position_size_by_risk


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def prepare_ema_rsi_signals(df: pd.DataFrame, ema_fast: int = 9, ema_slow: int = 21, rsi_period: int = 14) -> pd.DataFrame:
    df = df.copy().reset_index(drop=True)
    df["ema_fast"] = df["close"].ewm(span=ema_fast, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=ema_slow, adjust=False).mean()
    df["rsi"] = calculate_rsi(df["close"], rsi_period)

    df["long_signal"] = (
        (df["ema_fast"] > df["ema_slow"]) &
        (df["ema_fast"].shift(1) <= df["ema_slow"].shift(1)) &
        (df["rsi"] > 50) &
        (df["rsi"] < 70)
    )
    df["short_signal"] = (
        (df["ema_fast"] < df["ema_slow"]) &
        (df["ema_fast"].shift(1) >= df["ema_slow"].shift(1)) &
        (df["rsi"] > 30) &
        (df["rsi"] < 50)
    )
    return df


def emarsi_backtest(
    df: pd.DataFrame,
    ema_fast: int = 9,
    ema_slow: int = 21,
    rsi_period: int = 14,
    stop_pips: float = 0.7,
    initial_capital: float = 10000.0,
    pct_per_trade: float = 0.01,
) -> Dict:
    df = prepare_ema_rsi_signals(df, ema_fast=ema_fast, ema_slow=ema_slow, rsi_period=rsi_period)

    cash = initial_capital
    position = 0.0
    direction = 0
    entry_price = 0.0
    stop_price = 0.0
    take_profit = 0.0
    trades: List[Dict] = []

    for i in range(1, len(df) - 1):
        if direction != 0:
            high = df.loc[i, "high"]
            low = df.loc[i, "low"]
            exit_price = None
            if direction == 1:
                if low <= stop_price:
                    exit_price = stop_price
                elif high >= take_profit:
                    exit_price = take_profit
            elif direction == -1:
                if high >= stop_price:
                    exit_price = stop_price
                elif low <= take_profit:
                    exit_price = take_profit

            if exit_price is not None:
                if direction == 1:
                    cash += position * exit_price
                    trades.append({"type": "sell", "index": i, "price": exit_price, "qty": position, "reason": "tp/sl"})
                else:
                    cash -= position * exit_price
                    trades.append({"type": "cover", "index": i, "price": exit_price, "qty": position, "reason": "tp/sl"})
                direction = 0
                position = 0.0
                continue

        if direction != 0:
            if direction == 1 and df.loc[i, "short_signal"]:
                exit_price = df.loc[i + 1, "open"]
                cash += position * exit_price
                trades.append({"type": "sell", "index": i + 1, "price": exit_price, "qty": position, "reason": "opposite_signal"})
                direction = 0
                position = 0.0
                continue
            if direction == -1 and df.loc[i, "long_signal"]:
                exit_price = df.loc[i + 1, "open"]
                cash -= position * exit_price
                trades.append({"type": "cover", "index": i + 1, "price": exit_price, "qty": position, "reason": "opposite_signal"})
                direction = 0
                position = 0.0
                continue

        if direction == 0:
            if df.loc[i, "long_signal"]:
                entry_price = df.loc[i + 1, "open"]
                allocation = cash * pct_per_trade
                position = allocation / entry_price
                cash -= allocation
                direction = 1
                stop_price = entry_price - stop_pips
                take_profit = entry_price + stop_pips
                trades.append({"type": "buy", "index": i + 1, "price": entry_price, "qty": position, "reason": "long_entry"})
            elif df.loc[i, "short_signal"]:
                entry_price = df.loc[i + 1, "open"]
                allocation = cash * pct_per_trade
                position = allocation / entry_price
                cash += allocation
                direction = -1
                stop_price = entry_price + stop_pips
                take_profit = entry_price - stop_pips
                trades.append({"type": "sell_short", "index": i + 1, "price": entry_price, "qty": position, "reason": "short_entry"})

    if direction != 0:
        last_price = df.loc[len(df) - 1, "close"]
        if direction == 1:
            cash += position * last_price
            trades.append({"type": "sell", "index": len(df) - 1, "price": last_price, "qty": position, "reason": "final_close"})
        else:
            cash -= position * last_price
            trades.append({"type": "cover", "index": len(df) - 1, "price": last_price, "qty": position, "reason": "final_close"})
        direction = 0
        position = 0.0

    equity = cash
    pnl = equity - initial_capital
    metrics = compute_trade_metrics(trades, initial_capital)
    return {
        "initial_capital": initial_capital,
        "final_equity": equity,
        "pnl": pnl,
        "trades": trades,
        "num_trades": len(trades) // 2,
        "metrics": metrics,
    }
