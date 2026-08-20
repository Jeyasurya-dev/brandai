from datetime import datetime, timezone
import json

from flask import Blueprint, request, jsonify, g

from app.extensions import db, limiter
from app.models import Plan, Subscription, User
from app.utils.auth import login_required
from app.services.payment_service import PaymentService, PaymentServiceError

bp = Blueprint("payments", __name__, url_prefix="/api/payments")


@bp.post("/checkout")
@login_required
@limiter.limit("10 per hour")
def create_checkout():
    """
    Creates a Razorpay order for the selected subscription plan.

    The subscription is NOT activated here.
    The frontend receives the Razorpay order details and opens
    Razorpay Checkout. After successful payment, the frontend sends
    the payment details back for server-side signature verification.
    """

    user = g.current_user

    data = request.get_json(silent=True) or {}
    plan_id = data.get("plan_id")

    if not plan_id:
        return jsonify({
            "error": "plan_id is required."
        }), 400

    plan = Plan.query.get(plan_id)

    if not plan or not plan.is_active:
        return jsonify({
            "error": "Plan not found."
        }), 404

    payment_service = PaymentService.from_app_config()

    if not payment_service.is_configured():
        return jsonify({
            "error": (
                "Checkout is currently unavailable. "
                "Configure Razorpay payment settings on the server."
            )
        }), 503

    try:

        checkout_data = (
            payment_service.create_checkout_session(
                user,
                plan
            )
        )

    except PaymentServiceError as e:

        return jsonify({
            "error": str(e)
        }), 502

    try:
        checkout_data = json.loads(checkout_data)
    except (TypeError, ValueError):
        return jsonify({
            "error": "Invalid checkout data returned by payment provider."
        }), 502

    return jsonify({
        "provider": "razorpay",
        "order_id": checkout_data["order_id"],
        "amount": checkout_data["amount"],
        "currency": checkout_data["currency"],
        "key_id": checkout_data["key_id"],
        "name": checkout_data.get("name"),
        "description": checkout_data.get("description"),
        "prefill": checkout_data.get("prefill", {}),
        "notes": checkout_data.get("notes", {}),
    }), 200

@bp.post("/verify")
@login_required
@limiter.limit("20 per hour")
def verify_payment():
    """
    Verifies a Razorpay payment signature server-side and activates
    the user's subscription only after successful verification.
    """

    user = g.current_user

    data = request.get_json(silent=True) or {}

    order_id = data.get("razorpay_order_id")
    payment_id = data.get("razorpay_payment_id")
    signature = data.get("razorpay_signature")
    plan_id = data.get("plan_id")

    if not all([
        order_id,
        payment_id,
        signature,
        plan_id,
    ]):
        return jsonify({
            "error": "Missing payment verification fields."
        }), 400

    plan = Plan.query.get(plan_id)

    if not plan or not plan.is_active:
        return jsonify({
            "error": "Plan not found."
        }), 404

    payment_service = PaymentService.from_app_config()

    if not payment_service.is_configured():
        return jsonify({
            "error": "Payment provider is not configured."
        }), 503

    try:

        verified = payment_service.verify_payment_signature(
            order_id=order_id,
            payment_id=payment_id,
            signature=signature,
        )

    except PaymentServiceError as e:

        return jsonify({
            "error": str(e)
        }), 502

    if not verified:
        return jsonify({
            "error": "Payment verification failed."
        }), 400

    # Avoid creating duplicate subscriptions if the frontend
    # retries the verification request.
    existing = Subscription.query.filter_by(
        user_id=user.id,
        provider="razorpay",
        provider_subscription_id=payment_id,
    ).first()

    if existing:
        return jsonify({
            "message": "Payment already verified.",
            "subscription": {
                "id": existing.id,
                "status": existing.status,
                "plan_id": existing.plan_id,
            },
        }), 200

    # Cancel previous active subscription(s) before activating
    # the newly purchased plan.
    previous_subscriptions = Subscription.query.filter_by(
        user_id=user.id,
        status="active",
    ).all()

    for previous in previous_subscriptions:
        previous.status = "cancelled"

    subscription = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        provider="razorpay",
        provider_subscription_id=payment_id,
    )

    db.session.add(subscription)
    db.session.commit()

    return jsonify({
        "message": "Payment verified and subscription activated.",
        "subscription": {
            "id": subscription.id,
            "status": subscription.status,
            "plan_id": subscription.plan_id,
        },
    }), 200


@bp.post("/portal")
@login_required
@limiter.limit("10 per hour")
def create_portal():
    """
    Razorpay billing management endpoint.

    Razorpay does not provide a Stripe-style hosted billing portal
    through this integration, so we return the user's current
    subscription information instead.
    """

    user = g.current_user

    subscription = (
        Subscription.query
        .filter_by(
            user_id=user.id,
            status="active"
        )
        .order_by(
            Subscription.created_at.desc()
        )
        .first()
    )

    if not subscription:
        return jsonify({
            "provider": "razorpay",
            "message": "No active subscription found.",
            "subscription": None,
        }), 200

    return jsonify({
        "provider": "razorpay",
        "message": "Subscription is managed through Razorpay.",
        "subscription": {
            "id": subscription.id,
            "plan_id": subscription.plan_id,
            "status": subscription.status,
            "provider": subscription.provider,
            "provider_subscription_id": (
                subscription.provider_subscription_id
            ),
            "current_period_end": (
                subscription.current_period_end.isoformat()
                if subscription.current_period_end
                else None
            ),
        },
    }), 200


@bp.post("/webhook")
def razorpay_webhook():
    """
    Razorpay webhook receiver.

    No login/JWT is required because Razorpay calls this
    endpoint server-to-server.

    Authentication is done using the Razorpay webhook signature.
    """

    payment_service = PaymentService.from_app_config()

    signature = request.headers.get(
        "X-Razorpay-Signature",
        ""
    )

    payload = request.get_data()

    try:
        event = payment_service.verify_and_parse_webhook(
            payload,
            signature
        )

    except PaymentServiceError:
        return jsonify({
            "error": "Webhook verification failed."
        }), 400

    try:

        event_type = event.get("event")

        # Payment successfully captured
        if event_type == "payment.captured":

            payment_entity = (
                event
                .get("payload", {})
                .get("payment", {})
                .get("entity", {})
            )

            _handle_razorpay_payment(
                payment_entity
            )

        # Payment failed
        elif event_type == "payment.failed":

            payment_entity = (
                event
                .get("payload", {})
                .get("payment", {})
                .get("entity", {})
            )

            _handle_razorpay_payment_failed(
                payment_entity
            )

    except Exception:
        db.session.rollback()

    return jsonify({
        "received": True
    }), 200


def _handle_razorpay_payment(payment_obj):
    """
    Handles a successful Razorpay payment.

    The payment itself was already signature-verified
    before reaching this function.
    """

    payment_id = payment_obj.get("id")

    notes = payment_obj.get("notes") or {}

    user_id = notes.get("user_id")
    plan_id = notes.get("plan_id")

    if not user_id or not plan_id:
        return

    user = User.query.get(user_id)
    plan = Plan.query.get(plan_id)

    if not user or not plan:
        return

    existing = Subscription.query.filter_by(
        user_id=user.id,
        provider="razorpay",
        provider_subscription_id=payment_id
    ).first()

    if existing:
        return

    # Cancel previous active subscriptions
    previous_subscriptions = Subscription.query.filter_by(
        user_id=user.id,
        status="active"
    ).all()

    for previous in previous_subscriptions:
        previous.status = "cancelled"

    subscription = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        provider="razorpay",
        provider_subscription_id=payment_id,
    )

    db.session.add(subscription)
    db.session.commit()

def _handle_razorpay_payment_failed(payment_obj):
    """
    Handles a failed Razorpay payment.

    We intentionally do not activate or modify an existing
    subscription here.
    """

    # Payment failed.
    # No subscription should be activated.
    return