#!/usr/bin/env python3
"""Check Binance API keys from .env and optionally place a test order.

Usage:
  ./scripts/check_keys.py
  ./scripts/check_keys.py --test-order --symbol BTCUSDT --qty 0.001
"""
import argparse
import os
from dotenv import load_dotenv, find_dotenv
from loguru import logger

# import after load_dotenv to allow module-level env usage
load_dotenv(find_dotenv())

from trading_bot.binance_connector import BinanceConnector  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Validate Binance API keys and optionally place a test order")
    parser.add_argument("--test-order", action="store_true", help="Place a test order (does not execute a real trade)")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--qty", type=float, default=0.001)
    args = parser.parse_args()

    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    testnet = os.getenv("BINANCE_TESTNET", "True").lower() in ("1", "true", "yes")

    print("BINANCE_TESTNET=", testnet)
    if not api_key or not api_secret:
        logger.error("BINANCE_API_KEY or BINANCE_API_SECRET not found in environment (.env)")
        return

    connector = BinanceConnector(api_key=api_key, api_secret=api_secret, testnet=testnet)
    if connector.client is None:
        logger.error("Authenticated Binance client is unavailable. Check keys and python-binance installation.")
        return

    try:
        usdt = connector.get_asset_balance("USDT")
        btc = connector.get_asset_balance("BTC")
        print("USDT balance:", usdt)
        print("BTC balance:", btc)
    except Exception as exc:
        logger.exception("Failed to fetch balances: {}", exc)
        return

    if args.test_order:
        try:
            # create_test_order is supported by python-binance client and does not place a real order
            resp = connector.client.create_test_order(symbol=args.symbol, side="BUY", type="MARKET", quantity=args.qty)
            print("Test order successful (no trade placed):", resp)
        except Exception as exc:
            logger.exception("Test order failed: {}", exc)


if __name__ == "__main__":
    main()
