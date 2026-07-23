from __future__ import annotations

import json
import ipaddress
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from loguru import logger

from .mt5_execution import _build_staged_position_state, manage_mt5_position_cycle
from .mt5_connector import MT5Connector
from .state_store import TradingStateStore


_INTERVAL_TO_PERIOD = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


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
    lot_per_500_balance: float = 0.0
    base_magic: int = 20260629
    auto_magic: bool = True
    staged_exit_enabled: bool = False
    staged_be_trigger_pips: float = 30.0
    staged_be_offset_pips: float = 5.0
    staged_trail_pips: float = 50.0
    staged_tp4_open: bool = False
    trailing_stop: bool = False
    trail_activate_r: float = 1.0
    trail_atr_period: int = 14
    trail_atr_mult: float = 1.0
    trail_min_step_atr: float = 0.2
    management_interval: str = "15m"
    management_limit: int = 500
    management_poll_seconds: float = 5.0
    allow_multiple_positions: bool = False


def _effective_magic_for_interval(interval: str, settings: WebhookTradeSettings) -> int:
    if not settings.auto_magic:
        return settings.base_magic
    return settings.base_magic + _INTERVAL_TO_PERIOD.get(str(interval).lower(), 0)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_side(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value in {"buy", "long"}:
        return "BUY"
    if value in {"sell", "short"}:
        return "SELL"
    raise ValueError("side must be one of: buy, sell, long, short")


def _is_sdk_web_language_probe(path: str) -> bool:
    normalized = path.rstrip("/")
    return normalized == "/SDK/webLanguage"


def _should_suppress_probe_log(request_line: str, status_code: int) -> bool:
    # Public webhook endpoints receive constant scanner traffic; suppress common noise.
    if status_code in (404, 400, 405, 505):
        if request_line.startswith(("GET / ", "GET /favicon.ico", "GET /robots.txt", "PRI * HTTP/2.0")):
            return True
        if "GET /." in request_line or "GET /cgi-bin/" in request_line or "GET /hudson" in request_line:
            return True
        if "GET /_next/image" in request_line or "POST /goform/" in request_line:
            return True
        if "\x16\x03\x01" in request_line:
            return True
    return False


def _parse_allowed_source_ips(allowed_source_ips: list[str] | None) -> list[ipaddress._BaseNetwork]:
    networks: list[ipaddress._BaseNetwork] = []
    for raw in allowed_source_ips or []:
        value = str(raw).strip()
        if not value:
            continue
        if "/" in value:
            networks.append(ipaddress.ip_network(value, strict=False))
        else:
            ip_obj = ipaddress.ip_address(value)
            # Host-only rule: /32 for IPv4, /128 for IPv6.
            prefix_len = 32 if ip_obj.version == 4 else 128
            networks.append(ipaddress.ip_network(f"{value}/{prefix_len}", strict=False))
    return networks


def _is_source_ip_allowed(remote_ip: str, allowed_networks: list[ipaddress._BaseNetwork]) -> bool:
    if not allowed_networks:
        return True
    try:
        addr = ipaddress.ip_address(remote_ip)
    except ValueError:
        return False
    return any(addr in network for network in allowed_networks)


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
    timeframe = str(signal.get("timeframe") or settings.management_interval).lower()
    signal_magic = _effective_magic_for_interval(timeframe, settings)
    signal_key = f"tv:{signal['signal_id']}"

    if state_store.is_signal_processed(symbol, signal_key):
        return {"status": "duplicate", "signal_id": signal["signal_id"]}

    # By default we enforce one active position per symbol in webhook mode.
    position = connector.get_net_position(symbol, magic=None)
    if position is not None and not settings.allow_multiple_positions:
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

    if settings.lot_per_500_balance > 0:
        raw_volume = settings.lot_per_500_balance * (balance / 500.0)
        normalizer = getattr(connector, "normalize_volume", None)
        volume = float(normalizer(symbol, raw_volume)) if callable(normalizer) else raw_volume
    else:
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
        "timeframe": timeframe,
        "magic": signal_magic,
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
                "timeframe": timeframe,
                "magic": signal_magic,
                "updated_at": signal["timestamp"],
                "source": "tradingview",
                "strategy_id": signal["strategy_id"],
                "signal_id": signal["signal_id"],
            }
        )
        tp = _safe_float(position_state.get("tp", tp), default=tp)

    response = connector.place_market_order(
        symbol=symbol,
        side=side,
        volume=volume,
        sl=sl,
        tp=tp,
        comment=f"tv-{signal['strategy_id']}-{timeframe}",
    )

    state_store.set_position(symbol, position_state)
    state_store.mark_signal_processed(symbol, signal_key, {"action": side.lower(), "qty": volume})

    logger.info(
        "TradingView signal executed: symbol={} timeframe={} side={} volume={} entry={} sl={} tp={} strategy_id={} signal_id={} magic={}",
        symbol,
        timeframe,
        side,
        volume,
        entry_price,
        sl,
        tp,
        signal["strategy_id"],
        signal["signal_id"],
        signal_magic,
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


def _run_position_management_pass(
    connector_factory: Callable[[], MT5Connector],
    settings: WebhookTradeSettings,
) -> int:
    state_store = TradingStateStore(settings.state_file)
    positions = (state_store.load().get("positions") or {}).keys()
    managed_count = 0

    for symbol in positions:
        tracked = state_store.get_position(symbol) or {}
        tracked_timeframe = str(tracked.get("timeframe") or settings.management_interval).lower()
        tracked_magic = int(tracked.get("magic") or _effective_magic_for_interval(tracked_timeframe, settings))

        connector = connector_factory()
        connector.connect()
        try:
            manage_mt5_position_cycle(
                connector=connector,
                symbol=symbol,
                interval=tracked_timeframe,
                limit=settings.management_limit,
                pip_size=settings.pip_size,
                trailing_stop=settings.trailing_stop,
                trail_activate_r=settings.trail_activate_r,
                trail_atr_period=settings.trail_atr_period,
                trail_atr_mult=settings.trail_atr_mult,
                trail_min_step_atr=settings.trail_min_step_atr,
                staged_exit_enabled=settings.staged_exit_enabled,
                staged_be_trigger_pips=settings.staged_be_trigger_pips,
                staged_be_offset_pips=settings.staged_be_offset_pips,
                staged_trail_pips=settings.staged_trail_pips,
                staged_tp4_open=settings.staged_tp4_open,
                magic=tracked_magic,
                state_file=settings.state_file,
            )
            managed_count += 1
        finally:
            connector.shutdown()

    return managed_count


def start_tradingview_webhook_server(
    host: str,
    port: int,
    path: str,
    secret: str,
    connector_factory: Callable[[], MT5Connector],
    settings: WebhookTradeSettings,
    allowed_symbols: list[str] | None = None,
    allowed_timeframes: list[str] | None = None,
    allowed_source_ips: list[str] | None = None,
) -> None:
    normalized_path = path if path.startswith("/") else f"/{path}"
    allowed_networks = _parse_allowed_source_ips(allowed_source_ips)

    def _management_loop() -> None:
        poll_seconds = max(1.0, settings.management_poll_seconds)
        while True:
            try:
                managed_count = _run_position_management_pass(connector_factory=connector_factory, settings=settings)
                if managed_count > 0:
                    logger.debug("TVWebhook manager pass complete: managed_positions={}", managed_count)
            except Exception as exc:
                logger.warning("TVWebhook manager loop failed: {}", exc)
            time.sleep(poll_seconds)

    class _WebhookHTTPServer(ThreadingHTTPServer):
        def handle_error(self, request, client_address) -> None:  # type: ignore[override]
            exc_type, exc, _ = sys.exc_info()
            if exc_type is ConnectionResetError or isinstance(exc, ConnectionResetError):
                logger.debug("TVWebhook {} - connection reset by peer", client_address[0])
                return
            super().handle_error(request, client_address)

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") in ("", "/"):
                self._send_json(200, {"status": "ok"})
                return
            if _is_sdk_web_language_probe(self.path):
                self._send_json(200, {"language": "en"})
                return
            self._send_json(404, {"error": "not_found"})

        def do_HEAD(self) -> None:  # noqa: N802
            if self.path.rstrip("/") in ("", "/"):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            remote_ip = self.client_address[0]
            if not _is_source_ip_allowed(remote_ip, allowed_networks):
                logger.warning(
                    "TVWebhook rejected: outcome=rejected reason=source_ip_not_allowed ip={} path={}",
                    remote_ip,
                    self.path,
                )
                self._send_json(403, {"error": "forbidden_source_ip"})
                return

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

                outcome = str(result.get("status", "unknown"))
                reason = str(result.get("reason", ""))
                logger.info(
                    "TVWebhook outcome=accepted status={} symbol={} timeframe={} side={} signal_id={} ip={} reason={}",
                    outcome,
                    signal.get("symbol", ""),
                    signal.get("timeframe", ""),
                    signal.get("side", ""),
                    signal.get("signal_id", ""),
                    remote_ip,
                    reason,
                )
                self._send_json(200, result)
            except ValueError as exc:
                logger.warning("TradingView webhook rejected: {}", exc)
                logger.warning("TVWebhook outcome=rejected reason={} ip={} path={}", str(exc), remote_ip, self.path)
                self._send_json(400, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover - runtime integration
                logger.exception("TradingView webhook failed: {}", exc)
                logger.error("TVWebhook outcome=rejected reason=internal_error ip={} path={}", remote_ip, self.path)
                self._send_json(500, {"error": str(exc)})

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            message = format % args
            parts = message.rsplit(" ", 1)
            status_code = 0
            if len(parts) == 2 and parts[1].isdigit():
                status_code = int(parts[1])
            request_line = self.requestline or ""
            if _should_suppress_probe_log(request_line, status_code):
                return
            logger.debug("TVWebhook {} - {}", self.address_string(), message)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    manager_thread = threading.Thread(target=_management_loop, name="tv-webhook-position-manager", daemon=True)
    manager_thread.start()

    server = _WebhookHTTPServer((host, port), _Handler)
    logger.info("TradingView webhook server listening on http://{}:{}{}", host, port, normalized_path)
    server.serve_forever()
