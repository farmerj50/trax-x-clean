from flask import Blueprint, jsonify, request

from utils.contact_alerts import register_contact_alert


alert_contacts_bp = Blueprint("alert_contacts_bp", __name__)


@alert_contacts_bp.route("/api/alerts/contact", methods=["POST"])
def alert_contact():
    try:
        payload = request.get_json(silent=True) or {}
        result = register_contact_alert(payload)
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
