from __future__ import annotations

from typing import Any
from uuid import uuid4

import config
from trading.store import mutate_state, read_state, utc_now


class PaperBrokerError(ValueError):
    pass


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    return num if num == num else default


def _round_money(value: float) -> float:
    return round(float(value), 2)


def _round_qty(value: float) -> float:
    return round(float(value), 8)


def _positions_list(positions: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for symbol, raw in sorted((positions or {}).items()):
        qty = _safe_float(raw.get("qty"))
        avg_price = _safe_float(raw.get("avgPrice"))
        if abs(qty) <= 0.00000001:
            continue
        rows.append(
            {
                "symbol": symbol,
                "qty": _round_qty(qty),
                "avgPrice": _round_money(avg_price),
                "marketValue": _round_money(qty * avg_price),
                "assetClass": raw.get("assetClass") or "stock",
                "updatedAt": raw.get("updatedAt"),
            }
        )
    return rows


def get_account_snapshot() -> dict[str, Any]:
    state = read_state()
    positions = _positions_list(state.get("positions") or {})
    invested = sum(_safe_float(row.get("marketValue")) for row in positions)
    cash = _safe_float(state.get("cash"), float(config.TRADING_STARTING_CASH))
    return {
        "mode": "paper",
        "cash": _round_money(cash),
        "buyingPower": _round_money(_safe_float(state.get("buyingPower"), cash)),
        "portfolioValue": _round_money(cash + invested),
        "positionCount": len(positions),
        "openOrderCount": len(
            [
                order
                for order in state.get("orders", [])
                if order.get("status") in {"accepted", "pending_new", "partially_filled"}
            ]
        ),
        "updatedAt": state.get("updatedAt"),
    }


def list_positions() -> list[dict[str, Any]]:
    state = read_state()
    return _positions_list(state.get("positions") or {})


def list_orders(limit: int = 100) -> list[dict[str, Any]]:
    state = read_state()
    orders = list(state.get("orders") or [])
    return orders[-max(1, min(int(limit), 500)) :][::-1]


def _apply_fill(state: dict[str, Any], order: dict[str, Any], fill_price: float) -> None:
    symbol = order["symbol"]
    side = order["side"]
    qty = _safe_float(order["qty"])
    notional = _round_money(qty * fill_price)
    cash = _safe_float(state.get("cash"), float(config.TRADING_STARTING_CASH))
    positions = state.setdefault("positions", {})
    position = positions.get(symbol) or {
        "symbol": symbol,
        "qty": 0.0,
        "avgPrice": 0.0,
        "assetClass": order.get("assetClass") or "stock",
    }
    current_qty = _safe_float(position.get("qty"))
    current_avg = _safe_float(position.get("avgPrice"))

    if side == "buy":
        if notional > cash:
            raise PaperBrokerError("Insufficient paper buying power.")
        new_qty = current_qty + qty
        new_avg = ((current_qty * current_avg) + notional) / new_qty if new_qty else 0.0
        position["qty"] = _round_qty(new_qty)
        position["avgPrice"] = _round_money(new_avg)
        cash -= notional
    else:
        if qty > current_qty:
            raise PaperBrokerError("Paper account does not hold enough shares to sell.")
        new_qty = current_qty - qty
        if new_qty <= 0.00000001:
            positions.pop(symbol, None)
        else:
            position["qty"] = _round_qty(new_qty)
            position["avgPrice"] = _round_money(current_avg)
        cash += notional

    if symbol in positions or side == "buy":
        position["updatedAt"] = utc_now()
        positions[symbol] = position

    state["cash"] = _round_money(cash)
    state["buyingPower"] = _round_money(cash)
    order["status"] = "filled"
    order["filledQty"] = _round_qty(qty)
    order["filledAvgPrice"] = _round_money(fill_price)
    order["filledAt"] = utc_now()


def _can_fill_limit(order: dict[str, Any], reference_price: float) -> bool:
    limit_price = _safe_float(order.get("limitPrice"))
    if limit_price <= 0 or reference_price <= 0:
        return False
    if order.get("side") == "buy":
        return reference_price <= limit_price
    return reference_price >= limit_price


def submit_order(order: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    record = {
        "id": f"paper-{uuid4().hex[:12]}",
        "clientOrderId": order.get("clientOrderId") or f"trax-{uuid4().hex[:12]}",
        "symbol": order["symbol"],
        "assetClass": order.get("assetClass", "stock"),
        "side": order["side"],
        "type": order["type"],
        "timeInForce": order["timeInForce"],
        "qty": _round_qty(order["qty"]),
        "limitPrice": _round_money(order.get("limitPrice")) if order.get("limitPrice") else None,
        "estimatedPrice": _round_money(order.get("estimatedPrice")) if order.get("estimatedPrice") else None,
        "status": "accepted",
        "filledQty": 0.0,
        "filledAvgPrice": None,
        "submittedAt": now,
        "updatedAt": now,
        "source": order.get("source") or "manual",
    }

    def _mutate(state: dict[str, Any]) -> dict[str, Any]:
        reference_price = _safe_float(record.get("estimatedPrice"))
        should_fill = False
        if config.TRADING_PAPER_AUTO_FILL:
            if record["type"] == "market":
                should_fill = reference_price > 0
            elif record["type"] == "limit":
                should_fill = _can_fill_limit(record, reference_price)

        if should_fill:
            _apply_fill(state, record, reference_price)
        state.setdefault("orders", []).append(record)
        return record

    return mutate_state(_mutate)


def cancel_order(order_id: str) -> dict[str, Any]:
    order_id = str(order_id or "").strip()
    if not order_id:
        raise PaperBrokerError("Order id is required.")

    def _mutate(state: dict[str, Any]) -> dict[str, Any]:
        for order in state.get("orders", []):
            if str(order.get("id")) != order_id:
                continue
            if order.get("status") in {"filled", "canceled", "rejected"}:
                raise PaperBrokerError(f"Cannot cancel an order with status {order.get('status')}.")
            order["status"] = "canceled"
            order["canceledAt"] = utc_now()
            order["updatedAt"] = order["canceledAt"]
            return order
        raise PaperBrokerError("Order not found.")

    return mutate_state(_mutate)
