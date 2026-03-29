import pandas as pd
from flask import Blueprint, jsonify, request

from utils.options_data import fetch_option_chain_for_ticker
from utils.options_sniper import (
    build_candidates_from_payload,
    build_option_sniper_candidates,
    filter_underlying_breakout_setups,
)
from utils.stock_scanner import get_latest_scanner_rows, get_scanner_row_for_ticker


options_bp = Blueprint("options_bp", __name__)


def _build_auto_candidates(stock_rows: list, top_contracts_per_ticker: int = 3) -> dict:
    stock_df = pd.DataFrame(stock_rows or [])
    if stock_df.empty:
        return {"count": 0, "candidates": [], "message": "No scanner rows found"}

    tickers = [
        str(ticker or "").upper()
        for ticker in stock_df.get("ticker", pd.Series(dtype=str)).dropna().tolist()
        if str(ticker or "").strip()
    ]
    chain_map = {}
    chain_rows = {}
    chain_sources = {}
    failures = []
    for ticker in dict.fromkeys(tickers):
        try:
            rows = fetch_option_chain_for_ticker(ticker)
        except Exception:
            rows = []
        if rows:
            chain_map[ticker] = pd.DataFrame(rows)
            chain_rows[ticker] = len(rows)
            chain_sources[ticker] = str(rows[0].get("source") or "unknown")
        else:
            failures.append(ticker)

    result, contract_debug, stock_debug = build_option_sniper_candidates(
        stock_df,
        chain_map,
        top_contracts_per_ticker=top_contracts_per_ticker,
        return_debug=True,
    )
    qualified_stock_count = 0
    try:
        qualified_stock_count = len(filter_underlying_breakout_setups(stock_df))
    except Exception:
        qualified_stock_count = 0
    if result.empty:
        message = "No option sniper candidates passed the stock + option filters."
        if failures:
            message = f"{message} Missing or unusable chain data for: {', '.join(failures[:5])}"
        return {
            "count": 0,
            "candidates": [],
            "message": message,
            "chain_rows": chain_rows,
            "chain_sources": chain_sources,
            "qualified_stock_count": qualified_stock_count,
            "contract_debug": contract_debug,
            "stock_debug": stock_debug,
        }

    return {
        "count": len(result),
        "candidates": result.to_dict(orient="records"),
        "scanner_count": len(stock_df),
        "chain_count": len(chain_map),
        "chain_rows": chain_rows,
        "chain_sources": chain_sources,
        "qualified_stock_count": qualified_stock_count,
        "contract_debug": contract_debug,
        "stock_debug": stock_debug,
    }


@options_bp.route("/api/options/sniper", methods=["POST"])
def options_sniper():
    try:
        payload = request.get_json() or {}
        stock_rows = payload.get("stocks", [])
        option_chains = payload.get("option_chains", {})
        top_contracts_per_ticker = int(payload.get("top_contracts_per_ticker", 3))

        result = build_candidates_from_payload(
            stock_rows=stock_rows,
            option_chains=option_chains,
            top_contracts_per_ticker=top_contracts_per_ticker,
        )
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"count": 0, "candidates": [], "error": str(e)}), 500


@options_bp.route("/api/options/sniper/auto", methods=["GET"])
def options_sniper_auto():
    try:
        limit = max(1, min(int(request.args.get("limit", 15)), 25))
        top_contracts_per_ticker = max(1, min(int(request.args.get("top_contracts_per_ticker", 3)), 10))
        stock_rows = get_latest_scanner_rows(limit=limit)
        result = _build_auto_candidates(stock_rows, top_contracts_per_ticker=top_contracts_per_ticker)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"count": 0, "candidates": [], "error": str(e)}), 500


@options_bp.route("/api/options/sniper/<ticker>", methods=["GET"])
def options_sniper_for_ticker(ticker):
    try:
        top_contracts_per_ticker = max(1, min(int(request.args.get("top_contracts_per_ticker", 5)), 10))
        stock_row = get_scanner_row_for_ticker(ticker)
        if not stock_row:
            return jsonify({"count": 0, "candidates": [], "message": f"{str(ticker).upper()} not found in scanner snapshot"}), 200

        result = _build_auto_candidates([stock_row], top_contracts_per_ticker=top_contracts_per_ticker)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"count": 0, "candidates": [], "error": str(e)}), 500
