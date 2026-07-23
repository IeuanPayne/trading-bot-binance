import json
import sqlite3
from pathlib import Path
from typing import Any


class TradingStateStore:
    """SQLite-backed store for order/position state across restarts."""

    def __init__(self, filepath: str = "trading_state.db") -> None:
        self.path = Path(filepath)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signals (
                    symbol TEXT NOT NULL,
                    signal_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (symbol, signal_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_state (
                    state_key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def load(self) -> dict[str, Any]:
        data: dict[str, Any] = {"positions": {}, "signals": {}}
        with self._connect() as conn:
            for symbol, payload in conn.execute("SELECT symbol, payload FROM positions"):
                data["positions"][symbol] = json.loads(payload)
            for symbol, signal_id, payload in conn.execute("SELECT symbol, signal_id, payload FROM signals"):
                symbol_signals = data["signals"].setdefault(symbol, {})
                symbol_signals[signal_id] = json.loads(payload)
        return data

    def save(self, data: dict[str, Any]) -> None:
        positions = data.get("positions", {})
        signals = data.get("signals", {})
        with self._connect() as conn:
            conn.execute("DELETE FROM positions")
            conn.execute("DELETE FROM signals")
            for symbol, payload in positions.items():
                conn.execute(
                    "INSERT INTO positions(symbol, payload) VALUES(?, ?)",
                    (symbol, json.dumps(payload, sort_keys=True)),
                )
            for symbol, signal_map in signals.items():
                for signal_id, payload in signal_map.items():
                    conn.execute(
                        "INSERT INTO signals(symbol, signal_id, payload) VALUES(?, ?, ?)",
                        (symbol, signal_id, json.dumps(payload, sort_keys=True)),
                    )
            conn.commit()

    def get_position(self, symbol: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM positions WHERE symbol = ?", (symbol,)).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def set_position(self, symbol: str, position: dict[str, Any]) -> None:
        payload = json.dumps(position, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO positions(symbol, payload) VALUES(?, ?) ON CONFLICT(symbol) DO UPDATE SET payload=excluded.payload",
                (symbol, payload),
            )
            conn.commit()

    def clear_position(self, symbol: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
            conn.commit()

    def is_signal_processed(self, symbol: str, signal_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM signals WHERE symbol = ? AND signal_id = ?",
                (symbol, signal_id),
            ).fetchone()
        return row is not None

    def mark_signal_processed(self, symbol: str, signal_id: str, metadata: dict[str, Any]) -> None:
        payload = json.dumps(metadata, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO signals(symbol, signal_id, payload) VALUES(?, ?, ?) ON CONFLICT(symbol, signal_id) DO UPDATE SET payload=excluded.payload",
                (symbol, signal_id, payload),
            )
            conn.commit()

    def get_runtime_state(self, key: str, default: dict[str, Any] | None = None) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM runtime_state WHERE state_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return default
        return json.loads(row[0])

    def set_runtime_state(self, key: str, value: dict[str, Any]) -> None:
        payload = json.dumps(value, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runtime_state(state_key, payload) VALUES(?, ?) ON CONFLICT(state_key) DO UPDATE SET payload=excluded.payload",
                (key, payload),
            )
            conn.commit()
