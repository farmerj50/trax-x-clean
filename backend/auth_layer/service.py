from __future__ import annotations

import copy
import hashlib
import json
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from werkzeug.security import check_password_hash, generate_password_hash

import config


AUTH_LOCK = RLock()
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.@-]{3,80}$")
LOGIN_ATTEMPTS: dict[str, list[float]] = {}


class AuthError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _state_path() -> Path:
    return Path(config.AUTH_STATE_PATH)


def _default_state() -> dict[str, Any]:
    now = utc_now()
    return {
        "users": {},
        "sessions": {},
        "createdAt": now,
        "updatedAt": now,
    }


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return _default_state()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthError("Authentication state is unavailable. Restore or repair the auth state file.", 503) from exc

    if not isinstance(payload, dict):
        raise AuthError("Authentication state is invalid. Restore or repair the auth state file.", 503)

    state = _default_state()
    state.update(payload)
    if not isinstance(state.get("users"), dict):
        raise AuthError("Authentication users state is invalid. Restore or repair the auth state file.", 503)
    if not isinstance(state.get("sessions"), dict):
        state["sessions"] = {}
    return state


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updatedAt"] = utc_now()
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _session_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=max(0.25, float(config.AUTH_SESSION_TTL_HOURS)))


def _cookie_max_age() -> int:
    return int(max(0.25, float(config.AUTH_SESSION_TTL_HOURS)) * 60 * 60)


def cookie_settings() -> dict[str, Any]:
    return {
        "key": config.AUTH_SESSION_COOKIE,
        "httponly": True,
        "secure": bool(config.AUTH_COOKIE_SECURE),
        "samesite": config.AUTH_COOKIE_SAMESITE,
        "path": "/",
        "max_age": _cookie_max_age(),
    }


def clear_cookie_settings() -> dict[str, Any]:
    return {
        "key": config.AUTH_SESSION_COOKIE,
        "path": "/",
    }


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "createdAt": user.get("createdAt"),
        "lastLoginAt": user.get("lastLoginAt"),
    }


def setup_required() -> bool:
    if not config.AUTH_ENABLED:
        return False
    with AUTH_LOCK:
        state = _load_state()
        return len(state.get("users") or {}) == 0


def _validate_username(username: Any) -> str:
    clean = str(username or "").strip()
    if not USERNAME_PATTERN.match(clean):
        raise AuthError("Username must be 3-80 characters using letters, numbers, dot, dash, underscore, or @.", 400)
    return clean


def _validate_password(password: Any) -> str:
    raw = str(password or "")
    min_length = int(config.AUTH_MIN_PASSWORD_LENGTH)
    if len(raw) < min_length:
        raise AuthError(f"Password must be at least {min_length} characters.", 400)
    if not re.search(r"[A-Z]", raw) or not re.search(r"[a-z]", raw) or not re.search(r"\d", raw):
        raise AuthError("Password must include uppercase, lowercase, and a number.", 400)
    return raw


def _cleanup_sessions(state: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    sessions = state.get("sessions") or {}
    for token_digest, session in list(sessions.items()):
        expires_at = _parse_time(session.get("expiresAt"))
        if expires_at is None or expires_at <= now:
            sessions.pop(token_digest, None)


def _login_rate_key(username: str, remote_addr: str) -> str:
    return f"{str(remote_addr or 'unknown')[:80].lower()}:{username.lower()}"


def _check_login_rate_limit(key: str) -> None:
    window = max(1, int(config.AUTH_LOGIN_WINDOW_SECONDS))
    max_attempts = max(1, int(config.AUTH_LOGIN_MAX_ATTEMPTS))
    cutoff = time.time() - window
    attempts = [attempt for attempt in LOGIN_ATTEMPTS.get(key, []) if attempt >= cutoff]
    LOGIN_ATTEMPTS[key] = attempts
    if len(attempts) >= max_attempts:
        raise AuthError("Too many login attempts. Try again later.", 429)


def _record_login_failure(key: str) -> None:
    LOGIN_ATTEMPTS.setdefault(key, []).append(time.time())


def _clear_login_failures(key: str) -> None:
    LOGIN_ATTEMPTS.pop(key, None)


def create_first_user(username: Any, password: Any) -> dict[str, Any]:
    clean_username = _validate_username(username)
    clean_password = _validate_password(password)
    with AUTH_LOCK:
        state = _load_state()
        if state.get("users"):
            raise AuthError("Initial user already exists.", 409)
        now = utc_now()
        user_id = str(uuid4())
        state["users"][user_id] = {
            "id": user_id,
            "username": clean_username,
            "passwordHash": generate_password_hash(clean_password),
            "createdAt": now,
            "updatedAt": now,
            "lastLoginAt": None,
        }
        _save_state(state)
        return _public_user(state["users"][user_id])


def _find_user_by_username(state: dict[str, Any], username: str) -> dict[str, Any] | None:
    normalized = username.lower()
    for user in (state.get("users") or {}).values():
        if str(user.get("username") or "").lower() == normalized:
            return user
    return None


def create_session(username: Any, password: Any, *, user_agent: str = "", remote_addr: str = "") -> dict[str, Any]:
    clean_username = _validate_username(username)
    raw_password = str(password or "")
    rate_key = _login_rate_key(clean_username, remote_addr)
    with AUTH_LOCK:
        _check_login_rate_limit(rate_key)
        state = _load_state()
        _cleanup_sessions(state)
        user = _find_user_by_username(state, clean_username)
        if not user or not check_password_hash(str(user.get("passwordHash") or ""), raw_password):
            _record_login_failure(rate_key)
            _save_state(state)
            raise AuthError("Invalid username or password.", 401)

        _clear_login_failures(rate_key)
        token = secrets.token_urlsafe(32)
        token_digest = _token_hash(token)
        expires_at = _session_expiry()
        now = utc_now()
        state["sessions"][token_digest] = {
            "id": str(uuid4()),
            "userId": user["id"],
            "createdAt": now,
            "expiresAt": expires_at.isoformat().replace("+00:00", "Z"),
            "userAgent": str(user_agent or "")[:240],
            "remoteAddr": str(remote_addr or "")[:80],
        }
        user["lastLoginAt"] = now
        user["updatedAt"] = now
        _save_state(state)
        return {
            "token": token,
            "expiresAt": expires_at.isoformat().replace("+00:00", "Z"),
            "user": _public_user(user),
        }


def get_token_from_request(req) -> str:
    return str(req.cookies.get(config.AUTH_SESSION_COOKIE) or "")


def get_session(token: str) -> dict[str, Any] | None:
    if not config.AUTH_ENABLED:
        return {"user": {"id": "auth-disabled", "username": "auth-disabled"}, "session": None}
    if not token:
        return None

    token_digest = _token_hash(token)
    with AUTH_LOCK:
        state = _load_state()
        _cleanup_sessions(state)
        session = (state.get("sessions") or {}).get(token_digest)
        if not session:
            _save_state(state)
            return None
        expires_at = _parse_time(session.get("expiresAt"))
        if expires_at is None or expires_at <= datetime.now(timezone.utc):
            state["sessions"].pop(token_digest, None)
            _save_state(state)
            return None
        user = (state.get("users") or {}).get(session.get("userId"))
        if not user:
            state["sessions"].pop(token_digest, None)
            _save_state(state)
            return None
        _save_state(state)
        return {
            "user": _public_user(copy.deepcopy(user)),
            "session": copy.deepcopy(session),
        }


def logout(token: str) -> None:
    if not token:
        return
    token_digest = _token_hash(token)
    with AUTH_LOCK:
        state = _load_state()
        if token_digest in state.get("sessions", {}):
            state["sessions"].pop(token_digest, None)
            _save_state(state)


def change_password(token: str, current_password: Any, new_password: Any) -> dict[str, Any]:
    raw_current = str(current_password or "")
    clean_new = _validate_password(new_password)
    token_digest = _token_hash(token)
    with AUTH_LOCK:
        state = _load_state()
        _cleanup_sessions(state)
        session = (state.get("sessions") or {}).get(token_digest)
        if not session:
            _save_state(state)
            raise AuthError("Authentication required.", 401)
        user = (state.get("users") or {}).get(session.get("userId"))
        if not user or not check_password_hash(str(user.get("passwordHash") or ""), raw_current):
            _save_state(state)
            raise AuthError("Current password is incorrect.", 403)
        now = utc_now()
        user["passwordHash"] = generate_password_hash(clean_new)
        user["updatedAt"] = now
        for digest, stored_session in list((state.get("sessions") or {}).items()):
            if stored_session.get("userId") == user["id"] and digest != token_digest:
                state["sessions"].pop(digest, None)
        _save_state(state)
        return _public_user(user)


def auth_status_for_request(req) -> dict[str, Any]:
    session = get_session(get_token_from_request(req))
    return {
        "authenticated": bool(session),
        "setupRequired": setup_required(),
        "user": session.get("user") if session else None,
        "sessionExpiresAt": session.get("session", {}).get("expiresAt") if session and session.get("session") else None,
    }


def _origin_from_value(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    match = re.match(r"^https?://[^/\s]+", raw, re.IGNORECASE)
    return match.group(0).rstrip("/") if match else raw.rstrip("/")


def _allowed_origins() -> set[str]:
    return {str(origin or "").strip().rstrip("/").lower() for origin in config.AUTH_ALLOWED_ORIGINS if origin}


def validate_request_origin(req) -> None:
    if not config.AUTH_ENABLED:
        return
    if str(req.method or "").upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    if not str(req.path or "").startswith("/api/"):
        return

    origin = _origin_from_value(req.headers.get("Origin", ""))
    if not origin:
        origin = _origin_from_value(req.headers.get("Referer", ""))
    if not origin:
        return
    if origin.lower() not in _allowed_origins():
        raise AuthError("Request origin is not allowed.", 403)


def is_public_path(path: str, method: str = "GET") -> bool:
    if not config.AUTH_ENABLED:
        return True
    if method == "OPTIONS":
        return True
    return (
        path == "/health"
        or path.startswith("/api/auth/")
        or path.startswith("/socket.io/")
    )
