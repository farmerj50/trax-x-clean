from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable

import config


STATE_LOCK = RLock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _state_path() -> Path:
    return Path(config.TRADING_STATE_PATH)


def _default_state() -> dict[str, Any]:
    now = utc_now()
    starting_cash = float(config.TRADING_STARTING_CASH)
    return {
        "cash": starting_cash,
        "buyingPower": starting_cash,
        "positions": {},
        "orders": [],
        "brokerAccounts": {
            "alpaca": {
                "selectedAccountId": "",
                "selectedAt": None,
            }
        },
        "createdAt": now,
        "updatedAt": now,
    }


def load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return _default_state()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_state()

    if not isinstance(payload, dict):
        return _default_state()

    state = _default_state()
    state.update(payload)
    if not isinstance(state.get("positions"), dict):
        state["positions"] = {}
    if not isinstance(state.get("orders"), list):
        state["orders"] = []
    if not isinstance(state.get("brokerAccounts"), dict):
        state["brokerAccounts"] = {"alpaca": {"selectedAccountId": "", "selectedAt": None}}
    if not isinstance(state["brokerAccounts"].get("alpaca"), dict):
        state["brokerAccounts"]["alpaca"] = {"selectedAccountId": "", "selectedAt": None}
    return state


def save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updatedAt"] = utc_now()
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")
    temp_path.replace(path)


def read_state() -> dict[str, Any]:
    with STATE_LOCK:
        return copy.deepcopy(load_state())


def mutate_state(mutator: Callable[[dict[str, Any]], Any]) -> Any:
    with STATE_LOCK:
        state = load_state()
        result = mutator(state)
        save_state(state)
        return result
