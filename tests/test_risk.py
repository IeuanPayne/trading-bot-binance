from trading_bot.risk import position_size_by_risk


def test_position_size_by_risk_basic():
    qty = position_size_by_risk(capital=10000.0, risk_per_trade=0.01, entry_price=100.0, stop_distance=1.0)
    # risk_usd = 100 -> qty = 100 / 1 = 100
    assert qty == 100.0


def test_position_size_invalid_inputs():
    assert position_size_by_risk(0, 0.01, 100, 1) == 0
    assert position_size_by_risk(10000, 0, 100, 1) == 0
    assert position_size_by_risk(10000, 0.01, 100, 0) == 0
