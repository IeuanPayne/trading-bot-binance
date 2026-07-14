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
    MT5_LOGIN,
    MT5_PASSWORD,
    MT5_SERVER,
    MT5_STATE_FILE,
    MT5_SYMBOL,
    MT5_TERMINAL_PATH,
    validate_runtime_args,
)
from trading_bot.mt5_connector import MT5Connector
from trading_bot.mt5_execution import run_mt5_trade


logger.add("trading_bot.log", rotation="10 MB", retention="7 days", level="DEBUG")


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
    connector = MT5Connector(
        login=int(MT5_LOGIN or "0"),
        password=MT5_PASSWORD or "",
        server=MT5_SERVER or "",
        terminal_path=MT5_TERMINAL_PATH,
    )
    try:
        connector.connect()
        run_mt5_trade(
            connector=connector,
            symbol=args.symbol,
            interval=args.interval,
            limit=args.limit,
            fast=args.fast,
            slow=args.slow,
            rsi_period=args.rsi_period,
            order_pct=args.order_pct,
            stop_pips=args.stop_pips,
            state_file=args.state_file,
        )
    finally:
        connector.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Controlled MT5 soak runner")
    parser.add_argument("--symbol", default=MT5_SYMBOL)
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--fast", type=int, default=9)
    parser.add_argument("--slow", type=int, default=21)
    parser.add_argument("--rsi-period", type=int, default=14)
    parser.add_argument("--order-pct", type=float, default=0.01)
    parser.add_argument("--stop-pips", type=float, default=0.7)
    parser.add_argument("--state-file", default=MT5_STATE_FILE)
    parser.add_argument("--duration-hours", type=float, default=24.0)
    parser.add_argument("--max-runs", type=int, default=0, help="0 means unlimited until duration expires")
    parser.add_argument("--buffer-seconds", type=int, default=5)
    parser.add_argument("--run-now", action="store_true", help="Run immediately before candle-aligned loop")
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
