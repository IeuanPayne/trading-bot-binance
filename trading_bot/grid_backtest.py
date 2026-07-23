"""Grid backtest runner — test multiple EMA and timeframe combinations."""
import csv
from datetime import datetime
from pathlib import Path

from loguru import logger

from .backtest import ema_channel_backtest
from .binance_connector import BinanceConnector
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
    NEWYORK_END,
    NEWYORK_START,
    SESSION,
    SESSION_TZ_OFFSET,
)


def run_grid_backtest(
    symbol: str = "BTCUSDT",
    ema_pairs: list | None = None,
    timeframes: list | None = None,
    limit: int = 1000,
    ema1_len: int = EMA1_LEN,
    ema2_len: int = EMA2_LEN,
    ema3_len: int = EMA3_LEN,
    ema4_len: int = EMA4_LEN,
    ema5_len: int = EMA5_LEN,
    session: str = SESSION,
    london_start: int = LONDON_START,
    london_end: int = LONDON_END,
    newyork_start: int = NEWYORK_START,
    newyork_end: int = NEWYORK_END,
    session_tz_offset: int = SESSION_TZ_OFFSET,
    modeled_spread_pips: float = MODELED_SPREAD_PIPS,
    max_spread_pips: float = MAX_SPREAD_PIPS,
    output_file: str | None = None,
):
    """Run backtest for multiple EMA and timeframe combinations.
    
    Args:
        symbol: Trading pair (e.g., 'BTCUSDT')
        ema_pairs: List of (ema1, ema3) tuples. Default: [(5,13), (9,21), (12,26), (20,50)]
        timeframes: List of candle intervals. Default: ['5m', '15m', '1h', '4h']
        limit: Number of candles per timeframe
        output_file: CSV file to write results. Default: 'backtest_grid_<timestamp>.csv'
    
    Returns:
        List of result dicts for each combination.
    """
    if ema_pairs is None:
        ema_pairs = [(5, 13), (9, 21), (12, 26), (20, 50)]
    if timeframes is None:
        timeframes = ["5m", "15m", "1h", "4h"]
    
    if output_file is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"backtest_grid_{timestamp}.csv"
    
    connector = BinanceConnector()
    results = []
    
    logger.info("Starting grid backtest for {} with {} EMA pairs and {} timeframes", symbol, len(ema_pairs), len(timeframes))
    
    for fast, slow in ema_pairs:
        for timeframe in timeframes:
            try:
                logger.info("Testing {} EMA{}/{} on {} candles", timeframe, fast, slow, limit)
                
                # Fetch data
                df = connector.fetch_klines(symbol, timeframe, limit)
                if df.empty:
                    logger.warning("No data for {} {}", symbol, timeframe)
                    continue
                
                # Run backtest
                backtest_result = ema_channel_backtest(
                    df,
                    ema_fast=fast,
                    ema_mid=ema2_len,
                    ema_slow=slow,
                    ema_slower=ema4_len,
                    ema_slowest=ema5_len,
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
                
                metrics = backtest_result.get("metrics", {})
                
                row = {
                    "symbol": symbol,
                    "ema_fast": fast,
                    "ema_slow": slow,
                    "timeframe": timeframe,
                    "num_trades": backtest_result.get("num_trades", 0),
                    "total_pnl": backtest_result.get("pnl", 0),
                    "final_equity": backtest_result.get("final_equity", INITIAL_CAPITAL),
                    "win_rate": metrics.get("win_rate", 0),
                    "avg_return": metrics.get("avg_return", 0),
                    "max_drawdown": metrics.get("max_drawdown", 0),
                }
                results.append(row)
                
                logger.info(
                    "✓ EMA{}/{} {}: trades={} pnl=${:.2f} win_rate={:.1f}% drawdown={:.1f}%",
                    fast, slow, timeframe,
                    row["num_trades"], row["total_pnl"], row["win_rate"] * 100, abs(row["max_drawdown"]) * 100
                )
            except Exception as exc:
                logger.error("✗ EMA{}/{} {} failed: {}", fast, slow, timeframe, exc)
                continue
    
    # Write to CSV
    if results:
        _write_results_csv(results, output_file)
        logger.info("Grid backtest complete. Results written to {}", output_file)
    else:
        logger.error("No results to write. Check data availability.")
    
    return results


def _write_results_csv(results: list, filepath: str) -> None:
    """Write grid backtest results to CSV."""
    output_path = Path(filepath)
    fieldnames = [
        "symbol", "ema_fast", "ema_slow", "timeframe",
        "num_trades", "total_pnl", "final_equity",
        "win_rate", "avg_return", "max_drawdown"
    ]
    
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    
    logger.info("Wrote {} rows to {}", len(results), output_path)


def print_grid_summary(results: list) -> None:
    """Print summary statistics from grid backtest results."""
    if not results:
        logger.warning("No results to summarize.")
        return
    
    # Filter out results with None values
    valid_results = [r for r in results if r["win_rate"] is not None and r["total_pnl"] is not None]
    if not valid_results:
        logger.warning("No valid results to summarize (all had None values).")
        return
    
    # Find best by win rate
    best_win_rate = max(valid_results, key=lambda x: x["win_rate"])
    best_pnl = max(valid_results, key=lambda x: x["total_pnl"])
    best_return = max(valid_results, key=lambda x: x["avg_return"])
    
    logger.info("=" * 60)
    logger.info("GRID BACKTEST SUMMARY ({} / {} combinations valid)", len(valid_results), len(results))
    logger.info("=" * 60)
    logger.info("Best Win Rate: EMA{}/{} {} → {:.1f}% ({} trades)", 
                best_win_rate["ema_fast"], best_win_rate["ema_slow"],
                best_win_rate["timeframe"], best_win_rate["win_rate"] * 100,
                best_win_rate["num_trades"])
    logger.info("Best PnL: EMA{}/{} {} → ${:.2f}",
                best_pnl["ema_fast"], best_pnl["ema_slow"],
                best_pnl["timeframe"], best_pnl["total_pnl"])
    logger.info("Best Avg Return: EMA{}/{} {} → {:.2f}%",
                best_return["ema_fast"], best_return["ema_slow"],
                best_return["timeframe"], best_return["avg_return"] * 100)
    logger.info("=" * 60)
