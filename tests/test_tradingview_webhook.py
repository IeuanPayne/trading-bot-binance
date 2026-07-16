from __future__ import annotations

from dataclasses import dataclass

from trading_bot.tradingview_webhook import (
    WebhookTradeSettings,
    process_tradingview_signal,
    validate_and_normalize_alert,
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
