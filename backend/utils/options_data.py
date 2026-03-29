from datetime import datetime, timedelta

import requests
from cachetools import TTLCache
import yfinance as yf

import config

API_KEY = config.POLYGON_API_KEY
CHAIN_CACHE = TTLCache(maxsize=200, ttl=90)


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _next_url_with_key(next_url: str) -> str:
    if "apiKey=" in next_url:
        return next_url
    separator = "&" if "?" in next_url else "?"
    return f"{next_url}{separator}apiKey={API_KEY}"


def _estimate_delta(contract_type: str, strike: float, spot: float) -> float:
    if strike <= 0 or spot <= 0:
        return 0.0
    moneyness = (strike - spot) / spot
    if contract_type == "call":
        return max(0.05, min(0.95, 0.5 - moneyness * 3.0))
    return max(0.05, min(0.95, 0.5 + moneyness * 3.0))


def _normalize_polygon_option(option: dict, underlying_ticker: str) -> dict | None:
    details = option.get("details") or {}
    quote = option.get("last_quote") or {}
    greeks = option.get("greeks") or {}
    day = option.get("day") or {}

    contract_type = str(details.get("contract_type") or option.get("type") or "").lower()
    if contract_type not in {"call", "put"}:
        return None

    expiry = details.get("expiration_date") or option.get("expiration_date")
    strike = _safe_float(details.get("strike_price") or option.get("strike_price"), 0.0)
    if not expiry or strike <= 0:
        return None

    bid = _safe_float(
        quote.get("bid")
        or quote.get("bid_price")
        or option.get("bid"),
        0.0,
    )
    ask = _safe_float(
        quote.get("ask")
        or quote.get("ask_price")
        or option.get("ask"),
        0.0,
    )
    volume = _safe_int(
        day.get("volume")
        or option.get("volume")
        or option.get("day_volume"),
        0,
    )
    open_interest = _safe_int(option.get("open_interest") or option.get("oi"), 0)
    implied_volatility = _safe_float(option.get("implied_volatility") or option.get("iv"), 0.0)
    delta = abs(
        _safe_float(
            greeks.get("delta")
            or option.get("delta"),
            0.0,
        )
    )

    return {
        "ticker": underlying_ticker,
        "option_ticker": details.get("ticker") or option.get("ticker") or "",
        "source": "polygon",
        "expiry": expiry,
        "strike": strike,
        "type": contract_type,
        "bid": bid,
        "ask": ask,
        "volume": volume,
        "open_interest": open_interest,
        "implied_volatility": implied_volatility,
        "delta": delta,
    }


def _safe_spot_from_yf(ticker_obj) -> float:
    try:
        fast = getattr(ticker_obj, "fast_info", {}) or {}
        for key in ("lastPrice", "last_price", "regularMarketPrice", "previousClose"):
            value = _safe_float(fast.get(key), 0.0) if isinstance(fast, dict) else 0.0
            if value > 0:
                return value
    except Exception:
        pass
    try:
        history = ticker_obj.history(period="5d", interval="1d")
        if history is not None and not history.empty:
            close = _safe_float(history["Close"].dropna().iloc[-1], 0.0)
            if close > 0:
                return close
    except Exception:
        pass
    return 0.0


def _fetch_yfinance_option_chain(ticker: str) -> list[dict]:
    symbol = str(ticker or "").upper().strip()
    if not symbol:
        return []

    rows = []
    try:
        ticker_obj = yf.Ticker(symbol)
        expiries = list(getattr(ticker_obj, "options", []) or [])
        if not expiries:
            return []

        today = datetime.utcnow().date()
        max_expiry = today + timedelta(days=30)
        spot = _safe_spot_from_yf(ticker_obj)

        for expiry in expiries:
            try:
                expiry_date = datetime.strptime(str(expiry), "%Y-%m-%d").date()
            except ValueError:
                continue
            if expiry_date < today or expiry_date > max_expiry:
                continue

            try:
                chain = ticker_obj.option_chain(str(expiry))
            except Exception:
                continue

            for contract_type, table in (("call", getattr(chain, "calls", None)), ("put", getattr(chain, "puts", None))):
                if table is None or table.empty:
                    continue
                for row in table.to_dict(orient="records"):
                    strike = _safe_float(row.get("strike"), 0.0)
                    bid = _safe_float(row.get("bid"), 0.0)
                    ask = _safe_float(row.get("ask"), 0.0)
                    if strike <= 0 or ask <= 0:
                        continue
                    delta = _estimate_delta(contract_type, strike, spot)
                    rows.append(
                        {
                            "ticker": symbol,
                            "option_ticker": row.get("contractSymbol") or "",
                            "source": "yfinance",
                            "expiry": str(expiry),
                            "strike": strike,
                            "type": contract_type,
                            "bid": bid,
                            "ask": ask,
                            "volume": _safe_int(row.get("volume"), 0),
                            "open_interest": _safe_int(row.get("openInterest"), 0),
                            "implied_volatility": _safe_float(row.get("impliedVolatility"), 0.0),
                            "delta": delta,
                        }
                    )
    except Exception:
        return []

    return rows


def fetch_option_chain_for_ticker(ticker: str, *, limit: int = 250, max_pages: int = 3) -> list[dict]:
    symbol = str(ticker or "").upper().strip()
    if not symbol:
        return []

    cache_key = f"{symbol}:{limit}:{max_pages}"
    if cache_key in CHAIN_CACHE:
        return CHAIN_CACHE[cache_key]

    today = datetime.utcnow().date()
    max_expiry = today + timedelta(days=30)
    url = f"https://api.polygon.io/v3/snapshot/options/{symbol}"
    params = {
        "apiKey": API_KEY,
        "limit": min(max(int(limit), 1), 250),
        "expiration_date.gte": today.isoformat(),
        "expiration_date.lte": max_expiry.isoformat(),
    }

    rows = []
    try:
        for _ in range(max_pages):
            response = requests.get(url, params=params, timeout=12)
            response.raise_for_status()
            payload = response.json()
            results = payload.get("results", [])

            for item in results:
                normalized = _normalize_polygon_option(item, symbol)
                if normalized:
                    rows.append(normalized)

            next_url = payload.get("next_url")
            if not next_url:
                break
            url = _next_url_with_key(next_url)
            params = None
    except Exception:
        rows = []

    if not rows:
        rows = _fetch_yfinance_option_chain(symbol)

    CHAIN_CACHE[cache_key] = rows
    return rows
