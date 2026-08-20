from flask import Blueprint, jsonify

from app.models import Plan

bp = Blueprint("plans", __name__, url_prefix="/api/plans")


@bp.get("")
def list_plans():
    plans = Plan.query.filter_by(is_active=True).all()
    return jsonify({"plans": [p.to_dict() for p in plans]}), 200
