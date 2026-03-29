from flask import Blueprint, jsonify, request

from utils.premarket_intelligence import get_premarket_detail, get_premarket_intelligence


premarket_intelligence_bp = Blueprint("premarket_intelligence_bp", __name__)


@premarket_intelligence_bp.route("/api/premarket/intelligence", methods=["GET"])
def premarket_intelligence():
    try:
        limit = max(3, min(int(request.args.get("limit", 8)), 15))
        filters = {
            "min_gap_pct": request.args.get("min_gap_pct", 0),
            "min_volume": request.args.get("min_volume", 0),
            "sector": request.args.get("sector", ""),
            "positive_only": request.args.get("positive_only", "false"),
        }
        payload = get_premarket_intelligence(limit=limit, filters=filters)
        return jsonify(payload), 200
    except Exception as exc:
        return jsonify({"error": str(exc), "topPicks": [], "heatmap": [], "stocks": []}), 500


@premarket_intelligence_bp.route("/api/premarket/intelligence/<ticker>", methods=["GET"])
def premarket_intelligence_detail(ticker):
    try:
        payload = get_premarket_detail(ticker)
        if not payload:
            return jsonify({"error": f"{str(ticker).upper()} not found in premarket intelligence universe"}), 404
        return jsonify(payload), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
