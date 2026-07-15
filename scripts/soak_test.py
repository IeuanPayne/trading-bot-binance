#!/usr/bin/env python3
"""Run controlled paper-trading soak tests aligned to candle closes."""

from __future__ import annotations

import argparse
import math
import time
from datetime import datetime, timezone

from loguru import logger

from trading_bot.execution import run_paper_trade
from trading_bot.config import (
    EMA1_LEN,
    EMA2_LEN,
    EMA3_LEN,
    EMA4_LEN,
    EMA5_LEN,
    LONDON_END,
    LONDON_START,
    MAX_SPREAD_PIPS,
    MODELED_SPREAD_PIPS,
    NEWYORK_END,
    NEWYORK_START,
    SESSION,
    SESSION_TZ_OFFSET,
)


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Controlled testnet soak runner")
    parser.add_argument("--symbol", default="BTCUSDT")
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
    parser.add_argument("--modeled-spread-pips", type=float, default=MODELED_SPREAD_PIPS)
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
            modeled_spread_pips=args.modeled_spread_pips,
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
            modeled_spread_pips=args.modeled_spread_pips,
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
