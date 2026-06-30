from trading_bot.state_store import TradingStateStore


def test_state_store_position_roundtrip(tmp_path):
    store_path = tmp_path / "state.db"
    store = TradingStateStore(str(store_path))

    store.set_position("BTCUSDT", {"side": "LONG", "qty": 0.01})
    position = store.get_position("BTCUSDT")
    assert position is not None
    assert position["side"] == "LONG"

    store.clear_position("BTCUSDT")
    assert store.get_position("BTCUSDT") is None


def test_state_store_signal_dedup(tmp_path):
    store = TradingStateStore(str(tmp_path / "state.db"))
    signal_id = "2026-01-01T00:00:00:1:0"

    assert store.is_signal_processed("BTCUSDT", signal_id) is False
    store.mark_signal_processed("BTCUSDT", signal_id, {"action": "buy"})
    assert store.is_signal_processed("BTCUSDT", signal_id) is True
