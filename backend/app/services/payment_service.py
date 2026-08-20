"""
PaymentService
---------------
Razorpay integration for subscription checkout, billing management,
and webhook verification.

Plan pricing is read live from the `plans` table.
"""

import hashlib
import hmac
import json
import razorpay

from flask import current_app


class PaymentServiceError(Exception):
    pass


class PaymentService:

    def __init__(
        self,
        provider: str,
        api_key: str = "",
        api_secret: str = "",
        webhook_secret: str = "",
        frontend_origin: str = "",
    ):
        self.provider = provider
        self.api_key = api_key
        self.api_secret = api_secret
        self.webhook_secret = webhook_secret
        self.frontend_origin = (frontend_origin or "").rstrip("/")

    @classmethod
    def from_app_config(cls):

        origin = current_app.config.get(
            "FRONTEND_ORIGIN",
            ""
        )

        return cls(
            provider=current_app.config.get(
                "PAYMENT_PROVIDER",
                "none"
            ),
            api_key=current_app.config.get(
                "PAYMENT_API_KEY",
                ""
            ),
            api_secret=current_app.config.get(
                "PAYMENT_API_SECRET",
                ""
            ),
            webhook_secret=current_app.config.get(
                "PAYMENT_WEBHOOK_SECRET",
                ""
            ),
            frontend_origin=(
                origin
                if origin and origin != "*"
                else "http://127.0.0.1:5500"
            ),
        )

    def is_configured(self) -> bool:

        return (
            self.provider == "razorpay"
            and bool(self.api_key)
            and bool(self.api_secret)
        )

    def _client(self):

        if not self.is_configured():
            raise PaymentServiceError(
                "Razorpay is not configured. "
                "Set PAYMENT_PROVIDER=razorpay, "
                "PAYMENT_API_KEY and PAYMENT_API_SECRET."
            )

        try:
            import razorpay
        except ImportError as e:
            raise PaymentServiceError(
                f"razorpay package not installed: {e}"
            )

        return razorpay.Client(
            auth=(
                self.api_key,
                self.api_secret,
            )
        )

    def create_checkout_session(self, user, plan) -> str:

        if not self.is_configured():
            raise PaymentServiceError(
                "Razorpay is not configured. "
                "Set PAYMENT_PROVIDER=razorpay, "
                "PAYMENT_API_KEY and PAYMENT_API_SECRET."
            )

        if not plan.price_cents:
            raise PaymentServiceError(
                "This plan has no price set and "
                "cannot be checked out for."
            )

        client = self._client()

        amount = int(plan.price_cents)

        currency = (
            plan.currency or "INR"
        ).upper()

        order_data = {
            "amount": amount,
            "currency": currency,
            "receipt": f"brandai_{user.id[:8]}",
            "notes": {
                "user_id": user.id,
                "plan_id": plan.id,
                "plan_name": plan.name,
            },
        }

        try:

            order = client.order.create(
                data=order_data
            )

        except Exception as e:

            raise PaymentServiceError(
                f"Razorpay order creation failed: {e}"
            )

        # Return a JSON string because Razorpay Checkout
        # needs the order_id, amount and currency on frontend.
        checkout_data = {
            "order_id": order["id"],
            "amount": amount,
            "currency": currency,
            "key_id": self.api_key,
            "name": plan.name,
            "description": (
                f"{plan.name} subscription"
            ),
            "prefill": {
                "name": user.full_name or "",
                "email": user.email,
            },
            "notes": {
                "user_id": user.id,
                "plan_id": plan.id,
            },
        }

        return json.dumps(checkout_data)

    def verify_payment_signature(
        self,
        order_id: str,
        payment_id: str,
        signature: str,
    ) -> bool:

        if not self.is_configured():
            raise PaymentServiceError(
                "Razorpay is not configured."
            )

        if not order_id or not payment_id or not signature:
            raise PaymentServiceError(
                "Missing Razorpay payment verification fields."
            )

        message = (
            f"{order_id}|{payment_id}"
        ).encode("utf-8")

        expected_signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(
            expected_signature,
            signature,
        )

    def verify_and_parse_webhook(
        self,
        payload: bytes,
        signature: str,
    ):

        if not self.is_configured():
            raise PaymentServiceError(
                "Razorpay is not configured; "
                "cannot verify webhook."
            )

        if not self.webhook_secret:
            raise PaymentServiceError(
                "PAYMENT_WEBHOOK_SECRET is not set — "
                "refusing to process an unverifiable webhook."
            )

        if not signature:
            raise PaymentServiceError(
                "Missing Razorpay webhook signature."
            )

        expected_signature = hmac.new(
            self.webhook_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(
            expected_signature,
            signature,
        ):
            raise PaymentServiceError(
                "Razorpay webhook signature verification failed."
            )

        try:
            return json.loads(
                payload.decode("utf-8")
            )

        except (ValueError, UnicodeDecodeError) as e:

            raise PaymentServiceError(
                f"Invalid Razorpay webhook payload: {e}"
            )