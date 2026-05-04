from __future__ import annotations

import json
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from threading import RLock
from typing import Any

import requests

import config


CONTACT_LOCK = RLock()
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean_text(value: Any, max_length: int = 200) -> str:
    return str(value or "").strip()[:max_length]


def _normalize_email(value: Any) -> str:
    return _clean_text(value, max_length=254).lower()


def _normalize_phone(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    has_plus = raw.startswith("+")
    digits = re.sub(r"\D+", "", raw)
    if not digits:
        return ""
    if has_plus:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+{digits}"


def _validate_contact(email: str, phone: str) -> None:
    if not email and not phone:
        raise ValueError("Email or phone number is required.")
    if email and not EMAIL_PATTERN.match(email):
        raise ValueError("Enter a valid email address.")
    if phone:
        digits = re.sub(r"\D+", "", phone)
        if len(digits) < 10:
            raise ValueError("Enter a valid phone number with at least 10 digits.")


def _load_contacts() -> list[dict[str, Any]]:
    path = Path(config.ALERT_CONTACTS_PATH)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def _save_contacts(rows: list[dict[str, Any]]) -> None:
    path = Path(config.ALERT_CONTACTS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(rows, ensure_ascii=True, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _load_event_log() -> dict[str, str]:
    path = Path(config.ALERT_EVENT_LOG_PATH)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_event_log(payload: dict[str, str]) -> None:
    path = Path(config.ALERT_EVENT_LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _smtp_configured() -> bool:
    return bool(config.SMTP_HOST and config.SMTP_PORT and config.SMTP_FROM_EMAIL)


def _twilio_configured() -> bool:
    return bool(config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN and config.TWILIO_FROM_NUMBER)


def send_email_alert(*, to_email: str, subject: str, body: str) -> dict[str, Any]:
    if not to_email:
        return {"channel": "email", "status": "skipped", "reason": "no_email"}
    if not _smtp_configured():
        return {"channel": "email", "status": "pending_configuration"}

    message = EmailMessage()
    message["Subject"] = _clean_text(subject, 160) or config.ALERT_DEFAULT_SUBJECT
    message["From"] = config.SMTP_FROM_EMAIL
    message["To"] = to_email
    message.set_content(body)

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as server:
            if config.SMTP_USE_TLS:
                server.starttls()
            if config.SMTP_USERNAME:
                server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            server.send_message(message)
        return {"channel": "email", "status": "sent"}
    except Exception as exc:
        return {"channel": "email", "status": "error", "reason": str(exc)}


def send_sms_alert(*, to_phone: str, body: str) -> dict[str, Any]:
    if not to_phone:
        return {"channel": "sms", "status": "skipped", "reason": "no_phone"}
    if not _twilio_configured():
        return {"channel": "sms", "status": "pending_configuration"}

    url = f"https://api.twilio.com/2010-04-01/Accounts/{config.TWILIO_ACCOUNT_SID}/Messages.json"
    payload = {
        "From": config.TWILIO_FROM_NUMBER,
        "To": to_phone,
        "Body": _clean_text(body, 1200),
    }
    try:
        response = requests.post(
            url,
            data=payload,
            auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
            timeout=15,
        )
        response.raise_for_status()
        return {"channel": "sms", "status": "sent"}
    except requests.exceptions.RequestException as exc:
        return {"channel": "sms", "status": "error", "reason": str(exc)}


def register_contact_alert(payload: dict[str, Any]) -> dict[str, Any]:
    email = _normalize_email(payload.get("email"))
    phone = _normalize_phone(payload.get("phone"))
    _validate_contact(email, phone)

    channels = payload.get("channels") if isinstance(payload.get("channels"), dict) else {}
    wants_email = bool(channels.get("email", True if email else False))
    wants_sms = bool(channels.get("sms", True if phone else False))

    if wants_email and not email:
        raise ValueError("Email alerts were selected, but no email address was provided.")
    if wants_sms and not phone:
        raise ValueError("SMS alerts were selected, but no phone number was provided.")

    page = _clean_text(payload.get("page"), max_length=120) or "/"
    name = _clean_text(payload.get("name"), max_length=120)
    message = _clean_text(payload.get("message"), max_length=400) or f"Alerts enabled for {page}"
    event_type = _clean_text(payload.get("eventType"), max_length=80) or "general"
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    record = {
        "createdAt": created_at,
        "name": name,
        "email": email,
        "phone": phone,
        "page": page,
        "eventType": event_type,
        "message": message,
        "channels": {
            "email": wants_email,
            "sms": wants_sms,
        },
    }

    with CONTACT_LOCK:
        rows = _load_contacts()
        duplicate_index = next(
            (
                index
                for index, row in enumerate(rows)
                if str(row.get("email") or "") == email
                and str(row.get("phone") or "") == phone
                and str(row.get("page") or "") == page
            ),
            None,
        )
        if duplicate_index is not None:
            rows[duplicate_index] = record
        else:
            rows.append(record)
        _save_contacts(rows)

    email_result = {"channel": "email", "status": "skipped"}
    sms_result = {"channel": "sms", "status": "skipped"}

    subject = f"{config.ALERT_DEFAULT_SUBJECT}: {page}"
    body = (
        f"Trax-X alert preferences saved.\n\n"
        f"Page: {page}\n"
        f"Event type: {event_type}\n"
        f"Message: {message}\n"
        f"Email alerts: {'on' if wants_email else 'off'}\n"
        f"SMS alerts: {'on' if wants_sms else 'off'}\n"
        f"Saved at: {created_at}\n"
    )

    if wants_email:
        email_result = send_email_alert(to_email=email, subject=subject, body=body)
    if wants_sms:
        sms_result = send_sms_alert(to_phone=phone, body=f"Trax-X alerts enabled for {page}. {message}")

    return {
        "ok": True,
        "saved": True,
        "subscription": {
            "name": name,
            "email": email,
            "phone": phone,
            "page": page,
            "eventType": event_type,
            "channels": record["channels"],
            "createdAt": created_at,
        },
        "delivery": {
            "email": email_result,
            "sms": sms_result,
        },
        "message": "Alert contact saved.",
    }


def _subscription_matches(subscription: dict[str, Any], *, page: str, event_type: str) -> bool:
    subscription_page = str(subscription.get("page") or "").strip() or "/"
    subscription_event = str(subscription.get("eventType") or "").strip().lower()
    normalized_page = str(page or "/").strip() or "/"
    normalized_event = str(event_type or "general").strip().lower()

    page_match = subscription_page == "/" or subscription_page == normalized_page
    event_match = subscription_event in {"", "general", "page_alert_subscription"} or subscription_event == normalized_event
    return page_match and event_match


def _make_event_cache_key(subscription: dict[str, Any], event: dict[str, Any]) -> str:
    email = str(subscription.get("email") or "").lower()
    phone = str(subscription.get("phone") or "")
    event_type = str(event.get("eventType") or "general").lower()
    page = str(event.get("page") or "/")
    symbol = str(event.get("symbol") or event.get("ticker") or "").upper()
    label = str(event.get("label") or event.get("alertState") or "").upper()
    instrument = str(event.get("instrument") or "").lower()
    return "|".join([email, phone, page, event_type, symbol, label, instrument])


def dispatch_alert_event(event: dict[str, Any]) -> dict[str, Any]:
    page = _clean_text(event.get("page"), 120) or "/"
    event_type = _clean_text(event.get("eventType"), 80) or "general"
    symbol = _clean_text(event.get("symbol") or event.get("ticker"), 40).upper()
    label = _clean_text(event.get("label") or event.get("alertState"), 40).upper()
    headline = _clean_text(event.get("headline"), 180)
    summary = _clean_text(event.get("summary"), 600)
    price = event.get("price")
    score = event.get("score")
    instrument = _clean_text(event.get("instrument"), 80)
    recommendation = _clean_text(event.get("recommendation"), 160)
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    with CONTACT_LOCK:
        subscriptions = _load_contacts()
        event_log = _load_event_log()
        now = datetime.now(timezone.utc)
        cooldown = max(int(config.ALERT_EVENT_COOLDOWN_MINUTES), 1)

        matching = [
            subscription
            for subscription in subscriptions
            if _subscription_matches(subscription, page=page, event_type=event_type)
        ]

        deliveries = []
        updated = False
        for subscription in matching:
            cache_key = _make_event_cache_key(subscription, event)
            previous_sent = event_log.get(cache_key)
            previous_dt = datetime.fromisoformat(previous_sent.replace("Z", "+00:00")) if previous_sent else None
            if previous_dt and (now - previous_dt).total_seconds() < cooldown * 60:
                deliveries.append(
                    {
                        "email": subscription.get("email", ""),
                        "phone": subscription.get("phone", ""),
                        "status": "cooldown",
                    }
                )
                continue

            subject = f"Trax-X {page} alert: {symbol or event_type}"
            body = (
                f"Trax-X generated an alert.\n\n"
                f"Page: {page}\n"
                f"Event type: {event_type}\n"
                f"Symbol: {symbol or '-'}\n"
                f"Label: {label or '-'}\n"
                f"Instrument: {instrument or '-'}\n"
                f"Recommendation: {recommendation or '-'}\n"
                f"Score: {score if score is not None else '-'}\n"
                f"Price: {price if price is not None else '-'}\n"
                f"Headline: {headline or '-'}\n"
                f"Summary: {summary or '-'}\n"
                f"Generated: {generated_at}\n"
            )

            email_result = {"channel": "email", "status": "skipped"}
            sms_result = {"channel": "sms", "status": "skipped"}
            channels = subscription.get("channels") if isinstance(subscription.get("channels"), dict) else {}

            if channels.get("email") and subscription.get("email"):
                email_result = send_email_alert(
                    to_email=str(subscription.get("email")),
                    subject=subject,
                    body=body,
                )
            if channels.get("sms") and subscription.get("phone"):
                sms_result = send_sms_alert(
                    to_phone=str(subscription.get("phone")),
                    body=f"{symbol or event_type} {label or 'alert'} on {page}. {recommendation or summary or headline or 'Trax-X signal detected.'}",
                )

            if email_result.get("status") in {"sent", "pending_configuration"} or sms_result.get("status") in {"sent", "pending_configuration"}:
                event_log[cache_key] = generated_at
                updated = True

            deliveries.append(
                {
                    "email": subscription.get("email", ""),
                    "phone": subscription.get("phone", ""),
                    "status": "attempted",
                    "emailDelivery": email_result,
                    "smsDelivery": sms_result,
                }
            )

        if updated:
            _save_event_log(event_log)

    return {
        "page": page,
        "eventType": event_type,
        "symbol": symbol,
        "label": label,
        "deliveryCount": len([item for item in deliveries if item.get("status") == "attempted"]),
        "subscriberCount": len(matching),
        "deliveries": deliveries,
    }
