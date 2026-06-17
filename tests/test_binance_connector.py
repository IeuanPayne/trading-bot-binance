import sys

from trading_bot.binance_connector import BinanceConnector


class FakeClient:
    def __init__(self, info):
        self.info = info

    def get_symbol_info(self, symbol: str):
        assert symbol == "BTCUSDT"
        return self.info


def test_round_quantity_returns_unchanged_without_client():
    connector = BinanceConnector()
    quantity = 1.234567
    assert connector.round_quantity("BTCUSDT", quantity) == quantity


def test_round_quantity_rounds_to_lot_size():
    connector = BinanceConnector()
    connector.client = FakeClient(
        {
            "filters": [
                {"filterType": "LOT_SIZE", "stepSize": "0.001"},
            ]
        }
    )

    assert connector.round_quantity("BTCUSDT", 0.0019) == 0.001
    assert connector.round_quantity("BTCUSDT", 0.0021) == 0.002
