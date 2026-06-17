#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "\nSetup complete. Activate the environment with: source .venv/bin/activate"
echo "Run backtests with: .venv/bin/python3 -m trading_bot.bot --symbol BTCUSDT --interval 15m --limit 500"
echo "Run paper trading with: .venv/bin/python3 -m trading_bot.bot --mode paper --symbol BTCUSDT --interval 15m --limit 500"
