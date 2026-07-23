from typing import Any

import pandas as pd

from .metrics import compute_trade_metrics

# Strategy contract: EMA channel continuation with first-retest confirmation.
# Entry long: EMA stack 1>2>3>4>5, close above channel, retest into channel,
# then a confirming close back above the channel top.
# Entry short: inverse of the above.
# Exits: fixed stop distance (stop_pips absolute price units)
# with 1:1 take-profit.


def in_session_window(
    timestamp: Any,
    session: str = "Both",
    london_start: int = 11,
    london_end: int = 20,
    newyork_start: int = 16,
    newyork_end: int = 25,
    session_tz_offset: int = 3,
) -> bool:
    """Match the friend EA's London/New York session gating using server time."""
    if session == "Off":
        return True

    ts = pd.Timestamp(timestamp)
    if pd.isna(ts):
        return True
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")

    server_ts = ts + pd.Timedelta(hours=session_tz_offset)
    hour = int(server_ts.hour)

    london = london_start <= hour < london_end
    if newyork_end > 24:
        newyork = hour >= newyork_start or hour < (newyork_end - 24)
    else:
        newyork = newyork_start <= hour < newyork_end

    if session == "London":
        return london
    if session == "NewYork":
        return newyork
    return london or newyork
def prepare_ema_channel_signals(
    df: pd.DataFrame,
    ema_fast: int = 8,
    ema_mid: int = 13,
    ema_slow: int = 21,
    ema_slower: int = 34,
    ema_slowest: int = 55,
    include_state: bool = False,
) -> pd.DataFrame:
    """Prepare EMA channel continuation signals on OHLC dataframe."""
    df = df.copy().reset_index(drop=True)
    df["ema_fast"] = df["close"].ewm(span=ema_fast, adjust=False).mean()
    df["ema_mid"] = df["close"].ewm(span=ema_mid, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=ema_slow, adjust=False).mean()
    df["ema_slower"] = df["close"].ewm(span=ema_slower, adjust=False).mean()
    df["ema_slowest"] = df["close"].ewm(span=ema_slowest, adjust=False).mean()

    long_signal = [False] * len(df)
    short_signal = [False] * len(df)
    trend = "NONE"
    entry_state = "IDLE"

    if include_state:
        entry_state_col = ["IDLE"] * len(df)
        trend_col = ["NONE"] * len(df)
        bull_stack_col = [False] * len(df)
        bear_stack_col = [False] * len(df)
        breakout_up_col = [False] * len(df)
        breakout_down_col = [False] * len(df)
        retest_up_col = [False] * len(df)
        retest_down_col = [False] * len(df)
        confirm_up_col = [False] * len(df)
        confirm_down_col = [False] * len(df)
        ch_top_col = [0.0] * len(df)
        ch_bot_col = [0.0] * len(df)

    for idx in range(1, len(df)):
        e1 = float(df.loc[idx, "ema_fast"])
        e2 = float(df.loc[idx, "ema_mid"])
        e3 = float(df.loc[idx, "ema_slow"])
        e4 = float(df.loc[idx, "ema_slower"])
        e5 = float(df.loc[idx, "ema_slowest"])

        ch_top = max(e1, e2, e3, e4, e5)
        ch_bot = min(e1, e2, e3, e4, e5)
        close1 = float(df.loc[idx, "close"])
        high1 = float(df.loc[idx, "high"])
        low1 = float(df.loc[idx, "low"])

        bull_stack = e1 > e2 > e3 > e4 > e5
        bear_stack = e1 < e2 < e3 < e4 < e5
        breakout_up = bull_stack and close1 > ch_top
        breakout_down = bear_stack and close1 < ch_bot
        retest_up = trend == "UP" and low1 <= ch_top and close1 >= ch_bot
        retest_down = trend == "DOWN" and high1 >= ch_bot and close1 <= ch_top
        confirm_up = trend == "UP" and close1 > ch_top
        confirm_down = trend == "DOWN" and close1 < ch_bot

        if include_state:
            bull_stack_col[idx] = bull_stack
            bear_stack_col[idx] = bear_stack
            breakout_up_col[idx] = breakout_up
            breakout_down_col[idx] = breakout_down
            retest_up_col[idx] = retest_up
            retest_down_col[idx] = retest_down
            confirm_up_col[idx] = confirm_up
            confirm_down_col[idx] = confirm_down
            ch_top_col[idx] = ch_top
            ch_bot_col[idx] = ch_bot

        if entry_state == "IDLE":
            if breakout_up:
                trend = "UP"
                entry_state = "WAIT_RETEST"
            elif breakout_down:
                trend = "DOWN"
                entry_state = "WAIT_RETEST"
            if include_state:
                trend_col[idx] = trend
                entry_state_col[idx] = entry_state
            continue

        if entry_state == "WAIT_RETEST":
            if retest_up or retest_down:
                entry_state = "WAIT_CONFIRM"

            if (trend == "UP" and bear_stack) or (trend == "DOWN" and bull_stack):
                trend = "NONE"
                entry_state = "IDLE"
            if include_state:
                trend_col[idx] = trend
                entry_state_col[idx] = entry_state
            continue

        if confirm_up:
            long_signal[idx] = True
        elif confirm_down:
            short_signal[idx] = True

        trend = "NONE"
        entry_state = "IDLE"

        if include_state:
            trend_col[idx] = trend
            entry_state_col[idx] = entry_state

    df["long_signal"] = long_signal
    df["short_signal"] = short_signal

    if include_state:
        df["entry_state"] = entry_state_col
        df["trend"] = trend_col
        df["bull_stack"] = bull_stack_col
        df["bear_stack"] = bear_stack_col
        df["breakout_up"] = breakout_up_col
        df["breakout_down"] = breakout_down_col
        df["retest_up"] = retest_up_col
        df["retest_down"] = retest_down_col
        df["confirm_up"] = confirm_up_col
        df["confirm_down"] = confirm_down_col
        df["channel_top"] = ch_top_col
        df["channel_bottom"] = ch_bot_col

    return df


def ema_channel_backtest(
    df: pd.DataFrame,
    ema_fast: int = 8,
    ema_mid: int = 13,
    ema_slow: int = 21,
    ema_slower: int = 34,
    ema_slowest: int = 55,
    session: str = "Both",
    london_start: int = 11,
    london_end: int = 20,
    newyork_start: int = 16,
    newyork_end: int = 25,
    session_tz_offset: int = 3,
    modeled_spread_pips: float = 0.0,
    max_spread_pips: float = 3.0,
    stop_pips: float = 0.7,
    initial_capital: float = 10000.0,
    pct_per_trade: float = 0.01,
) -> dict[str, Any]:
    if stop_pips <= 0:
        raise ValueError("stop_pips must be > 0 and represents an absolute price distance (e.g. 0.7)")
    if modeled_spread_pips < 0:
        raise ValueError("modeled_spread_pips must be >= 0")

    df = prepare_ema_channel_signals(
        df,
        ema_fast=ema_fast,
        ema_mid=ema_mid,
        ema_slow=ema_slow,
        ema_slower=ema_slower,
        ema_slowest=ema_slowest,
    )

    cash = initial_capital
    position = 0.0
    direction = 0
    entry_price = 0.0
    stop_price = 0.0
    take_profit = 0.0
    trades: list[dict] = []

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

        if direction == 0:
            session_allowed = in_session_window(
                df.loc[i, "close_time"],
                session=session,
                london_start=london_start,
                london_end=london_end,
                newyork_start=newyork_start,
                newyork_end=newyork_end,
                session_tz_offset=session_tz_offset,
            )
            if not session_allowed:
                continue
            if max_spread_pips > 0 and modeled_spread_pips > max_spread_pips:
                continue

            if df.loc[i, "long_signal"]:
                entry_price = df.loc[i + 1, "open"]
                allocation = cash * pct_per_trade
                position = allocation / entry_price
                cash -= allocation
                direction = 1
                stop_distance = stop_pips
                stop_price = entry_price - stop_distance
                take_profit = entry_price + stop_distance
                trades.append({"type": "buy", "index": i + 1, "price": entry_price, "qty": position, "reason": "long_entry"})
            elif df.loc[i, "short_signal"]:
                entry_price = df.loc[i + 1, "open"]
                allocation = cash * pct_per_trade
                position = allocation / entry_price
                cash += allocation
                direction = -1
                stop_distance = stop_pips
                stop_price = entry_price + stop_distance
                take_profit = entry_price - stop_distance
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
