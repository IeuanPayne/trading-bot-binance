from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from loguru import logger

from .mt5_execution import _build_staged_position_state
from .mt5_connector import MT5Connector
from .state_store import TradingStateStore


@dataclass
class WebhookTradeSettings:
    state_file: str
    max_spread_pips: float
    pip_size: float
    order_pct: float
    use_risk_pct: bool
    risk_pct: float
    sl_pips: float
    tp_pips: float
    stop_pips: float
    magic: int
    staged_exit_enabled: bool = False
    staged_be_trigger_pips: float = 30.0
    staged_be_offset_pips: float = 5.0
    staged_trail_pips: float = 50.0
    staged_tp4_open: bool = False


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_side(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value in {"buy", "long"}:
        return "BUY"
    if value in {"sell", "short"}:
        return "SELL"
    raise ValueError("side must be one of: buy, sell, long, short")


def validate_and_normalize_alert(
    payload: dict[str, Any],
    secret: str,
    allowed_symbols: list[str] | None = None,
    allowed_timeframes: list[str] | None = None,
) -> dict[str, str]:
    got_secret = str(payload.get("secret") or payload.get("token") or "")
    if not secret:
        raise ValueError("TV_WEBHOOK_SECRET is not configured")
    if got_secret != secret:
        raise ValueError("unauthorized: invalid secret")

    symbol = str(payload.get("symbol") or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")

    timeframe = str(payload.get("timeframe") or payload.get("interval") or "").strip().lower()
    if not timeframe:
        timeframe = "15m"

    side = _normalize_side(payload.get("side"))
    strategy_id = str(payload.get("strategy_id") or payload.get("strategy") or "tv").strip() or "tv"
    timestamp = str(payload.get("timestamp") or payload.get("time") or _utc_now_iso()).strip() or _utc_now_iso()

    if allowed_symbols:
        whitelist = {item.upper() for item in allowed_symbols}
        if symbol not in whitelist:
            raise ValueError(f"symbol {symbol} is not allowed")

    if allowed_timeframes:
        tf_whitelist = {item.lower() for item in allowed_timeframes}
        if timeframe not in tf_whitelist:
            raise ValueError(f"timeframe {timeframe} is not allowed")

    signal_id = str(payload.get("signal_id") or "").strip()
    if not signal_id:
        signal_id = f"{strategy_id}:{symbol}:{timeframe}:{side}:{timestamp}"

    return {
        "signal_id": signal_id,
        "strategy_id": strategy_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "timestamp": timestamp,
    }


def process_tradingview_signal(
    connector: MT5Connector,
    signal: dict[str, str],
    settings: WebhookTradeSettings,
) -> dict[str, Any]:
    state_store = TradingStateStore(settings.state_file)
    symbol = signal["symbol"]
    side = signal["side"]
    signal_key = f"tv:{signal['signal_id']}"

    if state_store.is_signal_processed(symbol, signal_key):
        return {"status": "duplicate", "signal_id": signal["signal_id"]}

    position = connector.get_net_position(symbol, magic=settings.magic)
    if position is not None:
        state_store.mark_signal_processed(symbol, signal_key, {"action": "skipped", "reason": "position_open"})
        return {"status": "skipped", "reason": "position_open", "signal_id": signal["signal_id"]}

    spread_pips = connector.get_spread_pips(symbol, pip_size=settings.pip_size)
    if settings.max_spread_pips > 0 and spread_pips > settings.max_spread_pips:
        state_store.mark_signal_processed(symbol, signal_key, {"action": "skipped", "reason": "spread_too_wide"})
        return {
            "status": "skipped",
            "reason": "spread_too_wide",
            "spread_pips": spread_pips,
            "signal_id": signal["signal_id"],
        }

    entry_price = connector.get_symbol_price(symbol, side=side)
    if entry_price <= 0:
        raise RuntimeError(f"unable to obtain entry price for {symbol}")

    balance = connector.get_account_balance()
    sl_distance = settings.sl_pips * settings.pip_size if settings.sl_pips > 0 else settings.stop_pips
    tp_distance = settings.tp_pips * settings.pip_size if settings.tp_pips > 0 else sl_distance

    if settings.use_risk_pct and settings.sl_pips > 0:
        risk_amount = balance * (settings.risk_pct / 100.0)
        volume = connector.volume_from_risk_pips(
            symbol=symbol,
            risk_amount=risk_amount,
            sl_pips=settings.sl_pips,
            pip_size=settings.pip_size,
        )
    else:
        allocation = balance * settings.order_pct
        volume = connector.volume_from_allocation(symbol, allocation=allocation, entry_price=entry_price)

    if volume <= 0:
        raise RuntimeError(f"calculated volume is too small for {symbol}")

    if side == "BUY":
        sl = entry_price - sl_distance
        tp = entry_price + tp_distance
    else:
        sl = entry_price + sl_distance
        tp = entry_price - tp_distance

    position_state = {
        "side": side,
        "qty": volume,
        "entry_price": entry_price,
        "sl": sl,
        "tp": tp,
        "updated_at": signal["timestamp"],
        "source": "tradingview",
        "signal_id": signal["signal_id"],
    }

    if settings.staged_exit_enabled:
        position_state = _build_staged_position_state(
            side=side,
            entry_price=entry_price,
            sl=sl,
            qty=volume,
            pip_size=settings.pip_size,
            staged_be_trigger_pips=settings.staged_be_trigger_pips,
            staged_be_offset_pips=settings.staged_be_offset_pips,
            staged_trail_pips=settings.staged_trail_pips,
            staged_tp4_open=settings.staged_tp4_open,
        )
        position_state.update(
            {
                "updated_at": signal["timestamp"],
                "source": "tradingview",
                "signal_id": signal["signal_id"],
            }
        )
        tp = float(position_state.get("tp", tp))

    response = connector.place_market_order(
        symbol=symbol,
        side=side,
        volume=volume,
        sl=sl,
        tp=tp,
        comment=f"tv-{signal['strategy_id']}",
    )

    state_store.set_position(symbol, position_state)
    state_store.mark_signal_processed(symbol, signal_key, {"action": side.lower(), "qty": volume})

    logger.info(
        "TradingView signal executed: symbol={} side={} volume={} entry={} sl={} tp={} signal_id={}",
        symbol,
        side,
        volume,
        entry_price,
        sl,
        tp,
        signal["signal_id"],
    )

    return {
        "status": "filled",
        "symbol": symbol,
        "side": side,
        "volume": volume,
        "entry_price": entry_price,
        "sl": sl,
        "tp": tp,
        "signal_id": signal["signal_id"],
        "response": response,
    }


def start_tradingview_webhook_server(
    host: str,
    port: int,
    path: str,
    secret: str,
    connector_factory: Callable[[], MT5Connector],
    settings: WebhookTradeSettings,
    allowed_symbols: list[str] | None = None,
    allowed_timeframes: list[str] | None = None,
) -> None:
    normalized_path = path if path.startswith("/") else f"/{path}"

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != normalized_path.rstrip("/"):
                self._send_json(404, {"error": "not_found"})
                return

            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length <= 0:
                    self._send_json(400, {"error": "empty_body"})
                    return
                body = self.rfile.read(content_length)
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("JSON payload must be an object")

                signal = validate_and_normalize_alert(
                    payload,
                    secret=secret,
                    allowed_symbols=allowed_symbols,
                    allowed_timeframes=allowed_timeframes,
                )

                connector = connector_factory()
                connector.connect()
                try:
                    result = process_tradingview_signal(connector, signal, settings)
                finally:
                    connector.shutdown()

                self._send_json(200, result)
            except ValueError as exc:
                logger.warning("TradingView webhook rejected: {}", exc)
                self._send_json(400, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover - runtime integration
                logger.exception("TradingView webhook failed: {}", exc)
                self._send_json(500, {"error": str(exc)})

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            logger.debug("TVWebhook {} - {}", self.address_string(), format % args)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer((host, port), _Handler)
    logger.info("TradingView webhook server listening on http://{}:{}{}", host, port, normalized_path)
    server.serve_forever()
