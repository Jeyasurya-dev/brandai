import os
from datetime import timedelta


class Config:
    # =========================================================
    # CORE
    # =========================================================

    SECRET_KEY = os.environ.get(
        "SECRET_KEY",
        "dev-secret-change-me"
    )

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "sqlite:///brandgen.db"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False


    # =========================================================
    # JWT
    # =========================================================

    JWT_SECRET_KEY = os.environ.get(
        "JWT_SECRET_KEY",
        "dev-jwt-secret-change-me"
    )

    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        minutes=int(
            os.environ.get(
                "JWT_ACCESS_TOKEN_EXPIRES_MIN",
                60
            )
        )
    )

    JWT_REFRESH_TOKEN_EXPIRES = timedelta(
        days=int(
            os.environ.get(
                "JWT_REFRESH_TOKEN_EXPIRES_DAYS",
                7
            )
        )
    )


    # =========================================================
    # FRONTEND / CORS
    # =========================================================

    FRONTEND_ORIGIN = os.environ.get(
        "FRONTEND_ORIGIN",
        "*"
    )


    # =========================================================
    # AI
    # =========================================================

    GEMINI_API_KEY = os.environ.get(
        "GEMINI_API_KEY",
        ""
    )

    AI_MODEL = os.environ.get(
        "AI_MODEL",
        "gemini-3-flash"
    )


    # =========================================================
    # LOGO GENERATION
    # =========================================================

    # Uses the same GEMINI_API_KEY for image generation.

    IMAGE_MODEL = os.environ.get(
        "IMAGE_MODEL",
        "imagen-4.0-generate-001"
    )


    # =========================================================
    # TRADEMARK
    # =========================================================

    # Provider options:
    #
    # none
    # markerapi
    # generic_rest

    TRADEMARK_PROVIDER = os.environ.get(
        "TRADEMARK_PROVIDER",
        "none"
    )

    TRADEMARK_API_KEY = os.environ.get(
        "TRADEMARK_API_KEY",
        ""
    )

    TRADEMARK_API_BASE_URL = os.environ.get(
        "TRADEMARK_API_BASE_URL",
        ""
    )

    # markerapi.com uses username/password.

    TRADEMARK_API_USERNAME = os.environ.get(
        "TRADEMARK_API_USERNAME",
        ""
    )

    TRADEMARK_API_PASSWORD = os.environ.get(
        "TRADEMARK_API_PASSWORD",
        ""
    )


    # =========================================================
    # DOMAIN
    # =========================================================

    # Provider options:
    #
    # rdap
    # none
    # generic_rest

    DOMAIN_PROVIDER = os.environ.get(
        "DOMAIN_PROVIDER",
        "rdap"
    )

    DOMAIN_API_KEY = os.environ.get(
        "DOMAIN_API_KEY",
        ""
    )

    DOMAIN_API_BASE_URL = os.environ.get(
        "DOMAIN_API_BASE_URL",
        ""
    )


    # =========================================================
    # PAYMENTS — RAZORPAY
    # =========================================================

    PAYMENT_PROVIDER = os.environ.get(
        "PAYMENT_PROVIDER",
        "none"
    )

    # Razorpay Live/Test API Key
    # Example:
    # rzp_live_xxxxxxxxxxxxx

    PAYMENT_API_KEY = os.environ.get(
        "PAYMENT_API_KEY",
        ""
    )

    # Razorpay Live/Test Key Secret

    PAYMENT_API_SECRET = os.environ.get(
        "PAYMENT_API_SECRET",
        ""
    )

    # Razorpay Webhook Secret

    PAYMENT_WEBHOOK_SECRET = os.environ.get(
        "PAYMENT_WEBHOOK_SECRET",
        ""
    )


    # =========================================================
    # RATE LIMITING
    # =========================================================

    RATELIMIT_STORAGE_URI = os.environ.get(
        "RATELIMIT_STORAGE_URI",
        "memory://"
    )


    # =========================================================
    # DEFAULT FREE PLAN
    # =========================================================

    DEFAULT_FREE_NAMES_PER_GENERATION = 25