import math
from loguru import logger

from .binance_connector import BinanceConnector
from .backtest import emarsi_backtest, prepare_ema_rsi_signals
from .config import BINANCE_API_KEY, BINANCE_API_SECRET, BINANCE_TESTNET, MAX_PCT_PER_TRADE


def _symbol_assets(symbol: str) -> tuple[str, str]:
    if symbol.endswith("USDT"):
        return symbol[:-4], "USDT"
    raise ValueError("Only USDT spot symbols are supported in this version of the paper trading bot.")


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calculate_order_quantity(conn: BinanceConnector, symbol: str, allocation_usdt: float, entry_price: float) -> float:
    quantity = allocation_usdt / entry_price
    rounded = conn.round_quantity(symbol, quantity)
    if rounded <= 0:
        raise ValueError(f"Order quantity too small after rounding: {quantity}")
    return rounded


def run_paper_trade(
    symbol: str,
    interval: str = "15m",
    limit: int = 500,
    fast: int = 9,
    slow: int = 21,
    rsi_period: int = 14,
    order_pct: float = MAX_PCT_PER_TRADE,
    stop_pips: float = 0.7,
    disable_oco: bool = False,
):
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        logger.error("Paper trading requires BINANCE_API_KEY and BINANCE_API_SECRET in .env")
        return

    if not BINANCE_TESTNET:
        logger.warning("BINANCE_TESTNET is disabled; paper trading will still attempt live spot orders.")

    connector = BinanceConnector(
        api_key=BINANCE_API_KEY,
        api_secret=BINANCE_API_SECRET,
        testnet=BINANCE_TESTNET,
    )

    if connector.client is None:
        logger.error("Authenticated Binance client is unavailable. Install python-binance and set API keys.")
        return

    df = connector.fetch_klines(symbol, interval, limit)
    if df.empty:
        logger.error("No candle data available for {}", symbol)
        return

    signals = prepare_ema_rsi_signals(df, ema_fast=fast, ema_slow=slow, rsi_period=rsi_period)
    latest = signals.iloc[-1]
    long_signal = bool(latest["long_signal"])
    short_signal = bool(latest["short_signal"])

    base_asset, quote_asset = _symbol_assets(symbol)
    quote_balance = connector.get_asset_balance(quote_asset)
    quote_free = _safe_float(quote_balance.get("free", 0.0))
    base_balance = connector.get_asset_balance(base_asset)
    base_free = _safe_float(base_balance.get("free", 0.0))

    logger.info("Latest candle close={} long_signal={} short_signal={}", latest["close"], long_signal, short_signal)
    logger.info("Balances: {} free={}, {} free={}", quote_asset, quote_free, base_asset, base_free)

    if long_signal:
        if base_free > 0:
            logger.info("Existing long position detected for {}: skipping new entry.", base_asset)
            return

        entry_price = _safe_float(connector.get_symbol_price(symbol).get("price", 0.0))
        if entry_price <= 0:
            logger.error("Unable to determine entry price for {}", symbol)
            return

        allocation = quote_free * order_pct
        if allocation <= 0:
            logger.error("No available {} quote balance to place an order.", quote_asset)
            return

        quantity = calculate_order_quantity(connector, symbol, allocation, entry_price)
        logger.info("Placing market buy for {} qty={} at price={} (allocation={} {} )", symbol, quantity, entry_price, allocation, quote_asset)
        order = connector.create_market_order(symbol, side="BUY", quantity=quantity)
        logger.info("Market order response: {}", order)

        if not disable_oco:
            stop_price = round(entry_price - stop_pips, 8)
            take_profit = round(entry_price + stop_pips, 8)
            stop_limit_price = round(stop_price * 0.999, 8)
            try:
                oco = connector.create_oco_order(
                    symbol=symbol,
                    side="SELL",
                    quantity=quantity,
                    price=take_profit,
                    stop_price=stop_price,
                    stop_limit_price=stop_limit_price,
                )
                logger.info("OCO stop-loss/take-profit order created: {}", oco)
            except Exception as exc:
                logger.warning("Failed to create OCO order: {}", exc)

        return

    if short_signal:
        if base_free <= 0:
            logger.info("Spot accounts cannot open short positions in this version. No action taken.")
            return

        logger.info("Short signal detected, closing existing long position for {}", base_asset)
        order = connector.create_market_order(symbol, side="SELL", quantity=base_free)
        logger.info("Market sell response: {}", order)
        return

    logger.info("No actionable signal in the latest candle for {}", symbol)


def run_paper_backtest(
    symbol: str,
    interval: str = "15m",
    limit: int = 500,
    fast: int = 9,
    slow: int = 21,
    rsi_period: int = 14,
):
    connector = BinanceConnector()
    df = connector.fetch_klines(symbol, interval, limit)
    if df.empty:
        logger.error("No data fetched for {}", symbol)
        return

    results = emarsi_backtest(
        df,
        ema_fast=fast,
        ema_slow=slow,
        rsi_period=rsi_period,
        initial_capital=10000.0,
        pct_per_trade=MAX_PCT_PER_TRADE,
    )
    logger.info(
        "Backtest results for {} ({}): PnL={} final equity={} trades={}",
        symbol,
        interval,
        results["pnl"],
        results["final_equity"],
        results["num_trades"],
    )
    logger.debug("Trades: {}", results["trades"])
    return results
