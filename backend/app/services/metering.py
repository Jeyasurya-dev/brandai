"""
Shared subscription-plan lookup and feature-usage metering helpers.
Originally lived only in generate_routes.py; extracted here once a second
route file (favorite_routes.py, for AI tagline generation) needed the same
enforcement logic, so there's exactly one implementation of "is this user
over their plan's limit for this feature" rather than two that could drift
apart.
"""

from datetime import datetime

from flask import jsonify

from app.extensions import db
from app.models import Plan, Subscription, FeatureUsage


def user_plan(user):
    sub = (
        Subscription.query.filter_by(user_id=user.id, status="active")
        .order_by(Subscription.created_at.desc())
        .first()
    )
    if sub and sub.plan:
        return sub.plan
    return Plan.query.filter_by(code="free").first()


def feature_usage_this_month(user_id, feature):
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return FeatureUsage.query.filter(
        FeatureUsage.user_id == user_id,
        FeatureUsage.feature == feature,
        FeatureUsage.created_at >= month_start,
    ).count()


def check_feature_limit(user, plan, feature, feature_key):
    """Returns a (response, status_code) tuple to short-circuit with if the
    user is over their plan's monthly limit for this feature, or None if
    the call should proceed. A missing/None limit on the plan means
    unlimited for that feature. Admins always bypass."""
    if user.role == "ADMIN":
        return None
    limit = (plan.features or {}).get(feature_key) if plan else None
    if limit is None:
        return None
    used = feature_usage_this_month(user.id, feature)
    if used >= limit:
        return (
            jsonify(
                {
                    "error": f"Monthly limit reached for this feature on your plan ({limit}/mo). "
                    "Upgrade your plan or wait for next month's reset.",
                    "feature": feature,
                    "plan": plan.code if plan else None,
                    "limit": limit,
                    "used_this_month": used,
                }
            ),
            403,
        )
    return None


def log_feature_usage(user_id, feature):
    db.session.add(FeatureUsage(user_id=user_id, feature=feature))
    db.session.commit()
