# trading-bot-binance

Python trading bot with Binance backtest/paper modes and MT5 execution modes, including TradingView webhook ingestion.

## What It Does

- Backtests and paper-trades an EMA channel continuation strategy.
- Runs live MT5 execution with spread gates, state persistence, and risk controls.
- Accepts TradingView webhook alerts and executes them on MT5.
- Manages open MT5 positions continuously (staged exits and optional trailing), including in webhook mode.

## Modes

- `backtest`: historical simulation on Binance candles.
- `paper`: Binance testnet paper execution.
- `grid-backtest`: parameter sweeps.
- `mt5`: indicator-driven MT5 loop.
- `tv-webhook`: TradingView alert listener that executes on MT5.

## Setup

```bash
cd trading-bot-binance
make setup
make install
cp .env.example .env
```

## Important Runtime Rules

- `order-pct` is a fraction in `(0, 1]`.
- `0.01` means `1%`.
- MT5 modes require:
  - `MT5_ENABLED=True`
  - `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`
- `tv-webhook` mode also requires `TV_WEBHOOK_SECRET`.

## Quick Commands

```bash
# backtest
make backtest

# paper
make paper

# tests
make test

# key check
make check-keys

# grid sweep
make grid-backtest

# long-running soaks
make soak-test
make soak-mt5
```

## CLI Examples

### Backtest

```bash
PYTHONPATH=$(pwd) .venv/bin/python3 -m trading_bot.bot --mode backtest \
  --symbol BTCUSDT --interval 15m --limit 500 \
  --ema1-len 8 --ema2-len 13 --ema3-len 21 --ema4-len 34 --ema5-len 55
```

### Paper

```bash
PYTHONPATH=$(pwd) .venv/bin/python3 -m trading_bot.bot --mode paper \
  --symbol BTCUSDT --interval 15m --limit 500 \
  --order-pct 0.01 --stop-pips 0.7 --modeled-spread-pips 0.5
```

### MT5

```bash
PYTHONPATH=$(pwd) .venv/bin/python3 -m trading_bot.bot --mode mt5 \
  --interval 15m --limit 500 \
  --session Both --max-spread-pips 3 --pip-size 0.10 \
  --order-pct 0.01 --use-risk-pct --risk-pct 1 \
  --sl-pips 70 --tp-pips 70
```

### TradingView Webhook -> MT5

```bash
PYTHONPATH=$(pwd) .venv/bin/python3 -m trading_bot.bot --mode tv-webhook \
  --interval 15m --limit 500 \
  --tv-host 0.0.0.0 --tv-port 8080 --tv-path /tradingview/webhook \
  --use-risk-pct --risk-pct 1 --sl-pips 70 --tp-pips 70
```

## Webhook Payload

Expected JSON:

```json
{
  "secret": "YOUR_SHARED_SECRET",
  "strategy_id": "pb-ema",
  "signal_id": "optional-unique-id",
  "symbol": "XAUUSD",
  "timeframe": "15m",
  "side": "buy",
  "timestamp": "2026-07-21T12:45:00Z"
}
```

Accepted `side` values: `buy`, `sell`, `long`, `short`.

## Webhook Behavior

- De-duplicates alerts by `signal_id` (or deterministic fallback key).
- Rejects unauthorized secrets.
- Optional allowlists for symbol/timeframe and source IP.
- Skips new entries if an MT5 position is already open for symbol/magic.
- Applies spread gate before entry.
- Stores execution state in `MT5_STATE_FILE`.
- Runs a background management loop in webhook mode to actively manage open positions after entry.
- Emits concise accepted/rejected outcome logs.

## TradingView/Pine Script

Script file:

- `scripts/tradingview_playbit_ema.pine`

Current script supports two signal modes:

- `EMA Touch` (default): signal when price touches selected EMA and closes on one side.
- `Continuation`: breakout -> retest -> confirmation state machine.

`alertcondition` lines are included for long and short webhook JSON alerts.

## Environment Variables

The runtime reads `.env` through `trading_bot/config.py`.

### Core

| Variable | Default | Notes |
|---|---|---|
| `BINANCE_API_KEY` | empty | Required for Binance access |
| `BINANCE_API_SECRET` | empty | Required for Binance access |
| `BINANCE_TESTNET` | `True` | Keep `True` for paper |
| `ALLOW_LIVE_TRADING` | `False` | Must be `True` to allow non-testnet orders |
| `INITIAL_CAPITAL` | `10000.0` | Backtest capital base |
| `MAX_PCT_PER_TRADE` | `0.01` | Fraction, not whole percent |
| `MAX_DAILY_LOSS_USDT` | `0` | `0` disables breaker |
| `MAX_DRAWDOWN_PCT` | `0` | `0` disables breaker |
| `MAX_CONSECUTIVE_LOSSES` | `0` | `0` disables breaker |
| `MAX_TRADES_PER_DAY` | `0` | `0` disables breaker |

### Strategy and Session

| Variable | Default |
|---|---|
| `EMA1_LEN` | `8` |
| `EMA2_LEN` | `13` |
| `EMA3_LEN` | `21` |
| `EMA4_LEN` | `34` |
| `EMA5_LEN` | `55` |
| `SESSION` | `Both` |
| `LONDON_START` | `11` |
| `LONDON_END` | `20` |
| `NEWYORK_START` | `16` |
| `NEWYORK_END` | `25` |
| `SESSION_TZ_OFFSET` | `3` |
| `MAX_SPREAD_PIPS` | `3.0` |
| `MODELED_SPREAD_PIPS` | `0.0` |
| `PIP_SIZE` | `0.10` |

### Alerts

| Variable | Default |
|---|---|
| `ALERTS_ENABLED` | `False` |
| `ALERT_SMS_PROVIDER` | `twilio` |
| `ALERT_PHONE_TO` | empty |
| `ALERT_PHONE_FROM` | empty |
| `TWILIO_ACCOUNT_SID` | empty |
| `TWILIO_AUTH_TOKEN` | empty |

### MT5

| Variable | Default |
|---|---|
| `MT5_ENABLED` | `False` |
| `MT5_LOGIN` | empty |
| `MT5_PASSWORD` | empty |
| `MT5_SERVER` | empty |
| `MT5_TERMINAL_PATH` | empty |
| `MT5_SYMBOL` | `BTCUSD` |
| `MT5_STATE_FILE` | `mt5_trading_state.db` |
| `MT5_USE_RISK_PCT` | `True` |
| `MT5_RISK_PCT` | `1.0` |
| `MT5_SL_PIPS` | `70.0` |
| `MT5_TP_PIPS` | `70.0` |
| `MT5_DYNAMIC_SLTP` | `False` |
| `MT5_ATR_PERIOD` | `14` |
| `MT5_SL_ATR_MULT` | `1.5` |
| `MT5_TP_ATR_MULT` | `2.0` |
| `MT5_TRAILING_STOP_ENABLED` | `False` |
| `MT5_TRAIL_ACTIVATE_R` | `1.0` |
| `MT5_TRAIL_ATR_PERIOD` | `14` |
| `MT5_TRAIL_ATR_MULT` | `1.0` |
| `MT5_TRAIL_MIN_STEP_ATR` | `0.2` |
| `MT5_STAGED_EXIT_ENABLED` | `False` |
| `MT5_STAGED_BE_TRIGGER_PIPS` | `30.0` |
| `MT5_STAGED_BE_OFFSET_PIPS` | `5.0` |
| `MT5_STAGED_TRAIL_PIPS` | `50.0` |
| `MT5_STAGED_TP4_OPEN` | `False` |
| `MT5_SLIPPAGE` | `30` |
| `MT5_AUTO_MAGIC` | `True` |
| `MT5_BASE_MAGIC` | `20260629` |
| `MT5_ALLOW_MULTIPLE_POSITIONS` | `False` |
| `MT5_SIGNAL_DEBUG` | `False` |

### TradingView Webhook

| Variable | Default | Notes |
|---|---|---|
| `TV_WEBHOOK_HOST` | `0.0.0.0` | Bind address |
| `TV_WEBHOOK_PORT` | `8080` | Listener port |
| `TV_WEBHOOK_PATH` | `/tradingview/webhook` | Route path |
| `TV_WEBHOOK_SECRET` | empty | Required in webhook mode |
| `TV_ALLOWED_SYMBOLS` | empty list | CSV allowlist |
| `TV_ALLOWED_TIMEFRAMES` | empty list | CSV allowlist |
| `TV_ALLOWED_SOURCE_IPS` | empty list | CSV IP/CIDR allowlist |

## Windows VPS: Auto Start + Weekend Reboot

Files included:

- `scripts/windows/run_tv_webhook_bot.ps1`
- `scripts/windows/tv_webhook_startup_task.xml`
- `scripts/windows/weekend_reboot_task.xml`

Recommended: create tasks with `schtasks` commands (avoids XML account mapping issues on many VPS images).

### Startup Task (on boot)

Run in elevated PowerShell:

```powershell
schtasks /create /tn "TradingBot-TVWebhook-Startup" /sc onstart /ru SYSTEM /rl HIGHEST /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\trading-bot-binance\scripts\windows\run_tv_webhook_bot.ps1 -RepoPath C:\trading-bot-binance -Interval 15m -Host 0.0.0.0 -Port 80 -Path /tradingview/webhook" /f
```

### Weekend Reboot Task

```powershell
schtasks /create /tn "TradingBot-Weekend-Reboot" /sc weekly /d SAT /st 06:00 /ru SYSTEM /rl HIGHEST /tr "shutdown.exe /r /f /t 60" /f
```

### Verify and Test

```powershell
schtasks /query /tn "TradingBot-TVWebhook-Startup" /v /fo list
schtasks /query /tn "TradingBot-Weekend-Reboot" /v /fo list
schtasks /run /tn "TradingBot-TVWebhook-Startup"
```

Wrapper log path:

- `logs/tv_webhook_wrapper.log`

## Testing

```bash
make test
# or
PYTHONPATH=$(pwd) .venv/bin/python3 -m pytest tests -q
```

Focused suites often used for MT5/webhook changes:

```bash
PYTHONPATH=$(pwd) .venv/bin/python3 -m pytest -q \
  tests/test_tradingview_webhook.py \
  tests/test_mt5_execution.py \
  tests/test_bot_cli.py \
  tests/test_cli.py
```

## Project Structure

```text
trading-bot-binance/
  README.md
  Makefile
  pyproject.toml
  requirements.txt
  .env.example
  scripts/
    check_keys.py
    soak_test.py
    soak_mt5.py
    tradingview_playbit_ema.pine
    windows/
      run_mt5_soak.ps1
      run_tv_webhook_bot.ps1
      mt5_soak_task.xml
      tv_webhook_startup_task.xml
      weekend_reboot_task.xml
  tests/
    test_backtest.py
    test_execution.py
    test_binance_connector.py
    test_cli.py
    test_bot_cli.py
    test_mt5_execution.py
    test_mt5_connector.py
    test_tradingview_webhook.py
  trading_bot/
    bot.py
    config.py
    backtest.py
    execution.py
    mt5_execution.py
    mt5_connector.py
    tradingview_webhook.py
    state_store.py
    risk.py
    metrics.py
    metrics_persistence.py
```

## Troubleshooting

### Order size validation fails

Use fractional `--order-pct` values such as `0.01` for 1%.

### Webhook returns 403

Check `TV_ALLOWED_SOURCE_IPS` and caller IP.

### Webhook returns 400 unauthorized

Verify TradingView `secret` matches `TV_WEBHOOK_SECRET` exactly.

### MT5 mode startup fails

Confirm `MT5_ENABLED=True` and required credentials are present.

## Security Notes

- Never commit real credentials.
- Keep Binance on testnet until you intentionally switch.
- Restrict key permissions and rotate exposed credentials immediately.

## License

See `LICENSE`.
