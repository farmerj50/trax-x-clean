from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable, Optional

import websocket

from .signal_engine import SignalEngine


logger = logging.getLogger(__name__)


class PolygonMarketStream:
    def __init__(
        self,
        ws_url: str,
        api_key: str,
        engine: SignalEngine,
        emit_signal: Callable[[dict], None],
        subscribe_params: str = "T.*,Q.*",
    ):
        self.ws_url = ws_url
        self.api_key = api_key
        self.engine = engine
        self.emit_signal = emit_signal
        self.subscribe_params = subscribe_params
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._authenticated = False
        self._subscribed = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="polygon-market-stream")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        backoff = 2
        while not self._stop_event.is_set():
            self._authenticated = False
            self._subscribed = False
            ws = websocket.WebSocketApp(
                self.ws_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            ws.run_forever()
            if self._stop_event.is_set():
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)

    def _on_open(self, ws) -> None:
        ws.send(json.dumps({"action": "auth", "params": self.api_key}))
        logger.info("Polygon market stream opened; awaiting auth for subscribe=%s", self.subscribe_params)

    def _on_message(self, ws, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("Invalid Polygon payload (non-JSON)")
            return

        if not isinstance(data, list):
            return

        for event in data:
            ev = event.get("ev")
            if ev == "status":
                status = str(event.get("status") or "").lower()
                logger.info(
                    "Polygon market stream status: status=%s message=%s",
                    event.get("status"),
                    event.get("message"),
                )
                if status == "auth_success" and not self._subscribed:
                    ws.send(json.dumps({"action": "subscribe", "params": self.subscribe_params}))
                    self._authenticated = True
                    self._subscribed = True
                    logger.info("Polygon market stream subscribed: %s", self.subscribe_params)
                elif status in {"auth_failed", "error"}:
                    logger.error("Polygon market stream rejected auth/subscribe: %s", event)
                continue
            if ev == "Q":
                symbol = event.get("sym")
                bid = event.get("bp")
                ask = event.get("ap")
                ts = event.get("t", int(time.time() * 1000))
                if symbol and bid and ask:
                    self.engine.on_quote(symbol=symbol, bid=float(bid), ask=float(ask), ts=int(ts))
            elif ev == "T":
                symbol = event.get("sym")
                price = event.get("p")
                size = event.get("s")
                ts = event.get("t", int(time.time() * 1000))
                if symbol and price and size:
                    signal = self.engine.on_trade(
                        symbol=symbol,
                        price=float(price),
                        size=float(size),
                        ts=int(ts),
                        source="polygon",
                    )
                    if signal:
                        self.emit_signal(signal)

    @staticmethod
    def _on_error(ws, error) -> None:
        logger.warning("Polygon market stream error: %s", error)

    @staticmethod
    def _on_close(ws, close_status_code, close_msg) -> None:
        logger.info("Polygon market stream closed: %s %s", close_status_code, close_msg)
