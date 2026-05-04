from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

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
    "TRADING_MAX_ORDER_NOTIONAL",
    "TRADING_MAX_ORDER_QTY",
    "TRADING_ALLOWED_SYMBOLS",
    "TRADING_ALLOW_SHORT_SELLS",
    "TRADING_REQUIRE_MARKET_OPEN",
    "ALPACA_BROKER_ENABLED",
    "ALPACA_BROKER_API_KEY",
    "ALPACA_BROKER_API_SECRET",
    "ALPACA_BROKER_ACCOUNT_ID",
    "ALPACA_BROKER_FIRM_ACCOUNT_NUMBER",
    "ALPACA_BROKER_ALLOW_ORDERS",
    "ALPACA_BROKER_ENV",
    "ALPACA_BROKER_API_BASE",
    "ALPACA_BROKER_AUTH_MODE",
    "ALPACA_BROKER_AUTH_BASE",
)


class TradingProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _broker_environment_label() -> str:
    return "sandbox" if config.ALPACA_BROKER_IS_SANDBOX else "live"


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
            "TRADING_MAX_ORDER_NOTIONAL": config.TRADING_MAX_ORDER_NOTIONAL,
            "TRADING_MAX_ORDER_QTY": config.TRADING_MAX_ORDER_QTY,
            "TRADING_ALLOWED_SYMBOLS": list(config.TRADING_ALLOWED_SYMBOLS),
            "TRADING_ALLOW_SHORT_SELLS": bool(config.TRADING_ALLOW_SHORT_SELLS),
            "TRADING_REQUIRE_MARKET_OPEN": bool(config.TRADING_REQUIRE_MARKET_OPEN),
            "ALPACA_BROKER_ENABLED": bool(config.ALPACA_BROKER_ENABLED),
            "ALPACA_BROKER_API_KEY": _presence_status(config.ALPACA_BROKER_API_KEY),
            "ALPACA_BROKER_API_SECRET": _presence_status(config.ALPACA_BROKER_API_SECRET),
            "ALPACA_BROKER_ACCOUNT_ID": _presence_status(config.ALPACA_BROKER_ACCOUNT_ID),
            "ALPACA_BROKER_FIRM_ACCOUNT_NUMBER": _presence_status(config.ALPACA_BROKER_FIRM_ACCOUNT_NUMBER),
            "ALPACA_BROKER_ALLOW_ORDERS": bool(config.ALPACA_BROKER_ALLOW_ORDERS),
            "ALPACA_BROKER_ENV": config.ALPACA_BROKER_ENV,
            "ALPACA_BROKER_API_BASE": _presence_status(config.ALPACA_BROKER_API_BASE),
            "ALPACA_BROKER_AUTH_MODE": config.ALPACA_BROKER_AUTH_MODE,
            "ALPACA_BROKER_AUTH_BASE": _presence_status(config.ALPACA_BROKER_AUTH_BASE),
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
    broker_env_label = _broker_environment_label()

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
            else "Set TRADING_PROVIDER=alpaca_broker when broker routing is ready.",
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
            "message": f"{broker_env_label.title()} order submission is unlocked."
            if config.ALPACA_BROKER_ALLOW_ORDERS
            else "Orders stay blocked until ALPACA_BROKER_ALLOW_ORDERS=true.",
        },
    ]

    if not config.ENABLE_TRADING:
        next_action = "Set ENABLE_TRADING=true in backend/.env, save it, then restart Flask."
    elif not api_status["configured"]:
        next_action = "Fill and save the Alpaca Broker API settings in backend/.env, then restart Flask."
    elif not full_status["accountIdConfigured"]:
        next_action = "Click Load Accounts, then Use on the broker account to select the routing account."
    elif provider != "alpaca_broker":
        next_action = "Set TRADING_PROVIDER=alpaca_broker and restart Flask when you want broker routing active."
    elif not config.ALPACA_BROKER_ALLOW_ORDERS:
        next_action = "Run Test Provider and Preview Order; unlock sandbox order submission only after that passes."
    elif not status["orderSubmissionEnabled"]:
        next_action = status["message"]
    else:
        next_action = f"{broker_env_label.title()} broker submission is ready."

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
    broker_env_label = _broker_environment_label()

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
            message = f"Alpaca Broker {broker_env_label} is configured, but order submission is locked."
        else:
            message = f"Alpaca Broker {broker_env_label} provider is configured and order submission is unlocked."
    else:
        supported = False
        message = f"Unsupported trading provider: {config.TRADING_PROVIDER}."

    return {
        "enabled": enabled,
        "mode": config.TRADING_MODE,
        "provider": provider,
        "brokerEnvironment": config.ALPACA_BROKER_ENV,
        "brokerIsSandbox": bool(config.ALPACA_BROKER_IS_SANDBOX),
        "supportedMode": supported,
        "liveTradingAvailable": bool(
            provider == "alpaca_broker"
            and not config.ALPACA_BROKER_IS_SANDBOX
            and order_submission_enabled
        ),
        "brokerConfigured": bool(provider == "alpaca_broker" and alpaca_status["configured"]),
        "paperAutoFill": bool(config.TRADING_PAPER_AUTO_FILL),
        "orderSubmissionEnabled": order_submission_enabled,
        "orderSubmissionLocked": bool(provider == "alpaca_broker" and not config.ALPACA_BROKER_ALLOW_ORDERS),
        "riskControls": _risk_policy(),
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
            "Alpaca Broker order submission is locked. Set ALPACA_BROKER_ALLOW_ORDERS=true to submit broker orders."
        )


def _risk_policy() -> dict[str, Any]:
    return {
        "maxOrderNotional": config.TRADING_MAX_ORDER_NOTIONAL,
        "maxOrderQty": config.TRADING_MAX_ORDER_QTY,
        "allowedSymbols": list(config.TRADING_ALLOWED_SYMBOLS),
        "allowShortSells": bool(config.TRADING_ALLOW_SHORT_SELLS),
        "requireMarketOpen": bool(config.TRADING_REQUIRE_MARKET_OPEN),
    }


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


def _enforce_order_guardrails(order: dict[str, Any]) -> dict[str, Any]:
    allowed_symbols = set(config.TRADING_ALLOWED_SYMBOLS)
    if allowed_symbols and order["symbol"] not in allowed_symbols:
        raise PermissionError(f"{order['symbol']} is not in TRADING_ALLOWED_SYMBOLS.")

    max_qty = float(config.TRADING_MAX_ORDER_QTY or 0)
    if max_qty > 0 and float(order["qty"]) > max_qty:
        raise PermissionError(f"Order quantity exceeds TRADING_MAX_ORDER_QTY={max_qty:g}.")

    max_notional = float(config.TRADING_MAX_ORDER_NOTIONAL or 0)
    estimated_notional = _estimated_notional(order)
    if max_notional > 0:
        if estimated_notional is None:
            raise ValueError("Estimated price or limit price is required for max notional risk checks.")
        if estimated_notional > max_notional:
            raise PermissionError(
                f"Estimated order notional ${estimated_notional:,.2f} exceeds TRADING_MAX_ORDER_NOTIONAL=${max_notional:,.2f}."
            )

    return {
        **_risk_policy(),
        "estimatedNotional": estimated_notional,
    }


def _position_qty(symbol: str, broker) -> float:
    total = 0.0
    for position in broker.list_positions():
        if str(position.get("symbol") or "").upper() == symbol:
            total += float(position.get("qty") or 0)
    return total


def _enforce_account_guardrails(order: dict[str, Any], broker) -> dict[str, Any]:
    estimated_notional = _estimated_notional(order)
    details: dict[str, Any] = {}

    if order["side"] == "buy" and estimated_notional is not None:
        account = broker.get_account_snapshot()
        buying_power = float(account.get("buyingPower") or 0)
        details["buyingPower"] = buying_power
        if estimated_notional > buying_power:
            raise PermissionError(
                f"Estimated order notional ${estimated_notional:,.2f} exceeds buying power ${buying_power:,.2f}."
            )

    if order["side"] == "sell" and not config.TRADING_ALLOW_SHORT_SELLS:
        held_qty = _position_qty(order["symbol"], broker)
        details["heldQty"] = held_qty
        if float(order["qty"]) > held_qty:
            raise PermissionError(
                f"Sell quantity {float(order['qty']):g} exceeds held quantity {held_qty:g}; short sells are disabled."
            )

    return details


def _enforce_market_guardrails(order: dict[str, Any]) -> dict[str, Any]:
    provider = _provider_name()
    should_check_clock = bool(
        provider == "alpaca_broker"
        and order["assetClass"] == "stock"
        and (config.TRADING_REQUIRE_MARKET_OPEN or not config.ALPACA_BROKER_IS_SANDBOX)
    )
    if not should_check_clock:
        return {"checked": False}

    clock = alpaca_broker.get_market_clock()
    if not clock.get("isOpen"):
        next_open = clock.get("nextOpen") or "the next market open"
        raise PermissionError(f"Market is closed. Next open: {next_open}.")
    return {"checked": True, **clock}


def _append_audit_event(
    action: str,
    outcome: str,
    *,
    order: Optional[dict[str, Any]] = None,
    broker_order: Optional[dict[str, Any]] = None,
    error: Optional[BaseException] = None,
) -> None:
    event = {
        "id": str(uuid4()),
        "at": utc_now(),
        "action": action,
        "outcome": outcome,
        "provider": _provider_name(),
        "accountIdSource": alpaca_broker.active_account_id_source() if _provider_name() == "alpaca_broker" else None,
        "symbol": order.get("symbol") if order else None,
        "side": order.get("side") if order else None,
        "type": order.get("type") if order else None,
        "timeInForce": order.get("timeInForce") if order else None,
        "qty": order.get("qty") if order else None,
        "limitPrice": order.get("limitPrice") if order else None,
        "estimatedNotional": _estimated_notional(order) if order else None,
        "brokerOrderId": broker_order.get("id") if broker_order else None,
        "brokerStatus": broker_order.get("status") if broker_order else None,
        "error": str(error)[:500] if error else None,
    }

    try:
        def _mutate(state: dict[str, Any]) -> list[dict[str, Any]]:
            audit_log = state.setdefault("auditLog", [])
            audit_log.append(event)
            state["auditLog"] = audit_log[-500:]
            return state["auditLog"]

        mutate_state(_mutate)
    except Exception:
        pass


def get_audit_log(limit: int = 100) -> dict[str, Any]:
    status = trading_status()
    state = read_state()
    rows = list(state.get("auditLog") or [])
    clean_limit = max(1, min(int(limit), 500))
    return {**status, "auditLog": rows[-clean_limit:][::-1]}


def get_market_clock() -> dict[str, Any]:
    status = trading_status()
    if status["provider"] != "alpaca_broker" or not status["brokerConfigured"]:
        return {**status, "clock": None}
    return {**status, "clock": alpaca_broker.get_market_clock()}


def preview_order(payload: dict[str, Any]) -> dict[str, Any]:
    order = None
    try:
        order = validate_order_payload(payload)
        guardrails = _enforce_order_guardrails(order)
        status = trading_status()
        provider = status["provider"]
        broker = _active_broker()
        account_guardrails = _enforce_account_guardrails(order, broker)
        market_guardrails = _enforce_market_guardrails(order)
        estimated_notional = _estimated_notional(order)
        _append_audit_event("preview_order", "accepted", order=order)
        return {
            "ok": True,
            "provider": provider,
            "orderSubmissionEnabled": status["orderSubmissionEnabled"],
            "orderSubmissionLocked": status["orderSubmissionLocked"],
            "message": status["message"],
            "riskControls": {
                **guardrails,
                **account_guardrails,
                "marketClock": market_guardrails,
            },
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
    except Exception as exc:
        _append_audit_event("preview_order", "rejected", order=order, error=exc)
        raise


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


def _sandbox_account_payload() -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    phone_suffix = str(int(suffix[:8], 16))[-4:].zfill(4)
    signed_at = datetime.now(timezone.utc).isoformat()
    return {
        "account_type": "trading",
        "contact": {
            "email_address": f"trax.sandbox.{suffix}@example.com",
            "phone_number": f"415555{phone_suffix}",
            "street_address": ["3 Harbor Drive"],
            "city": "San Mateo",
            "state": "CA",
            "postal_code": "94401",
        },
        "identity": {
            "given_name": "Trax",
            "family_name": f"Sandbox{suffix[:4].upper()}",
            "date_of_birth": "1990-01-01",
            "tax_id_type": "USA_SSN",
            "tax_id": "661-010-666",
            "country_of_citizenship": "USA",
            "country_of_birth": "USA",
            "country_of_tax_residence": "USA",
            "funding_source": ["employment_income"],
            "annual_income_min": "10000",
            "annual_income_max": "50000",
            "total_net_worth_min": "10000",
            "total_net_worth_max": "50000",
            "liquid_net_worth_min": "10000",
            "liquid_net_worth_max": "50000",
            "marital_status": "SINGLE",
            "number_of_dependents": 0,
        },
        "disclosures": {
            "is_control_person": False,
            "is_affiliated_exchange_or_finra": False,
            "is_affiliated_exchange_or_iiroc": False,
            "is_politically_exposed": False,
            "immediate_family_exposed": False,
        },
        "agreements": [
            {"agreement": "customer_agreement", "signed_at": signed_at, "ip_address": "127.0.0.1"},
            {"agreement": "margin_agreement", "signed_at": signed_at, "ip_address": "127.0.0.1"},
        ],
        "documents": [
            {
                "document_type": "identity_verification",
                "document_sub_type": "passport",
                "content": "/9j/Cg==",
                "mime_type": "image/jpeg",
            }
        ],
        "trusted_contact": {
            "given_name": "Sandbox",
            "family_name": "Contact",
            "email_address": f"trax.sandbox.contact.{suffix}@example.com",
        },
        "trading_configurations": {
            "risk_tolerance": "conservative",
            "investment_objective": "market_speculation",
            "investment_time_horizon": "more_than_10_years",
            "liquidity_needs": "does_not_matter",
        },
        "enabled_assets": ["us_equity"],
    }


def create_sandbox_alpaca_account() -> dict[str, Any]:
    if config.ALPACA_BROKER_ENV != "sandbox":
        raise TradingProviderError("Sandbox account creation is only available when ALPACA_BROKER_ENV=sandbox.", 403)

    api_status = alpaca_broker.api_configuration_status()
    if not api_status["configured"]:
        return {
            "ok": False,
            "alpaca": api_status,
            "account": None,
            "message": f"Alpaca Broker API is missing: {', '.join(api_status['missing'])}.",
        }

    account = alpaca_broker.create_broker_account(_sandbox_account_payload())
    account_id = str(account.get("id") or "").strip()
    selected = None
    if account_id:
        selected = set_selected_alpaca_account(account_id)

    return {
        "ok": True,
        "alpaca": api_status,
        "account": account,
        "selectedAccountId": account_id,
        "selected": selected,
        "message": f"Created sandbox Alpaca account {account.get('accountNumber') or account_id}.",
    }


def _sandbox_funding_amount(value: Any) -> float:
    if value in (None, ""):
        return 1000.0
    try:
        amount = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Funding amount must be a number.") from exc
    if amount <= 0:
        raise ValueError("Funding amount must be greater than zero.")
    if amount > 50000:
        raise ValueError("Sandbox funding amount cannot exceed 50000.")
    return round(amount, 2)


def fund_sandbox_alpaca_account(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if config.ALPACA_BROKER_ENV != "sandbox":
        raise TradingProviderError("Sandbox funding is only available when ALPACA_BROKER_ENV=sandbox.", 403)

    api_status = alpaca_broker.api_configuration_status()
    if not api_status["configured"]:
        return {
            "ok": False,
            "alpaca": api_status,
            "relationship": None,
            "transfer": None,
            "message": f"Alpaca Broker API is missing: {', '.join(api_status['missing'])}.",
        }

    amount = _sandbox_funding_amount((payload or {}).get("amount"))
    account_id = alpaca_broker.active_account_id()
    if not account_id:
        raise TradingProviderError("Select an Alpaca account before sandbox funding.", 400)

    account_before = alpaca_broker.get_account_snapshot()
    account_number = str(account_before.get("accountNumber") or "").strip()
    firm_account_number = str(config.ALPACA_BROKER_FIRM_ACCOUNT_NUMBER or "").strip()
    if firm_account_number:
        instant_funding = alpaca_broker.create_instant_funding(
            account_number=account_number,
            source_account_number=firm_account_number,
            amount=amount,
        )
        return {
            "ok": True,
            "alpaca": api_status,
            "method": "instant_funding",
            "instantFunding": instant_funding,
            "account": alpaca_broker.get_account_snapshot(),
            "message": f"Requested instant sandbox funding for ${amount:,.2f}.",
        }

    relationships = alpaca_broker.list_ach_relationships(account_id)
    relationship = next(
        (
            item
            for item in relationships
            if str(item.get("status") or "").upper() in {"APPROVED", "ACTIVE"}
        ),
        None,
    )
    if relationship is None:
        relationship = alpaca_broker.create_ach_relationship(account_id)

    transfer = alpaca_broker.create_transfer(
        account_id=account_id,
        relationship_id=str(relationship.get("id") or ""),
        amount=amount,
        direction="INCOMING",
    )

    return {
        "ok": True,
        "alpaca": api_status,
        "method": "ach_transfer",
        "relationship": relationship,
        "transfer": transfer,
        "account": alpaca_broker.get_account_snapshot(),
        "message": f"Requested sandbox funding transfer for ${amount:,.2f}.",
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
    order = None
    try:
        _require_enabled()
        _require_order_submission_allowed()
        order = validate_order_payload(payload)
        _enforce_order_guardrails(order)
        broker = _active_broker()
        _enforce_account_guardrails(order, broker)
        _enforce_market_guardrails(order)
        created = broker.submit_order(order)
        _append_audit_event("submit_order", "accepted", order=order, broker_order=created)
        return {"ok": True, "order": created, "account": broker.get_account_snapshot()}
    except Exception as exc:
        _append_audit_event("submit_order", "rejected", order=order, error=exc)
        raise


def cancel_order(order_id: str) -> dict[str, Any]:
    try:
        _require_enabled()
        broker = _active_broker()
        canceled = broker.cancel_order(order_id)
        _append_audit_event("cancel_order", "accepted", broker_order=canceled)
        return {"ok": True, "order": canceled, "account": broker.get_account_snapshot()}
    except Exception as exc:
        _append_audit_event("cancel_order", "rejected", error=exc)
        raise
