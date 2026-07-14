from __future__ import annotations

from loguru import logger

from .backtest import prepare_ema_rsi_signals
from .mt5_connector import MT5Connector


def run_mt5_trade(
    connector: MT5Connector,
    symbol: str,
    interval: str = "15m",
    limit: int = 500,
    fast: int = 9,
    slow: int = 21,
    rsi_period: int = 14,
    order_pct: float = 0.01,
    stop_pips: float = 0.7,
) -> None:
    """Run one MT5 strategy cycle at candle close."""
    df = connector.fetch_rates(symbol, interval=interval, limit=limit)
    if df.empty:
        logger.error("No MT5 candle data available for {}", symbol)
        return

    signals = prepare_ema_rsi_signals(df, ema_fast=fast, ema_slow=slow, rsi_period=rsi_period)
    latest = signals.iloc[-1]
    long_signal = bool(latest["long_signal"])
    short_signal = bool(latest["short_signal"])

    logger.info(
        "MT5 latest close={} long_signal={} short_signal={}",
        latest["close"],
        long_signal,
        short_signal,
    )

    position = connector.get_net_position(symbol)

    if position is not None:
        if position.side == "BUY" and short_signal:
            logger.info("MT5 opposite short signal detected: closing BUY position first")
            connector.close_position(symbol, position, comment="spec-opposite-close-buy")
            position = None
        elif position.side == "SELL" and long_signal:
            logger.info("MT5 opposite long signal detected: closing SELL position first")
            connector.close_position(symbol, position, comment="spec-opposite-close-sell")
            position = None

    if position is not None:
        logger.info("MT5 position already open for {} (side={}); no new entry.", symbol, position.side)
        return

    if not long_signal and not short_signal:
        logger.info("No MT5 actionable signal for {}", symbol)
        return

    side = "BUY" if long_signal else "SELL"
    entry_price = connector.get_symbol_price(symbol, side=side)
    if entry_price <= 0:
        logger.error("Unable to obtain MT5 entry price for {}", symbol)
        return

    balance = connector.get_account_balance()
    allocation = balance * order_pct
    volume = connector.volume_from_allocation(symbol, allocation=allocation, entry_price=entry_price)
    if volume <= 0:
        logger.error("Calculated MT5 volume is too small for {} (allocation={})", symbol, allocation)
        return

    if side == "BUY":
        sl = entry_price - stop_pips
        tp = entry_price + stop_pips
    else:
        sl = entry_price + stop_pips
        tp = entry_price - stop_pips

    response = connector.place_market_order(
        symbol=symbol,
        side=side,
        volume=volume,
        sl=sl,
        tp=tp,
        comment="spec-ema-rsi",
    )
    logger.info(
        "MT5 order placed: side={} volume={} entry={} sl={} tp={} response={}",
        side,
        volume,
        entry_price,
        sl,
        tp,
        response,
    )
