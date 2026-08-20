from flask import Blueprint, request, jsonify, g

from app.extensions import db
from app.models import (
    User, Plan, Subscription, TrademarkSearch, Generation, GeneratedName,
    AdminSetting, AuditLog, FeatureUsage,
)
from app.utils.auth import admin_required

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _log(action, details=None):
    db.session.add(AuditLog(actor_id=g.current_user.id, action=action, details=details or {}))


# ---------------- Users ----------------

@bp.get("/users")
@admin_required
def list_users():
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 25)), 100)
    query = User.query.order_by(User.created_at.desc())
    total = query.count()
    users = query.offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({"users": [u.to_public_dict() for u in users], "total": total, "page": page}), 200


@bp.patch("/users/<user_id>")
@admin_required
def update_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404
    data = request.get_json(silent=True) or {}

    if "role" in data and data["role"] in ("USER", "ADMIN"):
        user.role = data["role"]
    if "is_active" in data:
        user.is_active = bool(data["is_active"])

    _log("update_user", {"user_id": user_id, "changes": data})
    db.session.commit()
    return jsonify({"user": user.to_public_dict()}), 200


# ---------------- Plans & Subscriptions ----------------

@bp.get("/plans")
@admin_required
def admin_list_plans():
    plans = Plan.query.order_by(Plan.created_at.desc()).all()
    return jsonify({"plans": [p.to_dict() for p in plans]}), 200


@bp.post("/plans")
@admin_required
def create_plan():
    data = request.get_json(silent=True) or {}

    required = ["code", "name", "names_per_generation"]

    if not all(k in data for k in required):
        return jsonify({
            "error": f"Required fields: {required}"
        }), 400

    if Plan.query.filter_by(code=data["code"]).first():
        return jsonify({
            "error": "A plan with this code already exists."
        }), 409

    price = data.get("price_cents")

    # Admin UI sends price in normal currency.
    # Example: 499 INR -> 49900 paise.
    price_cents = (
        int(round(float(price) * 100))
        if price not in (None, "")
        else None
    )

    plan = Plan(
        code=data["code"],
        name=data["name"],
        names_per_generation=int(
            data["names_per_generation"]
        ),
        monthly_generation_limit=(
            int(data["monthly_generation_limit"])
            if data.get("monthly_generation_limit") not in (None, "")
            else None
        ),
        price_cents=price_cents,
        currency=data.get("currency", "INR"),
        billing_period=data.get(
            "billing_period",
            "monthly"
        ),
        features=data.get(
            "features",
            {}
        ),
    )

    db.session.add(plan)

    _log(
        "create_plan",
        {
            "code": plan.code,
            "price_cents": price_cents,
            "currency": plan.currency,
        }
    )

    db.session.commit()

    return jsonify({
        "plan": plan.to_dict()
    }), 201

@bp.patch("/plans/<plan_id>")
@admin_required
def update_plan(plan_id):
    plan = Plan.query.get(plan_id)

    if not plan:
        return jsonify({
            "error": "Plan not found."
        }), 404

    data = request.get_json(silent=True) or {}

    if "name" in data:
        plan.name = data["name"]

    if "names_per_generation" in data:
        plan.names_per_generation = int(
            data["names_per_generation"]
        )

    if "monthly_generation_limit" in data:
        plan.monthly_generation_limit = (
            int(data["monthly_generation_limit"])
            if data["monthly_generation_limit"] not in (None, "")
            else None
        )

    # Admin UI sends normal currency amount.
    # Example: ₹499 -> 49900 paise.
    if "price_cents" in data:
        price = data["price_cents"]

        plan.price_cents = (
            int(round(float(price) * 100))
            if price not in (None, "")
            else None
        )

    if "currency" in data:
        plan.currency = data["currency"]

    if "billing_period" in data:
        plan.billing_period = data["billing_period"]

    if "is_active" in data:
        plan.is_active = bool(data["is_active"])

    if "features" in data:
        plan.features = data["features"]

    _log(
        "update_plan",
        {
            "plan_id": plan_id,
            "changes": data,
        }
    )

    db.session.commit()

    return jsonify({
        "plan": plan.to_dict()
    }), 200

@bp.delete("/plans/<plan_id>")
@admin_required
def delete_plan(plan_id):
    plan = Plan.query.get(plan_id)

    if not plan:
        return jsonify({"error": "Plan not found."}), 404

    # Do not delete a plan that has active subscriptions.
    active_subscriptions = Subscription.query.filter_by(
        plan_id=plan_id,
        status="active"
    ).count()

    if active_subscriptions > 0:
        return jsonify({
            "error": (
                "This plan cannot be deleted because it has "
                "active subscriptions. Cancel or move those "
                "subscriptions first."
            )
        }), 409

    plan_code = plan.code

    _log(
        "delete_plan",
        {
            "plan_id": plan_id,
            "code": plan_code,
        }
    )

    db.session.delete(plan)
    db.session.commit()

    return jsonify({
        "message": "Plan deleted successfully."
    }), 200


@bp.get("/subscriptions")
@admin_required
def list_subscriptions():
    subs = Subscription.query.order_by(Subscription.created_at.desc()).limit(200).all()
    return (
        jsonify(
            {
                "subscriptions": [
                    {
                       "id": s.id,
                       "user_id": s.user_id,
                       "user": {
                          "id": s.user.id if s.user else None,
                          "email": s.user.email if s.user else None,
                          "full_name": s.user.full_name if s.user else None,
                        },
                        "plan": s.plan.to_dict() if s.plan else None,
                        "status": s.status,
                        "provider": s.provider,
                        "current_period_end": (
                            s.current_period_end.isoformat()
                            if s.current_period_end
                            else None
                        ),
                        "created_at": s.created_at.isoformat(),
                    }
                    for s in subs
                ]
            }
        ),
        200,
    )


@bp.post("/subscriptions")
@admin_required
def assign_subscription():
    """Admin manually assigns/changes a user's plan (e.g. comped Pro access).
    Real self-serve upgrades flow through PaymentService/webhooks instead."""
    data = request.get_json(silent=True) or {}
    user_id, plan_id = data.get("user_id"), data.get("plan_id")
    if not user_id or not plan_id:
        return jsonify({"error": "user_id and plan_id are required."}), 400
    if not User.query.get(user_id) or not Plan.query.get(plan_id):
        return jsonify({"error": "User or plan not found."}), 404

    sub = Subscription(user_id=user_id, plan_id=plan_id, status="active", provider="admin_manual")
    db.session.add(sub)
    _log("assign_subscription", {"user_id": user_id, "plan_id": plan_id})
    db.session.commit()
    return jsonify({"message": "Subscription assigned."}), 201

@bp.patch("/subscriptions/<subscription_id>")
@admin_required
def update_subscription(subscription_id):
    """Admin can update the status of a subscription."""
    subscription = Subscription.query.get(subscription_id)

    if not subscription:
        return jsonify({"error": "Subscription not found."}), 404

    data = request.get_json(silent=True) or {}
    status = data.get("status")

    allowed_statuses = {
        "active",
        "cancelled",
        "expired",
        "past_due",
    }

    if status not in allowed_statuses:
        return jsonify({
            "error": (
                "Invalid status. Allowed values: "
                "active, cancelled, expired, past_due."
            )
        }), 400

    subscription.status = status

    _log(
        "update_subscription",
        {
            "subscription_id": subscription_id,
            "status": status,
        },
    )

    db.session.commit()

    return jsonify({
        "message": "Subscription updated successfully.",
        "subscription": {
            "id": subscription.id,
            "user_id": subscription.user_id,
            "plan": subscription.plan.to_dict() if subscription.plan else None,
            "status": subscription.status,
            "provider": subscription.provider,
            "current_period_end": (
                subscription.current_period_end.isoformat()
                if subscription.current_period_end
                else None
            ),
            "created_at": subscription.created_at.isoformat(),
        },
    }), 200


# ---------------- Trademark search logs ----------------

@bp.get("/trademark-searches")
@admin_required
def trademark_logs():
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 50)), 200)
    query = TrademarkSearch.query.order_by(TrademarkSearch.created_at.desc())
    total = query.count()
    rows = query.offset((page - 1) * per_page).limit(per_page).all()
    return (
        jsonify(
            {
                "total": total,
                "page": page,
                "searches": [
                    {
                        "id": r.id,
                        "query_name": r.query_name,
                        "provider": r.provider,
                        "status": r.status,
                        "requested_by": r.requested_by,
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in rows
                ],
            }
        ),
        200,
    )


# ---------------- Analytics ----------------

METERED_FEATURES = ["logo_generation", "name_comparison", "name_refinement", "brand_intelligence", "tagline_generation"]


@bp.get("/analytics")
@admin_required
def analytics():
    from datetime import datetime
    from sqlalchemy import func

    total_users = User.query.count()
    total_generations = Generation.query.count()
    total_names = GeneratedName.query.count()
    completed_generations = Generation.query.filter_by(status="completed").count()
    failed_generations = Generation.query.filter_by(status="failed").count()
    active_subscriptions = Subscription.query.filter_by(status="active").count()

    total_trademark_searches = TrademarkSearch.query.count()
    trademark_by_status = dict(
        db.session.query(TrademarkSearch.status, func.count(TrademarkSearch.id))
        .group_by(TrademarkSearch.status)
        .all()
    )

    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    feature_usage_total = dict(
        db.session.query(FeatureUsage.feature, func.count(FeatureUsage.id)).group_by(FeatureUsage.feature).all()
    )
    feature_usage_this_month = dict(
        db.session.query(FeatureUsage.feature, func.count(FeatureUsage.id))
        .filter(FeatureUsage.created_at >= month_start)
        .group_by(FeatureUsage.feature)
        .all()
    )
    # Always include every known metered feature, even at zero, so the
    # admin dashboard doesn't have to guess which keys might be missing.
    feature_usage = {
        f: {
            "total": feature_usage_total.get(f, 0),
            "this_month": feature_usage_this_month.get(f, 0),
        }
        for f in METERED_FEATURES
    }

    return (
        jsonify(
            {
                "total_users": total_users,
                "total_generations": total_generations,
                "completed_generations": completed_generations,
                "failed_generations": failed_generations,
                "total_names_generated": total_names,
                "active_subscriptions": active_subscriptions,
                "trademark_searches": {
                    "total": total_trademark_searches,
                    "by_status": trademark_by_status,
                },
                "feature_usage": feature_usage,
            }
        ),
        200,
    )


# ---------------- System settings ----------------

@bp.get("/settings")
@admin_required
def get_settings():
    settings = AdminSetting.query.all()
    return jsonify({"settings": {s.key: s.value for s in settings}}), 200


@bp.put("/settings/<key>")
@admin_required
def update_setting(key):
    data = request.get_json(silent=True) or {}
    value = data.get("value")
    setting = AdminSetting.query.filter_by(key=key).first()
    if not setting:
        setting = AdminSetting(key=key, value=value)
        db.session.add(setting)
    else:
        setting.value = value
    _log("update_setting", {"key": key})
    db.session.commit()
    return jsonify({"key": key, "value": value}), 200
