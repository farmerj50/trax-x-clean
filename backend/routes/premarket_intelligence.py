from cachetools import TTLCache
from flask import Blueprint, jsonify, request

from utils.contact_alerts import dispatch_alert_event
from utils.premarket_intelligence import get_premarket_detail, get_premarket_intelligence
from utils.social_tracker import build_social_tracker_dashboard


premarket_intelligence_bp = Blueprint("premarket_intelligence_bp", __name__)
PREMARKET_ROUTE_CACHE = TTLCache(maxsize=48, ttl=45)


def _parse_csv_arg(value: str | None) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _dispatch_premarket_payload_alerts(payload: dict) -> None:
    top_picks = list(payload.get("topPicks") or [])
    for row in top_picks[:3]:
        social_state = str(row.get("socialAlertState") or "").lower()
        detector_state = str(row.get("detectorState") or "").lower()
        if social_state not in {"early_alert", "watch"} and detector_state not in {"triggered", "arming"}:
            continue
        try:
            dispatch_alert_event(
                {
                    "page": "/premarket-intelligence",
                    "eventType": "premarket_social",
                    "symbol": row.get("ticker"),
                    "label": social_state or detector_state or "alert",
                    "instrument": (row.get("socialRecommendation") or {}).get("instrument") or "stock",
                    "recommendation": (row.get("socialRecommendation") or {}).get("action") or row.get("setupType"),
                    "score": row.get("priorityScore") or row.get("score"),
                    "price": row.get("price"),
                    "headline": ((row.get("newsItems") or [{}])[0] or {}).get("title") if row.get("newsItems") else "",
                    "summary": row.get("socialSummary") or row.get("aiSummary") or "",
                }
            )
        except Exception:
            continue


def _dispatch_social_tracker_alerts(payload: dict) -> None:
    for row in list(payload.get("alerts") or [])[:4]:
        asset_class = str(row.get("assetClass") or "stock").lower()
        page = "/crypto" if asset_class == "crypto" else "/premarket-intelligence"
        event_type = "crypto_social" if asset_class == "crypto" else "social_tracker"
        try:
            dispatch_alert_event(
                {
                    "page": page,
                    "eventType": event_type,
                    "symbol": row.get("ticker"),
                    "label": row.get("socialAlertState"),
                    "instrument": (row.get("socialRecommendation") or {}).get("instrument") or asset_class,
                    "recommendation": (row.get("socialRecommendation") or {}).get("action") or "",
                    "score": row.get("socialCompositeScore"),
                    "price": row.get("price"),
                    "headline": ((row.get("newsItems") or [{}])[0] or {}).get("title") if row.get("newsItems") else "",
                    "summary": row.get("socialSummary") or "",
                }
            )
        except Exception:
            continue


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
        _dispatch_premarket_payload_alerts(payload)
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


@premarket_intelligence_bp.route("/api/premarket/social-tracker", methods=["GET"])
def premarket_social_tracker():
    try:
        cache_key = ("premarket_social_tracker", tuple(sorted((str(key), str(value)) for key, value in request.args.items())))
        cached_payload = PREMARKET_ROUTE_CACHE.get(cache_key)
        if cached_payload is not None:
            return jsonify(cached_payload), 200

        limit = max(3, min(int(request.args.get("limit", 8)), 15))
        tickers = _parse_csv_arg(request.args.get("tickers"))
        crypto = _parse_csv_arg(request.args.get("crypto"))
        events = _parse_csv_arg(request.args.get("events"))

        premarket_payload = get_premarket_intelligence(limit=max(limit * 3, 12), filters={})
        equity_rows = list(premarket_payload.get("stocks") or [])
        if tickers:
            ticker_set = {item.upper() for item in tickers}
            filtered_rows = [row for row in equity_rows if str(row.get("ticker") or "").upper() in ticker_set]
            seen = {str(row.get("ticker") or "").upper() for row in filtered_rows}
            for symbol in ticker_set - seen:
                filtered_rows.append(
                    {
                        "ticker": symbol,
                        "companyName": symbol,
                        "sector": "Unclassified",
                        "price": 0.0,
                        "marketCap": 0.0,
                        "relativeVolume": 0.0,
                        "gapPercent": 0.0,
                    }
                )
            equity_rows = filtered_rows

        payload = build_social_tracker_dashboard(
            equity_rows=equity_rows,
            tickers=tickers,
            crypto_symbols=crypto,
            event_topics=events,
            limit=limit,
        )
        _dispatch_social_tracker_alerts(payload)
        PREMARKET_ROUTE_CACHE[cache_key] = payload
        return jsonify(payload), 200
    except RuntimeError as exc:
        return jsonify({"error": str(exc), "leaders": [], "alerts": []}), 503
    except Exception as exc:
        return jsonify({"error": str(exc), "leaders": [], "alerts": []}), 500
