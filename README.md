# trading-bot-binance

A Python-based automated trading bot for Binance and MT5 with backtesting and paper trading capabilities. It now implements an **EMA channel continuation** strategy: stacked EMAs, breakout beyond the EMA channel, first retest into the channel, then confirmation in the trend direction.

## Features

- **Backtesting Engine**: Test strategies on historical OHLC data with configurable parameters.
- **Paper Trading**: Run live orders on Binance testnet without risking real capital.
- **EMA Channel Continuation Strategy**: Uses 8/13/21/34/55 EMAs and a breakout, retest, confirm entry pattern.
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
EMA1_LEN=8
EMA2_LEN=13
EMA3_LEN=21
EMA4_LEN=34
EMA5_LEN=55
SESSION=Both
LONDON_START=11
LONDON_END=20
NEWYORK_START=16
NEWYORK_END=25
SESSION_TZ_OFFSET=3
MAX_SPREAD_PIPS=3.0
MODELED_SPREAD_PIPS=0.0
PIP_SIZE=0.10
ALERTS_ENABLED=False
ALERT_SMS_PROVIDER=twilio
ALERT_PHONE_TO=
ALERT_PHONE_FROM=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
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
  --ema1-len 8 --ema2-len 13 --ema3-len 21 --ema4-len 34 --ema5-len 55
```

Expected output includes PnL, final equity, number of trades, and metrics.

### 5. Run Paper Trading

```bash
make paper
# or:
PYTHONPATH=$(pwd) .venv/bin/python3 -m trading_bot.bot --mode paper \
  --symbol BTCUSDT --interval 15m --limit 500 \
  --order-pct 2 --stop-pips 0.7 --modeled-spread-pips 0.5
```

### 6. Run MT5 Trading Mode

Configure MT5 credentials in `.env` (see table below), then run:

```bash
PYTHONPATH=$(pwd) .venv/bin/python3 -m trading_bot.bot --mode mt5 \
  --interval 15m --limit 500 \
  --ema1-len 8 --ema2-len 13 --ema3-len 21 --ema4-len 34 --ema5-len 55 \
  --session Both --max-spread-pips 3 --pip-size 0.10 \
  --order-pct 0.01 --stop-pips 0.7
```

For unattended VPS operation (candle-aligned loop with reconnect attempts):

```bash
PYTHONPATH=$(pwd) .venv/bin/python3 scripts/soak_mt5.py \
  --interval 15m --duration-hours 24 --run-now
```

On Windows VPS (auto-start on reboot), use:

```powershell
python scripts/soak_mt5.py --interval 15m --duration-hours 0 --run-now
```

`--duration-hours 0` means run indefinitely.

### 6b. Run TradingView Webhook Mode (MT5 Execution)

You can receive TradingView alerts over webhook and forward them to MT5 execution.

Start the webhook server:

```bash
PYTHONPATH=$(pwd) .venv/bin/python3 -m trading_bot.bot --mode tv-webhook \
  --interval 15m --use-risk-pct --risk-pct 1 --sl-pips 70 --tp-pips 70
```

Default endpoint comes from env vars:

- `TV_WEBHOOK_HOST` (default `0.0.0.0`)
- `TV_WEBHOOK_PORT` (default `8080`)
- `TV_WEBHOOK_PATH` (default `/tradingview/webhook`)
- `TV_WEBHOOK_SECRET` (required)

Expected TradingView webhook JSON payload:

```json
{
  "secret": "YOUR_SHARED_SECRET",
  "strategy_id": "playbit-ema",
  "signal_id": "optional-unique-id",
  "symbol": "XAUUSD",
  "timeframe": "15m",
  "side": "sell",
  "timestamp": "2026-07-16T12:45:00Z"
}
```

Notes:

- The bot de-duplicates by `signal_id` (or a deterministic fallback key).
- Allowed symbols/timeframes can be restricted via `TV_ALLOWED_SYMBOLS` and `TV_ALLOWED_TIMEFRAMES`.
- Orders are placed through the same MT5 risk, SL/TP, and magic settings you already use.

### 7. Windows VPS Auto-Start (Task Scheduler)

This repo includes a wrapper and task template:

- `scripts/windows/run_mt5_soak.ps1`
- `scripts/windows/mt5_soak_task.xml`

Setup steps on your Windows VPS:

1. Clone repo to a fixed path, for example `C:\trading-bot-binance`.
2. Edit `scripts/windows/mt5_soak_task.xml`:
   - Replace `YOUR_WINDOWS_USERNAME`.
   - If needed, update `-RepoPath` and script path arguments.
3. Import/register task (PowerShell as Administrator):

```powershell
$xml = Get-Content .\scripts\windows\mt5_soak_task.xml | Out-String
Register-ScheduledTask -TaskName "TradingBot-MT5-Soak" -Xml $xml -User "YOUR_WINDOWS_USERNAME" -Password "YOUR_WINDOWS_PASSWORD"
```

4. Start immediately (optional):

```powershell
Start-ScheduledTask -TaskName "TradingBot-MT5-Soak"
```

5. Check wrapper log output in `logs\mt5_wrapper.log` and strategy logs in `trading_bot.log`.

The MT5 flow persists signal de-duplication and breaker state in `MT5_STATE_FILE`.

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
| `EMA1_LEN` | `8` | Default fastest EMA period |
| `EMA2_LEN` | `13` | Default second EMA period |
| `EMA3_LEN` | `21` | Default middle EMA period |
| `EMA4_LEN` | `34` | Default fourth EMA period |
| `EMA5_LEN` | `55` | Default slowest EMA period |
| `SESSION` | `Both` | Default session gate: `London`, `NewYork`, `Both`, or `Off` |
| `LONDON_START` | `11` | Default London session start hour in server time |
| `LONDON_END` | `20` | Default London session end hour in server time |
| `NEWYORK_START` | `16` | Default New York session start hour in server time |
| `NEWYORK_END` | `25` | Default New York session end hour in server time |
| `SESSION_TZ_OFFSET` | `3` | Default server-time offset from UTC |
| `MAX_SPREAD_PIPS` | `3.0` | Default spread threshold before blocking entries |
| `MODELED_SPREAD_PIPS` | `0.0` | Default modeled spread used by backtest and paper mode |
| `PIP_SIZE` | `0.10` | Pip size used for MT5 spread conversion |
| `ALERTS_ENABLED` | `False` | Enable outbound alerts |
| `ALERT_SMS_PROVIDER` | `twilio` | Alert provider (currently `twilio`) |
| `ALERT_PHONE_TO` | `+15551234567` | Destination phone number for SMS alerts |
| `ALERT_PHONE_FROM` | `+15557654321` | Twilio sender phone number |
| `TWILIO_ACCOUNT_SID` | `AC...` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | `...` | Twilio auth token |
| `MT5_ENABLED` | `False` | Set `True` to enable MT5 mode |
| `MT5_LOGIN` | `12345678` | MT5 account login |
| `MT5_PASSWORD` | `...` | MT5 account password |
| `MT5_SERVER` | `Broker-Server` | MT5 broker server name |
| `MT5_TERMINAL_PATH` | `C:\\Program Files\\MetaTrader 5\\terminal64.exe` | Optional MT5 terminal path |
| `MT5_SYMBOL` | `BTCUSD` | MT5 trading symbol |
| `MT5_STATE_FILE` | `mt5_trading_state.db` | Persistent state for MT5 de-dup and breakers |

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
| `--ema1-len` | `8` | Fastest EMA period |
| `--ema2-len` | `13` | Second EMA period |
| `--ema3-len` | `21` | Middle EMA period |
| `--ema4-len` | `34` | Fourth EMA period |
| `--ema5-len` | `55` | Slowest EMA period |
| `--session` | `Both` | Session filter: `London`, `NewYork`, `Both`, or `Off` |
| `--london-start` | `11` | London session start hour in server time |
| `--london-end` | `20` | London session end hour in server time |
| `--newyork-start` | `16` | New York session start hour in server time |
| `--newyork-end` | `25` | New York session end hour in server time, supports wrap past midnight |
| `--session-tz-offset` | `3` | Server time offset from UTC used by the session gate |

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
| `--max-spread-pips` | `3.0` | Spread gate in pips before entry is blocked |
| `--modeled-spread-pips` | `0.0` | Simulated spread used by backtest and paper mode |
| `--pip-size` | `0.10` | MT5 pip size used to convert live spread into pips |

## Strategy: EMA Channel Continuation

Default EMA channel: `8 / 13 / 21 / 34 / 55`

### Entry Conditions

- **Trend qualification**: all five EMAs must be stacked in order.
- **Breakout**: price must close above the EMA channel for longs, or below it for shorts.
- **Retest**: the first pullback candle must revisit the EMA channel without invalidating the trend.
- **Confirmation**: the next candle must close back outside the channel in the trend direction.
- **Session gate**: entries are allowed only during the configured London and/or New York session window.
- **Spread gate**: in MT5 mode, entries are blocked when live spread exceeds the max; in backtest and paper mode, the modeled spread must also stay below the same threshold.
- **Single active position**: while a trade is open, the bot ignores new signals instead of flipping on an opposite signal.

### Exit Conditions (OCO Order)

- **Stop-Loss**: Fixed absolute distance from entry price (default `0.7` price units)
- **Take-Profit**: Same fixed absolute distance in the profit direction (1:1 reward/risk)

### Position Sizing

Calculated as:
```
qty = (account_equity * order_pct) / entry_price
```

Example: $10,000 account, 2% risk, $50,000 BTC, `0.7` stop distance
```
qty ≈ (10,000 * 0.02) / 50,000 ≈ 0.004 BTC
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
  --symbol BTCUSDT --ema1-len 10 --ema2-len 14 --ema3-len 24 --ema4-len 36 --ema5-len 60
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

## Controlled Soak Test (Testnet 24-72h)

Use this to validate long-running stability before real-capital rollout.

### 1. Pre-flight

Ensure:

- `BINANCE_TESTNET=True`
- `ALLOW_LIVE_TRADING=False`
- API keys are valid (`make check-keys`)
- Optional SMS alerting is configured for failures/breakers

### 2. Run 24h soak test

```bash
make soak-test
```

Equivalent explicit command:

```bash
PYTHONPATH=$(pwd) .venv/bin/python3 scripts/soak_test.py \
  --symbol BTCUSDT --interval 15m --duration-hours 24 --run-now
```

### 3. Extend to 72h

```bash
PYTHONPATH=$(pwd) .venv/bin/python3 scripts/soak_test.py \
  --symbol BTCUSDT --interval 15m --duration-hours 72 --run-now
```

### 4. Monitor during soak

```bash
tail -f trading_bot.log
```

Risk/position persistence is stored in `trading_state.db`.

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
- Verify EMA channel alignment, session window, and spread gate settings.
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