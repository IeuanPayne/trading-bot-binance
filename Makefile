VENV=.venv
PYTHON=$(VENV)/bin/python3
PIP=$(VENV)/bin/pip

.PHONY: help setup install test backtest paper check-keys grid-backtest

help:
	@echo "Usage: make <target>"
	@echo "Targets: setup install test backtest paper check-keys grid-backtest"
	@echo "  setup          Create virtualenv and install project dependencies."
	@echo "  install        Install the package in editable mode."
	@echo "  test           Run the unit test suite."
	@echo "  backtest       Run the EMA+RSI backtest example."
	@echo "  paper          Run paper trading mode against Binance testnet."
	@echo "  check-keys     Validate Binance API keys and fetch balances."
	@echo "  grid-backtest  Run grid backtest (test EMA/timeframe combos)."

setup:
	python3 -m venv $(VENV)
	. $(VENV)/bin/activate && $(PIP) install --upgrade pip
	. $(VENV)/bin/activate && $(PIP) install -r requirements.txt

install: setup
	. $(VENV)/bin/activate && $(PIP) install -e .

test:
	$(PYTHON) -m pytest tests -q

backtest:
	$(PYTHON) -m trading_bot.bot --mode backtest --symbol BTCUSDT --interval 15m --limit 500

paper:
	$(PYTHON) -m trading_bot.bot --mode paper --symbol BTCUSDT --interval 15m --limit 500

check-keys:
	PYTHONPATH=$(PWD) $(PYTHON) scripts/check_keys.py

grid-backtest:
	PYTHONPATH=$(PWD) $(PYTHON) -m trading_bot.bot --mode grid-backtest --symbol BTCUSDT --limit 1000
