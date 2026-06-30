import json
from pathlib import Path
from typing import Any, Dict, Optional


class TradingStateStore:
    """Simple JSON-backed store for order/position state across restarts."""

    def __init__(self, filepath: str = "trading_state.json") -> None:
        self.path = Path(filepath)

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"positions": {}, "signals": {}}
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("positions", {})
        data.setdefault("signals", {})
        return data

    def save(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        tmp_path.replace(self.path)

    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        data = self.load()
        return data["positions"].get(symbol)

    def set_position(self, symbol: str, position: Dict[str, Any]) -> None:
        data = self.load()
        data["positions"][symbol] = position
        self.save(data)

    def clear_position(self, symbol: str) -> None:
        data = self.load()
        data["positions"].pop(symbol, None)
        self.save(data)

    def is_signal_processed(self, symbol: str, signal_id: str) -> bool:
        data = self.load()
        return signal_id in data["signals"].get(symbol, {})

    def mark_signal_processed(self, symbol: str, signal_id: str, metadata: Dict[str, Any]) -> None:
        data = self.load()
        symbol_signals = data["signals"].setdefault(symbol, {})
        symbol_signals[signal_id] = metadata
        self.save(data)
