# Trading Bot (Binance testnet) — Minimal Starter

This repo contains a minimal Python trading-bot scaffold with:

- Binance public klines fetcher
- EMA9 / EMA21 crossover strategy
- RSI confirmation filter (50–70 long, 30–50 short)
- 15-minute candle backtester
- 70-pip stop loss and take profit

Quick start:

1. Create and activate a virtualenv (Python 3.10+):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Run the backtest example:

```bash
python3 -m trading_bot.bot --symbol BTCUSDT --interval 15m --limit 500
```

3. If you want a local editable install, run:

```bash
pip install -e .
```

4. If the virtualenv install is still pending, check with:

```bash
. .venv/bin/activate
python3 -m pip list | grep -E 'loguru|pandas|numpy|requests|python-binance|ccxt|python-dotenv|pytest'
```

3. To change the strategy parameters:

```bash
python3 -m trading_bot.bot --symbol BTCUSDT --interval 15m --limit 500 --fast 9 --slow 21 --rsi-period 14
```

## Makefile commands

You can also use the included `Makefile`:

```bash
make setup   # create venv and install dependencies
make install # install editable package after setup
make test    # run the unit test suite
make backtest # run the default backtest example
make paper   # run Binance testnet paper trading mode
```

The bot currently supports backtesting the EMA+RSI strategy. To add Binance testnet paper trading execution, copy `.env.example` to `.env` and set your testnet API keys.

## Paper trading usage

Create a `.env` file from `.env.example` and add your Binance testnet API key and secret. Keep `BINANCE_TESTNET=True` for paper trading.

Run paper trading mode:

```bash
.venv/bin/python3 -m trading_bot.bot --mode paper --symbol BTCUSDT --interval 15m --limit 500
```

If you want to adjust order sizing or OCO placement:

```bash
.venv/bin/python3 -m trading_bot.bot --mode paper --symbol BTCUSDT --interval 15m --limit 500 --order-pct 0.01 --stop-pips 0.7
```
