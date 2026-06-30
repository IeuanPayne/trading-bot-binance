from trading_bot.binance_connector import BinanceConnector


class FakeClient:
    def __init__(self, info):
        self.info = info
        self.last_create_order = None
        self.last_create_oco = None

    def get_symbol_info(self, symbol: str):
        assert symbol == "BTCUSDT"
        return self.info

    def create_order(self, **kwargs):
        self.last_create_order = kwargs
        return {"ok": True}

    def create_oco_order(self, **kwargs):
        self.last_create_oco = kwargs
        return {"ok": True}


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


def test_validate_market_order_checks_min_notional_and_lot_size():
    connector = BinanceConnector()
    connector.client = FakeClient(
        {
            "filters": [
                {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "1000", "stepSize": "0.001"},
                {"filterType": "MIN_NOTIONAL", "minNotional": "10"},
            ]
        }
    )

    valid, reason = connector.validate_market_order("BTCUSDT", quantity=0.005, reference_price=30000)
    assert valid is True
    assert reason == "ok"

    valid, reason = connector.validate_market_order("BTCUSDT", quantity=0.0005, reference_price=30000)
    assert valid is False
    assert "minQty" in reason

    valid, reason = connector.validate_market_order("BTCUSDT", quantity=0.001, reference_price=5000)
    assert valid is False
    assert "minNotional" in reason


def test_create_market_order_sets_client_order_id_when_provided():
    connector = BinanceConnector()
    fake = FakeClient({"filters": []})
    connector.client = fake

    connector.create_market_order("BTCUSDT", "BUY", 0.01, client_order_id="tb_buy_abc")
    assert fake.last_create_order["newClientOrderId"] == "tb_buy_abc"


def test_create_oco_order_sets_client_order_ids_when_provided():
    connector = BinanceConnector()
    fake = FakeClient({"filters": []})
    connector.client = fake

    connector.create_oco_order(
        symbol="BTCUSDT",
        side="SELL",
        quantity=0.01,
        price=51000,
        stop_price=49000,
        stop_limit_price=48950,
        list_client_order_id="tb_oco_list_abc",
        limit_client_order_id="tb_oco_tp_abc",
        stop_client_order_id="tb_oco_sl_abc",
    )

    assert fake.last_create_oco["listClientOrderId"] == "tb_oco_list_abc"
    assert fake.last_create_oco["limitClientOrderId"] == "tb_oco_tp_abc"
    assert fake.last_create_oco["stopClientOrderId"] == "tb_oco_sl_abc"
