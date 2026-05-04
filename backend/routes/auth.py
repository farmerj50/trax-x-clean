from flask import Blueprint, jsonify, make_response, request

from auth_layer import service
from auth_layer.service import AuthError


auth_bp = Blueprint("auth_bp", __name__)


def _error_response(exc, fallback_status=500):
    status_code = getattr(exc, "status_code", fallback_status)
    return jsonify({"error": str(exc)}), status_code


def _set_session_cookie(response, token: str):
    settings = service.cookie_settings()
    key = settings.pop("key")
    response.set_cookie(key, token, **settings)
    return response


def _clear_session_cookie(response):
    settings = service.clear_cookie_settings()
    key = settings.pop("key")
    response.delete_cookie(key, **settings)
    return response


@auth_bp.route("/api/auth/session", methods=["GET"])
def auth_session():
    try:
        return jsonify(service.auth_status_for_request(request)), 200
    except AuthError as exc:
        return _error_response(exc)


@auth_bp.route("/api/auth/setup", methods=["POST"])
def auth_setup():
    try:
        payload = request.get_json(silent=True) or {}
        user = service.create_first_user(payload.get("username"), payload.get("password"))
        session = service.create_session(
            payload.get("username"),
            payload.get("password"),
            user_agent=request.headers.get("User-Agent", ""),
            remote_addr=request.remote_addr or "",
        )
        response = make_response(
            jsonify(
                {
                    "ok": True,
                    "authenticated": True,
                    "setupRequired": False,
                    "user": user,
                    "sessionExpiresAt": session["expiresAt"],
                }
            ),
            201,
        )
        return _set_session_cookie(response, session["token"])
    except AuthError as exc:
        return _error_response(exc)
    except Exception as exc:
        return _error_response(exc, 500)


@auth_bp.route("/api/auth/login", methods=["POST"])
def auth_login():
    try:
        payload = request.get_json(silent=True) or {}
        session = service.create_session(
            payload.get("username"),
            payload.get("password"),
            user_agent=request.headers.get("User-Agent", ""),
            remote_addr=request.remote_addr or "",
        )
        response = make_response(
            jsonify(
                {
                    "ok": True,
                    "authenticated": True,
                    "setupRequired": False,
                    "user": session["user"],
                    "sessionExpiresAt": session["expiresAt"],
                }
            ),
            200,
        )
        return _set_session_cookie(response, session["token"])
    except AuthError as exc:
        return _error_response(exc)
    except Exception as exc:
        return _error_response(exc, 500)


@auth_bp.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    try:
        service.logout(service.get_token_from_request(request))
        response = make_response(jsonify({"ok": True, "authenticated": False}), 200)
        return _clear_session_cookie(response)
    except AuthError as exc:
        return _error_response(exc)


@auth_bp.route("/api/auth/change-password", methods=["POST"])
def auth_change_password():
    try:
        payload = request.get_json(silent=True) or {}
        user = service.change_password(
            service.get_token_from_request(request),
            payload.get("currentPassword"),
            payload.get("newPassword"),
        )
        return jsonify({"ok": True, "user": user}), 200
    except AuthError as exc:
        return _error_response(exc)
    except Exception as exc:
        return _error_response(exc, 500)
