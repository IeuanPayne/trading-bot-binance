"""Metrics persistence and HTML report generation."""
import csv
import json
from pathlib import Path
from datetime import datetime
from loguru import logger
from typing import List, Dict, Any


class TradeHistoryExporter:
    """Export trade history to CSV and JSON formats."""
    
    @staticmethod
    def export_trades_csv(trades: List[Dict[str, Any]], filepath: str) -> None:
        """Export trades to CSV file.
        
        Args:
            trades: List of trade dicts with entry, exit, pnl, etc.
            filepath: Output CSV file path
        """
        if not trades:
            logger.warning("No trades to export to CSV")
            return
        
        output_path = Path(filepath)
        fieldnames = trades[0].keys() if trades else []
        
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(trades)
        
        logger.info("Exported {} trades to {}", len(trades), output_path)
    
    @staticmethod
    def export_trades_json(trades: List[Dict[str, Any]], filepath: str) -> None:
        """Export trades to JSON file.
        
        Args:
            trades: List of trade dicts
            filepath: Output JSON file path
        """
        if not trades:
            logger.warning("No trades to export to JSON")
            return
        
        output_path = Path(filepath)
        with open(output_path, "w") as f:
            json.dump(trades, f, indent=2, default=str)
        
        logger.info("Exported {} trades to {}", len(trades), output_path)


class MetricsSnapshot:
    """Store and export a snapshot of backtest metrics."""
    
    def __init__(self, symbol: str, timeframe: str, ema_fast: int, ema_slow: int):
        self.symbol = symbol
        self.timeframe = timeframe
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.timestamp = datetime.now().isoformat()
        self.metrics = {}
    
    def record_metrics(self, metrics: Dict[str, Any]) -> None:
        """Record backtest metrics."""
        self.metrics = metrics.copy()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            **self.metrics,
        }
    
    def to_csv_row(self) -> Dict[str, Any]:
        """Convert to CSV row."""
        return self.to_dict()


class HTMLReportGenerator:
    """Generate HTML report from backtest metrics and trades."""
    
    @staticmethod
    def generate_report(
        symbol: str,
        ema_fast: int,
        ema_slow: int,
        timeframe: str,
        metrics: Dict[str, Any],
        trades: List[Dict[str, Any]] = None,
        output_file: str = None,
    ) -> str:
        """Generate HTML report.
        
        Args:
            symbol: Trading pair
            ema_fast: Fast EMA period
            ema_slow: Slow EMA period
            timeframe: Candle interval
            metrics: Backtest metrics dict
            trades: List of trades
            output_file: Output HTML file path. Default: report_<timestamp>.html
        
        Returns:
            Path to generated HTML file
        """
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"report_{symbol}_{ema_fast}_{ema_slow}_{timestamp}.html"
        
        trades = trades or []
        
        # Build HTML
        html = _build_html_report(symbol, ema_fast, ema_slow, timeframe, metrics, trades)
        
        output_path = Path(output_file)
        with open(output_path, "w") as f:
            f.write(html)
        
        logger.info("Generated HTML report: {}", output_path)
        return str(output_path)


def _build_html_report(
    symbol: str,
    ema_fast: int,
    ema_slow: int,
    timeframe: str,
    metrics: Dict[str, Any],
    trades: List[Dict[str, Any]],
) -> str:
    """Build HTML report content."""
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    metrics_rows = ""
    for key, value in metrics.items():
        if isinstance(value, float):
            formatted = f"{value:.4f}" if abs(value) < 1 else f"{value:.2f}"
        else:
            formatted = str(value)
        metrics_rows += f"<tr><td>{key}</td><td>{formatted}</td></tr>\n"
    
    trades_rows = ""
    if trades:
        for trade in trades:
            pnl = trade.get("pnl", 0)
            pnl_pct = trade.get("pnl_pct", 0)
            color = "green" if pnl >= 0 else "red"
            trades_rows += f"""<tr>
<td>{trade.get('entry_time', 'N/A')}</td>
<td>{trade.get('exit_time', 'N/A')}</td>
<td>{trade.get('entry_price', 0):.2f}</td>
<td>{trade.get('exit_price', 0):.2f}</td>
<td><span style="color: {color};">${pnl:.4f} ({pnl_pct:.2f}%)</span></td>
</tr>\n"""
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Backtest Report - {symbol} {ema_fast}/{ema_slow} {timeframe}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
            color: #333;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
        }}
        .header {{
            background-color: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }}
        .header-info {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }}
        .header-item {{
            display: flex;
            justify-content: space-between;
        }}
        .metrics-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }}
        .metrics-table th {{
            background-color: #34495e;
            color: white;
            padding: 10px;
            text-align: left;
        }}
        .metrics-table td {{
            border: 1px solid #bdc3c7;
            padding: 8px;
        }}
        .metrics-table tr:nth-child(even) {{
            background-color: #f9f9f9;
        }}
        .metrics-table tr:hover {{
            background-color: #ecf0f1;
        }}
        .trades-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }}
        .trades-table th {{
            background-color: #27ae60;
            color: white;
            padding: 10px;
            text-align: left;
        }}
        .trades-table td {{
            border: 1px solid #bdc3c7;
            padding: 8px;
        }}
        .trades-table tr:nth-child(even) {{
            background-color: #f9f9f9;
        }}
        .trades-table tr:hover {{
            background-color: #ecf0f1;
        }}
        .footer {{
            margin-top: 30px;
            padding-top: 10px;
            border-top: 1px solid #bdc3c7;
            color: #7f8c8d;
            font-size: 12px;
        }}
        .stat-box {{
            display: inline-block;
            margin: 10px 10px 0 0;
            padding: 10px 15px;
            background-color: #ecf0f1;
            border-radius: 5px;
            border-left: 4px solid #3498db;
        }}
        .stat-value {{
            font-weight: bold;
            font-size: 18px;
            color: #2c3e50;
        }}
        .stat-label {{
            color: #7f8c8d;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Backtest Report: {symbol}</h1>
        
        <div class="header">
            <div class="header-info">
                <div class="header-item">
                    <strong>Strategy:</strong> EMA{ema_fast}/{ema_slow} + RSI14
                </div>
                <div class="header-item">
                    <strong>Timeframe:</strong> {timeframe}
                </div>
                <div class="header-item">
                    <strong>Generated:</strong> {timestamp}
                </div>
            </div>
        </div>
        
        <h2>Key Metrics</h2>
        <div>
            <div class="stat-box">
                <div class="stat-label">Total Trades</div>
                <div class="stat-value">{metrics.get('num_trades', 0)}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Win Rate</div>
                <div class="stat-value">{metrics.get('win_rate', 0) * 100:.1f}%</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Total PnL</div>
                <div class="stat-value" style="color: {'green' if metrics.get('total_pnl', 0) >= 0 else 'red'};">
                    ${metrics.get('total_pnl', 0):.4f}
                </div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Avg Return</div>
                <div class="stat-value">{metrics.get('avg_return', 0) * 100:.2f}%</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Max Drawdown</div>
                <div class="stat-value">{metrics.get('max_drawdown', 0) * 100:.2f}%</div>
            </div>
        </div>
        
        <h2>Detailed Metrics</h2>
        <table class="metrics-table">
            <thead>
                <tr>
                    <th>Metric</th>
                    <th>Value</th>
                </tr>
            </thead>
            <tbody>
                {metrics_rows}
            </tbody>
        </table>
        
        <h2>Trade Details</h2>
        {'<p style="color: #7f8c8d;">No trades executed.</p>' if not trades else f'''<table class="trades-table">
            <thead>
                <tr>
                    <th>Entry Time</th>
                    <th>Exit Time</th>
                    <th>Entry Price</th>
                    <th>Exit Price</th>
                    <th>PnL</th>
                </tr>
            </thead>
            <tbody>
                {trades_rows}
            </tbody>
        </table>'''}
        
        <div class="footer">
            <p>Generated by trading-bot-binance v1.0</p>
        </div>
    </div>
</body>
</html>
"""
    
    return html
