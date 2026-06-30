import argparse
from loguru import logger
logger.add("trading_bot.log", rotation="10 MB", retention="7 days", level="DEBUG")
from .binance_connector import BinanceConnector
from .backtest import emarsi_backtest
from .execution import run_paper_trade
from .grid_backtest import run_grid_backtest, print_grid_summary
from .metrics_persistence import HTMLReportGenerator, TradeHistoryExporter
from .config import INITIAL_CAPITAL, MAX_PCT_PER_TRADE, validate_runtime_args


def run_backtest(symbol: str, interval: str = "15m", limit: int = 500, fast: int = 9, slow: int = 21, rsi_period: int = 14, export_report: bool = False):
    c = BinanceConnector()
    df = c.fetch_klines(symbol, interval, limit)
    if df.empty:
        logger.error("No data fetched for {}", symbol)
        return
    results = emarsi_backtest(
        df,
        ema_fast=fast,
        ema_slow=slow,
        rsi_period=rsi_period,
        initial_capital=INITIAL_CAPITAL,
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
    logger.info("Metrics: {}", results.get("metrics"))
    
    # Export report if requested
    if export_report:
        trades = results.get("trades", [])
        metrics = results.get("metrics", {})
        report_file = HTMLReportGenerator.generate_report(
            symbol=symbol,
            ema_fast=fast,
            ema_slow=slow,
            timeframe=interval,
            metrics=metrics,
            trades=trades,
        )
        logger.info("HTML report generated: {}", report_file)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--fast", type=int, default=9)
    parser.add_argument("--slow", type=int, default=21)
    parser.add_argument("--rsi-period", type=int, default=14)
    parser.add_argument("--mode", choices=["backtest", "paper", "grid-backtest"], default="backtest")
    parser.add_argument("--order-pct", type=float, default=MAX_PCT_PER_TRADE)
    parser.add_argument("--stop-pips", type=float, default=0.7)
    parser.add_argument("--disable-oco", action="store_true")
    parser.add_argument("--output", type=str, help="CSV output file for grid backtest results")
    parser.add_argument("--export-report", action="store_true", help="Generate HTML report for backtest")
    args = parser.parse_args()

    try:
        validate_runtime_args(args.mode, args.order_pct, args.stop_pips)
    except ValueError as exc:
        parser.error(str(exc))

    if args.mode == "paper":
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
        )
    elif args.mode == "grid-backtest":
        results = run_grid_backtest(
            symbol=args.symbol,
            limit=args.limit,
            rsi_period=args.rsi_period,
            output_file=args.output,
        )
        print_grid_summary(results)
    else:
        run_backtest(args.symbol, args.interval, args.limit, args.fast, args.slow, args.rsi_period, export_report=args.export_report)


if __name__ == "__main__":
    main()
