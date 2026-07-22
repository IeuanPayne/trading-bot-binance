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
    MT5_ALLOW_MULTIPLE_POSITIONS,
    MT5_BASE_MAGIC,
    MT5_STAGED_BE_OFFSET_PIPS,
    MT5_STAGED_BE_TRIGGER_PIPS,
    MT5_STAGED_EXIT_ENABLED,
    MT5_STAGED_TP4_OPEN,
    MT5_STAGED_TRAIL_PIPS,
    PIP_SIZE,
)
from .mt5_connector import MT5Connector
from .state_store import TradingStateStore


_STAGED_TP_MULTIPLIERS = {
    "tp1": 1.0,
    "tp2": 2.0,
    "tp3": 3.0,
    "tp4": 10.0,
}

_STAGED_TP_ORDER = ("tp1", "tp2", "tp3", "tp4")


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

    _record_realized_pnl(state_store, pnl)


def _record_realized_pnl(state_store: TradingStateStore, pnl: float) -> None:
    if pnl == 0:
        return

    risk_state = state_store.get_runtime_state("mt5_risk_state", default={}) or {}
    if risk_state.get("day") != _today_key():
        risk_state = _load_risk_state(state_store, current_equity=0.0)

    risk_state["realized_pnl_today"] = float(risk_state.get("realized_pnl_today", 0.0)) + pnl
    if pnl < 0:
        risk_state["consecutive_losses"] = int(risk_state.get("consecutive_losses", 0)) + 1
    else:
        risk_state["consecutive_losses"] = 0
    state_store.set_runtime_state("mt5_risk_state", risk_state)


def _staged_target_price(side: str, entry_price: float, initial_r: float, rr_multiple: float) -> float:
    if side == "BUY":
        return entry_price + (initial_r * rr_multiple)
    return entry_price - (initial_r * rr_multiple)


def _staged_trigger_price(side: str, entry_price: float, distance: float) -> float:
    if side == "BUY":
        return entry_price + distance
    return entry_price - distance


def _target_hit(side: str, mark_price: float, target_price: float) -> bool:
    if side == "BUY":
        return mark_price >= target_price
    return mark_price <= target_price


def _is_more_protective_stop(side: str, candidate: float, current: float) -> bool:
    if current <= 0:
        return True
    if side == "BUY":
        return candidate > current
    return candidate < current


def _is_valid_stop(side: str, stop_price: float, mark_price: float) -> bool:
    if stop_price <= 0 or mark_price <= 0:
        return False
    if side == "BUY":
        return stop_price < mark_price
    return stop_price > mark_price


def _normalize_partial_close_volume(connector: MT5Connector, symbol: str, requested: float, remaining: float, is_final: bool) -> float:
    if is_final:
        return remaining

    close_volume = requested
    volume_normalizer = getattr(connector, "normalize_volume", None)
    if callable(volume_normalizer):
        close_volume = float(volume_normalizer(symbol, requested))

    close_volume = min(close_volume, remaining)
    if close_volume <= 0:
        return 0.0
    return close_volume


def _round_position_qty(qty: float) -> float:
    return round(max(0.0, qty), 12)


def _build_staged_position_state(
    side: str,
    entry_price: float,
    sl: float,
    qty: float,
    pip_size: float,
    staged_be_trigger_pips: float,
    staged_be_offset_pips: float,
    staged_trail_pips: float,
    staged_tp4_open: bool,
) -> dict:
    initial_r = abs(entry_price - sl)
    be_trigger_distance = staged_be_trigger_pips * pip_size
    be_offset_distance = staged_be_offset_pips * pip_size
    trail_distance = staged_trail_pips * pip_size
    be_stop_price = entry_price + be_offset_distance if side == "BUY" else entry_price - be_offset_distance

    state = {
        "side": side,
        "qty": qty,
        "initial_qty": qty,
        "entry_price": entry_price,
        "sl": sl,
        "initial_sl": sl,
        "initial_r": initial_r,
        "updated_at": "",
        "staged_exit_enabled": True,
        "moved_to_be": False,
        "trailing_active": False,
        "be_trigger_price": _staged_trigger_price(side, entry_price, be_trigger_distance),
        "be_stop_price": be_stop_price,
        "trail_distance": trail_distance,
        "tp4_open": staged_tp4_open,
        "realized_pnl": 0.0,
    }

    for label, rr_multiple in _STAGED_TP_MULTIPLIERS.items():
        state[label] = _staged_target_price(side, entry_price, initial_r, rr_multiple)
        state[f"{label}_hit"] = False

    state["tp"] = 0.0 if staged_tp4_open else state["tp4"]
    return state


def _ensure_staged_position_state(
    tracked_position: dict | None,
    position,
    pip_size: float,
    staged_be_trigger_pips: float,
    staged_be_offset_pips: float,
    staged_trail_pips: float,
    staged_tp4_open: bool,
) -> dict | None:
    tracked = dict(tracked_position or {})
    side = str(tracked.get("side", getattr(position, "side", ""))).upper()
    entry_price = _safe_float(tracked.get("entry_price", getattr(position, "price_open", 0.0)))
    current_sl = _safe_float(tracked.get("initial_sl", tracked.get("sl", getattr(position, "sl", 0.0))))
    current_qty = _safe_float(tracked.get("qty", getattr(position, "volume", 0.0)))

    if side not in ("BUY", "SELL") or entry_price <= 0 or current_sl <= 0 or current_qty <= 0:
        return None

    base_state = _build_staged_position_state(
        side=side,
        entry_price=entry_price,
        sl=current_sl,
        qty=current_qty,
        pip_size=pip_size,
        staged_be_trigger_pips=staged_be_trigger_pips,
        staged_be_offset_pips=staged_be_offset_pips,
        staged_trail_pips=staged_trail_pips,
        staged_tp4_open=staged_tp4_open,
    )

    merged = base_state
    merged.update(tracked)
    merged["side"] = side
    merged["entry_price"] = entry_price
    merged.setdefault("initial_qty", current_qty)
    merged.setdefault("initial_sl", current_sl)
    merged.setdefault("initial_r", abs(entry_price - current_sl))
    merged.setdefault("be_trigger_price", base_state["be_trigger_price"])
    merged.setdefault("be_stop_price", base_state["be_stop_price"])
    merged.setdefault("trail_distance", base_state["trail_distance"])
    merged.setdefault("tp4_open", staged_tp4_open)
    merged.setdefault("tp", 0.0 if staged_tp4_open else merged.get("tp4", base_state["tp4"]))
    return merged


def _maybe_manage_staged_exit(
    connector: MT5Connector,
    state_store: TradingStateStore,
    symbol: str,
    position,
    tracked_position: dict | None,
    pip_size: float,
    staged_exit_enabled: bool,
    staged_be_trigger_pips: float,
    staged_be_offset_pips: float,
    staged_trail_pips: float,
    staged_tp4_open: bool,
    latest_close_time: str,
) -> bool:
    if not staged_exit_enabled:
        return False

    tracked = _ensure_staged_position_state(
        tracked_position=tracked_position,
        position=position,
        pip_size=pip_size,
        staged_be_trigger_pips=staged_be_trigger_pips,
        staged_be_offset_pips=staged_be_offset_pips,
        staged_trail_pips=staged_trail_pips,
        staged_tp4_open=staged_tp4_open,
    )
    if tracked is None:
        return False

    side = str(tracked.get("side", getattr(position, "side", ""))).upper()
    mark_price = connector.get_symbol_price(symbol, side="SELL" if side == "BUY" else "BUY")
    if mark_price <= 0:
        return True

    current_sl = _safe_float(getattr(position, "sl", tracked.get("sl", 0.0)), default=_safe_float(tracked.get("sl", 0.0)))
    current_tp = _safe_float(getattr(position, "tp", tracked.get("tp", 0.0)), default=_safe_float(tracked.get("tp", 0.0)))
    desired_sl = current_sl
    desired_tp = 0.0 if tracked.get("tp4_open", False) else _safe_float(tracked.get("tp4", current_tp), current_tp)
    remaining_qty = _safe_float(tracked.get("qty", getattr(position, "volume", 0.0)))
    initial_qty = _safe_float(tracked.get("initial_qty", remaining_qty))

    if not tracked.get("moved_to_be", False) and _target_hit(side, mark_price, _safe_float(tracked.get("be_trigger_price", 0.0))):
        be_stop_price = _safe_float(tracked.get("be_stop_price", 0.0))
        if _is_valid_stop(side, be_stop_price, mark_price) and _is_more_protective_stop(side, be_stop_price, desired_sl):
            desired_sl = be_stop_price
        tracked["moved_to_be"] = True

    for label in _STAGED_TP_ORDER:
        if label == "tp4" and tracked.get("tp4_open", False):
            continue
        if tracked.get(f"{label}_hit", False):
            continue

        target_price = _safe_float(tracked.get(label, 0.0))
        if target_price <= 0 or not _target_hit(side, mark_price, target_price):
            continue

        close_volume = _normalize_partial_close_volume(
            connector=connector,
            symbol=symbol,
            requested=initial_qty * 0.25,
            remaining=remaining_qty,
            is_final=(label == "tp4"),
        )
        if close_volume <= 0:
            logger.warning("Unable to close staged MT5 slice for {} at {} because calculated close volume was invalid.", symbol, label)
            break

        response = connector.close_position(
            symbol=symbol,
            position=position,
            volume=close_volume,
            comment=f"spec-ema-channel-{label}",
        )
        pnl = (mark_price - _safe_float(tracked.get("entry_price", 0.0))) * close_volume
        if side == "SELL":
            pnl = (_safe_float(tracked.get("entry_price", 0.0)) - mark_price) * close_volume
        _record_realized_pnl(state_store, pnl)

        remaining_qty = _round_position_qty(remaining_qty - close_volume)
        tracked["qty"] = remaining_qty
        tracked["realized_pnl"] = float(tracked.get("realized_pnl", 0.0)) + pnl
        tracked[f"{label}_hit"] = True
        tracked["updated_at"] = latest_close_time

        logger.info(
            "MT5 staged exit hit: symbol={} target={} side={} close_volume={} mark_price={} remaining_qty={} response={}",
            symbol,
            label,
            side,
            close_volume,
            mark_price,
            remaining_qty,
            response,
        )

        if label == "tp1":
            tracked["trailing_active"] = True
        elif label == "tp2":
            tracked["trailing_active"] = False
            tp1_price = _safe_float(tracked.get("tp1", 0.0))
            if _is_valid_stop(side, tp1_price, mark_price) and _is_more_protective_stop(side, tp1_price, desired_sl):
                desired_sl = tp1_price

        if remaining_qty <= 0:
            state_store.clear_position(symbol)
            return True

    if tracked.get("trailing_active", False) and not tracked.get("tp2_hit", False):
        trail_distance = _safe_float(tracked.get("trail_distance", 0.0))
        if trail_distance > 0:
            candidate_sl = mark_price - trail_distance if side == "BUY" else mark_price + trail_distance
            be_floor = _safe_float(tracked.get("be_stop_price", tracked.get("entry_price", 0.0)))
            if side == "BUY":
                candidate_sl = max(candidate_sl, be_floor)
            else:
                candidate_sl = min(candidate_sl, be_floor)
            if _is_valid_stop(side, candidate_sl, mark_price) and _is_more_protective_stop(side, candidate_sl, desired_sl):
                desired_sl = candidate_sl

    if tracked.get("tp2_hit", False):
        tp1_price = _safe_float(tracked.get("tp1", 0.0))
        if _is_valid_stop(side, tp1_price, mark_price) and _is_more_protective_stop(side, tp1_price, desired_sl):
            desired_sl = tp1_price

    sl_changed = abs(desired_sl - current_sl) > 1e-9
    tp_changed = abs(desired_tp - current_tp) > 1e-9
    if (sl_changed and _is_valid_stop(side, desired_sl, mark_price)) or tp_changed:
        response = connector.modify_position_sltp(symbol=symbol, position=position, sl=desired_sl, tp=desired_tp)
        tracked["sl"] = desired_sl
        tracked["tp"] = desired_tp
        logger.info(
            "MT5 staged stop updated: side={} entry={} mark={} old_sl={} new_sl={} tp={} response={}",
            side,
            _safe_float(tracked.get("entry_price", 0.0)),
            mark_price,
            current_sl,
            desired_sl,
            desired_tp,
            response,
        )
    else:
        tracked["sl"] = current_sl
        tracked["tp"] = current_tp

    tracked["updated_at"] = latest_close_time
    state_store.set_position(symbol, tracked)
    return True


def _prepare_strategy_signals(df, fast: int, slow: int, ema2: int, ema4: int, ema5: int):
    return prepare_ema_channel_signals(
        df,
        ema_fast=fast,
        ema_mid=ema2,
        ema_slow=slow,
        ema_slower=ema4,
        ema_slowest=ema5,
    )


def _compute_atr_distance(df, period: int) -> float | None:
    if period <= 0 or len(df) < period + 1:
        return None

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)

    tr = (high - low).abs()
    tr = tr.combine((high - prev_close).abs(), max)
    tr = tr.combine((low - prev_close).abs(), max)

    atr = tr.rolling(window=period, min_periods=period).mean().iloc[-1]
    atr_value = _safe_float(atr, default=0.0)
    if atr_value <= 0:
        return None
    return atr_value


def _maybe_apply_trailing_stop(
    connector: MT5Connector,
    state_store: TradingStateStore,
    symbol: str,
    position,
    df,
    tracked_position: dict | None,
    trailing_stop: bool,
    trail_activate_r: float,
    trail_atr_period: int,
    trail_atr_mult: float,
    trail_min_step_atr: float,
) -> None:
    if not trailing_stop:
        return

    tracked = tracked_position or {}
    side = str(getattr(position, "side", tracked.get("side", ""))).upper()
    entry_price = _safe_float(tracked.get("entry_price", getattr(position, "price_open", 0.0)))
    initial_sl = _safe_float(tracked.get("sl", getattr(position, "sl", 0.0)))
    current_sl = _safe_float(getattr(position, "sl", 0.0), default=initial_sl)
    current_tp = _safe_float(getattr(position, "tp", tracked.get("tp", 0.0)))
    initial_r = abs(entry_price - initial_sl)

    if side not in ("BUY", "SELL") or entry_price <= 0 or initial_r <= 0:
        return

    mark_price = connector.get_symbol_price(symbol, side="SELL" if side == "BUY" else "BUY")
    if mark_price <= 0:
        return

    favorable_move = mark_price - entry_price if side == "BUY" else entry_price - mark_price
    if favorable_move < (trail_activate_r * initial_r):
        return

    atr_distance = _compute_atr_distance(df, trail_atr_period)
    if atr_distance is None:
        logger.warning(
            "MT5 trailing stop active but ATR unavailable (period={} rows={}); skipping trail update.",
            trail_atr_period,
            len(df),
        )
        return

    trail_offset = atr_distance * trail_atr_mult
    if trail_offset <= 0:
        return
    min_step = max(0.0, atr_distance * trail_min_step_atr)

    if side == "BUY":
        candidate_sl = mark_price - trail_offset
        # After activation, never allow trailing SL below break-even.
        new_sl = max(candidate_sl, entry_price)
        if new_sl <= current_sl or new_sl >= mark_price:
            return
        if min_step > 0 and (new_sl - current_sl) < min_step:
            return
    else:
        candidate_sl = mark_price + trail_offset
        # After activation, never allow trailing SL above break-even.
        new_sl = min(candidate_sl, entry_price)
        if new_sl >= current_sl or new_sl <= mark_price:
            return
        if min_step > 0 and (current_sl - new_sl) < min_step:
            return

    response = connector.modify_position_sltp(symbol=symbol, position=position, sl=new_sl, tp=current_tp)
    tracked["sl"] = new_sl
    tracked["updated_at"] = str(df.iloc[-1].get("close_time"))
    if tracked:
        state_store.set_position(symbol, tracked)
    logger.info(
        "MT5 trailing stop updated: side={} entry={} mark={} old_sl={} new_sl={} tp={} response={}",
        side,
        entry_price,
        mark_price,
        current_sl,
        new_sl,
        current_tp,
        response,
    )


def _manage_existing_mt5_position(
    connector: MT5Connector,
    state_store: TradingStateStore,
    symbol: str,
    position,
    tracked_position: dict | None,
    df,
    latest_close_time: str,
    pip_size: float,
    trailing_stop: bool,
    trail_activate_r: float,
    trail_atr_period: int,
    trail_atr_mult: float,
    trail_min_step_atr: float,
    staged_exit_enabled: bool,
    staged_be_trigger_pips: float,
    staged_be_offset_pips: float,
    staged_trail_pips: float,
    staged_tp4_open: bool,
    magic: int | None,
    entry_mode: bool = True,
) -> bool:
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
            exit_price = _safe_float(df.iloc[-1].get("close", 0.0), 0.0)

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
        return False

    if position is None:
        return False

    try:
        if not _maybe_manage_staged_exit(
            connector=connector,
            state_store=state_store,
            symbol=symbol,
            position=position,
            tracked_position=tracked_position,
            pip_size=pip_size,
            staged_exit_enabled=staged_exit_enabled,
            staged_be_trigger_pips=staged_be_trigger_pips,
            staged_be_offset_pips=staged_be_offset_pips,
            staged_trail_pips=staged_trail_pips,
            staged_tp4_open=staged_tp4_open,
            latest_close_time=latest_close_time,
        ):
            _maybe_apply_trailing_stop(
                connector=connector,
                state_store=state_store,
                symbol=symbol,
                position=position,
                df=df,
                tracked_position=tracked_position,
                trailing_stop=trailing_stop,
                trail_activate_r=trail_activate_r,
                trail_atr_period=trail_atr_period,
                trail_atr_mult=trail_atr_mult,
                trail_min_step_atr=trail_min_step_atr,
            )
    except Exception as exc:
        logger.warning("MT5 trailing stop update skipped for {}: {}", symbol, exc)

    if entry_mode:
        logger.info("MT5 position already open for {} (side={}); no new entry.", symbol, position.side)
    else:
        logger.debug("MT5 management: existing position for {} (side={}) remains open.", symbol, position.side)
    return True


def manage_mt5_position_cycle(
    connector: MT5Connector,
    symbol: str,
    interval: str = "15m",
    limit: int = 500,
    pip_size: float = PIP_SIZE,
    trailing_stop: bool = False,
    trail_activate_r: float = 1.0,
    trail_atr_period: int = 14,
    trail_atr_mult: float = 1.0,
    trail_min_step_atr: float = 0.2,
    staged_exit_enabled: bool = MT5_STAGED_EXIT_ENABLED,
    staged_be_trigger_pips: float = MT5_STAGED_BE_TRIGGER_PIPS,
    staged_be_offset_pips: float = MT5_STAGED_BE_OFFSET_PIPS,
    staged_trail_pips: float = MT5_STAGED_TRAIL_PIPS,
    staged_tp4_open: bool = MT5_STAGED_TP4_OPEN,
    magic: int | None = MT5_BASE_MAGIC,
    state_file: str = "mt5_trading_state.db",
) -> bool:
    state_store = TradingStateStore(state_file)
    df = connector.fetch_rates(symbol, interval=interval, limit=limit)
    if df.empty:
        logger.error("No MT5 candle data available for {} during position management", symbol)
        return False

    tracked_position = state_store.get_position(symbol)
    position = connector.get_net_position(symbol, magic=magic)
    latest_close_time = str(df.iloc[-1].get("close_time"))

    return _manage_existing_mt5_position(
        connector=connector,
        state_store=state_store,
        symbol=symbol,
        position=position,
        tracked_position=tracked_position,
        df=df,
        latest_close_time=latest_close_time,
        pip_size=pip_size,
        trailing_stop=trailing_stop,
        trail_activate_r=trail_activate_r,
        trail_atr_period=trail_atr_period,
        trail_atr_mult=trail_atr_mult,
        trail_min_step_atr=trail_min_step_atr,
        staged_exit_enabled=staged_exit_enabled,
        staged_be_trigger_pips=staged_be_trigger_pips,
        staged_be_offset_pips=staged_be_offset_pips,
        staged_trail_pips=staged_trail_pips,
        staged_tp4_open=staged_tp4_open,
        magic=magic,
        entry_mode=False,
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
    dynamic_sltp: bool = False,
    atr_period: int = 14,
    sl_atr_mult: float = 1.5,
    tp_atr_mult: float = 2.0,
    trailing_stop: bool = False,
    trail_activate_r: float = 1.0,
    trail_atr_period: int = 14,
    trail_atr_mult: float = 1.0,
    trail_min_step_atr: float = 0.2,
    staged_exit_enabled: bool = MT5_STAGED_EXIT_ENABLED,
    staged_be_trigger_pips: float = MT5_STAGED_BE_TRIGGER_PIPS,
    staged_be_offset_pips: float = MT5_STAGED_BE_OFFSET_PIPS,
    staged_trail_pips: float = MT5_STAGED_TRAIL_PIPS,
    staged_tp4_open: bool = MT5_STAGED_TP4_OPEN,
    stop_pips: float = 0.7,
    magic: int | None = MT5_BASE_MAGIC,
    allow_multiple_positions: bool = MT5_ALLOW_MULTIPLE_POSITIONS,
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
    has_open_position = _manage_existing_mt5_position(
        connector=connector,
        state_store=state_store,
        symbol=symbol,
        position=position,
        tracked_position=tracked_position,
        df=df,
        latest_close_time=latest_close_time,
        pip_size=pip_size,
        trailing_stop=trailing_stop,
        trail_activate_r=trail_activate_r,
        trail_atr_period=trail_atr_period,
        trail_atr_mult=trail_atr_mult,
        trail_min_step_atr=trail_min_step_atr,
        staged_exit_enabled=staged_exit_enabled,
        staged_be_trigger_pips=staged_be_trigger_pips,
        staged_be_offset_pips=staged_be_offset_pips,
        staged_trail_pips=staged_trail_pips,
        staged_tp4_open=staged_tp4_open,
        magic=magic,
        entry_mode=True,
    )
    if has_open_position and not allow_multiple_positions:
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

    dynamic_applied = False
    if dynamic_sltp:
        atr_distance = _compute_atr_distance(df, atr_period)
        if atr_distance is not None:
            sl_distance = atr_distance * sl_atr_mult
            tp_distance = atr_distance * tp_atr_mult
            if pip_size > 0:
                effective_sl_pips = sl_distance / pip_size
                effective_tp_pips = tp_distance / pip_size
            dynamic_applied = True
            logger.info(
                "MT5 dynamic SL/TP: atr={} period={} sl_atr_mult={} tp_atr_mult={} sl_distance={} tp_distance={}",
                atr_distance,
                atr_period,
                sl_atr_mult,
                tp_atr_mult,
                sl_distance,
                tp_distance,
            )
        else:
            logger.warning(
                "MT5 dynamic SL/TP enabled but ATR unavailable (period={} rows={}); falling back to configured pips.",
                atr_period,
                len(df),
            )

    if not dynamic_applied:
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

    position_state = {
        "side": side,
        "qty": volume,
        "entry_price": entry_price,
        "sl": sl,
        "tp": tp,
        "initial_r": abs(entry_price - sl),
        "updated_at": latest_close_time,
    }

    if staged_exit_enabled:
        position_state = _build_staged_position_state(
            side=side,
            entry_price=entry_price,
            sl=sl,
            qty=volume,
            pip_size=pip_size,
            staged_be_trigger_pips=staged_be_trigger_pips,
            staged_be_offset_pips=staged_be_offset_pips,
            staged_trail_pips=staged_trail_pips,
            staged_tp4_open=staged_tp4_open,
        )
        position_state["updated_at"] = latest_close_time
        tp = _safe_float(position_state.get("tp", tp), tp)

    response = connector.place_market_order(
        symbol=symbol,
        side=side,
        volume=volume,
        sl=sl,
        tp=tp,
        comment="spec-ema-channel",
    )
    state_store.set_position(symbol, position_state)
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
