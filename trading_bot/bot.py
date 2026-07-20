import argparse
from loguru import logger

from .binance_connector import BinanceConnector
from .backtest import ema_channel_backtest
from .execution import run_paper_trade
from .mt5_execution import run_mt5_trade
from .mt5_connector import MT5Connector
from .tradingview_webhook import WebhookTradeSettings, start_tradingview_webhook_server
from .grid_backtest import run_grid_backtest, print_grid_summary
from .metrics_persistence import HTMLReportGenerator
from .config import (
    EMA1_LEN,
    EMA2_LEN,
    EMA3_LEN,
    EMA4_LEN,
    EMA5_LEN,
    INITIAL_CAPITAL,
    LONDON_END,
    LONDON_START,
    MAX_PCT_PER_TRADE,
    MAX_SPREAD_PIPS,
    MODELED_SPREAD_PIPS,
    MT5_AUTO_MAGIC,
    MT5_BASE_MAGIC,
    MT5_DYNAMIC_SLTP,
    MT5_LOGIN,
    MT5_PASSWORD,
    MT5_ATR_PERIOD,
    MT5_RISK_PCT,
    MT5_SIGNAL_DEBUG,
    MT5_SERVER,
    MT5_SL_ATR_MULT,
    MT5_SLIPPAGE,
    MT5_SL_PIPS,
    MT5_STAGED_BE_OFFSET_PIPS,
    MT5_STAGED_BE_TRIGGER_PIPS,
    MT5_STAGED_EXIT_ENABLED,
    MT5_STATE_FILE,
    MT5_STAGED_TP4_OPEN,
    MT5_STAGED_TRAIL_PIPS,
    MT5_SYMBOL,
    MT5_TERMINAL_PATH,
    MT5_TRAILING_STOP_ENABLED,
    MT5_TRAIL_ACTIVATE_R,
    MT5_TRAIL_ATR_MULT,
    MT5_TRAIL_MIN_STEP_ATR,
    MT5_TRAIL_ATR_PERIOD,
    MT5_TP_ATR_MULT,
    MT5_TP_PIPS,
    MT5_USE_RISK_PCT,
    NEWYORK_END,
    NEWYORK_START,
    PIP_SIZE,
    SESSION,
    SESSION_TZ_OFFSET,
    TV_ALLOWED_SYMBOLS,
    TV_ALLOWED_SOURCE_IPS,
    TV_ALLOWED_TIMEFRAMES,
    TV_WEBHOOK_HOST,
    TV_WEBHOOK_PATH,
    TV_WEBHOOK_PORT,
    TV_WEBHOOK_SECRET,
    validate_runtime_args,
)

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


def run_backtest(
    symbol: str,
    interval: str = "15m",
    limit: int = 500,
    fast: int = EMA1_LEN,
    slow: int = EMA3_LEN,
    ema2: int = EMA2_LEN,
    ema4: int = EMA4_LEN,
    ema5: int = EMA5_LEN,
    session: str = SESSION,
    london_start: int = LONDON_START,
    london_end: int = LONDON_END,
    newyork_start: int = NEWYORK_START,
    newyork_end: int = NEWYORK_END,
    session_tz_offset: int = SESSION_TZ_OFFSET,
    modeled_spread_pips: float = MODELED_SPREAD_PIPS,
    max_spread_pips: float = MAX_SPREAD_PIPS,
    export_report: bool = False,
):
    c = BinanceConnector()
    df = c.fetch_klines(symbol, interval, limit)
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

    if export_report:
        trades = results.get("trades", [])
        metrics = results.get("metrics", {})
        report_file = HTMLReportGenerator.generate_report(
            symbol=symbol,
            ema_fast=fast,
            ema_mid=ema2,
            ema_slow=slow,
            ema_slower=ema4,
            ema_slowest=ema5,
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
    parser.add_argument("--ema1-len", "--fast", dest="ema1_len", type=int, default=EMA1_LEN)
    parser.add_argument("--ema2-len", dest="ema2_len", type=int, default=EMA2_LEN)
    parser.add_argument("--ema3-len", "--slow", dest="ema3_len", type=int, default=EMA3_LEN)
    parser.add_argument("--ema4-len", dest="ema4_len", type=int, default=EMA4_LEN)
    parser.add_argument("--ema5-len", dest="ema5_len", type=int, default=EMA5_LEN)
    parser.add_argument("--mode", choices=["backtest", "paper", "grid-backtest", "mt5", "tv-webhook"], default="backtest")
    parser.add_argument("--session", choices=["London", "NewYork", "Both", "Off"], default=SESSION)
    parser.add_argument("--london-start", type=int, default=LONDON_START)
    parser.add_argument("--london-end", type=int, default=LONDON_END)
    parser.add_argument("--newyork-start", type=int, default=NEWYORK_START)
    parser.add_argument("--newyork-end", type=int, default=NEWYORK_END)
    parser.add_argument("--session-tz-offset", type=int, default=SESSION_TZ_OFFSET)
    parser.add_argument("--max-spread-pips", type=float, default=MAX_SPREAD_PIPS)
    parser.add_argument("--modeled-spread-pips", type=float, default=MODELED_SPREAD_PIPS)
    parser.add_argument("--pip-size", type=float, default=PIP_SIZE)
    parser.add_argument("--order-pct", type=float, default=MAX_PCT_PER_TRADE)
    parser.add_argument("--use-risk-pct", action=argparse.BooleanOptionalAction, default=MT5_USE_RISK_PCT)
    parser.add_argument("--risk-pct", type=float, default=MT5_RISK_PCT)
    parser.add_argument("--sl-pips", type=float, default=MT5_SL_PIPS)
    parser.add_argument("--tp-pips", type=float, default=MT5_TP_PIPS)
    parser.add_argument("--dynamic-sltp", action=argparse.BooleanOptionalAction, default=MT5_DYNAMIC_SLTP)
    parser.add_argument("--atr-period", type=int, default=MT5_ATR_PERIOD)
    parser.add_argument("--sl-atr-mult", type=float, default=MT5_SL_ATR_MULT)
    parser.add_argument("--tp-atr-mult", type=float, default=MT5_TP_ATR_MULT)
    parser.add_argument("--trailing-stop", action=argparse.BooleanOptionalAction, default=MT5_TRAILING_STOP_ENABLED)
    parser.add_argument("--trail-activate-r", type=float, default=MT5_TRAIL_ACTIVATE_R)
    parser.add_argument("--trail-atr-period", type=int, default=MT5_TRAIL_ATR_PERIOD)
    parser.add_argument("--trail-atr-mult", type=float, default=MT5_TRAIL_ATR_MULT)
    parser.add_argument("--trail-min-step-atr", type=float, default=MT5_TRAIL_MIN_STEP_ATR)
    parser.add_argument("--staged-exit", action=argparse.BooleanOptionalAction, default=MT5_STAGED_EXIT_ENABLED)
    parser.add_argument("--staged-be-trigger-pips", type=float, default=MT5_STAGED_BE_TRIGGER_PIPS)
    parser.add_argument("--staged-be-offset-pips", type=float, default=MT5_STAGED_BE_OFFSET_PIPS)
    parser.add_argument("--staged-trail-pips", type=float, default=MT5_STAGED_TRAIL_PIPS)
    parser.add_argument("--staged-tp4-open", action=argparse.BooleanOptionalAction, default=MT5_STAGED_TP4_OPEN)
    parser.add_argument("--slippage", type=int, default=MT5_SLIPPAGE)
    parser.add_argument("--auto-magic", action=argparse.BooleanOptionalAction, default=MT5_AUTO_MAGIC)
    parser.add_argument("--base-magic", type=int, default=MT5_BASE_MAGIC)
    parser.add_argument("--signal-debug", action=argparse.BooleanOptionalAction, default=MT5_SIGNAL_DEBUG)
    parser.add_argument("--stop-pips", type=float, default=0.7)
    parser.add_argument("--disable-oco", action="store_true")
    parser.add_argument("--state-file", default=MT5_STATE_FILE)
    parser.add_argument("--tv-host", default=TV_WEBHOOK_HOST)
    parser.add_argument("--tv-port", type=int, default=TV_WEBHOOK_PORT)
    parser.add_argument("--tv-path", default=TV_WEBHOOK_PATH)
    parser.add_argument("--tv-secret", default=TV_WEBHOOK_SECRET)
    parser.add_argument("--tv-allowed-source-ips", default=",".join(TV_ALLOWED_SOURCE_IPS))
    parser.add_argument("--tv-staged-exit", action=argparse.BooleanOptionalAction, default=MT5_STAGED_EXIT_ENABLED)
    parser.add_argument("--tv-staged-be-trigger-pips", type=float, default=MT5_STAGED_BE_TRIGGER_PIPS)
    parser.add_argument("--tv-staged-be-offset-pips", type=float, default=MT5_STAGED_BE_OFFSET_PIPS)
    parser.add_argument("--tv-staged-trail-pips", type=float, default=MT5_STAGED_TRAIL_PIPS)
    parser.add_argument("--tv-staged-tp4-open", action=argparse.BooleanOptionalAction, default=MT5_STAGED_TP4_OPEN)
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
            fast=args.ema1_len,
            slow=args.ema3_len,
            ema2=args.ema2_len,
            ema4=args.ema4_len,
            ema5=args.ema5_len,
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
    elif args.mode == "mt5":
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
                symbol=MT5_SYMBOL or args.symbol,
                interval=args.interval,
                limit=args.limit,
                fast=args.ema1_len,
                slow=args.ema3_len,
                ema2=args.ema2_len,
                ema4=args.ema4_len,
                ema5=args.ema5_len,
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
                dynamic_sltp=args.dynamic_sltp,
                atr_period=args.atr_period,
                sl_atr_mult=args.sl_atr_mult,
                tp_atr_mult=args.tp_atr_mult,
                trailing_stop=args.trailing_stop,
                trail_activate_r=args.trail_activate_r,
                trail_atr_period=args.trail_atr_period,
                trail_atr_mult=args.trail_atr_mult,
                trail_min_step_atr=args.trail_min_step_atr,
                staged_exit_enabled=args.staged_exit,
                staged_be_trigger_pips=args.staged_be_trigger_pips,
                staged_be_offset_pips=args.staged_be_offset_pips,
                staged_trail_pips=args.staged_trail_pips,
                staged_tp4_open=args.staged_tp4_open,
                stop_pips=args.stop_pips,
                magic=magic,
                signal_debug=args.signal_debug,
                state_file=args.state_file,
            )
        finally:
            connector.shutdown()
    elif args.mode == "tv-webhook":
        if not args.tv_secret:
            parser.error("tv-webhook mode requires TV_WEBHOOK_SECRET (or --tv-secret)")

        magic = _effective_magic(args.interval, args.base_magic, args.auto_magic)

        def _connector_factory() -> MT5Connector:
            return MT5Connector(
                login=int(MT5_LOGIN or "0"),
                password=MT5_PASSWORD or "",
                server=MT5_SERVER or "",
                terminal_path=MT5_TERMINAL_PATH,
                deviation=args.slippage,
                magic=magic,
            )

        settings = WebhookTradeSettings(
            state_file=args.state_file,
            max_spread_pips=args.max_spread_pips,
            pip_size=args.pip_size,
            order_pct=args.order_pct,
            use_risk_pct=args.use_risk_pct,
            risk_pct=args.risk_pct,
            sl_pips=args.sl_pips,
            tp_pips=args.tp_pips,
            stop_pips=args.stop_pips,
            magic=magic,
            staged_exit_enabled=args.tv_staged_exit,
            staged_be_trigger_pips=args.tv_staged_be_trigger_pips,
            staged_be_offset_pips=args.tv_staged_be_offset_pips,
            staged_trail_pips=args.tv_staged_trail_pips,
            staged_tp4_open=args.tv_staged_tp4_open,
        )
        start_tradingview_webhook_server(
            host=args.tv_host,
            port=args.tv_port,
            path=args.tv_path,
            secret=args.tv_secret,
            connector_factory=_connector_factory,
            settings=settings,
            allowed_symbols=TV_ALLOWED_SYMBOLS,
            allowed_timeframes=TV_ALLOWED_TIMEFRAMES,
            allowed_source_ips=[item.strip() for item in str(args.tv_allowed_source_ips).split(",") if item.strip()],
        )
    elif args.mode == "grid-backtest":
        results = run_grid_backtest(
            symbol=args.symbol,
            limit=args.limit,
            ema1_len=args.ema1_len,
            ema2_len=args.ema2_len,
            ema3_len=args.ema3_len,
            ema4_len=args.ema4_len,
            ema5_len=args.ema5_len,
            session=args.session,
            london_start=args.london_start,
            london_end=args.london_end,
            newyork_start=args.newyork_start,
            newyork_end=args.newyork_end,
            session_tz_offset=args.session_tz_offset,
            modeled_spread_pips=args.modeled_spread_pips,
            max_spread_pips=args.max_spread_pips,
            output_file=args.output,
        )
        print_grid_summary(results)
    else:
        run_backtest(
            symbol=args.symbol,
            interval=args.interval,
            limit=args.limit,
            fast=args.ema1_len,
            slow=args.ema3_len,
            ema2=args.ema2_len,
            ema4=args.ema4_len,
            ema5=args.ema5_len,
            session=args.session,
            london_start=args.london_start,
            london_end=args.london_end,
            newyork_start=args.newyork_start,
            newyork_end=args.newyork_end,
            session_tz_offset=args.session_tz_offset,
            modeled_spread_pips=args.modeled_spread_pips,
            max_spread_pips=args.max_spread_pips,
            export_report=args.export_report,
        )


if __name__ == "__main__":
    main()
