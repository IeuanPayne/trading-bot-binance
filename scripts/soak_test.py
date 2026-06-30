#!/usr/bin/env python3
"""Run controlled paper-trading soak tests aligned to candle closes."""

from __future__ import annotations

import argparse
import math
import time
from datetime import datetime, timezone

from loguru import logger

from trading_bot.execution import run_paper_trade


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Controlled testnet soak runner")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--fast", type=int, default=9)
    parser.add_argument("--slow", type=int, default=21)
    parser.add_argument("--rsi-period", type=int, default=14)
    parser.add_argument("--order-pct", type=float, default=0.01)
    parser.add_argument("--stop-pips", type=float, default=0.7)
    parser.add_argument("--disable-oco", action="store_true")
    parser.add_argument("--state-file", default="trading_state.db")
    parser.add_argument("--duration-hours", type=float, default=24.0)
    parser.add_argument("--max-runs", type=int, default=0, help="0 means unlimited until duration expires")
    parser.add_argument("--buffer-seconds", type=int, default=5)
    parser.add_argument("--run-now", action="store_true", help="Run immediately before candle-aligned loop")
    args = parser.parse_args()

    interval_seconds = _interval_to_seconds(args.interval)
    start_ts = time.time()
    deadline = start_ts + (args.duration_hours * 3600)
    run_count = 0

    logger.info(
        "Starting soak test: symbol={} interval={} duration_hours={} state_file={}",
        args.symbol,
        args.interval,
        args.duration_hours,
        args.state_file,
    )

    if args.run_now:
        logger.info("Running immediate pre-loop cycle")
        run_paper_trade(
            symbol=args.symbol,
            interval=args.interval,
            limit=args.limit,
            fast=args.fast,
            slow=args.slow,
            rsi_period=args.rsi_period,
            order_pct=args.order_pct,
            stop_pips=args.stop_pips,
            disable_oco=args.disable_oco,
            state_file=args.state_file,
        )
        run_count += 1

    while time.time() < deadline:
        if args.max_runs > 0 and run_count >= args.max_runs:
            logger.info("Reached max-runs={}; stopping soak test", args.max_runs)
            break

        delay = _next_run_delay(interval_seconds, args.buffer_seconds)
        next_run = datetime.now(timezone.utc).timestamp() + delay
        logger.info(
            "Sleeping {:.1f}s until next candle-close run (UTC epoch {:.0f})",
            delay,
            next_run,
        )
        time.sleep(delay)

        logger.info("Executing soak cycle #{}", run_count + 1)
        run_paper_trade(
            symbol=args.symbol,
            interval=args.interval,
            limit=args.limit,
            fast=args.fast,
            slow=args.slow,
            rsi_period=args.rsi_period,
            order_pct=args.order_pct,
            stop_pips=args.stop_pips,
            disable_oco=args.disable_oco,
            state_file=args.state_file,
        )
        run_count += 1

    elapsed = (time.time() - start_ts) / 3600
    logger.info("Soak test finished: runs={} elapsed_hours={:.2f}", run_count, elapsed)


if __name__ == "__main__":
    main()
