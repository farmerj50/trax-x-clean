from flask import Blueprint, jsonify, request

from trading import service
from trading.service import TradingProviderError
from trading.alpaca_broker import AlpacaBrokerError
from trading.paper_broker import PaperBrokerError


trading_bp = Blueprint("trading_bp", __name__)


def _error_response(exc, fallback_status=500):
    status_code = getattr(exc, "status_code", fallback_status)
    return jsonify({"error": str(exc)}), status_code


@trading_bp.route("/api/trading/status", methods=["GET"])
def trading_status():
    return jsonify(service.trading_status()), 200


@trading_bp.route("/api/trading/provider-test", methods=["GET"])
def trading_provider_test():
    try:
        return jsonify(service.test_provider_connection()), 200
    except (TradingProviderError, AlpacaBrokerError) as exc:
        return _error_response(exc)
    except Exception as exc:
        return _error_response(exc, 500)


@trading_bp.route("/api/trading/env-diagnostics", methods=["GET"])
def trading_env_diagnostics():
    try:
        return jsonify(service.env_diagnostics()), 200
    except Exception as exc:
        return _error_response(exc, 500)


@trading_bp.route("/api/trading/readiness", methods=["GET"])
def trading_readiness():
    try:
        return jsonify(service.execution_readiness()), 200
    except Exception as exc:
        return _error_response(exc, 500)


@trading_bp.route("/api/trading/alpaca/accounts", methods=["GET"])
def alpaca_accounts():
    try:
        try:
            limit = int(request.args.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50
        payload = service.list_alpaca_accounts(
            query=request.args.get("query", ""),
            status=request.args.get("status", ""),
            limit=limit,
        )
        return jsonify(payload), 200
    except (TradingProviderError, AlpacaBrokerError) as exc:
        return _error_response(exc)
    except Exception as exc:
        return _error_response(exc, 500)


@trading_bp.route("/api/trading/alpaca/accounts/<account_id>", methods=["GET"])
def alpaca_account(account_id):
    try:
        return jsonify(service.get_alpaca_account(account_id)), 200
    except (TradingProviderError, AlpacaBrokerError) as exc:
        return _error_response(exc)
    except Exception as exc:
        return _error_response(exc, 500)


@trading_bp.route("/api/trading/alpaca/sandbox-account", methods=["POST"])
def create_sandbox_alpaca_account():
    try:
        return jsonify(service.create_sandbox_alpaca_account()), 201
    except (TradingProviderError, AlpacaBrokerError) as exc:
        return _error_response(exc)
    except Exception as exc:
        return _error_response(exc, 500)


@trading_bp.route("/api/trading/alpaca/sandbox-funding", methods=["POST"])
def fund_sandbox_alpaca_account():
    try:
        payload = request.get_json(silent=True) or {}
        return jsonify(service.fund_sandbox_alpaca_account(payload)), 201
    except (TradingProviderError, AlpacaBrokerError) as exc:
        return _error_response(exc)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return _error_response(exc, 500)


@trading_bp.route("/api/trading/alpaca/selected-account", methods=["GET"])
def get_selected_alpaca_account():
    try:
        return jsonify(service.get_selected_alpaca_account()), 200
    except Exception as exc:
        return _error_response(exc, 500)


@trading_bp.route("/api/trading/alpaca/selected-account", methods=["POST"])
def set_selected_alpaca_account():
    try:
        payload = request.get_json(silent=True) or {}
        result = service.set_selected_alpaca_account(payload.get("accountId"))
        return jsonify(result), 200
    except (TradingProviderError, AlpacaBrokerError) as exc:
        return _error_response(exc)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return _error_response(exc, 500)


@trading_bp.route("/api/trading/alpaca/selected-account", methods=["DELETE"])
def clear_selected_alpaca_account():
    try:
        return jsonify(service.clear_selected_alpaca_account()), 200
    except Exception as exc:
        return _error_response(exc, 500)


@trading_bp.route("/api/trading/account", methods=["GET"])
def trading_account():
    try:
        return jsonify(service.get_account()), 200
    except (TradingProviderError, AlpacaBrokerError) as exc:
        return _error_response(exc)
    except Exception as exc:
        return _error_response(exc, 500)


@trading_bp.route("/api/trading/positions", methods=["GET"])
def trading_positions():
    try:
        return jsonify(service.get_positions()), 200
    except (TradingProviderError, AlpacaBrokerError) as exc:
        return _error_response(exc)
    except Exception as exc:
        return _error_response(exc, 500)


@trading_bp.route("/api/trading/orders", methods=["GET"])
def trading_orders():
    try:
        limit = int(request.args.get("limit", 100))
    except (TypeError, ValueError):
        limit = 100
    try:
        return jsonify(service.get_orders(limit=limit)), 200
    except (TradingProviderError, AlpacaBrokerError) as exc:
        return _error_response(exc)
    except Exception as exc:
        return _error_response(exc, 500)


@trading_bp.route("/api/trading/audit-log", methods=["GET"])
def trading_audit_log():
    try:
        limit = int(request.args.get("limit", 100))
    except (TypeError, ValueError):
        limit = 100
    try:
        return jsonify(service.get_audit_log(limit=limit)), 200
    except Exception as exc:
        return _error_response(exc, 500)


@trading_bp.route("/api/trading/market-clock", methods=["GET"])
def trading_market_clock():
    try:
        return jsonify(service.get_market_clock()), 200
    except (TradingProviderError, AlpacaBrokerError) as exc:
        return _error_response(exc)
    except Exception as exc:
        return _error_response(exc, 500)


@trading_bp.route("/api/trading/orders/preview", methods=["POST"])
def preview_trading_order():
    try:
        payload = request.get_json(silent=True) or {}
        return jsonify(service.preview_order(payload)), 200
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except (TradingProviderError, AlpacaBrokerError) as exc:
        return _error_response(exc)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@trading_bp.route("/api/trading/orders", methods=["POST"])
def submit_trading_order():
    try:
        payload = request.get_json(silent=True) or {}
        return jsonify(service.submit_order(payload)), 201
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except (TradingProviderError, AlpacaBrokerError) as exc:
        return _error_response(exc)
    except (ValueError, PaperBrokerError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@trading_bp.route("/api/trading/orders/<order_id>", methods=["DELETE"])
def cancel_trading_order(order_id):
    try:
        return jsonify(service.cancel_order(order_id)), 200
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except (TradingProviderError, AlpacaBrokerError) as exc:
        return _error_response(exc)
    except (ValueError, PaperBrokerError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
