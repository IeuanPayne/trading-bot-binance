import time
import hashlib
from datetime import datetime, timezone
from loguru import logger

from .binance_connector import BinanceConnector
from .backtest import ema_channel_backtest, in_session_window, prepare_ema_channel_signals
from .alerts import send_alert
from .state_store import TradingStateStore

# Strategy contract: EMA channel continuation with first-retest confirmation.
# Long: stacked EMAs, breakout above the channel, retest into the channel,
# then a confirming close back above the channel top.
# Short: inverse of the above.
# Spot accounts cannot open native shorts, so paper mode models short lifecycle
# synthetically (entry/stop/tp) in persisted state.
# Risk exits: stop_pips is absolute price distance (default 0.7), with 1:1 TP.
from .config import (
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    BINANCE_TESTNET,
    ALLOW_LIVE_TRADING,
    MAX_SPREAD_PIPS,
    MAX_PCT_PER_TRADE,
    MODELED_SPREAD_PIPS,
    MAX_DAILY_LOSS_USDT,
    MAX_DRAWDOWN_PCT,
    MAX_CONSECUTIVE_LOSSES,
    MAX_TRADES_PER_DAY,
)


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


def _prepare_strategy_signals(df, fast: int, slow: int, ema2: int, ema4: int, ema5: int):
    return prepare_ema_channel_signals(
        df,
        ema_fast=fast,
        ema_mid=ema2,
        ema_slow=slow,
        ema_slower=ema4,
        ema_slowest=ema5,
    )


def run_paper_trade(
    symbol: str,
    interval: str = "15m",
    limit: int = 500,
    fast: int = 8,
    slow: int = 21,
    ema2: int = 13,
    ema4: int = 34,
    ema5: int = 55,
    session: str = "Both",
    london_start: int = 11,
    london_end: int = 20,
    newyork_start: int = 16,
    newyork_end: int = 25,
    session_tz_offset: int = 3,
    max_spread_pips: float = MAX_SPREAD_PIPS,
    modeled_spread_pips: float = MODELED_SPREAD_PIPS,
    order_pct: float = MAX_PCT_PER_TRADE,
    stop_pips: float = 0.7,
    disable_oco: bool = False,
    state_file: str = "trading_state.db",
):
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        logger.error("Paper trading requires BINANCE_API_KEY and BINANCE_API_SECRET in .env")
        return

    if not BINANCE_TESTNET and not ALLOW_LIVE_TRADING:
        logger.error(
            "Refusing to place live orders with BINANCE_TESTNET=False. Set ALLOW_LIVE_TRADING=True to explicitly enable live trading."
        )
        return
    if not BINANCE_TESTNET and ALLOW_LIVE_TRADING:
        logger.warning("Live trading is enabled (BINANCE_TESTNET=False and ALLOW_LIVE_TRADING=True).")

    if stop_pips <= 0:
        logger.error("stop_pips must be greater than zero and is interpreted as absolute price distance (e.g. 0.7).")
        return

    connector = BinanceConnector(
        api_key=BINANCE_API_KEY,
        api_secret=BINANCE_API_SECRET,
        testnet=BINANCE_TESTNET,
    )

    if connector.client is None:
        logger.error("Authenticated Binance client is unavailable. Install python-binance and set API keys.")
        return

    state_store = TradingStateStore(state_file)

    df = connector.fetch_klines(symbol, interval, limit)
    if df.empty:
        logger.error("No candle data available for {}", symbol)
        return

    signals = _prepare_strategy_signals(df, fast, slow, ema2, ema4, ema5)
    latest = signals.iloc[-1]
    long_signal = bool(latest["long_signal"])
    short_signal = bool(latest["short_signal"])
    latest_close_time = str(latest.get("close_time"))
    signal_id = f"{latest_close_time}:{int(long_signal)}:{int(short_signal)}"
    session_allowed = in_session_window(
        latest.get("close_time"),
        session=session,
        london_start=london_start,
        london_end=london_end,
        newyork_start=newyork_start,
        newyork_end=newyork_end,
        session_tz_offset=session_tz_offset,
    )

    base_asset, quote_asset = _symbol_assets(symbol)
    quote_balance = connector.get_asset_balance(quote_asset)
    quote_free = _safe_float(quote_balance.get("free", 0.0))
    base_balance = connector.get_asset_balance(base_asset)
    base_free = _safe_float(base_balance.get("free", 0.0))

    logger.info("Latest candle close={} long_signal={} short_signal={}", latest["close"], long_signal, short_signal)
    logger.info("Balances: {} free={}, {} free={}", quote_asset, quote_free, base_asset, base_free)

    active_position = state_store.get_position(symbol)
    if active_position and active_position.get("side") == "SHORT":
        close_reason, close_price = _evaluate_short_exit(active_position, latest)
        if close_reason is not None and close_price is not None:
            logger.info("Closing synthetic short for {} due to {} at price={}", symbol, close_reason, close_price)
            _record_exit_risk_metrics(state_store, symbol, close_price)
            state_store.clear_position(symbol)
            state_store.mark_signal_processed(
                symbol,
                signal_id,
                {"action": "cover", "reason": close_reason, "price": close_price},
            )
            return
        logger.info("Synthetic short already open for {}; no new entry.", symbol)
        return

    if active_position and active_position.get("side") == "LONG":
        logger.info("Long position already open for {}; no new entry.", symbol)
        return

    current_equity = _current_equity(quote_free, base_free, _safe_float(latest["close"]))
    risk_state = _load_risk_state(state_store, current_equity)
    was_tripped = bool(risk_state.get("breaker_tripped", False))
    tripped, reason = _risk_breaker_reason(risk_state, current_equity)
    if tripped:
        risk_state["breaker_tripped"] = True
        risk_state["breaker_reason"] = reason
        state_store.set_runtime_state("risk_state", risk_state)
        logger.error("Risk breaker active: {}", reason)
        if not was_tripped:
            send_alert(f"Risk breaker activated for {symbol}: {reason}", level="CRITICAL")
    else:
        risk_state["breaker_tripped"] = False
        risk_state["breaker_reason"] = ""
        state_store.set_runtime_state("risk_state", risk_state)
        if was_tripped:
            send_alert(f"Risk breaker cleared for {symbol}. Trading can resume.", level="INFO")

    if state_store.is_signal_processed(symbol, signal_id):
        logger.info("Signal already processed for {} at {}. Skipping duplicate execution.", symbol, latest_close_time)
        return

    if (long_signal or short_signal) and not session_allowed:
        logger.info("Signal for {} ignored because it is outside the configured session window.", symbol)
        state_store.mark_signal_processed(symbol, signal_id, {"action": "skipped", "reason": "out_of_session"})
        return

    if (long_signal or short_signal) and max_spread_pips > 0 and modeled_spread_pips > max_spread_pips:
        logger.info(
            "Signal for {} ignored because modeled spread is too wide: {} > {} pips.",
            symbol,
            modeled_spread_pips,
            max_spread_pips,
        )
        state_store.mark_signal_processed(symbol, signal_id, {"action": "skipped", "reason": "spread_too_wide"})
        return

    if long_signal:
        if tripped:
            logger.warning("Skipping long entry due to active risk breaker: {}", reason)
            state_store.mark_signal_processed(symbol, signal_id, {"action": "skipped", "reason": reason})
            return

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
        is_valid, reason = connector.validate_market_order(symbol, quantity, entry_price)
        if not is_valid:
            logger.error("Pre-trade validation failed for {} BUY qty={}: {}", symbol, quantity, reason)
            return
        logger.info("Placing market buy for {} qty={} at price={} (allocation={} {} )", symbol, quantity, entry_price, allocation, quote_asset)
        market_buy_id = _build_client_order_id(symbol, latest_close_time, "buy")
        order = _submit_with_retry(
            connector.create_market_order,
            symbol=symbol,
            side="BUY",
            quantity=quantity,
            client_order_id=market_buy_id,
            action="market buy",
        )
        logger.info("Market order response: {}", order)

        position = {
            "side": "LONG",
            "qty": quantity,
            "entry_price": entry_price,
            "entry_order": order,
            "updated_at": latest_close_time,
        }

        if not disable_oco:
            stop_distance = stop_pips
            stop_price = connector.round_price(symbol, entry_price - stop_distance)
            take_profit = connector.round_price(symbol, entry_price + stop_distance)
            stop_limit_price = connector.round_price(symbol, stop_price * 0.999)
            try:
                list_id = _build_client_order_id(symbol, latest_close_time, "oco_list")
                tp_id = _build_client_order_id(symbol, latest_close_time, "oco_tp")
                sl_id = _build_client_order_id(symbol, latest_close_time, "oco_sl")
                oco = _submit_with_retry(
                    connector.create_oco_order,
                    symbol=symbol,
                    side="SELL",
                    quantity=quantity,
                    price=take_profit,
                    stop_price=stop_price,
                    stop_limit_price=stop_limit_price,
                    list_client_order_id=list_id,
                    limit_client_order_id=tp_id,
                    stop_client_order_id=sl_id,
                    action="oco create",
                )
                position["oco"] = oco
                logger.info("OCO stop-loss/take-profit order created: {}", oco)
            except Exception as exc:
                logger.error("Failed to create OCO order: {}", exc)
                send_alert(f"OCO placement failed for {symbol}. Attempting emergency flatten.", level="ERROR")
                flatten_id = _build_client_order_id(symbol, latest_close_time, "emergency_sell")
                try:
                    flatten_order = _submit_with_retry(
                        connector.create_market_order,
                        symbol=symbol,
                        side="SELL",
                        quantity=quantity,
                        client_order_id=flatten_id,
                        action="emergency market sell",
                    )
                    logger.warning("Emergency flatten order placed after OCO failure: {}", flatten_order)
                    send_alert(f"Emergency flatten executed for {symbol} after OCO failure.", level="CRITICAL")
                    state_store.clear_position(symbol)
                    state_store.mark_signal_processed(
                        symbol,
                        signal_id,
                        {"action": "emergency_flatten", "qty": quantity, "reason": "oco_failed"},
                    )
                    return
                except Exception as flatten_exc:
                    logger.error("Emergency flatten failed after OCO failure: {}", flatten_exc)
                    send_alert(
                        f"Emergency flatten FAILED for {symbol}. Position may be unprotected. Immediate action required.",
                        level="CRITICAL",
                    )
                    position["protection_status"] = "unprotected"
                    position["protection_error"] = str(exc)

        state_store.set_position(symbol, position)
        risk_state["trades_today"] = int(risk_state.get("trades_today", 0)) + 1
        state_store.set_runtime_state("risk_state", risk_state)
        state_store.mark_signal_processed(symbol, signal_id, {"action": "buy", "qty": quantity})

        return

    if short_signal:
        if base_free <= 0:
            entry_price = _safe_float(connector.get_symbol_price(symbol).get("price", 0.0))
            if entry_price <= 0:
                logger.error("Unable to determine entry price for synthetic short on {}", symbol)
                return

            allocation = quote_free * order_pct
            if allocation <= 0:
                logger.error("No available {} quote balance to model a short position.", quote_asset)
                return

            quantity = calculate_order_quantity(connector, symbol, allocation, entry_price)
            stop_price = connector.round_price(symbol, entry_price + stop_pips)
            take_profit = connector.round_price(symbol, entry_price - stop_pips)
            position = {
                "side": "SHORT",
                "qty": quantity,
                "entry_price": entry_price,
                "stop_price": stop_price,
                "take_profit": take_profit,
                "entry_mode": "synthetic",
                "updated_at": latest_close_time,
            }
            state_store.set_position(symbol, position)
            risk_state["trades_today"] = int(risk_state.get("trades_today", 0)) + 1
            state_store.set_runtime_state("risk_state", risk_state)
            state_store.mark_signal_processed(
                symbol,
                signal_id,
                {"action": "sell_short", "qty": quantity, "entry_price": entry_price},
            )
            logger.info(
                "Synthetic short opened for {} qty={} entry={} stop={} tp={}",
                symbol,
                quantity,
                entry_price,
                stop_price,
                take_profit,
            )
            return
        logger.info("Spot long position detected for {}; friend-style strategy does not flip on opposite signal.", base_asset)
        return

    logger.info("No actionable signal in the latest candle for {}", symbol)


def _submit_with_retry(fn, retries: int = 3, initial_delay: float = 0.5, action: str = "order", **kwargs):
    """Retry transient order failures with exponential backoff."""
    delay = initial_delay
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return fn(**kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt == retries:
                break
            logger.warning("{} failed (attempt {}/{}): {}. Retrying in {}s.", action, attempt, retries, exc, delay)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"{action} failed after {retries} attempts: {last_exc}")


def _build_client_order_id(symbol: str, candle_id: str, action: str) -> str:
    """Build deterministic Binance client order IDs for idempotent retries."""
    payload = f"{symbol}|{candle_id}|{action}".encode("utf-8")
    digest = hashlib.sha1(payload).hexdigest()[:20]
    return f"tb_{action[:8]}_{digest}"


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _current_equity(quote_free: float, base_free: float, mark_price: float) -> float:
    return quote_free + (base_free * mark_price)


def _load_risk_state(state_store: TradingStateStore, current_equity: float) -> dict:
    state = state_store.get_runtime_state("risk_state", default={}) or {}
    today = _today_key()
    if state.get("day") != today:
        state["day"] = today
        state["realized_pnl_today"] = 0.0
        state["trades_today"] = 0
        state["consecutive_losses"] = 0
        state["day_start_equity"] = current_equity
    state["peak_equity"] = max(float(state.get("peak_equity", current_equity)), current_equity)
    state.setdefault("breaker_tripped", False)
    state.setdefault("breaker_reason", "")
    return state


def _risk_breaker_reason(risk_state: dict, current_equity: float) -> tuple[bool, str]:
    daily_pnl = float(risk_state.get("realized_pnl_today", 0.0))
    if MAX_DAILY_LOSS_USDT > 0 and daily_pnl <= -MAX_DAILY_LOSS_USDT:
        return True, f"daily loss limit reached ({daily_pnl:.4f} <= -{MAX_DAILY_LOSS_USDT:.4f})"

    peak_equity = float(risk_state.get("peak_equity", current_equity))
    if MAX_DRAWDOWN_PCT > 0 and peak_equity > 0:
        drawdown_pct = ((peak_equity - current_equity) / peak_equity) * 100.0
        if drawdown_pct >= MAX_DRAWDOWN_PCT:
            return True, f"max drawdown reached ({drawdown_pct:.2f}% >= {MAX_DRAWDOWN_PCT:.2f}%)"

    consecutive_losses = int(risk_state.get("consecutive_losses", 0))
    if MAX_CONSECUTIVE_LOSSES > 0 and consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
        return True, f"max consecutive losses reached ({consecutive_losses} >= {MAX_CONSECUTIVE_LOSSES})"

    trades_today = int(risk_state.get("trades_today", 0))
    if MAX_TRADES_PER_DAY > 0 and trades_today >= MAX_TRADES_PER_DAY:
        return True, f"max trades per day reached ({trades_today} >= {MAX_TRADES_PER_DAY})"

    return False, ""


def _record_exit_risk_metrics(state_store: TradingStateStore, symbol: str, exit_price: float) -> None:
    position = state_store.get_position(symbol)
    if not position:
        return

    qty = _safe_float(position.get("qty", 0.0))
    entry_price = _safe_float(position.get("entry_price", 0.0))
    if qty <= 0 or entry_price <= 0 or exit_price <= 0:
        return

    side = str(position.get("side", "LONG")).upper()
    if side == "SHORT":
        pnl = (entry_price - exit_price) * qty
    else:
        pnl = (exit_price - entry_price) * qty
    risk_state = state_store.get_runtime_state("risk_state", default={}) or {}
    if risk_state.get("day") != _today_key():
        # Keep daily boundaries consistent even if called after midnight rollover.
        risk_state = _load_risk_state(state_store, current_equity=0.0)

    risk_state["realized_pnl_today"] = float(risk_state.get("realized_pnl_today", 0.0)) + pnl
    if pnl < 0:
        risk_state["consecutive_losses"] = int(risk_state.get("consecutive_losses", 0)) + 1
    else:
        risk_state["consecutive_losses"] = 0
    state_store.set_runtime_state("risk_state", risk_state)


def _evaluate_short_exit(position: dict, latest) -> tuple[str | None, float | None]:
    """Evaluate synthetic short exits against the latest closed candle."""
    stop_price = _safe_float(position.get("stop_price", 0.0))
    take_profit = _safe_float(position.get("take_profit", 0.0))
    high = _safe_float(latest.get("high", 0.0))
    low = _safe_float(latest.get("low", 0.0))
    close = _safe_float(latest.get("close", 0.0))

    if stop_price > 0 and high >= stop_price:
        return "tp/sl", stop_price
    if take_profit > 0 and low <= take_profit:
        return "tp/sl", take_profit
    return None, None


def run_paper_backtest(
    symbol: str,
    interval: str = "15m",
    limit: int = 500,
    fast: int = 8,
    slow: int = 21,
    ema2: int = 13,
    ema4: int = 34,
    ema5: int = 55,
    session: str = "Both",
    london_start: int = 11,
    london_end: int = 20,
    newyork_start: int = 16,
    newyork_end: int = 25,
    session_tz_offset: int = 3,
    modeled_spread_pips: float = MODELED_SPREAD_PIPS,
    max_spread_pips: float = MAX_SPREAD_PIPS,
):
    connector = BinanceConnector()
    df = connector.fetch_klines(symbol, interval, limit)
    if df.empty:
        logger.error("No data fetched for {}", symbol)
        return

    results = ema_channel_backtest(
        df,
        ema_fast=fast,
        ema_mid=ema2,
        ema_slow=slow,
        ema_slower=ema4,
        ema_slowest=ema5,
        session=session,
        london_start=london_start,
        london_end=london_end,
        newyork_start=newyork_start,
        newyork_end=newyork_end,
        session_tz_offset=session_tz_offset,
        modeled_spread_pips=modeled_spread_pips,
        max_spread_pips=max_spread_pips,
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
