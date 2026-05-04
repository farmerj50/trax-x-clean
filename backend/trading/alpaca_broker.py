from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

import requests

import config
from trading.store import read_state


class AlpacaBrokerError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


_TOKEN_CACHE = {
    "accessToken": "",
    "expiresAt": 0.0,
}


def _auth_mode() -> str:
    mode = str(config.ALPACA_BROKER_AUTH_MODE or "client_credentials").strip().lower()
    return mode if mode in {"client_credentials", "legacy"} else "client_credentials"


def _environment_mismatches() -> list[str]:
    api_base = str(config.ALPACA_BROKER_API_BASE or "").lower()
    auth_base = str(config.ALPACA_BROKER_AUTH_BASE or "").lower()
    mismatches = []
    if config.ALPACA_BROKER_IS_SANDBOX:
        if "sandbox" not in api_base:
            mismatches.append("ALPACA_BROKER_API_BASE must point to sandbox when ALPACA_BROKER_ENV=sandbox")
        if _auth_mode() == "client_credentials" and "sandbox" not in auth_base:
            mismatches.append("ALPACA_BROKER_AUTH_BASE must point to sandbox when ALPACA_BROKER_ENV=sandbox")
    else:
        if "sandbox" in api_base:
            mismatches.append("ALPACA_BROKER_API_BASE must not point to sandbox for live Broker trading")
        if _auth_mode() == "client_credentials" and "sandbox" in auth_base:
            mismatches.append("ALPACA_BROKER_AUTH_BASE must not point to sandbox for live Broker trading")
    return mismatches


def is_configured() -> bool:
    return bool(
        config.ALPACA_BROKER_ENABLED
        and config.ALPACA_BROKER_API_BASE
        and config.ALPACA_BROKER_API_KEY
        and config.ALPACA_BROKER_API_SECRET
        and active_account_id()
        and not _environment_mismatches()
    )


def is_api_configured() -> bool:
    return bool(
        config.ALPACA_BROKER_ENABLED
        and config.ALPACA_BROKER_API_BASE
        and config.ALPACA_BROKER_API_KEY
        and config.ALPACA_BROKER_API_SECRET
        and not _environment_mismatches()
    )


def configuration_status() -> dict[str, Any]:
    missing = []
    account_id = active_account_id()
    if not config.ALPACA_BROKER_ENABLED:
        missing.append("ALPACA_BROKER_ENABLED")
    if not config.ALPACA_BROKER_API_KEY:
        missing.append("ALPACA_BROKER_API_KEY")
    if not config.ALPACA_BROKER_API_SECRET:
        missing.append("ALPACA_BROKER_API_SECRET")
    if not account_id:
        missing.append("ALPACA_BROKER_ACCOUNT_ID")
    missing.extend(_environment_mismatches())
    return {
        "configured": len(missing) == 0,
        "env": config.ALPACA_BROKER_ENV,
        "apiBase": config.ALPACA_BROKER_API_BASE,
        "authMode": _auth_mode(),
        "authBase": config.ALPACA_BROKER_AUTH_BASE if _auth_mode() == "client_credentials" else None,
        "accountIdConfigured": bool(account_id),
        "accountIdSource": active_account_id_source(),
        "orderSubmitAllowed": bool(config.ALPACA_BROKER_ALLOW_ORDERS),
        "missing": missing,
    }


def api_configuration_status() -> dict[str, Any]:
    missing = []
    if not config.ALPACA_BROKER_ENABLED:
        missing.append("ALPACA_BROKER_ENABLED")
    if not config.ALPACA_BROKER_API_KEY:
        missing.append("ALPACA_BROKER_API_KEY")
    if not config.ALPACA_BROKER_API_SECRET:
        missing.append("ALPACA_BROKER_API_SECRET")
    missing.extend(_environment_mismatches())
    return {
        "configured": len(missing) == 0,
        "env": config.ALPACA_BROKER_ENV,
        "apiBase": config.ALPACA_BROKER_API_BASE,
        "authMode": _auth_mode(),
        "authBase": config.ALPACA_BROKER_AUTH_BASE if _auth_mode() == "client_credentials" else None,
        "missing": missing,
    }


def _base_url() -> str:
    return config.ALPACA_BROKER_API_BASE.rstrip("/")


def selected_account_id() -> str:
    state = read_state()
    alpaca = state.get("brokerAccounts", {}).get("alpaca", {})
    return str(alpaca.get("selectedAccountId") or "").strip()


def active_account_id() -> str:
    return config.ALPACA_BROKER_ACCOUNT_ID.strip() or selected_account_id()


def active_account_id_source() -> str:
    if config.ALPACA_BROKER_ACCOUNT_ID.strip():
        return "env"
    if selected_account_id():
        return "selected"
    return "missing"


def _account_id() -> str:
    account_id = active_account_id()
    if not account_id:
        raise AlpacaBrokerError("ALPACA_BROKER_ACCOUNT_ID is required for Alpaca Broker trading.", 503)
    return account_id


def _auth() -> tuple[str, str]:
    if not config.ALPACA_BROKER_API_KEY or not config.ALPACA_BROKER_API_SECRET:
        raise AlpacaBrokerError("Alpaca Broker API credentials are not configured.", 503)
    return (config.ALPACA_BROKER_API_KEY, config.ALPACA_BROKER_API_SECRET)


def _access_token() -> str:
    if not config.ALPACA_BROKER_API_KEY or not config.ALPACA_BROKER_API_SECRET:
        raise AlpacaBrokerError("Alpaca Broker client credentials are not configured.", 503)

    now = time.time()
    cached_token = str(_TOKEN_CACHE.get("accessToken") or "")
    expires_at = float(_TOKEN_CACHE.get("expiresAt") or 0)
    if cached_token and expires_at - 60 > now:
        return cached_token

    token_url = f"{config.ALPACA_BROKER_AUTH_BASE}/v1/oauth2/token"
    try:
        response = requests.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": config.ALPACA_BROKER_API_KEY,
                "client_secret": config.ALPACA_BROKER_API_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=config.ALPACA_BROKER_TIMEOUT_SECONDS,
        )
    except requests.exceptions.Timeout as exc:
        raise AlpacaBrokerError("Alpaca Broker token request timed out.", 504) from exc
    except requests.exceptions.RequestException as exc:
        raise AlpacaBrokerError(f"Alpaca Broker token request failed: {exc}", 502) from exc

    try:
        payload = response.json() if response.text else {}
    except ValueError:
        payload = {}

    if response.status_code >= 400:
        if response.status_code == 401:
            message = (
                "Alpaca rejected the Broker API Client ID/Secret. Confirm the Client ID and "
                "Client Secret match the selected Broker Dashboard environment."
            )
        else:
            message = _extract_error_message(payload) or f"Alpaca Broker token endpoint returned HTTP {response.status_code}."
        raise AlpacaBrokerError(message, _map_status_code(response.status_code))

    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise AlpacaBrokerError("Alpaca Broker token endpoint did not return an access token.", 502)

    expires_in = _safe_float(payload.get("expires_in"), 899)
    _TOKEN_CACHE["accessToken"] = token
    _TOKEN_CACHE["expiresAt"] = now + max(60, expires_in)
    return token


def _auth_headers() -> dict[str, str]:
    if _auth_mode() == "client_credentials":
        return {"Authorization": f"Bearer {_access_token()}"}
    return {}


def _request(method: str, path: str, **kwargs: Any) -> Any:
    if not config.ALPACA_BROKER_ENABLED:
        raise AlpacaBrokerError("Alpaca Broker provider is disabled.", 403)

    url = f"{_base_url()}{path}"
    request_kwargs = dict(kwargs)
    headers = dict(request_kwargs.pop("headers", {}) or {})
    headers.update(_auth_headers())
    try:
        response = requests.request(
            method,
            url,
            auth=_auth() if _auth_mode() == "legacy" else None,
            headers=headers or None,
            timeout=config.ALPACA_BROKER_TIMEOUT_SECONDS,
            **request_kwargs,
        )
    except requests.exceptions.Timeout as exc:
        raise AlpacaBrokerError("Alpaca Broker request timed out.", 504) from exc
    except requests.exceptions.RequestException as exc:
        raise AlpacaBrokerError(f"Alpaca Broker request failed: {exc}", 502) from exc

    if response.status_code == 204:
        return None

    try:
        payload = response.json() if response.text else None
    except ValueError:
        payload = response.text

    if response.status_code >= 400:
        if response.status_code == 401:
            message = (
                "Alpaca rejected the Broker API credentials. Confirm the Broker API key and secret "
                "match the selected Broker Dashboard environment."
            )
        else:
            message = _extract_error_message(payload) or f"Alpaca Broker returned HTTP {response.status_code}."
        raise AlpacaBrokerError(message, _map_status_code(response.status_code))

    return payload


def _map_status_code(status_code: int) -> int:
    if status_code in {400, 401, 403, 404, 422}:
        return status_code
    if status_code == 429:
        return 429
    return 502


def _extract_error_message(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("message", "error", "detail"):
            if payload.get(key):
                return str(payload.get(key))
        code = payload.get("code")
        if code:
            return f"Alpaca Broker error {code}."
    if isinstance(payload, str):
        return payload[:300]
    return ""


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    return num if num == num else default


def _normalize_account(payload: dict[str, Any]) -> dict[str, Any]:
    cash = _safe_float(payload.get("cash"))
    buying_power = _safe_float(payload.get("buying_power"), cash)
    portfolio_value = _safe_float(payload.get("portfolio_value"), cash)
    return {
        "mode": "alpaca_broker",
        "accountId": payload.get("id") or active_account_id(),
        "accountNumber": payload.get("account_number"),
        "status": payload.get("status"),
        "cash": round(cash, 2),
        "buyingPower": round(buying_power, 2),
        "portfolioValue": round(portfolio_value, 2),
        "tradingBlocked": bool(payload.get("trading_blocked")),
        "accountBlocked": bool(payload.get("account_blocked")),
        "patternDayTrader": bool(payload.get("pattern_day_trader")),
        "updatedAt": payload.get("updated_at") or payload.get("created_at"),
    }


def _normalize_market_clock(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": payload.get("timestamp"),
        "isOpen": bool(payload.get("is_open")),
        "nextOpen": payload.get("next_open"),
        "nextClose": payload.get("next_close"),
    }


def _normalize_broker_account(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": payload.get("id"),
        "accountNumber": payload.get("account_number"),
        "status": payload.get("status"),
        "cryptoStatus": payload.get("crypto_status"),
        "currency": payload.get("currency"),
        "createdAt": payload.get("created_at"),
        "updatedAt": payload.get("updated_at"),
        "lastEquity": payload.get("last_equity"),
        "kycStatus": payload.get("kyc_results", {}).get("summary")
        if isinstance(payload.get("kyc_results"), dict)
        else None,
    }


def create_broker_account(payload: dict[str, Any]) -> dict[str, Any]:
    response = _request("POST", "/v1/accounts", json=payload)
    return _normalize_broker_account(response or {})


def _normalize_ach_relationship(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": payload.get("id"),
        "accountId": payload.get("account_id"),
        "status": payload.get("status"),
        "accountOwnerName": payload.get("account_owner_name"),
        "bankAccountType": payload.get("bank_account_type"),
        "nickname": payload.get("nickname"),
        "createdAt": payload.get("created_at"),
        "updatedAt": payload.get("updated_at"),
    }


def _normalize_transfer(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": payload.get("id"),
        "accountId": payload.get("account_id"),
        "relationshipId": payload.get("relationship_id"),
        "bankId": payload.get("bank_id"),
        "type": payload.get("type") or payload.get("transfer_type"),
        "status": payload.get("status"),
        "amount": _safe_float(payload.get("amount")),
        "direction": payload.get("direction"),
        "createdAt": payload.get("created_at"),
        "updatedAt": payload.get("updated_at"),
        "expiresAt": payload.get("expires_at"),
    }


def _normalize_instant_funding(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": payload.get("id"),
        "accountNumber": payload.get("account_no"),
        "sourceAccountNumber": payload.get("source_account_no"),
        "status": payload.get("status"),
        "amount": _safe_float(payload.get("amount")),
        "remainingPayable": _safe_float(payload.get("remaining_payable")),
        "deadline": payload.get("deadline"),
        "systemDate": payload.get("system_date"),
        "createdAt": payload.get("created_at"),
        "updatedAt": payload.get("updated_at"),
    }


def list_ach_relationships(account_id: str | None = None) -> list[dict[str, Any]]:
    clean_account_id = str(account_id or active_account_id() or "").strip()
    if not clean_account_id:
        raise AlpacaBrokerError("Account id is required.", 400)
    payload = _request("GET", f"/v1/accounts/{clean_account_id}/ach_relationships")
    return [_normalize_ach_relationship(item) for item in list(payload or [])]


def create_ach_relationship(account_id: str | None = None) -> dict[str, Any]:
    clean_account_id = str(account_id or active_account_id() or "").strip()
    if not clean_account_id:
        raise AlpacaBrokerError("Account id is required.", 400)
    response = _request(
        "POST",
        f"/v1/accounts/{clean_account_id}/ach_relationships",
        json={
            "account_owner_name": "Trax Sandbox",
            "bank_account_type": "CHECKING",
            "bank_account_number": "32131231abc",
            "bank_routing_number": "121000358",
            "nickname": "Sandbox Checking",
            "instant": True,
        },
    )
    return _normalize_ach_relationship(response or {})


def create_transfer(
    *,
    account_id: str | None = None,
    relationship_id: str,
    amount: float,
    direction: str = "INCOMING",
) -> dict[str, Any]:
    clean_account_id = str(account_id or active_account_id() or "").strip()
    clean_relationship_id = str(relationship_id or "").strip()
    if not clean_account_id:
        raise AlpacaBrokerError("Account id is required.", 400)
    if not clean_relationship_id:
        raise AlpacaBrokerError("ACH relationship id is required.", 400)
    if amount <= 0:
        raise AlpacaBrokerError("Transfer amount must be greater than zero.", 400)
    response = _request(
        "POST",
        f"/v1/accounts/{clean_account_id}/transfers",
        json={
            "transfer_type": "ach",
            "relationship_id": clean_relationship_id,
            "amount": f"{amount:.2f}",
            "direction": direction,
            "timing": "immediate",
        },
    )
    return _normalize_transfer(response or {})


def create_instant_funding(
    *,
    account_number: str,
    source_account_number: str,
    amount: float,
) -> dict[str, Any]:
    clean_account_number = str(account_number or "").strip()
    clean_source_account_number = str(source_account_number or "").strip()
    if not clean_account_number:
        raise AlpacaBrokerError("Account number is required for instant funding.", 400)
    if not clean_source_account_number:
        raise AlpacaBrokerError("Firm account number is required for instant funding.", 400)
    if amount <= 0:
        raise AlpacaBrokerError("Instant funding amount must be greater than zero.", 400)
    response = _request(
        "POST",
        "/v1/instant_funding",
        json={
            "account_no": clean_account_number,
            "source_account_no": clean_source_account_number,
            "amount": f"{amount:.2f}",
        },
        headers={"Idempotency-Key": f"trax-instant-funding-{uuid4()}"},
    )
    return _normalize_instant_funding(response or {})


def _normalize_position(payload: dict[str, Any]) -> dict[str, Any]:
    market_value = _safe_float(payload.get("market_value"))
    return {
        "symbol": payload.get("symbol"),
        "qty": _safe_float(payload.get("qty")),
        "avgPrice": round(_safe_float(payload.get("avg_entry_price")), 2),
        "marketValue": round(market_value, 2),
        "assetClass": payload.get("asset_class") or "stock",
        "side": payload.get("side"),
        "unrealizedPl": round(_safe_float(payload.get("unrealized_pl")), 2),
        "unrealizedPlpc": _safe_float(payload.get("unrealized_plpc")),
        "updatedAt": payload.get("updated_at"),
    }


def _normalize_order(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": payload.get("id"),
        "clientOrderId": payload.get("client_order_id"),
        "symbol": payload.get("symbol"),
        "assetClass": payload.get("asset_class") or "stock",
        "side": payload.get("side"),
        "type": payload.get("type"),
        "timeInForce": payload.get("time_in_force"),
        "qty": _safe_float(payload.get("qty")),
        "notional": _safe_float(payload.get("notional")) if payload.get("notional") is not None else None,
        "limitPrice": _safe_float(payload.get("limit_price")) if payload.get("limit_price") is not None else None,
        "status": payload.get("status"),
        "filledQty": _safe_float(payload.get("filled_qty")),
        "filledAvgPrice": (
            _safe_float(payload.get("filled_avg_price"))
            if payload.get("filled_avg_price") is not None
            else None
        ),
        "submittedAt": payload.get("submitted_at"),
        "updatedAt": payload.get("updated_at"),
        "filledAt": payload.get("filled_at"),
        "canceledAt": payload.get("canceled_at"),
        "source": "alpaca_broker",
    }


def _order_payload(order: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "symbol": order["symbol"],
        "side": order["side"],
        "type": order["type"],
        "time_in_force": order["timeInForce"],
        "qty": str(order["qty"]),
    }
    if order.get("limitPrice") is not None:
        payload["limit_price"] = str(order["limitPrice"])
    if order.get("clientOrderId"):
        payload["client_order_id"] = order["clientOrderId"]
    return payload


def get_account_snapshot() -> dict[str, Any]:
    account_id = _account_id()
    payload = _request("GET", f"/v1/trading/accounts/{account_id}/account")
    return _normalize_account(payload or {})


def get_market_clock() -> dict[str, Any]:
    payload = _request("GET", "/v1/clock")
    return _normalize_market_clock(payload or {})


def list_broker_accounts(
    *,
    query: str = "",
    status: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "sort": "desc",
        "entities": "trading_configurations",
    }
    clean_query = str(query or "").strip()
    clean_status = str(status or "").strip().upper()
    if clean_query:
        params["query"] = clean_query
    if clean_status:
        params["status"] = clean_status

    payload = _request("GET", "/v1/accounts", params=params)
    rows = [_normalize_broker_account(item) for item in list(payload or [])]
    return rows[: max(1, min(int(limit), 100))]


def get_broker_account(account_id: str) -> dict[str, Any]:
    clean_id = str(account_id or "").strip()
    if not clean_id:
        raise AlpacaBrokerError("Account id is required.", 400)
    payload = _request("GET", f"/v1/accounts/{clean_id}")
    return _normalize_broker_account(payload or {})


def list_positions() -> list[dict[str, Any]]:
    account_id = _account_id()
    payload = _request("GET", f"/v1/trading/accounts/{account_id}/positions")
    return [_normalize_position(item) for item in list(payload or [])]


def list_orders(limit: int = 100) -> list[dict[str, Any]]:
    account_id = _account_id()
    params = {
        "status": "all",
        "limit": max(1, min(int(limit), 500)),
        "direction": "desc",
    }
    payload = _request("GET", f"/v1/trading/accounts/{account_id}/orders", params=params)
    return [_normalize_order(item) for item in list(payload or [])]


def submit_order(order: dict[str, Any]) -> dict[str, Any]:
    if not config.ALPACA_BROKER_ALLOW_ORDERS:
        raise AlpacaBrokerError(
            "Alpaca Broker order submission is locked. Set ALPACA_BROKER_ALLOW_ORDERS=true to submit broker orders.",
            403,
        )
    account_id = _account_id()
    payload = _request(
        "POST",
        f"/v1/trading/accounts/{account_id}/orders",
        json=_order_payload(order),
    )
    return _normalize_order(payload or {})


def cancel_order(order_id: str) -> dict[str, Any]:
    account_id = _account_id()
    clean_id = str(order_id or "").strip()
    if not clean_id:
        raise AlpacaBrokerError("Order id is required.", 400)
    _request("DELETE", f"/v1/trading/accounts/{account_id}/orders/{clean_id}")
    return {
        "id": clean_id,
        "status": "cancel_requested",
        "source": "alpaca_broker",
    }
