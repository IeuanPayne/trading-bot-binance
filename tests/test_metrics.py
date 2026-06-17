from trading_bot.metrics import compute_trade_metrics


def test_compute_trade_metrics_empty():
    res = compute_trade_metrics([], initial_capital=1000.0)
    assert res["total_pnl"] == 0
    assert res["num_pairs"] == 0


def test_compute_trade_metrics_simple_pair():
    trades = [
        {"type": "buy", "price": 10.0, "qty": 1.0, "reason": "long_entry"},
        {"type": "sell", "price": 12.0, "qty": 1.0, "reason": "tp/sl"},
    ]
    res = compute_trade_metrics(trades, initial_capital=1000.0)
    assert res["total_pnl"] == 2.0
    assert res["num_pairs"] == 1
    assert res["win_rate"] == 1.0
