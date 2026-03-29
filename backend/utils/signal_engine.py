from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque, Dict, Optional


@dataclass
class QuoteSnapshot:
    bid: float
    ask: float
    ts: int


class SignalEngine:
    def __init__(self, big_print_threshold: float = 10_000_000, max_recent_signals: int = 500):
        self.big_print_threshold = big_print_threshold
        self.latest_nbbo: Dict[str, QuoteSnapshot] = {}
        self.recent_signals: Deque[dict] = deque(maxlen=max_recent_signals)

    def on_quote(self, symbol: str, bid: float, ask: float, ts: int) -> None:
        if not symbol or bid <= 0 or ask <= 0:
            return
        self.latest_nbbo[symbol] = QuoteSnapshot(bid=bid, ask=ask, ts=ts)

    def on_trade(self, symbol: str, price: float, size: float, ts: int, source: str = "polygon") -> Optional[dict]:
        if not symbol or price <= 0 or size <= 0:
            return None

        notional = float(price) * float(size)
        if notional < self.big_print_threshold:
            return None

        side = self._classify_side(symbol=symbol, trade_price=float(price))
        signal = {
            "type": "BIG_PRINT",
            "symbol": symbol,
            "price": float(price),
            "size": float(size),
            "notional": notional,
            "side": side,
            "ts": int(ts) if ts else self._now_ms(),
            "source": source,
            "meta": {},
        }
        self.recent_signals.append(signal)
        return signal

    def _classify_side(self, symbol: str, trade_price: float) -> str:
        quote = self.latest_nbbo.get(symbol)
        if quote is None:
            return "unknown"
        if trade_price >= quote.ask:
            return "buy"
        if trade_price <= quote.bid:
            return "sell"
        return "mid"

    @staticmethod
    def _now_ms() -> int:
        return int(datetime.now(tz=timezone.utc).timestamp() * 1000)
