from cachetools import TTLCache
from flask import Blueprint, jsonify, request

from utils.premarket_intelligence import get_premarket_detail, get_premarket_intelligence


premarket_intelligence_bp = Blueprint("premarket_intelligence_bp", __name__)
PREMARKET_ROUTE_CACHE = TTLCache(maxsize=48, ttl=45)


@premarket_intelligence_bp.route("/api/premarket/intelligence", methods=["GET"])
def premarket_intelligence():
    try:
        cache_key = ("premarket_intelligence", tuple(sorted((str(key), str(value)) for key, value in request.args.items())))
        cached_payload = PREMARKET_ROUTE_CACHE.get(cache_key)
        if cached_payload is not None:
            return jsonify(cached_payload), 200

        limit = max(3, min(int(request.args.get("limit", 8)), 15))
        filters = {
            "min_gap_pct": request.args.get("min_gap_pct", 0),
            "min_volume": request.args.get("min_volume", 0),
            "sector": request.args.get("sector", ""),
            "positive_only": request.args.get("positive_only", "false"),
        }
        payload = get_premarket_intelligence(limit=limit, filters=filters)
        PREMARKET_ROUTE_CACHE[cache_key] = payload
        return jsonify(payload), 200
    except RuntimeError as exc:
        return jsonify(
            {
                "error": str(exc),
                "topPicks": [],
                "earlySetupWatch": [],
                "heatmap": [],
                "stocks": [],
                "marketSummary": {
                    "bullishCount": 0,
                    "bearishCount": 0,
                    "highestConvictionSector": "Unclassified",
                    "earlySetupCount": 0,
                },
                "marketSession": "premarket",
            }
        ), 503
    except Exception as exc:
        return jsonify({"error": str(exc), "topPicks": [], "heatmap": [], "stocks": []}), 500


@premarket_intelligence_bp.route("/api/premarket/intelligence/<ticker>", methods=["GET"])
def premarket_intelligence_detail(ticker):
    try:
        cache_key = ("premarket_intelligence_detail", str(ticker).upper().strip())
        cached_payload = PREMARKET_ROUTE_CACHE.get(cache_key)
        if cached_payload is not None:
            return jsonify(cached_payload), 200

        payload = get_premarket_detail(ticker)
        if not payload:
            return jsonify({"error": f"{str(ticker).upper()} not found in premarket intelligence universe"}), 404
        PREMARKET_ROUTE_CACHE[cache_key] = payload
        return jsonify(payload), 200
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
