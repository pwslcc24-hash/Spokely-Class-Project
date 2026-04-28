"""
REST API v1 — session-authenticated JSON endpoints for the current user's work orders.
"""

from flask import Blueprint, g, jsonify

from models import WorkOrder

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")


def _json_response(payload: dict, status: int = 200):
    """Build a JSON Response with an explicit status (avoids client quirks with tuple returns)."""
    r = jsonify(payload)
    r.status_code = status
    return r


def _serialize_work_order(wo: WorkOrder) -> dict:
    """Stable JSON shape for integrations (includes user_id for ownership context)."""
    data = wo.to_dict()
    data["user_id"] = wo.user_id
    return data


@api_v1_bp.before_request
def _require_authenticated_user():
    """API uses the same Flask session as the web UI; unauthenticated callers get JSON 401."""
    if getattr(g, "current_user", None) is None:
        return _json_response(
            {
                "success": False,
                "error": "Authentication required.",
                "code": "unauthorized",
            },
            401,
        )


@api_v1_bp.route("/workorders", methods=["GET"])
def list_work_orders():
    """Return all work orders for the logged-in user (no auto-created sample rows)."""
    uid = g.current_user.id
    rows = WorkOrder.query.filter_by(user_id=uid).order_by(WorkOrder.id).all()
    items = [_serialize_work_order(wo) for wo in rows]
    return _json_response(
        {
            "success": True,
            "api_version": "v1",
            "count": len(items),
            "work_orders": items,
        },
        200,
    )


@api_v1_bp.route("/workorders/<int:workorder_id>", methods=["GET"])
def get_work_order(workorder_id: int):
    """Return one work order by id if it belongs to the logged-in user."""
    uid = g.current_user.id
    wo = WorkOrder.query.filter_by(id=workorder_id, user_id=uid).first()
    if wo is None:
        return _json_response(
            {
                "success": False,
                "error": "Work order not found.",
                "code": "not_found",
            },
            404,
        )
    return _json_response(
        {
            "success": True,
            "api_version": "v1",
            "work_order": _serialize_work_order(wo),
        },
        200,
    )
