#!/usr/bin/env python3
"""Run controlled MT5 strategy cycles aligned to candle closes."""

from __future__ import annotations

import argparse
import math
import time
from datetime import datetime, timezone

from loguru import logger

from trading_bot.alerts import send_alert
from trading_bot.config import (
    EMA1_LEN,
    EMA2_LEN,
    EMA3_LEN,
    EMA4_LEN,
    EMA5_LEN,
    LONDON_END,
    LONDON_START,
    MAX_SPREAD_PIPS,
    MT5_AUTO_MAGIC,
    MT5_BASE_MAGIC,
    MT5_LOGIN,
    MT5_PASSWORD,
    MT5_RISK_PCT,
    MT5_SIGNAL_DEBUG,
    MT5_SERVER,
    MT5_SLIPPAGE,
    MT5_SL_PIPS,
    MT5_STATE_FILE,
    MT5_SYMBOL,
    MT5_TERMINAL_PATH,
    MT5_TP_PIPS,
    MT5_USE_RISK_PCT,
    NEWYORK_END,
    NEWYORK_START,
    PIP_SIZE,
    SESSION,
    SESSION_TZ_OFFSET,
    validate_runtime_args,
)
from trading_bot.mt5_connector import MT5Connector
from trading_bot.mt5_execution import run_mt5_trade
from trading_bot.state_store import TradingStateStore


logger.add("trading_bot.log", rotation="10 MB", retention="7 days", level="DEBUG")

_INTERVAL_TO_PERIOD = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


def _effective_magic(interval: str, base_magic: int, auto_magic: bool) -> int:
    if not auto_magic:
        return base_magic
    return base_magic + _INTERVAL_TO_PERIOD.get(interval, 0)


def _interval_to_seconds(interval: str) -> int:
    unit = interval[-1].lower()
    value = int(interval[:-1])
    if unit == "m":
        return value * 60
    if unit == "h":
        return value * 3600
    if unit == "d":
        return value * 86400
    raise ValueError(f"Unsupported interval: {interval}")


def _next_run_delay(interval_seconds: int, buffer_seconds: int) -> float:
    now = time.time()
    next_boundary = (math.floor(now / interval_seconds) + 1) * interval_seconds
    return max(0.0, next_boundary + buffer_seconds - now)


def _run_cycle(args) -> None:
    magic = _effective_magic(args.interval, args.base_magic, args.auto_magic)
    connector = MT5Connector(
        login=int(MT5_LOGIN or "0"),
        password=MT5_PASSWORD or "",
        server=MT5_SERVER or "",
        terminal_path=MT5_TERMINAL_PATH,
        deviation=args.slippage,
        magic=magic,
    )
    try:
        connector.connect()
        run_mt5_trade(
            connector=connector,
            symbol=args.symbol,
            interval=args.interval,
            limit=args.limit,
            fast=args.fast,
            ema2=args.ema2,
            slow=args.slow,
            ema4=args.ema4,
            ema5=args.ema5,
            session=args.session,
            london_start=args.london_start,
            london_end=args.london_end,
            newyork_start=args.newyork_start,
            newyork_end=args.newyork_end,
            session_tz_offset=args.session_tz_offset,
            max_spread_pips=args.max_spread_pips,
            pip_size=args.pip_size,
            order_pct=args.order_pct,
            use_risk_pct=args.use_risk_pct,
            risk_pct=args.risk_pct,
            sl_pips=args.sl_pips,
            tp_pips=args.tp_pips,
            stop_pips=args.stop_pips,
            magic=magic,
            signal_debug=args.signal_debug,
            state_file=args.state_file,
        )
    finally:
        connector.shutdown()


def _reset_risk_state(state_file: str) -> None:
    store = TradingStateStore(state_file)
    store.set_runtime_state(
        "mt5_risk_state",
        {
            "day": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "realized_pnl_today": 0.0,
            "trades_today": 0,
            "consecutive_losses": 0,
            "breaker_tripped": False,
            "breaker_reason": "",
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Controlled MT5 soak runner")
    parser.add_argument("--symbol", default=MT5_SYMBOL)
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--ema1-len", "--fast", dest="fast", type=int, default=EMA1_LEN)
    parser.add_argument("--ema2-len", dest="ema2", type=int, default=EMA2_LEN)
    parser.add_argument("--ema3-len", "--slow", dest="slow", type=int, default=EMA3_LEN)
    parser.add_argument("--ema4-len", dest="ema4", type=int, default=EMA4_LEN)
    parser.add_argument("--ema5-len", dest="ema5", type=int, default=EMA5_LEN)
    parser.add_argument("--session", choices=["London", "NewYork", "Both", "Off"], default=SESSION)
    parser.add_argument("--london-start", type=int, default=LONDON_START)
    parser.add_argument("--london-end", type=int, default=LONDON_END)
    parser.add_argument("--newyork-start", type=int, default=NEWYORK_START)
    parser.add_argument("--newyork-end", type=int, default=NEWYORK_END)
    parser.add_argument("--session-tz-offset", type=int, default=SESSION_TZ_OFFSET)
    parser.add_argument("--max-spread-pips", type=float, default=MAX_SPREAD_PIPS)
    parser.add_argument("--pip-size", type=float, default=PIP_SIZE)
    parser.add_argument("--order-pct", type=float, default=0.01)
    parser.add_argument("--use-risk-pct", action=argparse.BooleanOptionalAction, default=MT5_USE_RISK_PCT)
    parser.add_argument("--risk-pct", type=float, default=MT5_RISK_PCT)
    parser.add_argument("--sl-pips", type=float, default=MT5_SL_PIPS)
    parser.add_argument("--tp-pips", type=float, default=MT5_TP_PIPS)
    parser.add_argument("--slippage", type=int, default=MT5_SLIPPAGE)
    parser.add_argument("--auto-magic", action=argparse.BooleanOptionalAction, default=MT5_AUTO_MAGIC)
    parser.add_argument("--base-magic", type=int, default=MT5_BASE_MAGIC)
    parser.add_argument("--signal-debug", action=argparse.BooleanOptionalAction, default=MT5_SIGNAL_DEBUG)
    parser.add_argument("--stop-pips", type=float, default=0.7)
    parser.add_argument("--state-file", default=MT5_STATE_FILE)
    parser.add_argument("--duration-hours", type=float, default=24.0)
    parser.add_argument("--max-runs", type=int, default=0, help="0 means unlimited until duration expires")
    parser.add_argument("--buffer-seconds", type=int, default=5)
    parser.add_argument("--run-now", action="store_true", help="Run immediately before candle-aligned loop")
    parser.add_argument(
        "--reset-risk-state",
        action="store_true",
        help="Reset persisted MT5 risk breaker counters before running.",
    )
    args = parser.parse_args()

    validate_runtime_args("mt5", args.order_pct, args.stop_pips)

    interval_seconds = _interval_to_seconds(args.interval)
    start_ts = time.time()
    deadline = float("inf") if args.duration_hours <= 0 else start_ts + (args.duration_hours * 3600)
    run_count = 0

    logger.info(
        "Starting MT5 soak: symbol={} interval={} duration_hours={} state_file={}",
        args.symbol,
        args.interval,
        args.duration_hours,
        args.state_file,
    )

    if args.reset_risk_state:
        _reset_risk_state(args.state_file)
        logger.warning("Reset MT5 risk state in {}", args.state_file)

    if args.run_now:
        logger.info("Running immediate pre-loop MT5 cycle")
        try:
            _run_cycle(args)
            run_count += 1
        except Exception as exc:
            logger.error("MT5 immediate cycle failed: {}", exc)
            send_alert(f"MT5 immediate cycle failed: {exc}", level="ERROR")

    while time.time() < deadline:
        if args.max_runs > 0 and run_count >= args.max_runs:
            logger.info("Reached max-runs={}; stopping MT5 soak", args.max_runs)
            break

        delay = _next_run_delay(interval_seconds, args.buffer_seconds)
        next_run = datetime.now(timezone.utc).timestamp() + delay
        logger.info(
            "Sleeping {:.1f}s until next MT5 candle-close run (UTC epoch {:.0f})",
            delay,
            next_run,
        )
        time.sleep(delay)

        logger.info("Executing MT5 soak cycle #{}", run_count + 1)
        try:
            _run_cycle(args)
            run_count += 1
        except Exception as exc:
            logger.error("MT5 soak cycle failed: {}", exc)
            send_alert(f"MT5 soak cycle failed: {exc}", level="ERROR")

    elapsed = (time.time() - start_ts) / 3600
    logger.info("MT5 soak finished: runs={} elapsed_hours={:.2f}", run_count, elapsed)


if __name__ == "__main__":
    main()
