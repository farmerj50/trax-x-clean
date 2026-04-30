from __future__ import annotations

import re
from typing import Any, Optional

from dotenv import dotenv_values

import config
from trading import alpaca_broker, paper_broker
from trading.store import mutate_state, read_state, utc_now


SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")
SUPPORTED_ASSET_CLASSES = {"stock", "crypto"}
SUPPORTED_SIDES = {"buy", "sell"}
SUPPORTED_ORDER_TYPES = {"market", "limit"}
SUPPORTED_TIME_IN_FORCE = {"day", "gtc", "ioc"}
SUPPORTED_PROVIDERS = {"paper", "alpaca_broker"}
ENV_DIAGNOSTIC_KEYS = (
    "ENABLE_TRADING",
    "TRADING_PROVIDER",
    "TRADING_MODE",
    "ALPACA_BROKER_ENABLED",
    "ALPACA_BROKER_API_KEY",
    "ALPACA_BROKER_API_SECRET",
    "ALPACA_BROKER_ACCOUNT_ID",
    "ALPACA_BROKER_ALLOW_ORDERS",
    "ALPACA_BROKER_ENV",
    "ALPACA_BROKER_API_BASE",
)


class TradingProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _provider_name() -> str:
    provider = str(config.TRADING_PROVIDER or "paper").strip().lower()
    return provider if provider in SUPPORTED_PROVIDERS else "unsupported"


def _active_broker():
    provider = _provider_name()
    if provider == "paper":
        return paper_broker
    if provider == "alpaca_broker":
        return alpaca_broker
    raise TradingProviderError(f"Unsupported trading provider: {config.TRADING_PROVIDER}", 400)


def _presence_status(value: Any) -> dict[str, Any]:
    clean = str(value or "").strip()
    return {
        "present": bool(clean),
        "blank": not bool(clean),
        "length": len(clean),
    }


def _env_file_status(path) -> dict[str, Any]:
    exists = path.exists()
    parsed = {}
    error = None
    if exists:
        try:
            parsed = dotenv_values(path)
        except Exception as exc:
            error = str(exc)

    return {
        "path": str(path),
        "exists": exists,
        "error": error,
        "keys": {
            key: {
                "defined": key in parsed,
                "blank": not bool(str(parsed.get(key) or "").strip()) if key in parsed else True,
                "length": len(str(parsed.get(key) or "").strip()) if key in parsed else 0,
            }
            for key in ENV_DIAGNOSTIC_KEYS
        },
    }


def env_diagnostics() -> dict[str, Any]:
    api_status = alpaca_broker.api_configuration_status()
    full_status = alpaca_broker.configuration_status()

    return {
        "ok": True,
        "loadedAt": utc_now(),
        "envFiles": {
            "backend": _env_file_status(config.BASE_DIR / ".env"),
            "root": _env_file_status(config.PROJECT_ROOT / ".env"),
        },
        "runtime": {
            "ENABLE_TRADING": bool(config.ENABLE_TRADING),
            "TRADING_PROVIDER": config.TRADING_PROVIDER,
            "TRADING_MODE": config.TRADING_MODE,
            "ALPACA_BROKER_ENABLED": bool(config.ALPACA_BROKER_ENABLED),
            "ALPACA_BROKER_API_KEY": _presence_status(config.ALPACA_BROKER_API_KEY),
            "ALPACA_BROKER_API_SECRET": _presence_status(config.ALPACA_BROKER_API_SECRET),
            "ALPACA_BROKER_ACCOUNT_ID": _presence_status(config.ALPACA_BROKER_ACCOUNT_ID),
            "ALPACA_BROKER_ALLOW_ORDERS": bool(config.ALPACA_BROKER_ALLOW_ORDERS),
            "ALPACA_BROKER_ENV": config.ALPACA_BROKER_ENV,
            "ALPACA_BROKER_API_BASE": _presence_status(config.ALPACA_BROKER_API_BASE),
        },
        "alpacaApiConfigured": bool(api_status["configured"]),
        "alpacaTradingConfigured": bool(full_status["configured"]),
        "apiMissing": api_status["missing"],
        "tradingMissing": full_status["missing"],
    }


def execution_readiness() -> dict[str, Any]:
    status = trading_status()
    provider = status["provider"]
    api_status = alpaca_broker.api_configuration_status()
    full_status = alpaca_broker.configuration_status()
    selected = get_selected_alpaca_account()

    checks = [
        {
            "key": "trading_enabled",
            "label": "Trading Enabled",
            "state": "ready" if config.ENABLE_TRADING else "blocked",
            "message": "ENABLE_TRADING is enabled."
            if config.ENABLE_TRADING
            else "Set ENABLE_TRADING=true in backend/.env.",
        },
        {
            "key": "paper_provider",
            "label": "Paper Provider",
            "state": "ready" if provider == "paper" and config.TRADING_MODE == "paper" else "pending",
            "message": "Paper trading is ready."
            if provider == "paper" and config.TRADING_MODE == "paper"
            else "Paper remains the fallback execution provider.",
        },
        {
            "key": "alpaca_provider_selected",
            "label": "Alpaca Provider Selected",
            "state": "ready" if provider == "alpaca_broker" else "pending",
            "message": "TRADING_PROVIDER=alpaca_broker is active."
            if provider == "alpaca_broker"
            else "Set TRADING_PROVIDER=alpaca_broker when sandbox routing is ready.",
        },
        {
            "key": "alpaca_api_credentials",
            "label": "Alpaca API Credentials",
            "state": "ready" if api_status["configured"] else "blocked",
            "message": "Alpaca Broker API credentials are loaded."
            if api_status["configured"]
            else f"Missing: {', '.join(api_status['missing'])}.",
        },
        {
            "key": "alpaca_account",
            "label": "Alpaca Account",
            "state": "ready" if full_status["accountIdConfigured"] else "blocked",
            "message": f"Account ID source: {full_status['accountIdSource']}."
            if full_status["accountIdConfigured"]
            else "Load accounts and select one, or set ALPACA_BROKER_ACCOUNT_ID.",
        },
        {
            "key": "provider_connection",
            "label": "Provider Connection",
            "state": "pending",
            "message": "Use Test Provider after env changes or account selection.",
        },
        {
            "key": "order_submission_lock",
            "label": "Order Submission Lock",
            "state": "ready" if config.ALPACA_BROKER_ALLOW_ORDERS else "locked",
            "message": "Sandbox order submission is unlocked."
            if config.ALPACA_BROKER_ALLOW_ORDERS
            else "Orders stay blocked until ALPACA_BROKER_ALLOW_ORDERS=true.",
        },
    ]

    if not config.ENABLE_TRADING:
        next_action = "Set ENABLE_TRADING=true in backend/.env, save it, then restart Flask."
    elif not api_status["configured"]:
        next_action = "Fill and save the Alpaca Broker API settings in backend/.env, then restart Flask."
    elif not full_status["accountIdConfigured"]:
        next_action = "Click Load Accounts, then Use on the sandbox account to select the routing account."
    elif provider != "alpaca_broker":
        next_action = "Set TRADING_PROVIDER=alpaca_broker and restart Flask when you want sandbox routing active."
    elif not config.ALPACA_BROKER_ALLOW_ORDERS:
        next_action = "Run Test Provider and Preview Order; unlock sandbox order submission only after that passes."
    elif not status["orderSubmissionEnabled"]:
        next_action = status["message"]
    else:
        next_action = "Sandbox broker submission is ready."

    return {
        "ok": True,
        "provider": provider,
        "mode": config.TRADING_MODE,
        "paperReady": bool(config.ENABLE_TRADING and provider == "paper" and config.TRADING_MODE == "paper"),
        "alpacaDiscoveryReady": bool(api_status["configured"]),
        "alpacaRoutingReady": bool(provider == "alpaca_broker" and full_status["configured"]),
        "orderSubmissionReady": bool(status["orderSubmissionEnabled"]),
        "orderSubmissionLocked": bool(status["orderSubmissionLocked"]),
        "activeAccountIdSource": selected["activeAccountIdSource"],
        "selectedAccountIdPresent": bool(selected["selectedAccountId"]),
        "envAccountIdConfigured": bool(selected["envAccountIdConfigured"]),
        "nextAction": next_action,
        "checks": checks,
    }


def trading_status() -> dict[str, Any]:
    enabled = bool(config.ENABLE_TRADING)
    provider = _provider_name()
    alpaca_status = alpaca_broker.configuration_status()
    order_submission_enabled = False

    if provider == "paper":
        supported = config.TRADING_MODE == "paper"
        order_submission_enabled = bool(enabled and supported)
        message = (
            "Paper trading is enabled."
            if enabled and supported
            else "Trading is disabled. Set ENABLE_TRADING=true and TRADING_MODE=paper to use paper trading."
        )
    elif provider == "alpaca_broker":
        supported = alpaca_status["configured"]
        order_submission_enabled = bool(enabled and supported and config.ALPACA_BROKER_ALLOW_ORDERS)
        if not enabled:
            message = "Trading is disabled by configuration."
        elif not supported:
            message = f"Alpaca Broker provider is missing: {', '.join(alpaca_status['missing'])}."
        elif not config.ALPACA_BROKER_ALLOW_ORDERS:
            message = "Alpaca Broker sandbox is configured, but order submission is locked."
        else:
            message = "Alpaca Broker sandbox provider is configured and order submission is unlocked."
    else:
        supported = False
        message = f"Unsupported trading provider: {config.TRADING_PROVIDER}."

    return {
        "enabled": enabled,
        "mode": config.TRADING_MODE,
        "provider": provider,
        "supportedMode": supported,
        "liveTradingAvailable": False,
        "brokerConfigured": bool(provider == "alpaca_broker" and alpaca_status["configured"]),
        "paperAutoFill": bool(config.TRADING_PAPER_AUTO_FILL),
        "orderSubmissionEnabled": order_submission_enabled,
        "orderSubmissionLocked": bool(provider == "alpaca_broker" and not config.ALPACA_BROKER_ALLOW_ORDERS),
        "alpaca": alpaca_status,
        "message": message,
    }


def _require_enabled() -> None:
    if not config.ENABLE_TRADING:
        raise PermissionError("Trading is disabled by configuration.")
    provider = _provider_name()
    if provider == "paper" and config.TRADING_MODE != "paper":
        raise PermissionError("Only paper trading mode is implemented.")
    if provider == "alpaca_broker" and not alpaca_broker.is_configured():
        status = alpaca_broker.configuration_status()
        raise PermissionError(f"Alpaca Broker provider is not configured: {', '.join(status['missing'])}.")
    if provider == "unsupported":
        raise PermissionError(f"Unsupported trading provider: {config.TRADING_PROVIDER}.")


def _require_order_submission_allowed() -> None:
    provider = _provider_name()
    if provider == "alpaca_broker" and not config.ALPACA_BROKER_ALLOW_ORDERS:
        raise PermissionError(
            "Alpaca Broker order submission is locked. Set ALPACA_BROKER_ALLOW_ORDERS=true to submit sandbox orders."
        )


def _clean_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not SYMBOL_PATTERN.match(symbol):
        raise ValueError("Enter a valid ticker symbol.")
    return symbol


def _clean_choice(value: Any, allowed: set[str], label: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise ValueError(f"Unsupported {label}.")
    return normalized


def _positive_float(value: Any, label: str) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number.")
    if num <= 0:
        raise ValueError(f"{label} must be greater than zero.")
    return num


def _optional_positive_float(value: Any, label: str) -> Optional[float]:
    if value is None or value == "":
        return None
    return _positive_float(value, label)


def validate_order_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Order payload must be an object.")

    symbol = _clean_symbol(payload.get("symbol"))
    side = _clean_choice(payload.get("side"), SUPPORTED_SIDES, "side")
    order_type = _clean_choice(payload.get("type", "market"), SUPPORTED_ORDER_TYPES, "order type")
    time_in_force = _clean_choice(payload.get("timeInForce", "day"), SUPPORTED_TIME_IN_FORCE, "time in force")
    asset_class = _clean_choice(payload.get("assetClass", "stock"), SUPPORTED_ASSET_CLASSES, "asset class")
    qty = _positive_float(payload.get("qty"), "Quantity")
    limit_price = _optional_positive_float(payload.get("limitPrice"), "Limit price")
    estimated_price = _optional_positive_float(payload.get("estimatedPrice"), "Estimated price")

    if order_type == "limit" and limit_price is None:
        raise ValueError("Limit orders require a limit price.")
    if (
        _provider_name() == "paper"
        and order_type == "market"
        and config.TRADING_PAPER_AUTO_FILL
        and estimated_price is None
    ):
        raise ValueError("Paper market orders require an estimated price for fill simulation.")

    return {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "timeInForce": time_in_force,
        "assetClass": asset_class,
        "qty": qty,
        "limitPrice": limit_price,
        "estimatedPrice": estimated_price,
        "clientOrderId": str(payload.get("clientOrderId") or "").strip()[:80],
        "source": str(payload.get("source") or "manual").strip()[:80],
    }


def _estimated_notional(order: dict[str, Any]) -> Optional[float]:
    price = order.get("limitPrice") if order.get("type") == "limit" else order.get("estimatedPrice")
    if price is None:
        return None
    return round(float(price) * float(order["qty"]), 2)


def preview_order(payload: dict[str, Any]) -> dict[str, Any]:
    order = validate_order_payload(payload)
    status = trading_status()
    provider = status["provider"]
    estimated_notional = _estimated_notional(order)
    return {
        "ok": True,
        "provider": provider,
        "orderSubmissionEnabled": status["orderSubmissionEnabled"],
        "orderSubmissionLocked": status["orderSubmissionLocked"],
        "message": status["message"],
        "preview": {
            "symbol": order["symbol"],
            "assetClass": order["assetClass"],
            "side": order["side"],
            "type": order["type"],
            "timeInForce": order["timeInForce"],
            "qty": order["qty"],
            "limitPrice": order["limitPrice"],
            "estimatedPrice": order["estimatedPrice"],
            "estimatedNotional": estimated_notional,
            "willAutoFillPaper": bool(
                provider == "paper"
                and config.TRADING_PAPER_AUTO_FILL
                and order["type"] == "market"
                and order["estimatedPrice"] is not None
            ),
            "requiresBrokerOrderUnlock": bool(provider == "alpaca_broker" and not config.ALPACA_BROKER_ALLOW_ORDERS),
            "accountIdSource": alpaca_broker.active_account_id_source() if provider == "alpaca_broker" else None,
        },
    }


def get_account() -> dict[str, Any]:
    status = trading_status()
    if status["provider"] == "alpaca_broker" and not status["brokerConfigured"]:
        return {**status, "account": None}
    account = _active_broker().get_account_snapshot()
    return {**status, "account": account}


def get_positions() -> dict[str, Any]:
    status = trading_status()
    if status["provider"] == "alpaca_broker" and not status["brokerConfigured"]:
        return {**status, "positions": []}
    return {**status, "positions": _active_broker().list_positions()}


def get_orders(limit: int = 100) -> dict[str, Any]:
    status = trading_status()
    if status["provider"] == "alpaca_broker" and not status["brokerConfigured"]:
        return {**status, "orders": []}
    return {**status, "orders": _active_broker().list_orders(limit=limit)}


def test_provider_connection() -> dict[str, Any]:
    status = trading_status()
    provider = status["provider"]

    if provider == "paper":
        return {
            **status,
            "ok": True,
            "tested": "paper_account_snapshot",
            "account": paper_broker.get_account_snapshot(),
        }

    if provider == "alpaca_broker":
        if not status["brokerConfigured"]:
            return {
                **status,
                "ok": False,
                "tested": "alpaca_configuration",
                "error": status["message"],
            }
        account = alpaca_broker.get_account_snapshot()
        return {
            **status,
            "ok": True,
            "tested": "alpaca_account_snapshot",
            "account": account,
        }

    raise TradingProviderError(f"Unsupported trading provider: {config.TRADING_PROVIDER}", 400)


def list_alpaca_accounts(*, query: str = "", status: str = "", limit: int = 50) -> dict[str, Any]:
    api_status = alpaca_broker.api_configuration_status()
    if not api_status["configured"]:
        return {
            "ok": False,
            "alpaca": api_status,
            "accounts": [],
            "message": f"Alpaca Broker API is missing: {', '.join(api_status['missing'])}.",
        }

    accounts = alpaca_broker.list_broker_accounts(query=query, status=status, limit=limit)
    return {
        "ok": True,
        "alpaca": api_status,
        "accounts": accounts,
        "count": len(accounts),
    }


def get_alpaca_account(account_id: str) -> dict[str, Any]:
    api_status = alpaca_broker.api_configuration_status()
    if not api_status["configured"]:
        return {
            "ok": False,
            "alpaca": api_status,
            "account": None,
            "message": f"Alpaca Broker API is missing: {', '.join(api_status['missing'])}.",
        }

    return {
        "ok": True,
        "alpaca": api_status,
        "account": alpaca_broker.get_broker_account(account_id),
    }


def get_selected_alpaca_account() -> dict[str, Any]:
    state = read_state()
    alpaca_state = state.get("brokerAccounts", {}).get("alpaca", {})
    selected_account_id = str(alpaca_state.get("selectedAccountId") or "").strip()
    return {
        "ok": True,
        "selectedAccountId": selected_account_id,
        "selectedAt": alpaca_state.get("selectedAt"),
        "activeAccountIdSource": alpaca_broker.active_account_id_source(),
        "envAccountIdConfigured": bool(config.ALPACA_BROKER_ACCOUNT_ID),
    }


def set_selected_alpaca_account(account_id: str) -> dict[str, Any]:
    clean_id = str(account_id or "").strip()
    if not clean_id:
        raise ValueError("Account id is required.")

    api_status = alpaca_broker.api_configuration_status()
    if not api_status["configured"]:
        return {
            "ok": False,
            "alpaca": api_status,
            "selectedAccountId": "",
            "message": f"Alpaca Broker API is missing: {', '.join(api_status['missing'])}.",
        }

    account = alpaca_broker.get_broker_account(clean_id)
    verified_id = str(account.get("id") or clean_id).strip()

    def _mutate(state: dict[str, Any]) -> dict[str, Any]:
        broker_accounts = state.setdefault("brokerAccounts", {})
        alpaca = broker_accounts.setdefault("alpaca", {})
        alpaca["selectedAccountId"] = verified_id
        alpaca["selectedAt"] = utc_now()
        alpaca["selectedAccountNumber"] = account.get("accountNumber")
        alpaca["selectedStatus"] = account.get("status")
        return alpaca

    selected = mutate_state(_mutate)
    return {
        "ok": True,
        "alpaca": api_status,
        "selectedAccountId": selected.get("selectedAccountId"),
        "selectedAt": selected.get("selectedAt"),
        "account": account,
    }


def clear_selected_alpaca_account() -> dict[str, Any]:
    def _mutate(state: dict[str, Any]) -> dict[str, Any]:
        broker_accounts = state.setdefault("brokerAccounts", {})
        alpaca = broker_accounts.setdefault("alpaca", {})
        alpaca["selectedAccountId"] = ""
        alpaca["selectedAt"] = None
        alpaca.pop("selectedAccountNumber", None)
        alpaca.pop("selectedStatus", None)
        return alpaca

    selected = mutate_state(_mutate)
    return {
        "ok": True,
        "selectedAccountId": selected.get("selectedAccountId", ""),
        "selectedAt": selected.get("selectedAt"),
    }


def submit_order(payload: dict[str, Any]) -> dict[str, Any]:
    _require_enabled()
    _require_order_submission_allowed()
    order = validate_order_payload(payload)
    broker = _active_broker()
    created = broker.submit_order(order)
    return {"ok": True, "order": created, "account": broker.get_account_snapshot()}


def cancel_order(order_id: str) -> dict[str, Any]:
    _require_enabled()
    broker = _active_broker()
    canceled = broker.cancel_order(order_id)
    return {"ok": True, "order": canceled, "account": broker.get_account_snapshot()}
