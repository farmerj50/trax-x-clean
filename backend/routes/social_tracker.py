from __future__ import annotations

from cachetools import TTLCache
from flask import Blueprint, jsonify, request

from utils.premarket_intelligence import get_premarket_intelligence
from utils.social_tracker import build_social_tracker_dashboard


social_tracker_bp = Blueprint("social_tracker_bp", __name__)
SOCIAL_TRACKER_ROUTE_CACHE = TTLCache(maxsize=48, ttl=45)


def _parse_csv_arg(value: str | None) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _manual_equity_rows(tickers: list[str]) -> list[dict]:
    return [
        {
            "ticker": symbol.upper(),
            "companyName": symbol.upper(),
            "sector": "Unclassified",
            "price": 0.0,
            "marketCap": 0.0,
            "relativeVolume": 0.0,
            "gapPercent": 0.0,
            "assetClass": "stock",
        }
        for symbol in tickers
    ]


@social_tracker_bp.route("/api/social-tracker", methods=["GET"])
def social_tracker_dashboard():
    try:
        cache_key = ("social_tracker_dashboard", tuple(sorted((str(key), str(value)) for key, value in request.args.items())))
        cached_payload = SOCIAL_TRACKER_ROUTE_CACHE.get(cache_key)
        if cached_payload is not None:
            return jsonify(cached_payload), 200

        limit = max(3, min(int(request.args.get("limit", 8)), 15))
        tickers = _parse_csv_arg(request.args.get("tickers"))
        crypto = _parse_csv_arg(request.args.get("crypto"))
        events = _parse_csv_arg(request.args.get("events"))

        equity_rows: list[dict]
        if tickers:
            equity_rows = _manual_equity_rows(tickers)
        else:
            try:
                premarket_payload = get_premarket_intelligence(limit=max(limit * 3, 12), filters={})
                equity_rows = list(premarket_payload.get("stocks") or [])
            except RuntimeError:
                equity_rows = []

        payload = build_social_tracker_dashboard(
            equity_rows=equity_rows,
            tickers=tickers,
            crypto_symbols=crypto,
            event_topics=events,
            limit=limit,
        )
        SOCIAL_TRACKER_ROUTE_CACHE[cache_key] = payload
        return jsonify(payload), 200
    except RuntimeError as exc:
        return jsonify({"error": str(exc), "leaders": [], "alerts": [], "stocks": [], "crypto": [], "predictionMarkets": []}), 503
    except Exception as exc:
        return jsonify({"error": str(exc), "leaders": [], "alerts": [], "stocks": [], "crypto": [], "predictionMarkets": []}), 500
