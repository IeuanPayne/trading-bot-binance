from __future__ import annotations

from dataclasses import dataclass

from trading_bot.tradingview_webhook import (
    WebhookTradeSettings,
    _is_source_ip_allowed,
    _parse_allowed_source_ips,
    _should_suppress_probe_log,
    process_tradingview_signal,
    validate_and_normalize_alert,
    _is_sdk_web_language_probe,
)


@dataclass
class _FakePosition:
    side: str


class _FakeConnector:
    def __init__(self):
        self.orders = []
        self.position = None

    def get_net_position(self, symbol: str, magic: int | None = None):
        return self.position

    def get_spread_pips(self, symbol: str, pip_size: float = 0.10) -> float:
        return 1.0

    def get_symbol_price(self, symbol: str, side: str = "BUY") -> float:
        return 100.0 if side == "BUY" else 99.9

    def get_account_balance(self) -> float:
        return 10_000.0

    def volume_from_risk_pips(self, symbol: str, risk_amount: float, sl_pips: float, pip_size: float) -> float:
        assert risk_amount > 0
        assert sl_pips > 0
        assert pip_size > 0
        return 0.01

    def volume_from_allocation(self, symbol: str, allocation: float, entry_price: float) -> float:
        assert allocation > 0
        assert entry_price > 0
        return 0.01

    def place_market_order(self, symbol: str, side: str, volume: float, sl: float, tp: float, comment: str):
        self.orders.append(
            {
                "symbol": symbol,
                "side": side,
                "volume": volume,
                "sl": sl,
                "tp": tp,
                "comment": comment,
            }
        )
        return {"retcode": 10009, "order": 1, "deal": 2}


def _settings(state_file: str) -> WebhookTradeSettings:
    return WebhookTradeSettings(
        state_file=state_file,
        max_spread_pips=100.0,
        pip_size=0.10,
        order_pct=0.01,
        use_risk_pct=True,
        risk_pct=1.0,
        sl_pips=70.0,
        tp_pips=70.0,
        stop_pips=0.7,
        magic=20260644,
    )


def _staged_settings(state_file: str) -> WebhookTradeSettings:
    return WebhookTradeSettings(
        state_file=state_file,
        max_spread_pips=100.0,
        pip_size=0.10,
        order_pct=0.01,
        use_risk_pct=True,
        risk_pct=1.0,
        sl_pips=70.0,
        tp_pips=70.0,
        stop_pips=0.7,
        magic=20260644,
        staged_exit_enabled=True,
        staged_be_trigger_pips=30.0,
        staged_be_offset_pips=5.0,
        staged_trail_pips=50.0,
        staged_tp4_open=False,
    )


def test_validate_and_normalize_alert_rejects_bad_secret():
    payload = {
        "secret": "wrong",
        "symbol": "XAUUSD",
        "timeframe": "15m",
        "side": "sell",
        "timestamp": "2026-07-16T10:00:00Z",
    }

    try:
        validate_and_normalize_alert(payload, secret="right")
        assert False, "expected validation failure"
    except ValueError as exc:
        assert "invalid secret" in str(exc)


def test_process_tradingview_signal_dedupes(tmp_path):
    connector = _FakeConnector()
    settings = _settings(str(tmp_path / "tv_state.db"))
    signal = {
        "signal_id": "abc123",
        "strategy_id": "playbit",
        "symbol": "XAUUSD",
        "timeframe": "15m",
        "side": "SELL",
        "timestamp": "2026-07-16T10:00:00Z",
    }

    first = process_tradingview_signal(connector, signal, settings)
    second = process_tradingview_signal(connector, signal, settings)

    assert first["status"] == "filled"
    assert second["status"] == "duplicate"
    assert len(connector.orders) == 1


def test_process_tradingview_signal_skips_when_position_open(tmp_path):
    connector = _FakeConnector()
    connector.position = _FakePosition(side="BUY")
    settings = _settings(str(tmp_path / "tv_state.db"))
    signal = {
        "signal_id": "def456",
        "strategy_id": "playbit",
        "symbol": "XAUUSD",
        "timeframe": "15m",
        "side": "SELL",
        "timestamp": "2026-07-16T10:15:00Z",
    }

    result = process_tradingview_signal(connector, signal, settings)

    assert result["status"] == "skipped"
    assert result["reason"] == "position_open"
    assert len(connector.orders) == 0


def test_process_tradingview_signal_stores_staged_exit_state(tmp_path):
    connector = _FakeConnector()
    settings = _staged_settings(str(tmp_path / "tv_state.db"))
    signal = {
        "signal_id": "ghi789",
        "strategy_id": "playbit",
        "symbol": "XAUUSD",
        "timeframe": "15m",
        "side": "BUY",
        "timestamp": "2026-07-16T10:30:00Z",
    }

    result = process_tradingview_signal(connector, signal, settings)

    assert result["status"] == "filled"
    assert len(connector.orders) == 1

    from trading_bot.state_store import TradingStateStore

    store = TradingStateStore(str(tmp_path / "tv_state.db"))
    position = store.get_position("XAUUSD")
    assert position is not None
    assert position["staged_exit_enabled"] is True
    assert position["tp1"] == 107.0
    assert position["tp2"] == 114.0
    assert position["tp3"] == 121.0
    assert position["tp4"] == 170.0
    assert position["moved_to_be"] is False
    assert position["trailing_active"] is False


def test_is_sdk_web_language_probe_matches_expected_path():
    assert _is_sdk_web_language_probe("/SDK/webLanguage") is True
    assert _is_sdk_web_language_probe("/SDK/webLanguage/") is True
    assert _is_sdk_web_language_probe("/SDK/other") is False


def test_should_suppress_probe_log_for_common_scanner_requests():
    assert _should_suppress_probe_log("GET / HTTP/1.1", 404) is True
    assert _should_suppress_probe_log("GET /.env HTTP/1.1", 404) is True
    assert _should_suppress_probe_log("POST /goform/formJsonAjaxReq HTTP/1.1", 404) is True
    assert _should_suppress_probe_log("POST /tradingview/webhook HTTP/1.1", 200) is False


def test_parse_allowed_source_ips_supports_ip_and_cidr():
    networks = _parse_allowed_source_ips(["94.154.43.243", "172.16.0.0/12"])
    assert _is_source_ip_allowed("94.154.43.243", networks) is True
    assert _is_source_ip_allowed("172.16.4.12", networks) is True
    assert _is_source_ip_allowed("8.8.8.8", networks) is False


def test_parse_allowed_source_ips_invalid_value_raises():
    try:
        _parse_allowed_source_ips(["not-an-ip"])
        assert False, "expected parse failure"
    except ValueError:
        assert True
