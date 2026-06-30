# trading-bot-binance

A Python-based automated trading bot for Binance with backtesting and paper trading capabilities. Implements an **EMA9/EMA21 Trend + RSI14 Filter** strategy with position sizing, risk management, and OCO (One-Cancels-Other) orders.

## Features

- **Backtesting Engine**: Test strategies on historical OHLC data with configurable parameters.
- **Paper Trading**: Run live orders on Binance testnet without risking real capital.
- **EMA + RSI Strategy**: 9/21 EMA crossover with RSI14 filter for trend confirmation.
- **Risk Management**: Position sizing based on account equity and risk per trade.
- **OCO Orders**: Automatic stop-loss and take-profit orders for safe exits.
- **Testnet Support**: Full integration with Binance testnet for safe development and testing.
- **Metrics & Analytics**: Win rate, average return, max drawdown, and trade-by-trade analysis.
- **Logging**: Structured logging with file rotation and debug output.
- **CLI Interface**: Simple command-line interface for backtest and paper trading modes.

## Quick Start

### 1. Clone and Setup

```bash
cd trading-bot-binance
make setup
make install
```

### 2. Configure Environment

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Then edit `.env` with your Binance testnet credentials (get them from [Binance Testnet](https://testnet.binance.vision/)):

```ini
BINANCE_API_KEY=your_testnet_api_key
BINANCE_API_SECRET=your_testnet_api_secret
BINANCE_TESTNET=True
ALLOW_LIVE_TRADING=False
INITIAL_CAPITAL=10000
MAX_PCT_PER_TRADE=2
MAX_DAILY_LOSS_USDT=0
MAX_DRAWDOWN_PCT=0
MAX_CONSECUTIVE_LOSSES=0
MAX_TRADES_PER_DAY=0
```

### 3. Verify Keys (Optional)

```bash
PYTHONPATH=$(pwd) .venv/bin/python3 scripts/check_keys.py
```

Output should show your testnet USDT and BTC balances:

```
BINANCE_TESTNET= True
USDT balance: {'asset': 'USDT', 'free': '10000.00000000', 'locked': '0.00000000'}
BTC balance: {'asset': 'BTC', 'free': '1.00000000', 'locked': '0.00000000'}
```

### 4. Run Backtest

```bash
make backtest
# or with custom parameters:
PYTHONPATH=$(pwd) .venv/bin/python3 -m trading_bot.bot --mode backtest \
  --symbol BTCUSDT --interval 15m --limit 500 \
  --fast 9 --slow 21 --rsi-period 14
```

Expected output includes PnL, final equity, number of trades, and metrics.

### 5. Run Paper Trading

```bash
make paper
# or:
PYTHONPATH=$(pwd) .venv/bin/python3 -m trading_bot.bot --mode paper \
  --symbol BTCUSDT --interval 15m --limit 500 \
  --order-pct 2 --stop-pips 0.7
```

## Project Structure

```
trading-bot-binance/
├── README.md                          # This file
├── Makefile                           # Development tasks
├── requirements.txt                   # Python dependencies
├── tsconfig.json                      # TypeScript config (if applicable)
├── .env.example                       # Example environment configuration
├── scripts/
│   └── check_keys.py                  # Validate Binance API keys and balances
├── trading_bot/
│   ├── __init__.py
│   ├── bot.py                         # CLI entry point
│   ├── config.py                      # Configuration (loads .env)
│   ├── binance_connector.py           # Binance API client wrapper
│   ├── backtest.py                    # Backtesting engine
│   ├── execution.py                   # Paper trading logic
│   ├── risk.py                        # Position sizing & risk management
│   └── metrics.py                     # Trade metrics & performance analysis
└── tests/
    ├── test_backtest.py
    ├── test_execution.py
    ├── test_binance_connector.py
    ├── test_risk.py
    ├── test_metrics.py
    └── test_cli.py
```

## Configuration

### Environment Variables (`.env`)

| Variable | Example | Description |
|----------|---------|-------------|
| `BINANCE_API_KEY` | `xxxxx` | Binance testnet API key |
| `BINANCE_API_SECRET` | `xxxxx` | Binance testnet API secret |
| `BINANCE_TESTNET` | `True` | Set to `True` for testnet, `False` for live (not recommended) |
| `ALLOW_LIVE_TRADING` | `False` | Must be `True` to allow live orders when `BINANCE_TESTNET=False` |
| `INITIAL_CAPITAL` | `10000` | Starting capital in USDT |
| `MAX_PCT_PER_TRADE` | `2` | Max percentage of capital per trade (%) |
| `MAX_DAILY_LOSS_USDT` | `0` | Max realized daily loss before blocking new entries (0 disables) |
| `MAX_DRAWDOWN_PCT` | `0` | Max drawdown percentage before blocking new entries (0 disables) |
| `MAX_CONSECUTIVE_LOSSES` | `0` | Max consecutive losing exits before blocking new entries (0 disables) |
| `MAX_TRADES_PER_DAY` | `0` | Max entries per UTC day before blocking new entries (0 disables) |

### CLI Arguments

#### Backtest Mode

```bash
python -m trading_bot.bot --mode backtest [options]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--symbol` | `BTCUSDT` | Trading pair (e.g., `ETHUSDT`, `BNBUSDT`) |
| `--interval` | `15m` | Candle interval (1m, 5m, 15m, 1h, 4h, 1d) |
| `--limit` | `500` | Number of candles to fetch |
| `--fast` | `9` | Fast EMA period |
| `--slow` | `21` | Slow EMA period |
| `--rsi-period` | `14` | RSI period |

#### Paper Trading Mode

```bash
python -m trading_bot.bot --mode paper [options]
```

All backtest arguments, plus:

| Argument | Default | Description |
|----------|---------|-------------|
| `--order-pct` | `2` | Percentage of capital per order (%) |
| `--stop-pips` | `0.7` | Stop-loss/take-profit distance in absolute price units (70 pips) |
| `--disable-oco` | `False` | Disable OCO orders (if set, only market orders) |

## Strategy: EMA9/EMA21 + RSI14 Filter

### Entry Conditions

- **Uptrend**: EMA9 > EMA21 **AND** RSI14 ≥ 50 → **BUY signal**
- **Downtrend**: EMA9 < EMA21 **AND** RSI14 ≤ 50 → **SELL signal**

### Exit Conditions (OCO Order)

- **Stop-Loss**: Fixed distance (default 0.7%) below entry price
- **Take-Profit**: 2× stop-loss distance above entry price (e.g., 1.4% for 0.7% stop)

### Position Sizing

Calculated as:
```
qty = (account_equity * risk_pct) / (entry_price * stop_distance)
```

Example: $10,000 account, 2% risk, $50,000 BTC, 0.7% stop
```
qty ≈ (10,000 * 0.02) / (50,000 * 0.007) ≈ 0.057 BTC
```

## Usage Examples

### Backtest Multiple Timeframes

```bash
# 15-minute candles
PYTHONPATH=$(pwd) .venv/bin/python3 -m trading_bot.bot --mode backtest \
  --symbol BTCUSDT --interval 15m --limit 1000

# 1-hour candles
PYTHONPATH=$(pwd) .venv/bin/python3 -m trading_bot.bot --mode backtest \
  --symbol BTCUSDT --interval 1h --limit 500
```

### Paper Trade Different Pairs

```bash
# Bitcoin
PYTHONPATH=$(pwd) .venv/bin/python3 -m trading_bot.bot --mode paper \
  --symbol BTCUSDT --order-pct 1.5 --stop-pips 0.5

# Ethereum
PYTHONPATH=$(pwd) .venv/bin/python3 -m trading_bot.bot --mode paper \
  --symbol ETHUSDT --order-pct 2.0 --stop-pips 0.8
```

### Test EMA Parameters

```bash
PYTHONPATH=$(pwd) .venv/bin/python3 -m trading_bot.bot --mode backtest \
  --symbol BTCUSDT --fast 12 --slow 26 --rsi-period 14
```

## Testing

Run the full test suite:

```bash
make test
# or:
PYTHONPATH=$(pwd) .venv/bin/python3 -m pytest tests -q
```

Tests cover:
- Backtesting logic (entry/exit signals, metrics)
- Execution flow (paper trading order placement)
- Risk management (position sizing)
- Metrics calculation (PnL, win rate, drawdown)
- Binance connector (API calls, error handling)

## Logging

All output is logged to `trading_bot.log` in the project root with a 10 MB rotation and 7-day retention. Console output includes:

- Strategy signals (entry/exit)
- Trade summary (PnL, equity)
- Metrics (win rate, avg return, max drawdown)
- Errors and warnings

## Development

### Install in Editable Mode

```bash
make install
```

### Run Tests

```bash
make test
```

### Check Logs

```bash
tail -f trading_bot.log
```

## Binance Testnet

1. **Get Testnet Credentials**:
   - Visit [Binance Testnet](https://testnet.binance.vision/)
   - Sign in with your Binance account or create a testnet account
   - Generate API keys

2. **Add to `.env`**:
   ```ini
   BINANCE_API_KEY=your_key
   BINANCE_API_SECRET=your_secret
   BINANCE_TESTNET=True
   ```

3. **Verify Connection**:
   ```bash
   PYTHONPATH=$(pwd) .venv/bin/python3 scripts/check_keys.py --test-order
   ```

## Security Notes

- **Never commit `.env`** with real API keys.
- Store API keys in a secure location (e.g., environment variables, password manager).
- Use testnet credentials only until thoroughly tested.
- Restrict API key permissions on Binance (IP whitelist, trading only, no withdrawals).
- If keys are exposed, immediately revoke them on Binance and generate new ones.

## Troubleshooting

### `ModuleNotFoundError: No module named 'trading_bot'`

Ensure `PYTHONPATH=$(pwd)` is set when running scripts:

```bash
PYTHONPATH=$(pwd) .venv/bin/python3 -m trading_bot.bot --mode backtest
```

Or use Make commands, which handle this automatically:

```bash
make backtest
```

### `.env` Not Loading

Make sure `.env` is in the project root. The app loads it via `python-dotenv` and the `trading_bot.config` module. Verify with:

```bash
PYTHONPATH=$(pwd) .venv/bin/python3 scripts/check_keys.py
```

### No Balances Returned

Check that:
1. Your API key and secret are correct (from Binance testnet).
2. `BINANCE_TESTNET=True` is set in `.env`.
3. Testnet account has been initialized (fund it via the testnet faucet).

### Orders Not Placed

If paper trading runs but no orders are placed:
- Check `trading_bot.log` for strategy signals.
- Verify RSI and EMA conditions (may require different candle history).
- Ensure `--order-pct` and `--stop-pips` are reasonable (not too small/large).

## License

See [LICENSE](LICENSE) for details.

## Contributing

1. Fork and create a feature branch.
2. Implement changes and add tests.
3. Run `make test` to verify.
4. Submit a pull request.

## Support

For issues or questions:
- Check the logs (`trading_bot.log`).
- Review the strategy entry/exit conditions.
- Test with smaller position sizes or different parameters.