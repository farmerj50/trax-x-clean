from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Deque, Optional, Set

import requests


logger = logging.getLogger(__name__)


class IntrinioOptionsFlowPoller:
    def __init__(
        self,
        api_key: str,
        endpoint_url: str,
        poll_seconds: int,
        min_premium: float,
        emit_signal: Callable[[dict], None],
        max_items: int = 100,
    ):
        self.api_key = api_key
        self.endpoint_url = endpoint_url
        self.poll_seconds = max(5, int(poll_seconds))
        self.min_premium = float(min_premium)
        self.max_items = max(1, int(max_items))
        self.emit_signal = emit_signal
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._seen_ids: Set[str] = set()
        self._seen_order: Deque[str] = deque(maxlen=2000)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="intrinio-options-flow")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                logger.warning("Options flow poll failed: %s", exc)
            self._stop_event.wait(self.poll_seconds)

    def _poll_once(self) -> None:
        params = {
            "api_key": self.api_key,
            "page_size": self.max_items,
        }
        response = requests.get(self.endpoint_url, params=params, timeout=15)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("unusual_activity") or payload.get("data") or payload.get("results") or []
        if not isinstance(rows, list):
            return

        for row in rows:
            signal = self._to_signal(row)
            if signal is None:
                continue
            dedupe_id = signal.get("meta", {}).get("event_id")
            if dedupe_id and dedupe_id in self._seen_ids:
                continue
            if dedupe_id:
                self._track_seen_id(dedupe_id)
            self.emit_signal(signal)

    def _to_signal(self, row: dict) -> Optional[dict]:
        premium = self._get_float(row, "premium")
        contracts = self._get_float(row, "size", "contracts", "quantity", default=0)
        if premium is None:
            option_price = self._get_float(row, "price", "option_price", default=0) or 0
            contract_size = self._get_float(row, "contract_size", default=100) or 100
            premium = option_price * contracts * contract_size
        if premium is None or premium < self.min_premium:
            return None

        symbol = (
            row.get("underlying_symbol")
            or row.get("underlying")
            or row.get("symbol")
            or row.get("ticker")
            or "UNKNOWN"
        )
        option_symbol = row.get("option_symbol") or row.get("symbol") or row.get("ticker")
        side = (row.get("sentiment") or row.get("side") or "unknown").lower()
        ts = self._to_epoch_ms(row.get("timestamp") or row.get("trade_time") or row.get("time"))
        event_id = (
            str(row.get("id") or row.get("activity_id") or row.get("trade_id") or "")
            or f"{option_symbol}:{ts}:{premium}"
        )

        return {
            "type": "BIG_OPTIONS_FLOW",
            "symbol": str(symbol).upper(),
            "price": self._get_float(row, "price", "option_price", default=0) or 0,
            "size": contracts,
            "notional": float(premium),
            "side": side,
            "ts": ts,
            "source": "intrinio",
            "meta": {
                "event_id": event_id,
                "option_symbol": option_symbol,
                "raw_type": row.get("type"),
                "expiration": row.get("expiration"),
                "strike": row.get("strike"),
            },
        }

    @staticmethod
    def _get_float(row: dict, *keys: str, default=None):
        for key in keys:
            value = row.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return default

    @staticmethod
    def _to_epoch_ms(value) -> int:
        if value is None:
            return int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        if isinstance(value, (int, float)):
            if value > 1_000_000_000_000:
                return int(value)
            return int(float(value) * 1000)
        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return int(dt.timestamp() * 1000)
            except ValueError:
                return int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        return int(datetime.now(tz=timezone.utc).timestamp() * 1000)

    def _track_seen_id(self, dedupe_id: str) -> None:
        if dedupe_id in self._seen_ids:
            return
        if len(self._seen_order) == self._seen_order.maxlen:
            oldest = self._seen_order[0]
            self._seen_ids.discard(oldest)
        self._seen_order.append(dedupe_id)
        self._seen_ids.add(dedupe_id)
