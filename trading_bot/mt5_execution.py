from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger

from .alerts import send_alert
from .backtest import in_session_window, prepare_ema_channel_signals
from .config import (
    MAX_SPREAD_PIPS,
    MAX_CONSECUTIVE_LOSSES,
    MAX_DAILY_LOSS_USDT,
    MAX_DRAWDOWN_PCT,
    MAX_TRADES_PER_DAY,
    MT5_BASE_MAGIC,
    PIP_SIZE,
)
from .mt5_connector import MT5Connector
from .state_store import TradingStateStore


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_risk_state(state_store: TradingStateStore, current_equity: float) -> dict:
    state = state_store.get_runtime_state("mt5_risk_state", default={}) or {}
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

    side = str(position.get("side", "BUY")).upper()
    pnl = (exit_price - entry_price) * qty if side == "BUY" else (entry_price - exit_price) * qty

    risk_state = state_store.get_runtime_state("mt5_risk_state", default={}) or {}
    if risk_state.get("day") != _today_key():
        risk_state = _load_risk_state(state_store, current_equity=0.0)

    risk_state["realized_pnl_today"] = float(risk_state.get("realized_pnl_today", 0.0)) + pnl
    if pnl < 0:
        risk_state["consecutive_losses"] = int(risk_state.get("consecutive_losses", 0)) + 1
    else:
        risk_state["consecutive_losses"] = 0
    state_store.set_runtime_state("mt5_risk_state", risk_state)


def _prepare_strategy_signals(df, fast: int, slow: int, ema2: int, ema4: int, ema5: int):
    return prepare_ema_channel_signals(
        df,
        ema_fast=fast,
        ema_mid=ema2,
        ema_slow=slow,
        ema_slower=ema4,
        ema_slowest=ema5,
    )


def run_mt5_trade(
    connector: MT5Connector,
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
    pip_size: float = PIP_SIZE,
    order_pct: float = 0.01,
    use_risk_pct: bool = True,
    risk_pct: float = 1.0,
    sl_pips: float | None = None,
    tp_pips: float | None = None,
    stop_pips: float = 0.7,
    magic: int | None = MT5_BASE_MAGIC,
    signal_debug: bool = False,
    state_file: str = "mt5_trading_state.db",
) -> None:
    """Run one MT5 strategy cycle at candle close."""
    state_store = TradingStateStore(state_file)
    df = connector.fetch_rates(symbol, interval=interval, limit=limit)
    if df.empty:
        logger.error("No MT5 candle data available for {}", symbol)
        return

    signals = prepare_ema_channel_signals(
        df,
        ema_fast=fast,
        ema_mid=ema2,
        ema_slow=slow,
        ema_slower=ema4,
        ema_slowest=ema5,
        include_state=signal_debug,
    )
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

    if state_store.is_signal_processed(symbol, signal_id):
        logger.info("MT5 signal already processed for {} at {}. Skipping duplicate.", symbol, latest_close_time)
        return

    logger.info(
        "MT5 latest close={} long_signal={} short_signal={}",
        latest["close"],
        long_signal,
        short_signal,
    )
    if signal_debug:
        logger.info(
            "MT5 signal-debug: entry_state={} trend={} bull_stack={} bear_stack={} breakout_up={} breakout_down={} retest_up={} retest_down={} confirm_up={} confirm_down={} close={} channel_top={} channel_bottom={}",
            latest.get("entry_state"),
            latest.get("trend"),
            bool(latest.get("bull_stack", False)),
            bool(latest.get("bear_stack", False)),
            bool(latest.get("breakout_up", False)),
            bool(latest.get("breakout_down", False)),
            bool(latest.get("retest_up", False)),
            bool(latest.get("retest_down", False)),
            bool(latest.get("confirm_up", False)),
            bool(latest.get("confirm_down", False)),
            latest["close"],
            latest.get("channel_top"),
            latest.get("channel_bottom"),
        )

    current_equity = connector.get_account_equity()
    risk_state = _load_risk_state(state_store, current_equity)
    was_tripped = bool(risk_state.get("breaker_tripped", False))
    tripped, reason = _risk_breaker_reason(risk_state, current_equity)
    if tripped:
        risk_state["breaker_tripped"] = True
        risk_state["breaker_reason"] = reason
        state_store.set_runtime_state("mt5_risk_state", risk_state)
        logger.error("MT5 risk breaker active: {}", reason)
        if not was_tripped:
            send_alert(f"MT5 risk breaker activated for {symbol}: {reason}", level="CRITICAL")
    else:
        risk_state["breaker_tripped"] = False
        risk_state["breaker_reason"] = ""
        state_store.set_runtime_state("mt5_risk_state", risk_state)
        if was_tripped:
            send_alert(f"MT5 risk breaker cleared for {symbol}. Trading can resume.", level="INFO")

    tracked_position = state_store.get_position(symbol)
    position = connector.get_net_position(symbol, magic=magic)
    if position is None and tracked_position:
        outcome = None
        outcome_fetcher = getattr(connector, "get_latest_closed_outcome", None)
        if callable(outcome_fetcher):
            try:
                outcome = outcome_fetcher(symbol=symbol, magic=magic)
            except Exception as exc:
                logger.warning("Unable to fetch MT5 closed outcome for {}: {}", symbol, exc)

        entry_price = _safe_float(tracked_position.get("entry_price", 0.0))
        qty = _safe_float(tracked_position.get("qty", 0.0))
        side = str(tracked_position.get("side", "")).upper() or "UNKNOWN"
        exit_price = _safe_float((outcome.exit_price if outcome else 0.0), 0.0)
        if exit_price <= 0:
            exit_price = _safe_float(latest.get("close", 0.0), 0.0)

        if entry_price > 0 and qty > 0 and exit_price > 0:
            if side == "BUY":
                estimated_pnl = (exit_price - entry_price) * qty
            else:
                estimated_pnl = (entry_price - exit_price) * qty
            realized_pnl = float(outcome.pnl) if outcome else estimated_pnl
            result = "WIN" if realized_pnl > 0 else "LOSS" if realized_pnl < 0 else "FLAT"
            logger.info(
                "MT5 trade outcome: result={} side={} qty={} entry={} exit={} pnl={} closed_at={} reason={}",
                result,
                side,
                qty,
                entry_price,
                exit_price,
                realized_pnl,
                outcome.close_time if outcome else latest_close_time,
                outcome.reason if outcome else "state_reconcile",
            )
            _record_exit_risk_metrics(state_store, symbol, exit_price)
        state_store.clear_position(symbol)

    if position is not None:
        logger.info("MT5 position already open for {} (side={}); no new entry.", symbol, position.side)
        state_store.mark_signal_processed(symbol, signal_id, {"action": "skipped", "reason": "position_open"})
        return

    if not long_signal and not short_signal:
        logger.info("No MT5 actionable signal for {}", symbol)
        return

    if tripped:
        logger.warning("Skipping MT5 entry due to active risk breaker: {}", reason)
        state_store.mark_signal_processed(symbol, signal_id, {"action": "skipped", "reason": reason})
        return

    if not session_allowed:
        logger.info("Skipping MT5 entry for {} because it is outside the configured session window.", symbol)
        state_store.mark_signal_processed(symbol, signal_id, {"action": "skipped", "reason": "out_of_session"})
        return

    spread_pips = connector.get_spread_pips(symbol, pip_size=pip_size)
    if max_spread_pips > 0 and spread_pips > max_spread_pips:
        logger.info(
            "Skipping MT5 entry for {} because spread is too wide: {} > {} pips.",
            symbol,
            spread_pips,
            max_spread_pips,
        )
        state_store.mark_signal_processed(symbol, signal_id, {"action": "skipped", "reason": "spread_too_wide"})
        return

    side = "BUY" if long_signal else "SELL"
    entry_price = connector.get_symbol_price(symbol, side=side)
    if entry_price <= 0:
        logger.error("Unable to obtain MT5 entry price for {}", symbol)
        return

    balance = connector.get_account_balance()
    effective_sl_pips = sl_pips if sl_pips is not None else 0.0
    effective_tp_pips = tp_pips if tp_pips is not None else 0.0

    if effective_sl_pips > 0:
        sl_distance = effective_sl_pips * pip_size
    else:
        # Backward compatibility: legacy stop_pips is an absolute price distance.
        sl_distance = stop_pips
    if effective_tp_pips > 0:
        tp_distance = effective_tp_pips * pip_size
    else:
        tp_distance = sl_distance

    if use_risk_pct and effective_sl_pips > 0:
        risk_amount = balance * (risk_pct / 100.0)
        volume = connector.volume_from_risk_pips(
            symbol=symbol,
            risk_amount=risk_amount,
            sl_pips=effective_sl_pips,
            pip_size=pip_size,
        )
        allocation = risk_amount
    else:
        allocation = balance * order_pct
        volume = connector.volume_from_allocation(symbol, allocation=allocation, entry_price=entry_price)

    if volume <= 0:
        logger.error("Calculated MT5 volume is too small for {} (allocation={})", symbol, allocation)
        return

    if side == "BUY":
        sl = entry_price - sl_distance
        tp = entry_price + tp_distance
    else:
        sl = entry_price + sl_distance
        tp = entry_price - tp_distance

    response = connector.place_market_order(
        symbol=symbol,
        side=side,
        volume=volume,
        sl=sl,
        tp=tp,
        comment="spec-ema-channel",
    )
    state_store.set_position(
        symbol,
        {
            "side": side,
            "qty": volume,
            "entry_price": entry_price,
            "updated_at": latest_close_time,
        },
    )
    risk_state["trades_today"] = int(risk_state.get("trades_today", 0)) + 1
    state_store.set_runtime_state("mt5_risk_state", risk_state)
    state_store.mark_signal_processed(symbol, signal_id, {"action": side.lower(), "qty": volume})
    logger.info(
        "MT5 order placed: side={} volume={} entry={} sl={} tp={} response={}",
        side,
        volume,
        entry_price,
        sl,
        tp,
        response,
    )
